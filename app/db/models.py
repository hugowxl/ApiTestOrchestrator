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
    # 测试设计者对「当前接口」的补充说明，生成用例时以高优先级注入 LLM（与 OpenAPI 冲突时仍以契约为准）
    test_design_notes: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb"),
        nullable=True,
    )
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


# ---------------------------------------------------------------------------
#  Mock 数据平台
# ---------------------------------------------------------------------------


class MockScenario(Base):
    """Mock 业务场景：如"购买理财产品"，包含多张数据表和 API 规则。"""

    __tablename__ = "mock_scenario"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tables: Mapped[list["MockDataTable"]] = relationship(back_populates="scenario", cascade="all, delete-orphan")
    api_rules: Mapped[list["MockApiRule"]] = relationship(back_populates="scenario", cascade="all, delete-orphan")


class MockDataTable(Base):
    """Mock 数据表：schema_json 描述列定义，rows_json 存储实际数据行。"""

    __tablename__ = "mock_data_table"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("mock_scenario.id"), nullable=False, index=True)
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_json: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    rows_json: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    # reset 快照：用于在 Mock 运行时（通过 mock-server CRUD 或外部 state 更新）发生数据变更后恢复原始版本
    reset_rows_json: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scenario: Mapped["MockScenario"] = relationship(back_populates="tables")
    api_rules: Mapped[list["MockApiRule"]] = relationship(back_populates="table")


class MockDataTableRuntimeState(Base):
    """Mock 运行时覆盖层（overlay）。

    约束：用于测试时的增删改查，避免直接修改 `MockDataTable.rows_json`（设计侧基准数据）。
    """

    __tablename__ = "mock_data_table_runtime_state"

    table_id: Mapped[str] = mapped_column(String(36), ForeignKey("mock_data_table.id"), primary_key=True)
    # 运行时 rows_json：当存在该行时，mock-server CRUD 读写/响应以此为准
    rows_json: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    table: Mapped["MockDataTable"] = relationship()


class MockApiRule(Base):
    """Mock API 规则：将 HTTP 请求映射到数据表的 CRUD 操作。"""

    __tablename__ = "mock_api_rule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("mock_scenario.id"), nullable=False, index=True)
    table_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("mock_data_table.id"), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    key_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    response_template_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    scenario: Mapped["MockScenario"] = relationship(back_populates="api_rules")
    table: Mapped["MockDataTable | None"] = relationship(back_populates="api_rules")


class MockEndpointMapping(Base):
    """Endpoint mapping：把 mock 运行时数据映射到类似生产环境的外部 URL。

    约束：读写都作用在运行时 overlay（MockDataTableRuntimeState），不覆盖设计侧基准 rows_json。
    """

    __tablename__ = "mock_endpoint_mapping"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mock_scenario.id"), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    table_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("mock_data_table.id"), nullable=True, index=True)
    key_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    required_body_fields: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    response_template_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
#  Agent 多轮对话测试
# ---------------------------------------------------------------------------


class AgentTestRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    passed = "passed"
    failed = "failed"
    partial = "partial"
    error = "error"


class AgentTarget(Base):
    """被测 Agent 端点：对话 API 地址、认证、工具定义等。

    api_format:
      - "openai_chat"  → 标准 OpenAI Chat Completions 格式
      - "agent_engine" → DevelopmentAgentEngine 的 /api/v1/agent/execute 格式
    """

    __tablename__ = "agent_target"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    chat_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    api_format: Mapped[str] = mapped_column(String(32), default="openai_chat")
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_type: Mapped[str] = mapped_column(String(32), default="bearer")
    auth_config: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    tools_schema: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    default_system_prompt: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb"),
        nullable=True,
    )
    # Agent Engine 专属字段
    engine_agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    engine_agent_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    engine_base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    agent_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_tools: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    extra_config: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scenarios: Mapped[list["ConversationScenario"]] = relationship(
        back_populates="agent_target", cascade="all, delete-orphan"
    )


class ConversationScenario(Base):
    """多轮对话测试场景：如"新用户购买中低风险基金"。"""

    __tablename__ = "conversation_scenario"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_target_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_target.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    initial_context: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    max_turns: Mapped[int] = mapped_column(Integer, default=20)
    active_mock_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent_target: Mapped["AgentTarget"] = relationship(back_populates="scenarios")
    turns: Mapped[list["ConversationTurn"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", order_by="ConversationTurn.turn_index"
    )
    runs: Mapped[list["AgentTestRun"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )
    mock_profiles: Mapped[list["MockProfile"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )


class MockProfile(Base):
    """Mock 数据配置集：定义某次测试执行时工作流 Mock 应返回的业务数据。"""

    __tablename__ = "mock_profile"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversation_scenario.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_data: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scenario: Mapped["ConversationScenario"] = relationship(back_populates="mock_profiles")


class ConversationTurn(Base):
    """场景中的单轮对话定义：用户说什么 + 期望 Agent 做什么。"""

    __tablename__ = "conversation_turn"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversation_scenario.id"), nullable=False, index=True
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    user_message: Mapped[str] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb"),
        nullable=False,
    )
    expected_intent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_tool_calls: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    expected_keywords: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    forbidden_keywords: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    assertions: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    extract: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    scenario: Mapped["ConversationScenario"] = relationship(back_populates="turns")


class AgentTestRun(Base):
    """一次对话场景的执行记录。"""

    __tablename__ = "agent_test_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversation_scenario.id"), nullable=False, index=True
    )
    status: Mapped[AgentTestRunStatus] = mapped_column(
        Enum(AgentTestRunStatus, native_enum=False, values_callable=lambda x: [i.value for i in x]),
        default=AgentTestRunStatus.pending,
    )
    total_turns: Mapped[int] = mapped_column(Integer, default=0)
    passed_turns: Mapped[int] = mapped_column(Integer, default=0)
    failed_turns: Mapped[int] = mapped_column(Integer, default=0)
    config_override: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    scenario: Mapped["ConversationScenario"] = relationship(back_populates="runs")
    turn_results: Mapped[list["TurnResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="TurnResult.turn_index"
    )


class TurnResult(Base):
    """单轮对话的执行结果。"""

    __tablename__ = "turn_result"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_test_run.id"), nullable=False, index=True
    )
    turn_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversation_turn.id"), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_user_message: Mapped[str] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb"),
        nullable=False,
    )
    actual_agent_response: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb"),
        nullable=True,
    )
    actual_tool_calls: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 请求快照：记录实际发出的 URL / headers / body，用于调试
    request_snapshot: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    assertion_results: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    extracted_vars: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["AgentTestRun"] = relationship(back_populates="turn_results")
    turn: Mapped["ConversationTurn"] = relationship()
