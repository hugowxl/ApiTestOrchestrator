"""Agent 多轮对话测试的 Pydantic 请求/响应模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
#  AgentTarget
# ---------------------------------------------------------------------------


class AgentTargetCreate(BaseModel):
    name: str = Field(..., max_length=255)
    chat_url: str = Field(..., description="Agent 对话 API 地址")
    api_format: str = Field(
        default="openai_chat",
        description="openai_chat (标准Chat Completions) | agent_engine (DevelopmentAgentEngine)",
    )
    model: str | None = Field(default=None, description="模型名称（如 gpt-4）")
    auth_type: str = Field(default="bearer", description="bearer | api_key | none")
    auth_config: dict[str, Any] | None = Field(
        default=None,
        description='认证配置，如 {"token": "sk-..."} 或 {"header": "X-Api-Key", "value": "..."}',
    )
    tools_schema: list[dict[str, Any]] | None = Field(
        default=None,
        description="Agent 声明的工具/函数定义列表（OpenAI function calling 格式）",
    )
    default_system_prompt: str | None = None
    engine_agent_id: str | None = Field(default=None, description="Agent Engine 中的 agent_id")
    engine_agent_type: str | None = Field(default=None, description="Agent Engine 中的 agent_type_name")
    engine_base_url: str | None = Field(default=None, description="Agent Engine 基地址（用于发现接口）")
    agent_description: str | None = None
    agent_tools: list[dict[str, Any]] | None = Field(default=None, description="Agent 可用工具描述列表")
    extra_config: dict[str, Any] | None = None


class AgentTargetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    chat_url: str | None = None
    api_format: str | None = None
    model: str | None = None
    auth_type: str | None = None
    auth_config: dict[str, Any] | None = None
    tools_schema: list[dict[str, Any]] | None = None
    default_system_prompt: str | None = None
    engine_agent_id: str | None = None
    engine_agent_type: str | None = None
    engine_base_url: str | None = None
    agent_description: str | None = None
    agent_tools: list[dict[str, Any]] | None = None
    extra_config: dict[str, Any] | None = None


class AgentTargetOut(BaseModel):
    id: str
    name: str
    chat_url: str
    api_format: str = "openai_chat"
    model: str | None = None
    auth_type: str = "none"
    tools_schema: list[Any] | None = None
    default_system_prompt: str | None = None
    engine_agent_id: str | None = None
    engine_agent_type: str | None = None
    engine_base_url: str | None = None
    agent_description: str | None = None
    agent_tools: list[Any] | None = None
    extra_config: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
#  ConversationScenario
# ---------------------------------------------------------------------------


class ConversationTurnCreate(BaseModel):
    turn_index: int = Field(..., ge=0)
    user_message: str
    expected_intent: str | None = None
    expected_tool_calls: list[dict[str, Any]] | None = None
    expected_keywords: list[str] | None = None
    forbidden_keywords: list[str] | None = None
    assertions: list[dict[str, Any]] | None = None
    extract: list[dict[str, Any]] | None = None


class ConversationTurnOut(BaseModel):
    id: str
    scenario_id: str
    turn_index: int
    user_message: str
    expected_intent: str | None = None
    expected_tool_calls: list[Any] | None = None
    expected_keywords: list[str] | None = None
    forbidden_keywords: list[str] | None = None
    assertions: list[Any] | None = None
    extract: list[Any] | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ConversationTurnUpdate(BaseModel):
    turn_index: int | None = None
    user_message: str | None = None
    expected_intent: str | None = None
    expected_tool_calls: list[dict[str, Any]] | None = None
    expected_keywords: list[str] | None = None
    forbidden_keywords: list[str] | None = None
    assertions: list[dict[str, Any]] | None = None
    extract: list[dict[str, Any]] | None = None


class ScenarioCreate(BaseModel):
    agent_target_id: str
    name: str = Field(..., max_length=512)
    description: str | None = None
    tags: list[str] | None = None
    initial_context: dict[str, Any] | None = None
    max_turns: int = Field(default=20, ge=1, le=100)
    turns: list[ConversationTurnCreate] | None = Field(
        default=None, description="可选：创建场景时一并创建轮次"
    )


class ScenarioOut(BaseModel):
    id: str
    agent_target_id: str
    name: str
    description: str | None = None
    tags: list[str] | None = None
    initial_context: dict[str, Any] | None = None
    max_turns: int
    active_mock_profile_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ScenarioDetailOut(ScenarioOut):
    turns: list[ConversationTurnOut] = Field(default_factory=list)
    agent_target: AgentTargetOut | None = None


# ---------------------------------------------------------------------------
#  AgentTestRun / TurnResult
# ---------------------------------------------------------------------------


class RunScenarioRequest(BaseModel):
    chat_url_override: str | None = Field(default=None, description="覆盖 AgentTarget 的 chat_url")
    auth_override: dict[str, Any] | None = None
    model_override: str | None = None
    extra_variables: dict[str, str] | None = Field(
        default=None, description="额外变量注入（合并到 initial_context）"
    )


class TurnResultOut(BaseModel):
    id: str
    run_id: str
    turn_id: str
    turn_index: int
    actual_user_message: str
    actual_agent_response: str | None = None
    actual_tool_calls: list[Any] | None = None
    latency_ms: int = 0
    request_snapshot: dict[str, Any] | None = None
    raw_response: dict[str, Any] | None = None
    passed: bool = False
    assertion_results: list[Any] | None = None
    extracted_vars: dict[str, Any] | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AgentTestRunOut(BaseModel):
    id: str
    scenario_id: str
    status: str
    total_turns: int
    passed_turns: int
    failed_turns: int
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("status", mode="before")
    @classmethod
    def _status_to_str(cls, v: Any) -> str:
        if isinstance(v, str):
            return v
        return str(getattr(v, "value", v))


class AgentTestRunDetailOut(AgentTestRunOut):
    turn_results: list[TurnResultOut] = Field(default_factory=list)
    scenario: ScenarioOut | None = None


# ---------------------------------------------------------------------------
#  Agent 发现 & 场景自动生成
# ---------------------------------------------------------------------------


class DiscoverAgentsRequest(BaseModel):
    engine_base_url: str = Field(..., description="Agent Engine 基地址，如 http://localhost:8080")


class DiscoveredAgent(BaseModel):
    agent_id: str
    agent_type_name: str
    description: str = ""
    status: str = ""
    tools: list[str] = Field(default_factory=list)


class DiscoverAgentsOut(BaseModel):
    engine_base_url: str
    agents: list[DiscoveredAgent]


class GenerateScenarioRequest(BaseModel):
    business_description: str = Field(
        ..., description="业务场景描述，如：测试理财Agent的基金推荐与购买流程"
    )
    max_turns: int = Field(default=5, ge=2, le=20)
    focus_tools: list[str] | None = Field(
        default=None, description="重点测试的工具列表（为空则覆盖所有工具）"
    )


# ---------------------------------------------------------------------------
#  MockProfile（Mock 数据配置集）
# ---------------------------------------------------------------------------


class MockProfileCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None
    profile_data: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = False


class MockProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    profile_data: dict[str, Any] | None = None
    is_active: bool | None = None


class MockProfileOut(BaseModel):
    id: str
    scenario_id: str
    name: str
    description: str | None = None
    profile_data: dict[str, Any]
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class GenerateBranchesRequest(BaseModel):
    business_description: str = Field(
        ..., description="业务场景描述，包含需要覆盖的路径分支"
    )
    max_branches: int = Field(default=3, ge=1, le=10)
    max_turns_per_branch: int = Field(default=5, ge=2, le=20)
