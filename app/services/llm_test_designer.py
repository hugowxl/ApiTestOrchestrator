"""组装 Prompt、调用 LLM、校验 Schema 并写入 test_suite / test_case。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from itertools import product
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Endpoint, TestCase, TestCaseStatus, TestSuite
from app.schemas.test_case_schema import validate_llm_test_design_normalized
from app.services.llm_client import LLMClient
from app.utils.errors import AppError, ErrorCode
from app.utils.generate_trace import tlog

SYSTEM_SINGLE = """你是 API 测试设计专家。用户会提供 OpenAPI 片段（接口契约），可能提供「★高优先级」测试负责人对当前接口的专项说明，以及「业务规则与场景说明」（产品/领域行为）。
路径、HTTP 方法、Query/Path/Body 字段名与枚举值必须以 OpenAPI 为准，不得编造文档中未出现的路径或字段；专项说明与业务说明用于设计多步调用顺序、数据准备、合法/非法分支与断言意图，且须落在 OpenAPI 允许的形状之内。专项说明在测试意图上优先于通用业务说明，但不得突破 OpenAPI 契约。
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

# 业务说明过长时截断，避免撑爆上下文（Schema 上限 48k，此处略收紧）
_MAX_BUSINESS_CONTEXT_IN_PROMPT = 45000
_MAX_ENDPOINT_NOTES_IN_PROMPT = 8000
_MAX_SCENARIO_LINE_IN_PROMPT = 500

_PATH_ID_LINE_RE = re.compile(r"^(path-\d{3})\s*:\s*(.*)$", re.DOTALL)


@dataclass(frozen=True)
class ScenarioPathCoverage:
    """场景矩阵 path-xxx 与生成用例名的匹配结果（用例名须包含 path-xxx）。"""

    enabled: bool
    expected_paths: list[str]
    covered_paths: list[str]
    missing_paths: list[str]
    total_cartesian_combinations: int
    expanded_paths_count: int
    truncated: bool
    coverage_ratio: float
    path_labels: dict[str, str]

_TASK_BLOCK = """【任务】
1. 写 endpoint_summary：2～4 句话说明业务意图与调用前提（如认证）；若提供了「★高优先级」接口专项说明或业务说明，应体现其与当前接口的关系。
2. 写 dependencies：字符串数组；无则 ["unknown"]。
3. 设计 3～8 条 test_cases；每条必须是「可执行的多步 HTTP 场景」，禁止只写 method/path/expected_status 的扁平字段——必须包在 steps 数组里，每步含 method、path、body_type、assertions 等；需要时用 extract 把上一步响应写入后续步骤可用的变量。
4. 若提供了【业务规则与场景说明】：至少 2 条用例应覆盖其中的关键规则或分支（如非法状态、缺前置、权限不足）；其余覆盖 OpenAPI 典型成功与常见客户端错误路径。未提供业务说明时，仅依据 OpenAPI 设计场景。

【最小合法示例（结构示意，path 请换成文档中的真实路径）】
{{"endpoint_summary":"…","dependencies":["unknown"],"test_cases":[{{"id":"tc-001","name":"成功删除","steps":[{{"method":"DELETE","path":"/api/…/{{{{agent_id}}}}","body_type":"none","assertions":[{{"type":"status_code","value":200}}]}}],"variables":{{"agent_id":"valid-id"}}}}]}}

【输出】
- 仅输出 JSON；不要真实密钥，用占位符。"""


def _expand_scenario_matrix(
    scenario_matrix: dict[str, list[str]] | None,
    *,
    max_combinations: int,
) -> tuple[list[str], int, bool]:
    """将场景矩阵展开为路径组合文案。"""
    if not scenario_matrix:
        return [], 0, False
    items: list[tuple[str, list[str]]] = []
    for k, opts in scenario_matrix.items():
        name = str(k).strip()
        if not name or not isinstance(opts, list):
            continue
        cleaned = [str(v).strip() for v in opts if str(v).strip()]
        if not cleaned:
            continue
        items.append((name, cleaned))
    if not items:
        return [], 0, False

    keys = [k for k, _ in items]
    option_lists = [opts for _, opts in items]
    total = 1
    for opts in option_lists:
        total *= len(opts)

    lines: list[str] = []
    limited = False
    for idx, combo in enumerate(product(*option_lists), start=1):
        if idx > max_combinations:
            limited = True
            break
        parts = [f"{k}={v}" for k, v in zip(keys, combo)]
        lines.append(f"path-{idx:03d}: " + " | ".join(parts))
        if idx >= _MAX_SCENARIO_LINE_IN_PROMPT:
            limited = True
            break
    return lines, total, limited


