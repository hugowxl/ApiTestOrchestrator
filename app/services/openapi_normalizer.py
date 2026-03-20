"""将 OpenAPI 2.0 / 3.x 解析为内部 Endpoint 列表与片段 JSON。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import yaml

from app.utils.errors import AppError, ErrorCode

_HTTP_METHODS = frozenset(
    m.lower() for m in ("get", "post", "put", "patch", "delete", "head", "options", "trace")
)


def _pointer_get(root: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith("#/"):
        raise ValueError("仅支持文档内 #/ 引用")
    parts = pointer[2:].split("/")
    cur: Any = root
    for raw in parts:
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(cur, dict) or key not in cur:
            raise KeyError(pointer)
        cur = cur[key]
    return cur


def resolve_refs(obj: Any, root: dict[str, Any], seen: frozenset[str] | None = None) -> Any:
    """浅层递归解析同一文档内的 $ref（#/definitions 或 #/components）。"""
    if seen is None:
        seen = frozenset()
    if isinstance(obj, dict):
        if "$ref" in obj and isinstance(obj["$ref"], str):
            ref = obj["$ref"]
            if ref in seen:
                return {"$ref": ref, "circular": True}
            try:
                resolved = _pointer_get(root, ref)
            except (KeyError, ValueError):
                return obj
            return resolve_refs(resolved, root, seen | {ref})
        return {k: resolve_refs(v, root, seen) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_refs(i, root, seen) for i in obj]
    return obj


def load_spec(content: bytes) -> dict[str, Any]:
    text = content.decode("utf-8", errors="replace").strip()
    try:
        if text.startswith("{"):
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        raise AppError(ErrorCode.SWAGGER_PARSE_FAILED, f"无法解析 YAML/JSON: {e}", retryable=False) from e
    if not isinstance(data, dict):
        raise AppError(ErrorCode.SWAGGER_PARSE_FAILED, "根节点必须为对象", retryable=False)
    return data


def _is_openapi3(spec: dict[str, Any]) -> bool:
    v = spec.get("openapi")
    return isinstance(v, str) and v.startswith("3.")


def _is_swagger2(spec: dict[str, Any]) -> bool:
    return spec.get("swagger") == "2.0"


def _merge_parameters(path_item_params: list[Any], op_params: list[Any] | None) -> list[Any]:
    out = list(path_item_params or [])
    for p in op_params or []:
        out.append(p)
    return out


def _build_operation_fragment(
    spec: dict[str, Any],
    path: str,
    method: str,
    operation: dict[str, Any],
    path_level_params: list[Any],
) -> dict[str, Any]:
    merged = _merge_parameters(path_level_params, operation.get("parameters"))
    frag = {
        "path": path,
        "method": method.upper(),
        "operationId": operation.get("operationId"),
        "summary": operation.get("summary"),
        "description": operation.get("description"),
        "parameters": merged,
        "tags": operation.get("tags"),
    }
    if _is_openapi3(spec):
        frag["requestBody"] = operation.get("requestBody")
        frag["responses"] = operation.get("responses")
        frag["security"] = operation.get("security", spec.get("security"))
    else:
        frag["consumes"] = operation.get("consumes") or spec.get("consumes")
        frag["produces"] = operation.get("produces") or spec.get("produces")
        frag["responses"] = operation.get("responses")
        frag["security"] = operation.get("security", spec.get("security"))
    return resolve_refs(frag, spec)


def _fingerprint(method: str, path: str, operation_id: str | None, fragment: dict[str, Any]) -> str:
    payload = json.dumps(
        {"method": method.upper(), "path": path, "operationId": operation_id, "fragment": fragment},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """
    每条为 dict: method, path, operation_id, spec_fragment (dict), fingerprint (str), spec_json (str)
    """
    if not (_is_openapi3(spec) or _is_swagger2(spec)):
        raise AppError(
            ErrorCode.SWAGGER_PARSE_FAILED,
            "仅支持 OpenAPI 3.x 或 Swagger 2.0",
            retryable=False,
        )
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise AppError(ErrorCode.SWAGGER_PARSE_FAILED, "缺少 paths", retryable=False)

    endpoints: list[dict[str, Any]] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_params = path_item.get("parameters") or []
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue
            fragment = _build_operation_fragment(spec, path, method, operation, path_params)
            op_id = operation.get("operationId")
            if isinstance(op_id, str):
                op_id_clean = op_id
            else:
                op_id_clean = None
            fp = _fingerprint(method, path, op_id_clean, fragment)
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": op_id_clean,
                    "spec_fragment": fragment,
                    "fingerprint": fp,
                    "spec_json": json.dumps(fragment, ensure_ascii=False, default=str),
                }
            )
    return endpoints
