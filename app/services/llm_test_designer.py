"""组装 Prompt、调用 LLM、校验 Schema 并写入 test_suite / test_case。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Endpoint, TestCase, TestCaseStatus, TestSuite
from app.schemas.test_case_schema import validate_llm_test_design_normalized
from app.services.llm_client import LLMClient
from app.utils.errors import AppError, ErrorCode
from app.utils.generate_trace import tlog

SYSTEM_SINGLE = """你是 API 测试设计专家。只根据用户提供的 OpenAPI 片段推断，不要编造文档中未出现的路径或字段名。
必须只输出一个 JSON 对象，不要 Markdown 代码围栏，不要前后说明文字。

【输出结构必须严格符合下列契约，缺一即无效】
- endpoint_summary: string
- dependencies: string 数组；无法推断时用 ["unknown"]，禁止用单个字符串 "unknown"
- test_cases: 数组；每一项必须同时包含：
  - id: 唯一字符串，如 "tc-001"
  - name: 简短中文或英文标题
  - steps: 非空数组；每一步是一次真实 HTTP 调用对象，至少含 method、path；常用 body_type: "none"|"json"|"form"|"raw"；用 assertions 断言结果（type 必填，如 status_code + value）
- 可选 tags: string 数组；variables: 对象且【所有值为字符串】——禁止数字/布尔裸值，必须写成 "123"、"true" 这种字符串
- path 与 OpenAPI 一致；占位符 {{{{varName}}}} 与 variables 键对应
- dependencies 必须是 JSON 数组，例如 ["auth"] 或 ["unknown"]，绝不能写成单个字符串"""

USER_SINGLE_TEMPLATE = """【OpenAPI 片段】
{spec}

【任务】
1. 写 endpoint_summary：2～4 句话说明业务意图与调用前提（如认证）。
2. 写 dependencies：字符串数组；无则 ["unknown"]。
3. 设计 3～8 条 test_cases；每条必须是「可执行的多步 HTTP 场景」，禁止只写 method/path/expected_status 的扁平字段——必须包在 steps 数组里，每步含 method、path、body_type、assertions 等。

【最小合法示例（结构示意，path 请换成文档中的真实路径）】
{{"endpoint_summary":"…","dependencies":["unknown"],"test_cases":[{{"id":"tc-001","name":"成功删除","steps":[{{"method":"DELETE","path":"/api/…/{{{{agent_id}}}}","body_type":"none","assertions":[{{"type":"status_code","value":200}}]}}],"variables":{{"agent_id":"valid-id"}}}}]}}

【输出】
- 仅输出 JSON；不要真实密钥，用占位符。"""

SYSTEM_REPAIR = """你是 JSON 修复助手。用户提供的对象用于「API 测试设计」，但未通过 jsonschema 校验。
请输出**仅一个**修正后的完整 JSON 对象：不要 Markdown 围栏，不要解释文字。
契约要点：endpoint_summary 为字符串；dependencies 为字符串数组；test_cases 至少 1 条；每条含 id、name、steps（非空数组）；
每步含 method、path；body_type 仅能为 none、json、form、raw；variables 若存在则所有值为字符串；assertions 若存在则每项必有 type，
且 type 只能是 status_code、json_path_exists、json_path_equals、header_equals、body_contains；extract 每项含 name、from、path，from 只能是 json_body、header、status。"""

USER_REPAIR_TEMPLATE = """【校验错误】
{errors}

【待修复的 JSON】
{payload}

