"""LLM 输出 JSON Schema（与需求文档一致），供 jsonschema 校验。"""

from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import Draft202012Validator

_BODY_TYPES = frozenset({"none", "json", "form", "raw"})
_ASSERT_TYPES = frozenset(
    {
        "status_code",
        "json_path_exists",
        "json_path_equals",
        "header_equals",
        "body_contains",
    }
)
_EXTRACT_FROM = frozenset({"json_body", "header", "status"})

_ASSERT_TYPE_ALIASES: dict[str, str] = {
    "statuscode": "status_code",
    "http_status": "status_code",
    "httpstatus": "status_code",
    "status": "status_code",
    "code": "status_code",
    "jsonpathexists": "json_path_exists",
    "json_path": "json_path_exists",
    "jpathexists": "json_path_exists",
    "jsonpathequals": "json_path_equals",
    "json_path_eq": "json_path_equals",
    "headersequals": "header_equals",
    "header": "header_equals",
    "bodycontains": "body_contains",
    "contains": "body_contains",
    "text_contains": "body_contains",
}

_EXTRACT_FROM_ALIASES: dict[str, str] = {
    "response": "json_body",
    "response_body": "json_body",
    "body": "json_body",
    "json": "json_body",
    "jsonbody": "json_body",
    "resp": "json_body",
    "headers": "header",
    "response_headers": "header",
    "http_status": "status",
    "status_code": "status",
}


def _json_deep_copy(obj: Any) -> Any:
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return obj