def compute_scenario_path_coverage(
    scenario_matrix: dict[str, list[str]] | None,
    *,
    scenario_max_combinations: int,
    test_case_names: list[str],
) -> ScenarioPathCoverage:
    """根据展开后的 path-NNN 与用例 name 子串匹配，统计覆盖与遗漏。"""
    path_lines, total_cartesian, truncated = _expand_scenario_matrix(
        scenario_matrix, max_combinations=max(1, scenario_max_combinations)
    )
    if not path_lines:
        return ScenarioPathCoverage(
            enabled=False,
            expected_paths=[],
            covered_paths=[],
            missing_paths=[],
            total_cartesian_combinations=0,
            expanded_paths_count=0,
            truncated=False,
            coverage_ratio=0.0,
            path_labels={},
        )

    expected_paths: list[str] = []
    path_labels: dict[str, str] = {}
    for raw in path_lines:
        line = raw.strip()
        m = _PATH_ID_LINE_RE.match(line)
        if not m:
            continue
        pid = m.group(1)
        expected_paths.append(pid)
        path_labels[pid] = (m.group(2) or "").strip()

    combined = "\n".join(str(n) for n in test_case_names)
    covered_set: set[str] = set()
    for pid in expected_paths:
        if re.search(re.escape(pid), combined, flags=re.IGNORECASE):
            covered_set.add(pid)

    def _path_sort_key(p: str) -> int:
        try:
            return int(p.split("-", 1)[1])
        except (IndexError, ValueError):
            return 0

    covered_sorted = sorted(covered_set, key=_path_sort_key)
    missing = [p for p in expected_paths if p not in covered_set]
    n_exp = len(expected_paths)
    ratio = (len(covered_set) / n_exp) if n_exp else 0.0
    return ScenarioPathCoverage(
        enabled=True,
        expected_paths=list(expected_paths),
        covered_paths=covered_sorted,
        missing_paths=missing,
        total_cartesian_combinations=total_cartesian,
        expanded_paths_count=n_exp,
        truncated=truncated,
        coverage_ratio=round(ratio, 4),
        path_labels=path_labels,
    )


def build_generate_user_prompt(
    spec: str,
    business_context: str | None,
    scenario_matrix: dict[str, list[str]] | None = None,
    *,
    scenario_max_combinations: int = 128,
    endpoint_test_design_notes: str | None = None,
) -> str:
    """拼接 OpenAPI 片段与可选业务说明，供单次生成用。"""
    spec_part = spec or ""
    parts: list[str] = [f"【OpenAPI 片段】\n{spec_part}"]
    focus = (endpoint_test_design_notes or "").strip()
    if focus:
        if len(focus) > _MAX_ENDPOINT_NOTES_IN_PROMPT:
            focus = focus[:_MAX_ENDPOINT_NOTES_IN_PROMPT] + "\n…(接口专项说明过长已截断)"
        parts.append(
            "【★高优先级｜测试负责人对「当前接口」的专项说明】\n"
            f"{focus}\n\n"
            "你必须优先落实上述说明中的测试意图、边界条件、风险点与断言关注点；"
            "HTTP 路径、方法以及请求/响应字段名与枚举值仍以 OpenAPI 为唯一契约依据，不得编造未出现的字段。"
            "若本说明与 OpenAPI 冲突，以 OpenAPI 落实请求形状，并在 endpoint_summary 中简要注明无法直接表达的意图。"
        )
    ctx = (business_context or "").strip()
    if ctx:
        if len(ctx) > _MAX_BUSINESS_CONTEXT_IN_PROMPT:
            ctx = ctx[:_MAX_BUSINESS_CONTEXT_IN_PROMPT] + "\n…(业务说明过长已截断)"
        parts.append(
            "【业务规则与场景说明（产品/领域知识，与 OpenAPI 互补）】\n"
            f"{ctx}\n\n"
            "【契约优先级】路径、方法、字段名与枚举必须以 OpenAPI 为准；业务说明仅用于顺序、前置、分支与断言意图。"
            "若与 OpenAPI 冲突，以 OpenAPI 为准，勿编造未出现的路径或字段。"
        )
    path_lines, total_paths, limited = _expand_scenario_matrix(
        scenario_matrix, max_combinations=max(1, scenario_max_combinations)
    )
    if path_lines:
        lines_text = "\n".join(f"- {line}" for line in path_lines)
        suffix = ""
        if limited:
            suffix = (
                f"\n注：组合总数={total_paths}，当前仅展示前 {len(path_lines)} 条用于控制 token。"
            )
        parts.append(
            "【业务场景路径组合（由场景矩阵自动展开）】\n"
            f"{lines_text}{suffix}\n\n"
            "【覆盖要求】请对每条 path-xxx 至少生成 1 条 test_case，"
            "并在 test_case.name 中包含对应 path-xxx 标识，便于后续追踪覆盖率。"
        )
    parts.append(_TASK_BLOCK)
    return "\n\n".join(parts)

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
        business_context: str | None = None,
        scenario_matrix: dict[str, list[str]] | None = None,
        scenario_max_combinations: int = 128,
    ) -> tuple[TestSuite, ScenarioPathCoverage]:
        tlog("GC-10", "generate_for_endpoint enter")
        tlog("GC-11", "db.get(Endpoint) before")
        ep = db.get(Endpoint, endpoint_id)
        tlog("GC-12", f"db.get after found={bool(ep)}")
        if not ep:
            raise AppError(ErrorCode.NOT_FOUND, "endpoint 不存在", details={"endpoint_id": endpoint_id})

        tlog(
            "GC-13",
            f"build_generate_user_prompt spec_json_len={len(ep.spec_json or '')} "
            f"business_context_len={len((business_context or '').strip())} "
            f"endpoint_notes_len={len((ep.test_design_notes or '').strip())} "
            f"scenario_dim_count={len(scenario_matrix or {})}",
        )
        user = build_generate_user_prompt(
            ep.spec_json or "",
            business_context,
            scenario_matrix,
            scenario_max_combinations=scenario_max_combinations,
            endpoint_test_design_notes=ep.test_design_notes,
        )
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
        names = [str(tc.get("name", "")) for tc in data["test_cases"]]
        coverage = compute_scenario_path_coverage(
            scenario_matrix,
            scenario_max_combinations=scenario_max_combinations,
            test_case_names=names,
        )
        return suite, coverage

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