请输出修复后的完整 JSON 对象。"""


class LLMTestDesigner:
    def __init__(self, llm: LLMClient | None = None):
        self._llm = llm or LLMClient()

    def generate_for_endpoint(
        self,
        db: Session,
        endpoint_id: str,
        *,
        suite_name: str | None = None,
        approve: bool = False,
    ) -> TestSuite:
        tlog("GC-10", "generate_for_endpoint enter")
        tlog("GC-11", "db.get(Endpoint) before")
        ep = db.get(Endpoint, endpoint_id)
        tlog("GC-12", f"db.get after found={bool(ep)}")
        if not ep:
            raise AppError(ErrorCode.NOT_FOUND, "endpoint 不存在", details={"endpoint_id": endpoint_id})

        tlog("GC-13", f"format USER_SINGLE_TEMPLATE spec_json_len={len(ep.spec_json or '')}")
        user = USER_SINGLE_TEMPLATE.format(spec=ep.spec_json)
        tlog("GC-14", "before LLM chat_json (若此后无 GC-15 则卡在对外 HTTP/读响应)")
        raw = self._llm.chat_json(SYSTEM_SINGLE, user, use_json_object_mode=True)
        tlog("GC-15", f"after LLM chat_json raw_len={len(raw)}")

        tlog("GC-16", "before parse_json_strict")
        try:
            data = self._llm.parse_json_strict(raw)
        except AppError:
            raise
        tlog("GC-17", "after parse_json_strict")

        tlog("GC-18", "before validate_llm_test_design (with normalize)")
        ok, errs, data = validate_llm_test_design_normalized(data)
        tlog("GC-19", f"after validate ok={ok} err_count={len(errs)}")
        if not ok:
            tlog("GC-19b", "schema failed, try LLM repair pass")
            ok, data = self._repair_and_validate(data, errs)
        if not ok:
            _, errs, _ = validate_llm_test_design_normalized(data)
            hint = errs[0] if errs else "未知校验错误"
            raise AppError(
                ErrorCode.LLM_SCHEMA_VALIDATION_FAILED,
                f"LLM 输出未通过 JSON Schema：{hint}",
                retryable=True,
                details={"errors": errs[:50], "error_count": len(errs)},
            )

        name = suite_name or f"LLM-{ep.method} {ep.path}"[:500]
        tlog("GC-20", "orm TestSuite + db.add")
        suite = TestSuite(
            service_id=ep.service_id,
            endpoint_id=ep.id,
            name=name,
            snapshot_id=ep.snapshot_id,
        )
        db.add(suite)
        tlog("GC-21", "db.flush suite")
        db.flush()

        st = TestCaseStatus.approved if approve else TestCaseStatus.draft
        n_cases = len(data["test_cases"])
        tlog("GC-22", f"loop insert TestCase count={n_cases}")
        for tc in data["test_cases"]:
            case = TestCase(
                suite_id=suite.id,
                external_id=tc["id"],
                name=tc["name"],
                priority=0,
                tags=tc.get("tags"),
                steps_json=tc["steps"],
                variables_json=tc.get("variables"),
                status=st,
            )
            db.add(case)

        tlog("GC-23", "db.commit")
        db.commit()
        tlog("GC-24", "db.refresh suite, return")
        db.refresh(suite)
        return suite

    def _repair_and_validate(self, failed_data: object, errs: list[str]) -> tuple[bool, dict[str, Any]]:
        """一次修复调用：把校验错误与当前 JSON 发给模型，再 normalize + 校验。"""
        if not errs:
            return False, failed_data if isinstance(failed_data, dict) else {}
        try:
            payload = json.dumps(failed_data, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            payload = str(failed_data)
        max_len = 24_000
        if len(payload) > max_len:
            payload = payload[:max_len] + "\n…(truncated for repair prompt)"

        err_text = "\n".join(errs[:40])
        if len(errs) > 40:
            err_text += f"\n… 共 {len(errs)} 条错误，此处仅列前 40 条"

        user = USER_REPAIR_TEMPLATE.format(errors=err_text, payload=payload)
        try:
            raw = self._llm.chat_json(SYSTEM_REPAIR, user, temperature=0.1, use_json_object_mode=True)
            data = self._llm.parse_json_strict(raw)
        except AppError:
            return False, failed_data if isinstance(failed_data, dict) else {}

        ok, _, data = validate_llm_test_design_normalized(data)
        return ok, data
