import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# PostgreSQL 可用 JSONB；SQLite 用 JSON
JSONType = SQLiteJSON


class SyncJobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class TestRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    partial = "partial"


class TestCaseStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"


class TargetService(Base):
    """被测目标服务：名称、运行时 base_url、Swagger 来源。"""

    __tablename__ = "target_service"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    swagger_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    auth_template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    snapshots: Mapped[list["SwaggerSnapshot"]] = relationship(back_populates="service")
    endpoints: Mapped[list["Endpoint"]] = relationship(back_populates="service")
    sync_jobs: Mapped[list["SyncJob"]] = relationship(back_populates="service")
    suites: Mapped[list["TestSuite"]] = relationship(back_populates="service")


class SwaggerSnapshot(Base):
    """某次拉取到的 OpenAPI 全文与内容哈希，用于增量同步。"""

    __tablename__ = "swagger_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    service_id: Mapped[str] = mapped_column(String(36), ForeignKey("target_service.id"), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    etag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # MySQL 默认 Text≈64KB，大型 OpenAPI 会 1406；LONGTEXT 约 4GB
    raw_spec_json: Mapped[str] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb"),
        nullable=False,
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    service: Mapped["TargetService"] = relationship(back_populates="snapshots")
    endpoints: Mapped[list["Endpoint"]] = relationship(back_populates="snapshot")


class SyncJob(Base):
    """一次同步任务：状态、错误码、统计。"""

    __tablename__ = "sync_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    service_id: Mapped[str] = mapped_column(String(36), ForeignKey("target_service.id"), nullable=False, index=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("swagger_snapshot.id"), nullable=True)
    status: Mapped[SyncJobStatus] = mapped_column(
        Enum(SyncJobStatus, native_enum=False, values_callable=lambda x: [i.value for i in x]),
        default=SyncJobStatus.pending,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    endpoints_added: Mapped[int] = mapped_column(Integer, default=0)
    endpoints_updated: Mapped[int] = mapped_column(Integer, default=0)
    endpoints_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    service: Mapped["TargetService"] = relationship(back_populates="sync_jobs")


class Endpoint(Base):
    """归一化后的单条 API：method + path + operationId + 片段 spec。

    MySQL/InnoDB + utf8mb4 下复合唯一索引字节上限 3072，path 过长会报错 1071；
    对 path 使用前缀长度（仅 MySQL 生效），其它方言仍为整列唯一。
    """

    __tablename__ = "endpoint"
    __table_args__ = (
        Index(
            "uq_endpoint_service_method_path",
            "service_id",
            "method",
            "path",
            unique=True,
            mysql_length={"path": 700},
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    service_id: Mapped[str] = mapped_column(String(36), ForeignKey("target_service.id"), nullable=False, index=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("swagger_snapshot.id"), nullable=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    operation_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    spec_json: Mapped[str] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb"),
        nullable=False,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    service: Mapped["TargetService"] = relationship(back_populates="endpoints")
    snapshot: Mapped["SwaggerSnapshot | None"] = relationship(back_populates="endpoints")
    suites: Mapped[list["TestSuite"]] = relationship(back_populates="endpoint")


class TestSuite(Base):
    """测试套件：可绑定单个 endpoint 或整服务（endpoint_id 为空）。"""

    __tablename__ = "test_suite"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    service_id: Mapped[str] = mapped_column(String(36), ForeignKey("target_service.id"), nullable=False, index=True)
    endpoint_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("endpoint.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    snapshot_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("swagger_snapshot.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    service: Mapped["TargetService"] = relationship(back_populates="suites")
    endpoint: Mapped["Endpoint | None"] = relationship(back_populates="suites")
    cases: Mapped[list["TestCase"]] = relationship(back_populates="suite")
    runs: Mapped[list["TestRun"]] = relationship(back_populates="suite")


class TestCase(Base):
    """单条可执行用例：来自 LLM 的结构化 steps + variables。"""

    __tablename__ = "test_case"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_suite.id"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    steps_json: Mapped[list] = mapped_column(JSONType, nullable=False)
    variables_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    status: Mapped[TestCaseStatus] = mapped_column(
        Enum(TestCaseStatus, native_enum=False, values_callable=lambda x: [i.value for i in x]),
        default=TestCaseStatus.draft,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    suite: Mapped["TestSuite"] = relationship(back_populates="cases")
    results: Mapped[list["TestResult"]] = relationship(back_populates="case")


class TestRun(Base):
    """一次执行：触发来源、整体状态、时间。"""

    __tablename__ = "test_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("test_suite.id"), nullable=True, index=True)
    trigger: Mapped[str] = mapped_column(String(64), default="api")
    status: Mapped[TestRunStatus] = mapped_column(
        Enum(TestRunStatus, native_enum=False, values_callable=lambda x: [i.value for i in x]),
        default=TestRunStatus.pending,
    )
    target_base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    suite: Mapped["TestSuite | None"] = relationship(back_populates="runs")
    results: Mapped[list["TestResult"]] = relationship(back_populates="run")
    reports: Mapped[list["Report"]] = relationship(back_populates="run")


class TestResult(Base):
    """每个用例在一次 run 中的结果。"""

    __tablename__ = "test_result"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_run.id"), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_case.id"), nullable=False, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    request_snapshot: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    response_snapshot: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["TestRun"] = relationship(back_populates="results")
    case: Mapped["TestCase"] = relationship(back_populates="results")


class Report(Base):
    """报告文件路径与汇总 JSON。"""

    __tablename__ = "report"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_run.id"), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    summary_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["TestRun"] = relationship(back_populates="reports")
