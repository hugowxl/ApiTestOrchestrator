import copy
import re
from typing import Any

_SENSITIVE_HEADER_KEYS = frozenset(
    k.lower()
    for k in (
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
    )
)


def redact_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    out: dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in _SENSITIVE_HEADER_KEYS or "token" in lk or "secret" in lk:
            out[k] = _mask_secret(str(v))
        else:
            out[k] = str(v)
    return out


def _mask_secret(value: str, keep: int = 6) -> str:
    if len(value) <= keep:
        return "***"
    if value.lower().startswith("bearer "):
        return "Bearer ***" + value[-4:] if len(value) > 12 else "Bearer ***"
    return value[:keep] + "***"


def redact_for_log(text: str, max_len: int = 2000) -> str:
    if not text:
        return ""
    t = re.sub(
        r"(?i)(authorization|bearer)\s*[:=]\s*[\w\-\._~+/]+=*",
        r"\1: ***",
        text,
    )
    t = re.sub(r'("password"\s*:\s*")([^"]*)(")', r'\1***\3', t)
    return t[:max_len] + ("…" if len(t) > max_len else "")


def snapshot_safe_dict(obj: dict[str, Any] | None) -> dict[str, Any]:
    """深拷贝并脱敏 headers。"""
    if not obj:
        return {}
    data = copy.deepcopy(obj)
    if isinstance(data.get("headers"), dict):
        data["headers"] = redact_headers({str(k): str(v) for k, v in data["headers"].items()})
    return data
