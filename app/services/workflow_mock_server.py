"""内嵌 + 独立运行工作流 Mock 服务器。

两种运行模式:
1. **内嵌模式** — 作为主应用的子路由挂载 (``/mock-workflow/{profile_id}/v1/...``)，
   从 ``MockProfile.profile_data`` 动态读取 Mock 数据。
2. **独立模式** — ``python -m app.services.workflow_mock_server`` 启动独立 FastAPI
   进程 (默认端口 30001)，使用 v4 兼容的硬编码 Mock 数据，
   与原 ``mock_workflow_server_v4.py`` 端点 100% 兼容。

支持的工作流类型（由用户 query 关键词路由）:
  wealth_purchase → 理财购买/申购结果
  transfer → 转账
  balance_query → 余额
  wealth_recommend → 产品推荐

SSE 流式响应格式保持与 VersatileProxy 兼容:
  Start → LLM (推理步骤) → QA / BusinessResult → End
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, AsyncGenerator

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  共享常量
# ---------------------------------------------------------------------------

DEFAULT_WORKFLOW_RESULT_NODE = os.getenv("PROXY_WORKFLOW_RESULT_NODE", "GXZQAResponseNode")
LLM_NODE = os.getenv("PROXY_LLM_NODE", "LLMNode")

# v4 兼容硬编码数据 (独立模式使用)
_V4_PRODUCT_FILTER: dict[str, Any] = {
    "bankCardNumber": "6605",
    "productList": (
        "[{'productCode': 'XLT1801', 'productName': '工银理财「添利宝」净值型理财产品(XLT1801)', "
        "'productType': '固定收益类', 'profitValue': '3.2%', 'riskLevel': 'R2'}, "
        "{'productCode': 'WM002', 'productName': '稳健增长理财计划(WM002)', "
        "'productType': '混合类', 'profitValue': '4.5%', 'riskLevel': 'R3'}, "
        "{'productCode': 'JJ003', 'productName': '进取型权益理财(JJ003)', "
        "'productType': '权益类', 'profitValue': '6.8%', 'riskLevel': 'R4'}]"
    ),
}

_V4_WEALTH_PURCHASE: dict[str, Any] = {
    "default_product_code": "XLT1801",
    "default_product_name": "工银理财「添利宝」净值型理财产品(XLT1801)",
    "default_amount": 1000.0,
    "default_purchase_status": "成功",
    "fail_cause": "",
    "default_confirmed_shares": 987.65,
    "order_id_prefix": "ORD",
}

# conversation_id -> 最近一次 wealth_recommend 的产品列表（用于 wealth_purchase 的“上下关联”）
_MOCK_CONV_WEALTH_CACHE: dict[str, dict[str, Any]] = {}
_MOCK_CONV_WEALTH_CACHE_TTL_SECONDS = int(os.environ.get("MOCK_CONV_WEALTH_CACHE_TTL_SECONDS", "3600"))

# conversation_id -> active MockProfile 映射（用于独立模式端点不带 profile_id 时仍能取到 profile_data）
_MOCK_CONV_PROFILE_ID: dict[str, dict[str, Any]] = {}
_MOCK_CONV_PROFILE_ID_TTL_SECONDS = int(os.environ.get("MOCK_CONV_PROFILE_ID_TTL_SECONDS", "3600"))

# conversation_id -> 已选中的推荐产品（用于后续“确认购买结果”等轮次不再重复产品名时仍保持一致）
_MOCK_CONV_SELECTED_PRODUCT: dict[str, dict[str, Any]] = {}
_MOCK_CONV_SELECTED_PRODUCT_TTL_SECONDS = int(os.environ.get("MOCK_CONV_SELECTED_PRODUCT_TTL_SECONDS", "3600"))


def set_mock_profile_for_conversation(conversation_id: str, profile_id: str | None) -> None:
    if not conversation_id or not profile_id:
        return
    _MOCK_CONV_PROFILE_ID[conversation_id] = {"profile_id": profile_id, "ts": time.time()}


def _get_mock_profile_for_conversation(conversation_id: str) -> dict[str, Any]:
    entry = _MOCK_CONV_PROFILE_ID.get(conversation_id)
    if not entry:
        return {}
    ts = float(entry.get("ts", 0) or 0)
    if _MOCK_CONV_PROFILE_ID_TTL_SECONDS > 0 and time.time() - ts > _MOCK_CONV_PROFILE_ID_TTL_SECONDS:
        _MOCK_CONV_PROFILE_ID.pop(conversation_id, None)
        return {}
    pid = entry.get("profile_id")
    if not pid:
        return {}
    try:
        return _load_profile(str(pid))
    except Exception:
        return {}


def _cache_get_selected_product(conversation_id: str) -> dict[str, Any] | None:
    entry = _MOCK_CONV_SELECTED_PRODUCT.get(conversation_id)
    if not entry:
        return None
    ts = float(entry.get("ts", 0) or 0)
    if _MOCK_CONV_SELECTED_PRODUCT_TTL_SECONDS > 0 and time.time() - ts > _MOCK_CONV_SELECTED_PRODUCT_TTL_SECONDS:
        _MOCK_CONV_SELECTED_PRODUCT.pop(conversation_id, None)
        return None
    return entry.get("product")


def _cache_set_selected_product(conversation_id: str, product: dict[str, Any]) -> None:
    _MOCK_CONV_SELECTED_PRODUCT[conversation_id] = {"product": product, "ts": time.time()}

# ---------------------------------------------------------------------------
#  工具函数
# ---------------------------------------------------------------------------


def _detect_workflow_type(query: str) -> str:
    """关键词优先级：购买类先于「理财/产品」，避免「购买理财」误走推荐。"""
    q = query.lower()
    if any(kw in q for kw in ("购买", "申购", "下单", "认购", "买入")):
        return "wealth_purchase"
    if any(kw in q for kw in ("转账", "转钱", "汇款")):
        return "transfer"
    if any(kw in q for kw in ("查询", "余额", "账户")):
        return "balance_query"
    if any(kw in q for kw in ("推荐", "理财", "产品")):
        return "wealth_recommend"
    return "unknown"


def _parse_product_list_string(raw: str) -> list[dict[str, Any]] | None:
    """将 profile / v4 中类 Python 列表字符串解析为字典列表（仅用于展示与调试）。"""
    s = raw.strip()
    if not s:
        return None
    try:
        val = ast.literal_eval(s)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
    except (SyntaxError, ValueError, TypeError):
        pass
    try:
        val = json.loads(s)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _normalize_product_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """把 productList 中的不同字段命名，统一成前端/展示所需的键。"""
    if not isinstance(row, dict):
        return None

    code = row.get("productCode") or row.get("product_code") or row.get("code")
    name = row.get("productName") or row.get("product_name") or row.get("name")
    profit = row.get("profitValue") or row.get("profit") or row.get("expected_return")
    risk = row.get("riskLevel") or row.get("risk_level")

    if not code and not name:
        return None

    return {
        "productCode": str(code or ""),
        "productName": str(name or ""),
        "profitValue": profit if profit is not None else "",
        "riskLevel": risk if risk is not None else "",
    }


def _normalize_product_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not rows:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        nr = _normalize_product_row(r)
        if nr:
            out.append(nr)
    return out


def _cache_get_products(conversation_id: str) -> list[dict[str, Any]] | None:
    entry = _MOCK_CONV_WEALTH_CACHE.get(conversation_id)
    if not entry:
        return None
    ts = float(entry.get("ts", 0) or 0)
    if _MOCK_CONV_WEALTH_CACHE_TTL_SECONDS > 0 and time.time() - ts > _MOCK_CONV_WEALTH_CACHE_TTL_SECONDS:
        _MOCK_CONV_WEALTH_CACHE.pop(conversation_id, None)
        return None
    return entry.get("products")


def _cache_set_recommend_products(conversation_id: str, products: list[dict[str, Any]]) -> None:
    _MOCK_CONV_WEALTH_CACHE[conversation_id] = {"products": products, "ts": time.time()}


def compute_mock_preview(profile_data: dict[str, Any]) -> dict[str, Any]:
    """合并默认值后的 Mock 数据快照，供页面展示与 ``GET .../workflow-preview`` 使用。"""
    wr = profile_data.get("wealth_recommend") or {}
    if not isinstance(wr, dict):
        wr = {}
    bank_card = wr.get("bankCardNumber", _V4_PRODUCT_FILTER["bankCardNumber"])
    plist_raw = wr.get("productList", _V4_PRODUCT_FILTER["productList"])
    if isinstance(plist_raw, str):
        plist_parsed = _parse_product_list_string(plist_raw)
        plist_display = plist_raw
    elif isinstance(plist_raw, list):
        plist_parsed = [x for x in plist_raw if isinstance(x, dict)]
        plist_display = json.dumps(plist_raw, ensure_ascii=False)
    else:
        plist_parsed = None
        plist_display = json.dumps(plist_raw, ensure_ascii=False) if plist_raw is not None else ""

    plist_products = _normalize_product_rows(plist_parsed or [])
    wealth_recommend = {
        "bankCardNumber": bank_card,
        "productList_raw": plist_display,
        "products": plist_products,
        "node_name": wr.get("node_name", DEFAULT_WORKFLOW_RESULT_NODE),
    }

    bq = profile_data.get("balance_query") or {}
    if not isinstance(bq, dict):
        bq = {}
    cards: list[dict[str, Any]] = []
    card_bal_re = re.compile(r"^card_(\d{4})_balance$")
    for k, v in sorted(bq.items()):
        m = card_bal_re.match(str(k))
        if m:
            tail = m.group(1)
            try:
                bal = float(v)
            except (TypeError, ValueError):
                bal = 0.0
            cards.append({
                "card_tail": tail,
                "masked_number": f"6222****{tail}",
                "balance_cny": bal,
            })
    default_tail = str(bq.get("default_card_tail", "") or "")
    if not cards and default_tail and re.fullmatch(r"\d{4}", default_tail):
        try:
            bal = float(bq.get(f"card_{default_tail}_balance", bq.get("default_balance", 50000.0)))
        except (TypeError, ValueError):
            bal = 50000.0
        cards.append({
            "card_tail": default_tail,
            "masked_number": f"6222****{default_tail}",
            "balance_cny": bal,
        })
    if not cards:
        cards = [
            {"card_tail": "3344", "masked_number": "6222****3344", "balance_cny": 125680.5},
            {"card_tail": "1122", "masked_number": "6222****1122", "balance_cny": 30000.0},
        ]
    balance_query = {"cards": cards, "config": bq}

    tr = profile_data.get("transfer") or {}
    if not isinstance(tr, dict):
        tr = {}
    transfer = {
        "default_amount": float(tr.get("default_amount", 1000.0)),
        "default_status": tr.get("default_status", "成功"),
        "fail_cause": tr.get("fail_cause", ""),
        "node_name": tr.get("node_name", DEFAULT_WORKFLOW_RESULT_NODE),
        "config": tr,
    }

    wp = profile_data.get("wealth_purchase") or {}
    if not isinstance(wp, dict):
        wp = {}
    wealth_purchase = {
        "default_product_code": wp.get("default_product_code", _V4_WEALTH_PURCHASE["default_product_code"]),
        "default_product_name": wp.get("default_product_name", _V4_WEALTH_PURCHASE["default_product_name"]),
        "default_amount": float(wp.get("default_amount", _V4_WEALTH_PURCHASE["default_amount"])),
        "default_purchase_status": wp.get("default_purchase_status", _V4_WEALTH_PURCHASE["default_purchase_status"]),
        "fail_cause": wp.get("fail_cause", _V4_WEALTH_PURCHASE["fail_cause"]),
        "default_confirmed_shares": float(
            wp.get("default_confirmed_shares", _V4_WEALTH_PURCHASE["default_confirmed_shares"]),
        ),
        "order_id_prefix": wp.get("order_id_prefix", _V4_WEALTH_PURCHASE["order_id_prefix"]),
        "node_name": wp.get("node_name", DEFAULT_WORKFLOW_RESULT_NODE),
        "config": wp,
    }

    # 让“购买默认产品”与“推荐的多条产品列表”对齐：
    # - 若 profile_data 指定 selected_product_code/name，则购买只选其中一条；
    # - 否则若 default_product_code 能在推荐列表中找到，也使用推荐列表里的对应名称。
    def _find_reco_by_code(code: str) -> dict[str, Any] | None:
        if not code:
            return None
        t = str(code).upper()
        for p in plist_products:
            if str(p.get("productCode", "")).upper() == t:
                return p
        return None

    def _find_reco_by_name_substring(name: str) -> dict[str, Any] | None:
        if not name:
            return None
        q_norm = re.sub(r"\s+", "", name or "")
        if not q_norm:
            return None
        for p in plist_products:
            pn = str(p.get("productName", "")).strip()
            pn_norm = re.sub(r"\s+", "", pn)
            if pn_norm and pn_norm in q_norm:
                return p
        return None

    resolved = None
    wp_sel_code = wp.get("selected_product_code")
    wp_sel_name = wp.get("selected_product_name")
    if wp_sel_code:
        resolved = _find_reco_by_code(str(wp_sel_code))
    if not resolved and wp_sel_name:
        resolved = _find_reco_by_name_substring(str(wp_sel_name))
    if not resolved:
        resolved = _find_reco_by_code(str(wealth_purchase.get("default_product_code", "")))
    if not resolved and plist_products:
        # 若完全没指定，则默认选择推荐列表的第一条（保证“只能买推荐里的某一条”）。
        resolved = plist_products[0]

    if resolved:
        wealth_purchase["default_product_code"] = str(resolved.get("productCode", wealth_purchase["default_product_code"]))
        wealth_purchase["default_product_name"] = str(resolved.get("productName", wealth_purchase["default_product_name"]))

    return {
        "wealth_recommend": wealth_recommend,
        "balance_query": balance_query,
        "transfer": transfer,
        "wealth_purchase": wealth_purchase,
    }


def _extract_query(body: dict[str, Any]) -> str:
    if "input" in body and isinstance(body["input"], dict):
        q = body["input"].get("query", "")
        if q:
            return q
    if "custom_data" in body and isinstance(body["custom_data"], dict):
        inputs = body["custom_data"].get("inputs", {})
        if isinstance(inputs, dict):
            q = inputs.get("query", "")
            if q:
                return q
    if "inputs" in body and isinstance(body["inputs"], dict):
        q = body["inputs"].get("query", "")
        if q:
            return q
    return body.get("query", "")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _validate_cookie(cookie: str) -> tuple[bool, str]:
    if not cookie:
        return False, "Cookie header is required"
    if "AGENT_SID=" not in cookie:
        return False, "AGENT_SID is required in Cookie"
    match = re.search(r"AGENT_SID=([^;]+)", cookie)
    if not match:
        return False, "Invalid AGENT_SID format"
    sid = match.group(1)
    redacted = f"{sid[:4]}…" if len(sid) > 4 else "****"
    _log.info("[MockServer] Cookie验证通过: AGENT_SID=%s", redacted)
    return True, ""


# ---------------------------------------------------------------------------
#  SSE 流式响应生成器（数据源可注入）
# ---------------------------------------------------------------------------


async def _wealth_recommend_stream(
    profile_data: dict[str, Any], query: str, conversation_id: str,
) -> AsyncGenerator[str, None]:
    wr = profile_data.get("wealth_recommend", {})
    # 将本次推荐的产品列表缓存到 conversation_id，供后续 wealth_purchase 进行“上下关联”
    plist_raw = wr.get("productList", _V4_PRODUCT_FILTER["productList"])
    plist_rows: list[dict[str, Any]] = []
    if isinstance(plist_raw, str):
        plist_rows = _parse_product_list_string(plist_raw) or []
    elif isinstance(plist_raw, list):
        plist_rows = [x for x in plist_raw if isinstance(x, dict)]
    plist_norm = _normalize_product_rows(plist_rows)
    _cache_set_recommend_products(conversation_id, plist_norm)
    _log.info(
        "[MockServer] wealth_recommend conv=%s productCodes=%s",
        conversation_id,
        [p.get("productCode") for p in plist_norm],
    )

    product_filter = {
        "bankCardNumber": wr.get("bankCardNumber", _V4_PRODUCT_FILTER["bankCardNumber"]),
        # 统一输出成“Python 字面量字符串”，避免下游解析因字段名/类型不一致而回退默认
        "productList": str(plist_norm) if plist_norm else wr.get("productList", _V4_PRODUCT_FILTER["productList"]),
    }

    yield _sse({"node_type": "Start", "node_name": "StartNode", "conversation_id": conversation_id})
    await asyncio.sleep(0.2)

    for step in ("正在分析您的资金情况...", "正在匹配理财产品...", "正在计算推荐结果..."):
        yield _sse({"text": step, "node_type": "LLM", "node_name": LLM_NODE})
        await asyncio.sleep(0.3)

    node_name = wr.get("node_name", DEFAULT_WORKFLOW_RESULT_NODE)
    yield _sse({
        "data": {
            "node_name": node_name,
            "node_type": "QA",
            "text": json.dumps(product_filter, ensure_ascii=False, separators=(",", ":")),
        }
    })
    await asyncio.sleep(0.1)
    yield _sse({"node_type": "End", "node_name": "EndNode"})


async def _balance_query_stream(
    profile_data: dict[str, Any], query: str, conversation_id: str,
) -> AsyncGenerator[str, None]:
    bq = profile_data.get("balance_query", {})

    yield _sse({"node_type": "Start", "node_name": "StartNode", "conversation_id": conversation_id})
    await asyncio.sleep(0.2)

    yield _sse({"text": "正在查询账户信息...", "node_type": "LLM", "node_name": LLM_NODE})
    await asyncio.sleep(0.3)
    yield _sse({"text": "正在获取余额数据...", "node_type": "LLM", "node_name": LLM_NODE})
    await asyncio.sleep(0.3)

    tail_match = re.search(r"尾号为?(\d{4})", query)
    requested_tail = tail_match.group(1) if tail_match else ""

    same_card_mode = os.environ.get("MOCK_BALANCE_SAME_CARD", "false").lower() == "true"

    if requested_tail:
        balance_key = f"card_{requested_tail}_balance"
        cny_balance = float(bq.get(balance_key, 1000.0 if requested_tail == "1122" else 50000.0))
        card_tail = requested_tail
    else:
        if bq:
            card_tail = str(bq.get("default_card_tail", "3344"))
            cny_balance = float(bq.get(f"card_{card_tail}_balance", bq.get("default_balance", 50000.0)))
        else:
            card_tail = "1122" if same_card_mode else "3344"
            cny_balance = 30000.0 if same_card_mode else 125680.5

    balance_data = {
        "bankCardBalanceList": [{
            "bankCardNumber": f"6222****{card_tail}",
            "queryStatus": "成功",
            "currencyBalanceList": [{"currencyCode": "CNY", "balance": cny_balance}],
        }]
    }

    node_name = bq.get("node_name", DEFAULT_WORKFLOW_RESULT_NODE)
    yield _sse({
        "data": {
            "node_name": node_name,
            "node_type": "QA",
            "text": json.dumps(balance_data, ensure_ascii=False, separators=(",", ":")),
        }
    })
    await asyncio.sleep(0.1)
    yield _sse({"node_type": "End", "node_name": "EndNode"})


def _extract_purchase_amount(query: str) -> float | None:
    for pat in (
        r"购买\s*(\d+(?:\.\d+)?)\s*元",
        r"申购\s*(\d+(?:\.\d+)?)\s*元",
        r"买入\s*(\d+(?:\.\d+)?)\s*元",
        r"(\d+(?:\.\d+)?)\s*元\s*购买",
    ):
        m = re.search(pat, query)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def _extract_product_code_from_query(query: str) -> str | None:
    m = re.search(r"(?:产品代码|产品编号|代码)[:：]?\s*([A-Za-z0-9]+)", query)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b([A-Z]{2,}\d+)\b", query)
    return m.group(1) if m else None


async def _wealth_purchase_stream(
    profile_data: dict[str, Any], query: str, conversation_id: str,
) -> AsyncGenerator[str, None]:
    wp = profile_data.get("wealth_purchase", {})
    if not isinstance(wp, dict):
        wp = {}

    yield _sse({"node_type": "Start", "node_name": "StartNode", "conversation_id": conversation_id})
    await asyncio.sleep(0.2)

    for step in ("正在校验产品状态...", "正在检查账户与风险等级...", "正在提交申购指令..."):
        yield _sse({"text": step, "node_type": "LLM", "node_name": LLM_NODE})
        await asyncio.sleep(0.3)

    amount = _extract_purchase_amount(query)
    if amount is None:
        try:
            amount = float(wp.get("default_amount", _V4_WEALTH_PURCHASE["default_amount"]))
        except (TypeError, ValueError):
            amount = float(_V4_WEALTH_PURCHASE["default_amount"])

    code_from_q = _extract_product_code_from_query(query)

    # 默认购买产品（兜底）
    product_code = str(wp.get("default_product_code", _V4_WEALTH_PURCHASE["default_product_code"]))
    product_name = str(wp.get("default_product_name", _V4_WEALTH_PURCHASE["default_product_name"]))

    # 推荐列表（多条）用于做“购买只能从推荐里选”。
    cached_products = _cache_get_products(conversation_id) or []

    def _match_from_cached_by_code(target_code: str) -> dict[str, Any] | None:
        t = str(target_code).upper()
        for p in cached_products:
            if str(p.get("productCode", "")).upper() == t:
                return p
        return None

    def _match_from_cached_by_name_substring(target_name: str) -> dict[str, Any] | None:
        q_norm = re.sub(r"\s+", "", (target_name or ""))
        if not q_norm:
            return None
        for p in cached_products:
            pn = str(p.get("productName", "")).strip()
            pn_norm = re.sub(r"\s+", "", pn)
            if pn_norm and pn_norm in q_norm:
                return p
        return None

    # 选择顺序（可泛化到类似场景）：
    # 1) wealth_purchase.selected_product_code/name（profile_data 显式选择）
    # 2) 从用户话术提取的 product code / product name（如“这个稳健增长混合基金不错，我想买…”）
    # 3) 如果后续轮次不再包含产品信息，则沿用上一轮已选中的推荐产品
    # 4) 兜底：default_product_code
    selected_from_wp: dict[str, Any] | None = None
    wp_sel_code = wp.get("selected_product_code")
    wp_sel_name = wp.get("selected_product_name")
    if wp_sel_code:
        selected_from_wp = _match_from_cached_by_code(str(wp_sel_code))
    if not selected_from_wp and wp_sel_name:
        # 允许用户在 profile_data 写“产品名”，我们用名称做子串匹配
        selected_from_wp = _match_from_cached_by_name_substring(str(wp_sel_name))
    if selected_from_wp:
        product_code = str(selected_from_wp.get("productCode", product_code) or product_code)
        product_name = str(selected_from_wp.get("productName", product_name) or product_name)
        _cache_set_selected_product(conversation_id, selected_from_wp)
    else:
        # 即使 cached_products 为空，也允许 profile_data 显式指定 selected_product_code/name，
        # 从而保证“只购买其中一条”。
        if wp_sel_code:
            product_code = str(wp_sel_code)
        if wp_sel_name:
            product_name = str(wp_sel_name)
        # 从话术抽取
        matched = None
        if code_from_q and cached_products:
            matched = _match_from_cached_by_code(code_from_q)
        if not matched and cached_products:
            q_norm = re.sub(r"\s+", "", query or "")
            for p in cached_products:
                pn = str(p.get("productName", "")).strip()
                pn_norm = re.sub(r"\s+", "", pn)
                if pn_norm and pn_norm in q_norm:
                    matched = p
                    break
        if matched:
            product_code = str(matched.get("productCode", product_code) or product_code)
            product_name = str(matched.get("productName", product_name) or product_name)
            _cache_set_selected_product(conversation_id, matched)
        else:
            # 若当前轮次没有明确产品信息，则沿用上一轮已选产品
            prev_sel = _cache_get_selected_product(conversation_id)
            if prev_sel:
                product_code = str(prev_sel.get("productCode", product_code) or product_code)
                product_name = str(prev_sel.get("productName", product_name) or product_name)

    status = str(wp.get("default_purchase_status", _V4_WEALTH_PURCHASE["default_purchase_status"]))
    fail_cause = str(wp.get("fail_cause", _V4_WEALTH_PURCHASE["fail_cause"]))
    try:
        shares = float(wp.get("default_confirmed_shares", _V4_WEALTH_PURCHASE["default_confirmed_shares"]))
    except (TypeError, ValueError):
        shares = float(_V4_WEALTH_PURCHASE["default_confirmed_shares"])
    prefix = str(wp.get("order_id_prefix", _V4_WEALTH_PURCHASE["order_id_prefix"]))

    purchase_payload = {
        "wealthPurchase": {
            "purchaseStatus": status,
            "failCause": fail_cause if status != "成功" else "",
            "productCode": product_code,
            "productName": product_name,
            "appliedAmount": amount,
            "confirmedShares": shares,
            "orderId": f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    }

    node_name = wp.get("node_name", DEFAULT_WORKFLOW_RESULT_NODE)
    yield _sse({
        "data": {
            "node_name": node_name,
            "node_type": "QA",
            "text": json.dumps(purchase_payload, ensure_ascii=False, separators=(",", ":")),
        }
    })
    await asyncio.sleep(0.1)
    yield _sse({"node_type": "End", "node_name": "EndNode"})


async def _transfer_stream(
    profile_data: dict[str, Any], query: str, conversation_id: str,
) -> AsyncGenerator[str, None]:
    tr_cfg = profile_data.get("transfer", {})

    yield _sse({"node_type": "Start", "node_name": "StartNode", "conversation_id": conversation_id})
    await asyncio.sleep(0.2)

    for step in ("正在验证账户信息...", "正在进行风控校验...", "正在执行转账..."):
        yield _sse({"text": step, "node_type": "LLM", "node_name": LLM_NODE})
        await asyncio.sleep(0.3)

    amount_match = re.search(r"转账(\d+(?:\.\d+)?)元", query)
    actual_amount = float(amount_match.group(1)) if amount_match else float(tr_cfg.get("default_amount", 1000.0))

    transfer_data = {
        "transferRemit": {
            "transferStatus": tr_cfg.get("default_status", "成功"),
            "failCause": tr_cfg.get("fail_cause", ""),
            "actualTransferredAmount": actual_amount,
            "transactionId": f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    }

    node_name = tr_cfg.get("node_name", DEFAULT_WORKFLOW_RESULT_NODE)
    yield _sse({
        "data": {
            "node_name": node_name,
            "node_type": "QA",
            "text": json.dumps(transfer_data, ensure_ascii=False, separators=(",", ":")),
        }
    })
    await asyncio.sleep(0.1)
    yield _sse({"node_type": "End", "node_name": "EndNode"})


async def _unknown_stream(query: str, conversation_id: str) -> AsyncGenerator[str, None]:
    yield _sse({
        "node_name": DEFAULT_WORKFLOW_RESULT_NODE,
        "node_type": "QA",
        "data": {"text": json.dumps({"error": "未知工作流类型", "query": query}, ensure_ascii=False)},
    })
    await asyncio.sleep(0.05)
    yield _sse({"node_type": "End", "node_name": "EndNode"})


async def _dispatch_stream(
    profile_data: dict[str, Any], query: str, conversation_id: str,
) -> StreamingResponse:
    wf_type = _detect_workflow_type(query)
    if wf_type == "wealth_recommend":
        gen = _wealth_recommend_stream(profile_data, query, conversation_id)
    elif wf_type == "balance_query":
        gen = _balance_query_stream(profile_data, query, conversation_id)
    elif wf_type == "transfer":
        gen = _transfer_stream(profile_data, query, conversation_id)
    elif wf_type == "wealth_purchase":
        gen = _wealth_purchase_stream(profile_data, query, conversation_id)
    else:
        gen = _unknown_stream(query, conversation_id)
    return StreamingResponse(gen, media_type="text/event-stream")


# =========================================================================
#  模式 1: 内嵌子路由 (挂载到主应用, 数据源为 MockProfile DB)
# =========================================================================

router = APIRouter()


def _load_profile(profile_id: str) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.db.models import MockProfile
    db = SessionLocal()
    try:
        mp = db.get(MockProfile, profile_id)
        if not mp:
            raise HTTPException(404, detail="MockProfile not found")
        data = mp.profile_data or {}
        # 只记录顶层 keys，避免把大段 profile_data 写入日志
        _log.info("[MockServer] load profile_id=%s keys=%s", profile_id, list(data.keys()))
        return data
    finally:
        db.close()


@router.post("/mock-workflow/{profile_id}/v1/chat/{conversation_id}")
@router.post("/mock-workflow/{profile_id}/v1/0/agent-manager/workflows/{workflow_id}/conversations/{conversation_id}")
async def mock_workflow_entry(profile_id: str, conversation_id: str, request: Request, workflow_id: str = ""):
    profile_data = _load_profile(profile_id)
    try:
        body = await request.json()
    except Exception:
        body = {}
    query = _extract_query(body)
    wf_type = _detect_workflow_type(query)
    _log.info("[MockWorkflow] profile=%s conv=%s type=%s query=%s", profile_id, conversation_id, wf_type, query[:60])
    return await _dispatch_stream(profile_data, query, conversation_id)


@router.get("/mock-workflow/{profile_id}/health")
async def mock_workflow_health(profile_id: str):
    profile_data = _load_profile(profile_id)
    return {
        "status": "healthy",
        "profile_id": profile_id,
        "workflows": list(profile_data.keys()),
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/mock-workflow/{profile_id}/preview")
async def mock_workflow_preview(profile_id: str):
    """返回合并默认值后的理财/余额/转账/购买 Mock 快照，便于页面展示。"""
    profile_data = _load_profile(profile_id)
    return {"profile_id": profile_id, **compute_mock_preview(profile_data)}


# =========================================================================
#  模式 2: 独立 FastAPI 应用 (v4 兼容, 硬编码数据, 独立端口)
# =========================================================================


def create_standalone_app() -> FastAPI:
    """创建独立运行的 Mock Workflow FastAPI 应用（v4 兼容）。"""

    app = FastAPI(
        title="Mock Workflow Server",
        description="独立 Mock 工作流服务器，兼容 AgentEngine VersatileProxy",
        version="4.1.0",
    )

    skip_cookie_auth = os.environ.get("MOCK_SKIP_COOKIE_AUTH", "true").lower() == "true"

    @app.post("/v1/chat/{conversation_id}")
    async def legacy_entry(conversation_id: str, request: Request):
        body = await _safe_json(request)
        query = _extract_query(body)
        _log.info("[MockServer] legacy conv=%s type=%s query=%s", conversation_id, _detect_workflow_type(query), query[:60])
        profile_data = _get_mock_profile_for_conversation(conversation_id)
        return await _dispatch_stream(profile_data, query, conversation_id)

    @app.post("/v1/0/agent-manager/workflows/{workflow_id}/conversations/{conversation_id}")
    async def new_entry(
        workflow_id: str,
        conversation_id: str,
        request: Request,
        cookie: str = Header(None, alias="Cookie"),
    ):
        if not skip_cookie_auth:
            ok, err = _validate_cookie(cookie or "")
            if not ok:
                raise HTTPException(401, detail={"error": "Unauthorized", "message": err})

        body = await _safe_json(request)
        query = _extract_query(body)
        _log.info("[MockServer] new conv=%s wf=%s type=%s query=%s", conversation_id, workflow_id, _detect_workflow_type(query), query[:60])
        profile_data = _get_mock_profile_for_conversation(conversation_id)
        return await _dispatch_stream(profile_data, query, conversation_id)

    @app.post("/mock-workflow/{profile_id}/v1/chat/{conversation_id}")
    @app.post("/mock-workflow/{profile_id}/v1/0/agent-manager/workflows/{workflow_id}/conversations/{conversation_id}")
    async def profile_entry(profile_id: str, conversation_id: str, request: Request, workflow_id: str = ""):
        try:
            profile_data = _load_profile(profile_id)
        except Exception:
            profile_data = {}
        body = await _safe_json(request)
        query = _extract_query(body)
        _log.info("[MockServer] profile=%s conv=%s type=%s query=%s", profile_id, conversation_id, _detect_workflow_type(query), query[:60])
        return await _dispatch_stream(profile_data, query, conversation_id)

    @app.get("/mock-workflow/{profile_id}/health")
    async def profile_health(profile_id: str):
        try:
            profile_data = _load_profile(profile_id)
        except Exception:
            profile_data = {}
        return {
            "status": "healthy",
            "profile_id": profile_id,
            "workflows": list(profile_data.keys()),
            "timestamp": datetime.now().isoformat(),
        }

    @app.get("/mock-workflow/{profile_id}/preview")
    async def profile_preview(profile_id: str):
        try:
            profile_data = _load_profile(profile_id)
        except Exception:
            profile_data = {}
        return {"profile_id": profile_id, **compute_mock_preview(profile_data)}

    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "version": "v4.1-standalone",
            "node_names": {
                "default": DEFAULT_WORKFLOW_RESULT_NODE,
                "llm": LLM_NODE,
            },
            "config": {
                "skip_cookie_auth": skip_cookie_auth,
            },
            "timestamp": datetime.now().isoformat(),
        }

    return app


async def _safe_json(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


# =========================================================================
#  主应用启动时自动拉起独立 Mock 服务器 (后台线程)
# =========================================================================

_mock_server_process = None


def _port_in_use(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def start_standalone_mock_server() -> None:
    """在后台线程中启动独立 Mock 服务器。由主应用 startup 事件调用。"""
    import threading

    from app.config import get_settings
    settings = get_settings()
    host = settings.mock_server_host
    port = settings.mock_server_port

    if _port_in_use(host, port):
        _log.info("Mock Workflow Server 端口 %d 已被占用，跳过启动（可能已有实例运行）", port)
        return

    def _run():
        import uvicorn
        mock_app = create_standalone_app()
        _log.info("Mock Workflow Server 启动中... http://%s:%d", host, port)
        uvicorn.run(mock_app, host=host, port=port, log_level="info")

    t = threading.Thread(target=_run, daemon=True, name="mock-workflow-server")
    t.start()
    _log.info("Mock Workflow Server 后台线程已启动 (port=%d)", port)


# =========================================================================
#  __main__: 直接运行 ``python -m app.services.workflow_mock_server``
# =========================================================================

if __name__ == "__main__":
    import sys
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    port = int(os.environ.get("MOCK_SERVER_PORT", "30001"))
    host = os.environ.get("MOCK_SERVER_HOST", "127.0.0.1")

    print("=" * 60)
    print("Mock Workflow Server 启动中...")
    print(f"服务地址: http://{host}:{port}")
    print(f"健康检查: http://{host}:{port}/health")
    print(f"旧版端点: http://{host}:{port}/v1/chat/{{conversation_id}}")
    print(f"新版端点: http://{host}:{port}/v1/0/agent-manager/workflows/{{workflow_id}}/conversations/{{conversation_id}}")
    print("-" * 60)
    print(f"节点名称: default={DEFAULT_WORKFLOW_RESULT_NODE}, llm={LLM_NODE}")
    print(f"Cookie 验证: {'跳过' if os.environ.get('MOCK_SKIP_COOKIE_AUTH', 'true').lower() == 'true' else '启用'}")
    print("=" * 60)

    standalone_app = create_standalone_app()
    uvicorn.run(standalone_app, host=host, port=port)
