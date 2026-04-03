import logging
import os
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
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


def _ensure_endpoint_test_design_notes_column() -> None:
    """旧库无 test_design_notes 列时启动自愈（create_all 不会 ALTER）。"""
    dialect = engine.dialect.name
    if dialect == "sqlite":
        with engine.begin() as conn:
            rows = conn.execute(text("PRAGMA table_info(endpoint)")).fetchall()
            cols = {row[1] for row in rows}
            if "test_design_notes" not in cols:
                conn.execute(text("ALTER TABLE endpoint ADD COLUMN test_design_notes TEXT"))
                logger.info("SQLite: 已添加列 endpoint.test_design_notes")
    elif dialect in ("mysql", "mariadb"):
        with engine.begin() as conn:
            r = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'endpoint'
                      AND COLUMN_NAME = 'test_design_notes'
                    """
                )
            )
            if int(r.scalar() or 0) == 0:
                conn.execute(text("ALTER TABLE `endpoint` ADD COLUMN `test_design_notes` LONGTEXT NULL"))
                logger.info("%s: 已添加列 endpoint.test_design_notes", dialect)
    elif dialect == "postgresql":
        with engine.begin() as conn:
            try:
                conn.execute(text("ALTER TABLE endpoint ADD COLUMN test_design_notes TEXT"))
                logger.info("PostgreSQL: 已添加列 endpoint.test_design_notes")
            except ProgrammingError:
                logger.debug("PostgreSQL endpoint.test_design_notes 已存在或无法添加，跳过", exc_info=True)


def _ensure_mock_data_table_reset_rows_json_column() -> None:
    """旧库无 reset_rows_json 列时启动自愈，并把空快照补齐为当前 rows_json。"""
    dialect = engine.dialect.name
    if dialect == "sqlite":
        with engine.begin() as conn:
            rows = conn.execute(text("PRAGMA table_info(mock_data_table)")).fetchall()
            cols = {row[1] for row in rows}
            if "reset_rows_json" not in cols:
                conn.execute(text("ALTER TABLE mock_data_table ADD COLUMN reset_rows_json TEXT"))
                logger.info("SQLite: 已添加列 mock_data_table.reset_rows_json")
            conn.execute(
                text(
                    "UPDATE mock_data_table SET reset_rows_json = rows_json WHERE reset_rows_json IS NULL"
                )
            )
        return

    if dialect in ("mysql", "mariadb"):
        with engine.begin() as conn:
            r = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'mock_data_table'
                      AND COLUMN_NAME = 'reset_rows_json'
                    """
                )
            )
            exists = int(r.scalar() or 0) > 0
            if not exists:
                # TEXT 取最通用的兼容性；SQLAlchemy JSONType 读取时会做解析
                conn.execute(text("ALTER TABLE `mock_data_table` ADD COLUMN `reset_rows_json` LONGTEXT NULL"))
                logger.info("%s: 已添加列 mock_data_table.reset_rows_json", dialect)
            conn.execute(
                text(
                    "UPDATE mock_data_table SET reset_rows_json = rows_json WHERE reset_rows_json IS NULL"
                )
            )
        return

    if dialect == "postgresql":
        with engine.begin() as conn:
            # PostgreSQL JSONB 类型更贴合，但为避免版本差异，采用 TEXT 方式增加列后再回填
            try:
                conn.execute(text("ALTER TABLE mock_data_table ADD COLUMN reset_rows_json TEXT NULL"))
                logger.info("PostgreSQL: 已添加列 mock_data_table.reset_rows_json（TEXT）")
            except Exception:
                # 已存在或无法添加：忽略
                logger.debug("PostgreSQL reset_rows_json 可能已存在或无法添加，忽略", exc_info=True)
            conn.execute(
                text(
                    "UPDATE mock_data_table SET reset_rows_json = rows_json WHERE reset_rows_json IS NULL"
                )
            )
        return


def _ensure_agent_target_new_columns() -> None:
    """旧库的 agent_target / turn_result 表缺少新增字段时启动自愈。"""
    new_cols: list[tuple[str, str, str]] = [
        ("api_format", "VARCHAR(32)", "'openai_chat'"),
        ("engine_agent_id", "VARCHAR(255)", "NULL"),
        ("engine_agent_type", "VARCHAR(255)", "NULL"),
        ("engine_base_url", "VARCHAR(2048)", "NULL"),
        ("agent_description", "TEXT", "NULL"),
        ("agent_tools", "TEXT", "NULL"),
    ]
    _add_missing_columns("agent_target", new_cols)

    _add_missing_columns("turn_result", [
        ("request_snapshot", "TEXT", "NULL"),
    ])


def _add_missing_columns(table: str, new_cols: list[tuple[str, str, str]]) -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {row[1] for row in rows}
            for col, col_type, default in new_cols:
                if col not in existing:
                    default_clause = f" DEFAULT {default}" if default != "NULL" else ""
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}{default_clause}"))
                    logger.info("SQLite: 已添加列 %s.%s", table, col)
        elif dialect in ("mysql", "mariadb"):
            for col, col_type, default in new_cols:
                r = conn.execute(text(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
                ), {"t": table, "c": col})
                if int(r.scalar() or 0) == 0:
                    default_clause = f" DEFAULT {default}" if default != "NULL" else " NULL"
                    conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{col}` {col_type}{default_clause}"))
                    logger.info("%s: 已添加列 %s.%s", dialect, table, col)


def init_db() -> None:
    if _settings.database_url.startswith("sqlite"):
        db_path = _settings.database_url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_mysql_longtext_openapi_columns()
    _ensure_endpoint_test_design_notes_column()
    _ensure_mock_data_table_reset_rows_json_column()
    _ensure_agent_target_new_columns()
    _add_missing_columns("conversation_scenario", [
        ("active_mock_profile_id", "VARCHAR(36)", "NULL"),
        ("parent_scenario_id", "VARCHAR(36)", "NULL"),
    ])


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
