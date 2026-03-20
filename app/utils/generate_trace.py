"""POST /endpoints/{id}/generate-cases 专用分步日志；未 begin 时不输出（批量生成不受影响）。"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from uuid import uuid4

_log = logging.getLogger("app.generate_cases.trace")  # 与 logging_setup 中强制级别一致

_trace_id: ContextVar[str | None] = ContextVar("generate_cases_trace_id", default=None)


def trace_begin() -> Token:
    return _trace_id.set(uuid4().hex[:12])


def trace_end(token: Token) -> None:
    _trace_id.reset(token)


def tlog(step: str, detail: str = "") -> None:
    tid = _trace_id.get()
    if tid is None:
        return
    if detail:
        _log.info("[trace=%s] %s | %s", tid, step, detail)
    else:
        _log.info("[trace=%s] %s", tid, step)
