"""对 HTTP 响应执行断言。"""

from __future__ import annotations

import json
from typing import Any

from jsonpath_ng import parse as jp_parse

def _get_json_path(obj: Any, path: str) -> list[Any]:
    path = (path or "").strip()
    if not path:
        return []
    try:
        expr = jp_parse(path)
    except Exception:
        return []
    return [m.value for m in expr.find(obj)]


def run_assertions(
    assertions: list[dict[str, Any]] | None,
    *,
    status_code: int,
    headers: dict[str, str],
    body_text: str,
    body_json: Any | None,
) -> tuple[bool, str | None]:
    if not assertions:
        return True, None

    for a in assertions:
        t = a.get("type")
        if t == "status_code":
            exp = a.get("value")
            try:
                exp_i = int(exp)
            except (TypeError, ValueError):
                return False, f"status_code 期望值非法: {exp}"
            if status_code != exp_i:
                return False, f"期望状态码 {exp_i}，实际 {status_code}"
        elif t == "json_path_exists":
            p = a.get("path")
            if body_json is None:
                return False, f"json_path_exists 需要 JSON 体: {p}"
            vals = _get_json_path(body_json, str(p))
            if not vals:
                return False, f"JSONPath 不存在: {p}"
        elif t == "json_path_equals":
            p = a.get("path")
            exp = a.get("value")
            if body_json is None:
                return False, f"json_path_equals 需要 JSON 体: {p}"
            vals = _get_json_path(body_json, str(p))
            if not vals:
                return False, f"JSONPath 无匹配: {p}"
            if vals[0] != exp and str(vals[0]) != str(exp):
                return False, f"JSONPath 值不等: {p} 期望 {exp!r} 实际 {vals[0]!r}"
        elif t == "header_equals":
            name = (a.get("path") or "").strip()
            exp = a.get("value")
            actual = headers.get(name) or headers.get(name.lower())
            if str(actual) != str(exp):
                return False, f"响应头 {name!r} 期望 {exp!r} 实际 {actual!r}"
        elif t == "body_contains":
            needle = a.get("value")
            if needle is None or str(needle) not in body_text:
                return False, f"body 不包含: {needle!r}"
        else:
            return False, f"未知断言类型: {t}"

    return True, None


def extract_values(
    extracts: list[dict[str, Any]] | None,
    *,
    status_code: int,
    headers: dict[str, str],
    body_json: Any | None,
) -> dict[str, str]:
    out: dict[str, str] = {}
    if not extracts:
        return out
    for ex in extracts:
        name = ex["name"]
        from_ = ex["from"]
        path = ex.get("path") or ""
        if from_ == "status":
            out[name] = str(status_code)
        elif from_ == "header":
            key = path.strip()
            v = headers.get(key) or headers.get(key.lower())
            out[name] = "" if v is None else str(v)
        elif from_ == "json_body":
            if body_json is None:
                out[name] = ""
            else:
                vals = _get_json_path(body_json, path)
                out[name] = "" if not vals else json.dumps(vals[0], ensure_ascii=False) if isinstance(vals[0], (dict, list)) else str(vals[0])
        else:
            out[name] = ""
    return out
