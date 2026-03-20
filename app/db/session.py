import logging
import os
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.base import Base

import app.db.models  # noqa: F401 — 注册 ORM 元数据

logger = logging.getLogger(__name__)
_settings = get_settings()

# SQLite 需要 check_same_thread=False 供 FastAPI 同步路由使用
_connect_args = {}
if _settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    _settings.database_url,
    connect_args=_connect_args,
    echo=_settings.debug,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _ensure_mysql_longtext_openapi_columns() -> None:
    """已有库若仍为 64KB 级 TEXT，插入大型 OpenAPI 会 1406；启动时自愈为 LONGTEXT。"""
    if engine.dialect.name not in ("mysql", "mariadb"):
        return
    alters: list[tuple[str, str]] = [
        ("swagger_snapshot", "raw_spec_json"),
        ("endpoint", "spec_json"),
    ]
    with engine.begin() as conn:
        for table, column in alters:
            try:
                r = conn.execute(
                    text(
                        """
                        SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE()
                          AND TABLE_NAME = :t AND COLUMN_NAME = :c
                        """
                    ),
                    {"t": table, "c": column},
                )
                row = r.fetchone()
                if not row:
                    continue
                ctype = (row[0] or "").lower()
                if "longtext" in ctype:
                    continue
                if any(x in ctype for x in ("text", "varchar", "char", "blob")):
                    conn.execute(
                        text(f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` LONGTEXT NOT NULL")
                    )
                    logger.info("MySQL 已升级列 %s.%s -> LONGTEXT（大型 OpenAPI 兼容）", table, column)
            except Exception:
                logger.warning(
                    "MySQL 列 %s.%s 无法自动升级为 LONGTEXT，请手工执行 README 中的 ALTER",
                    table,
                    column,
                    exc_info=True,
                )


def init_db() -> None:
    if _settings.database_url.startswith("sqlite"):
        db_path = _settings.database_url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_mysql_longtext_openapi_columns()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
