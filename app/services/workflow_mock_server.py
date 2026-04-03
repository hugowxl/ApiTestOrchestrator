"""内嵌 + 独立运行工作流 Mock 服务器。

两种运行模式:
1. **内嵌模式** — 作为主应用的子路由挂载 (``/mock-workflow/{profile_id}/v1/...``)，
   从 ``MockProfile.profile_data`` 动态读取 Mock 数据。
2. **独立模式** — ``python -m app.services.workflow_mock_server`` 启动独立 FastAPI
   进程 (默认端口 30001)，使用 v4 兼容的硬编码 Mock 数据，
   与原 ``mock_workflow_server_v4.py`` 端点 100% 兼容。

SSE 流式响应格式保持与 VersatileProxy 兼容:
  Start → LLM (推理步骤) → QA / BusinessResult → End
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
#  工具函数
# ---------------------------------------------------------------------------


def _detect_workflow_type(query: str) -> str:
    q = query.lower()
    if any(kw in q for kw in ("推荐", "理财", "产品")):
        return "wealth_recommend"
    if any(kw in q for kw in ("查询", "余额", "账户")):
        return "balance_query"
    if any(kw in q for kw in ("转账", "转钱", "汇款")):
        return "transfer"
    return "unknown"


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
    _log.info("[MockServer] Cookie验证通过: AGENT_SID=%s", match.group(1))
    return True, ""


# ---------------------------------------------------------------------------
#  SSE 流式响应生成器（数据源可注入）
# ---------------------------------------------------------------------------


async def _wealth_recommend_stream(
    profile_data: dict[str, Any], query: str, conversation_id: str,
) -> AsyncGenerator[str, None]:
    wr = profile_data.get("wealth_recommend", {})
    product_filter = {
        "bankCardNumber": wr.get("bankCardNumber", _V4_PRODUCT_FILTER["bankCardNumber"]),
        "productList": wr.get("productList", _V4_PRODUCT_FILTER["productList"]),
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
        return mp.profile_data or {}
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
        return await _dispatch_stream({}, query, conversation_id)

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
        return await _dispatch_stream({}, query, conversation_id)

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