def _norm_token(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    return s


def _coerce_body_type(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        t = raw.strip().lower()
        if t in _BODY_TYPES:
            return t
        if "json" in t or t in ("application/json", "application/json;charset=utf-8"):
            return "json"
        if "form" in t or "urlencoded" in t or "x-www-form" in t:
            return "form"
        if t in ("", "null", "nil", "n/a"):
            return "none"
        if "raw" in t or "text" in t or "xml" in t:
            return "raw"
    return None


def _norm_assert_type(raw: Any) -> str | None:
    if raw is None:
        return None
    t = _norm_token(raw)
    if t in _ASSERT_TYPES:
        return t
    return _ASSERT_TYPE_ALIASES.get(t)


def _norm_extract_from(raw: Any) -> str | None:
    if raw is None:
        return None
    t = _norm_token(raw)
    if t in _EXTRACT_FROM:
        return t
    return _EXTRACT_FROM_ALIASES.get(t)


def _stringify_variable_value(v: Any) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def normalize_llm_test_design(obj: Any) -> dict[str, Any]:
    """将常见 LLM 偏差纠正为可通过 Schema 的形状（深拷贝，不修改入参）。"""
    data = _json_deep_copy(obj)
    if not isinstance(data, dict):
        return {}

    # endpoint_summary
    es = data.get("endpoint_summary")
    data["endpoint_summary"] = es.strip() if isinstance(es, str) else ("" if es is None else str(es))

    # dependencies：常为单个字符串或漏写
    dep = data.get("dependencies")
    if dep is None or dep == "":
        data["dependencies"] = ["unknown"]
    elif isinstance(dep, str):
        data["dependencies"] = [dep] if dep.strip() else ["unknown"]
    elif isinstance(dep, list):
        data["dependencies"] = [str(x) for x in dep] if dep else ["unknown"]
    else:
        data["dependencies"] = ["unknown"]

    # test_cases
    raw_cases = data.get("test_cases")
    if not isinstance(raw_cases, list):
        data["test_cases"] = []
    else:
        fixed_cases: list[dict[str, Any]] = []
        for tc in raw_cases:
            if not isinstance(tc, dict):
                continue
            case = _json_deep_copy(tc)
            if not isinstance(case, dict):
                continue
            case["id"] = str(case.get("id", "")).strip() or "tc-auto"
            case["name"] = str(case.get("name", "")).strip() or case["id"]

            tags = case.get("tags")
            if isinstance(tags, list):
                case["tags"] = [str(x) for x in tags]
            elif tags is None:
                case.pop("tags", None)
            else:
                case["tags"] = [str(tags)]

            vars_ = case.get("variables")
            if isinstance(vars_, dict):
                case["variables"] = {str(k): _stringify_variable_value(v) for k, v in vars_.items()}
            elif vars_ is not None:
                case["variables"] = {"_": _stringify_variable_value(vars_)}
            else:
                case.pop("variables", None)

            steps_in = case.get("steps")
            steps_out: list[dict[str, Any]] = []
            if isinstance(steps_in, list):
                for st in steps_in:
                    if not isinstance(st, dict):
                        continue
                    step = _json_deep_copy(st)
                    if not isinstance(step, dict):
                        continue
                    step["method"] = str(step.get("method", "GET")).strip().upper() or "GET"
                    step["path"] = str(step.get("path", "/")).strip() or "/"

                    bt = _coerce_body_type(step.get("body_type"))
                    if bt is not None:
                        step["body_type"] = bt
                    else:
                        step.pop("body_type", None)

                    for hk in ("headers", "query"):
                        h = step.get(hk)
                        if isinstance(h, dict):
                            step[hk] = {str(k): _stringify_variable_value(v) for k, v in h.items()}
                        elif h is not None:
                            step.pop(hk, None)

                    assertions = step.get("assertions")
                    if isinstance(assertions, list):
                        fixed_a: list[dict[str, Any]] = []
                        for a in assertions:
                            if not isinstance(a, dict):
                                continue
                            aa = _json_deep_copy(a)
                            if not isinstance(aa, dict):
                                continue
                            nt = _norm_assert_type(aa.get("type"))
                            if nt is None:
                                continue
                            aa["type"] = nt
                            fixed_a.append(aa)
                        if fixed_a:
                            step["assertions"] = fixed_a
                        else:
                            step.pop("assertions", None)
                    elif assertions is not None:
                        step.pop("assertions", None)

                    ex = step.get("extract")
                    if isinstance(ex, list):
                        fixed_e: list[dict[str, Any]] = []
                        for item in ex:
                            if not isinstance(item, dict):
                                continue
                            ee = _json_deep_copy(item)
                            if not isinstance(ee, dict):
                                continue
                            if not all(k in ee for k in ("name", "from", "path")):
                                continue
                            nf = _norm_extract_from(ee.get("from"))
                            if nf is None:
                                continue
                            ee["from"] = nf
                            ee["name"] = str(ee.get("name", "")).strip()
                            ee["path"] = str(ee.get("path", "")).strip()
                            if ee["name"] and ee["path"]:
                                fixed_e.append(ee)
                        if fixed_e:
                            step["extract"] = fixed_e
                        else:
                            step.pop("extract", None)
                    elif ex is not None:
                        step.pop("extract", None)

                    steps_out.append(step)

            case["steps"] = steps_out
            fixed_cases.append(case)

        data["test_cases"] = fixed_cases

    return data

# 与用户提供摘要一致；assertions.items 中 type 必填，path/value 按类型可选
_STEP = {
    "type": "object",
    "required": ["method", "path"],
    "properties": {
        "name": {"type": "string"},
        "method": {"type": "string"},
        "path": {"type": "string"},
        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
        "query": {"type": "object", "additionalProperties": {"type": "string"}},
        "body": {},
        "body_type": {"type": "string", "enum": ["none", "json", "form", "raw"]},
        "extract": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "from", "path"],
                "properties": {
                    "name": {"type": "string"},
                    "from": {"type": "string", "enum": ["json_body", "header", "status"]},
                    "path": {"type": "string"},
                },
            },
        },
        "assertions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "status_code",
                            "json_path_exists",
                            "json_path_equals",
                            "header_equals",
                            "body_contains",
                        ],
                    },
                    "value": {},
                    "path": {"type": "string"},
                },
            },
        },
    },
}

LLM_TEST_DESIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["endpoint_summary", "dependencies", "test_cases"],
    "properties": {
        "endpoint_summary": {"type": "string"},
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "test_cases": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "name", "steps"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "steps": {"type": "array", "minItems": 1, "items": _STEP},
                    "variables": {"type": "object", "additionalProperties": {"type": "string"}},
                },
            },
        },
    },
}

_validator = Draft202012Validator(LLM_TEST_DESIGN_SCHEMA)


def validate_llm_test_design(obj: Any) -> tuple[bool, list[str]]:
    errors = sorted(_validator.iter_errors(obj), key=lambda e: e.path)
    msgs = [f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors]
    return (len(msgs) == 0, msgs)


def validate_llm_test_design_normalized(obj: Any) -> tuple[bool, list[str], dict[str, Any]]:
    """先 normalize 再校验，返回 (ok, errors, normalized_dict)。"""
    n = normalize_llm_test_design(obj)
    ok, errs = validate_llm_test_design(n)
    return ok, errs, n
