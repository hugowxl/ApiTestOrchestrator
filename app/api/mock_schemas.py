from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
#  MockScenario
# ---------------------------------------------------------------------------


class MockScenarioCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None


class MockScenarioOut(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class MockScenarioDetailOut(MockScenarioOut):
    tables: list["MockDataTableOut"] = Field(default_factory=list)
    api_rules: list["MockApiRuleOut"] = Field(default_factory=list)


# ---------------------------------------------------------------------------
#  MockDataTable
# ---------------------------------------------------------------------------


class ColumnDef(BaseModel):
    name: str
    type: str = "string"
    description: str | None = None


class MockDataTableCreate(BaseModel):
    table_name: str = Field(..., max_length=255)
    description: str | None = None
    schema_json: list[ColumnDef] = Field(default_factory=list)
    rows_json: list[dict[str, Any]] = Field(default_factory=list)


class MockDataTableUpdate(BaseModel):
    table_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    schema_json: list[ColumnDef] | None = None
    rows_json: list[dict[str, Any]] | None = None


class MockDataTableOut(BaseModel):
    id: str
    scenario_id: str
    table_name: str
    description: str | None
    schema_json: list[Any]
    rows_json: list[Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
#  MockApiRule
# ---------------------------------------------------------------------------


class MockApiRuleCreate(BaseModel):
    table_id: str | None = None
    method: str = Field(..., pattern=r"^(GET|POST|PUT|PATCH|DELETE)$")
    path: str = Field(..., max_length=2048)
    description: str | None = None
    action: str = Field(..., pattern=r"^(list|get_by_id|create|update|delete|custom)$")
    key_field: str | None = None
    response_template_json: dict[str, Any] | None = None


class MockApiRuleUpdate(BaseModel):
    table_id: str | None = None
    method: str | None = Field(default=None, pattern=r"^(GET|POST|PUT|PATCH|DELETE)$")
    path: str | None = Field(default=None, max_length=2048)
    description: str | None = None
    action: str | None = Field(default=None, pattern=r"^(list|get_by_id|create|update|delete|custom)$")
    key_field: str | None = None
    response_template_json: dict[str, Any] | None = None


class MockApiRuleOut(BaseModel):
    id: str
    scenario_id: str
    table_id: str | None
    method: str
    path: str
    description: str | None
    action: str
    key_field: str | None
    response_template_json: dict[str, Any] | None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
#  LLM 生成 Mock 数据
# ---------------------------------------------------------------------------


class MockLLMGenerateRequest(BaseModel):
    """让大模型根据业务描述自动设计 mock 数据表、示例数据和 API 规则。"""

    business_description: str = Field(
        ...,
        max_length=16000,
        description="业务场景描述，例如: 模拟购买理财产品，含理财产品查询、用户余额查询、余额操作",
    )
    table_count_hint: int = Field(default=0, ge=0, le=20, description="期望生成的数据表数量提示，0 表示由 LLM 自行决定")
    rows_per_table_hint: int = Field(default=5, ge=1, le=50, description="每张表的示例数据行数提示")


class MockLLMGenerateOut(BaseModel):
    scenario: MockScenarioOut
    tables_created: int
    rules_created: int


# ---------------------------------------------------------------------------
#  Mock 运行时数据：state 更新 / reset
# ---------------------------------------------------------------------------


class MockTableStateUpdate(BaseModel):
    """外部接口直接覆盖某张数据表的运行时数据 rows_json。"""

    table_id: str | None = None
    table_name: str | None = None
    rows_json: list[Any] = Field(default_factory=list)


class MockScenarioStateUpdateRequest(BaseModel):
    tables: list[MockTableStateUpdate] = Field(default_factory=list)


class MockScenarioStateUpdateOut(BaseModel):
    scenario_id: str
    updated_tables: list[MockDataTableOut] = Field(default_factory=list)


class MockScenarioResetOut(BaseModel):
    scenario_id: str
    reset_tables: int


# ---------------------------------------------------------------------------
#  Endpoint Mapping（运行时映射到类似生产环境 URL）
# ---------------------------------------------------------------------------


class MockEndpointMappingCreate(BaseModel):
    method: str = Field(..., pattern=r"^(GET|POST|PUT|PATCH|DELETE)$")
    path: str = Field(..., max_length=2048)
    action: str = Field(..., pattern=r"^(list|get_by_id|create|update|delete|custom)$")
    table_id: str | None = None
    key_field: str | None = None
    required_body_fields: list[str] = Field(default_factory=list)
    response_template_json: dict[str, Any] | None = None


class MockEndpointMappingUpdate(BaseModel):
    method: str | None = Field(default=None, pattern=r"^(GET|POST|PUT|PATCH|DELETE)$")
    path: str | None = Field(default=None, max_length=2048)
    action: str | None = Field(default=None, pattern=r"^(list|get_by_id|create|update|delete|custom)$")
    table_id: str | None = None
    key_field: str | None = None
    required_body_fields: list[str] | None = None
    response_template_json: dict[str, Any] | None = None


class MockEndpointMappingOut(BaseModel):
    id: str
    scenario_id: str
    method: str
    path: str
    action: str
    table_id: str | None
    key_field: str | None
    required_body_fields: list[str]
    response_template_json: dict[str, Any] | None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
