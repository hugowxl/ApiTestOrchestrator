"""文件日志：D:/applog/<项目名>/root.log；保证本机任意 HTTP 请求在应用内可见时均写入该文件。"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import Settings

_LOG_SETUP_DONE = False

# uvicorn 默认 LOGGING_CONFIG 里 uvicorn / uvicorn.access 为 propagate=False，不会传到 root，
# 必须在对应 logger 上挂载同一 FileHandler。
# 勿对 uvicorn.error 再挂文件 handler：其默认会向上传到 uvicorn，否则会写文件两次。
_UVICORN_LOGGERS = (
    "uvicorn",
    "uvicorn.access",
)


def _safe_dir_name(name: str) -> str:
    name = (name or "").strip() or "app"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:120] if name else "app"


def _level(settings: Settings) -> int:
    return logging.DEBUG if settings.debug else logging.INFO


def apply_forced_log_levels(settings: Settings) -> None:
    """
    强制本应用相关 logger 为 INFO/DEBUG，避免继承默认 root=WARNING 导致请求日志被丢弃。
    在 uvicorn dictConfig 之后也应再调一次（如 lifespan）。
    """
    lv = _level(settings)
    root = logging.getLogger()
    root.setLevel(lv)
    for name in (
        "app",
        "app.request",
        "app.http",
        "app.errors",
        "app.generate_cases",
        "app.generate_cases.trace",
        "app.services",
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
    ):
        logging.getLogger(name).setLevel(lv)


def setup_file_logging(settings: Settings) -> Path:
    """
    向 root 与 uvicorn 相关 logger 追加同一 RotatingFileHandler；
    不删除控制台 Handler。
    可安全多次调用：第二次起只刷新级别策略。
    """
    global _LOG_SETUP_DONE
    base = Path(settings.log_applog_base)
    sub = _safe_dir_name(settings.log_project_name or settings.app_name)
    log_dir = base / sub
    log_file = log_dir / "root.log"

    if _LOG_SETUP_DONE:
        apply_forced_log_levels(settings)
        return log_file

    log_dir.mkdir(parents=True, exist_ok=True)

    lv = _level(settings)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        log_file,
        maxBytes=10_485_760,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(lv)
    fh.setFormatter(fmt)

    root = logging.getLogger()
    root.addHandler(fh)
    apply_forced_log_levels(settings)

    for name in _UVICORN_LOGGERS:
        lg = logging.getLogger(name)
        lg.addHandler(fh)
        if lg.level == logging.NOTSET or lg.level > lv:
            lg.setLevel(lv)

    _LOG_SETUP_DONE = True
    logging.getLogger(__name__).info("文件日志已启用: %s（root + uvicorn.access 同文件）", log_file)
    return log_file


def flush_log_handlers() -> None:
    """刷盘：root / uvicorn 上挂载的 Handler（含共享文件 Handler）。"""
    seen: set[int] = set()
    for lg in (
        logging.getLogger(),
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.access"),
    ):
        for h in lg.handlers:
            i = id(h)
            if i in seen:
                continue
            seen.add(i)
            flush = getattr(h, "flush", None)
            if flush:
                try:
                    flush()
                except OSError:
                    pass
