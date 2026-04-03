from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServiceCreate(BaseModel):
    name: str = Field(..., max_length=255)
    base_url: str
    swagger_url: str | None = None


class ServiceOut(BaseModel):
    id: str
    name: str
    base_url: str
    swagger_url: str | None

    model_config = ConfigDict(from_attributes=True)


class EndpointListItemOut(BaseModel):
    """服务下 endpoint 列表项（含可编辑的测试设计说明）。"""

    id: str
    method: str
    path: str
    operation_id: str | None
    fingerprint: str
    test_design_notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class EndpointNotesPatch(BaseModel):
    test_design_notes: str | None = Field(
        default=None,
        max_length=16000,
        description="当前接口的测试设计补充说明，生成用例时以高优先级注入 LLM；传 null 或空串可清空。",
    )


class SyncRequest(BaseModel):
    swagger_url: str | None = None
    fetch_headers: dict[str, str] | None = None


class SyncJobOut(BaseModel):
    id: str
    service_id: str
    snapshot_id: str | None
    status: str
    error_code: str | None
    error_message: str | None
    endpoints_added: int
    endpoints_updated: int
    endpoints_unchanged: int

    model_config = ConfigDict(from_attributes=True)

    @field_validator("status", mode="before")
    @classmethod
    def _status_to_str(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        return str(getattr(v, "value", v))

    @field_validator("endpoints_added", "endpoints_updated", "endpoints_unchanged", mode="before")
    @classmethod
    def _counts_to_int(cls, v: Any) -> int:
        if v is None:
            return 0
        return int(v)


class GenerateCasesRequest(BaseModel):
    suite_name: str | None = None
    approve: bool = False
    business_context: str | None = Field(
        default=None,
        max_length=48000,
        description="产品/领域业务说明（状态机、前置条件、错误分支等），与 OpenAPI 一并传给 LLM。",
    )
    scenario_matrix: dict[str, list[str]] | None = Field(
        default=None,
        description=(
            "场景组合矩阵：key=场景变量名，value=可选值数组。后端会做笛卡尔积展开并要求 LLM 覆盖路径。"
            '例如 {"推荐产品数":["0","1","3+"],"理财卡余额":["足够","不足"]}'
        ),
    )
    scenario_max_combinations: int = Field(
        default=128,
        ge=1,
        le=2000,
        description="场景矩阵最大展开条数（超出会截断）。",
    )


class SuiteOut(BaseModel):
    id: str
    service_id: str
    endpoint_id: str | None
    name: str
    snapshot_id: str | None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ScenarioPathCoverageOut(BaseModel):
    """场景矩阵 path-NNN 在用例 name 中的覆盖情况（生成接口返回）。"""

    enabled: bool = False
    expected_paths: list[str] = Field(default_factory=list)
    covered_paths: list[str] = Field(default_factory=list)
    missing_paths: list[str] = Field(default_factory=list)
    total_cartesian_combinations: int = 0
    expanded_paths_count: int = 0
    truncated: bool = False
    coverage_ratio: float = 0.0
    path_labels: dict[str, str] = Field(default_factory=dict)


class GenerateCasesOut(BaseModel):
    suite: SuiteOut
    path_coverage: ScenarioPathCoverageOut


class TestCaseOut(BaseModel):
    """单条用例：含 LLM 生成的 steps_json / variables_json，供查看与执行。"""

    id: str
    suite_id: str
    external_id: str
    name: str
    priority: int
    tags: list[Any] | None = None
    steps_json: list[Any]
    variables_json: dict[str, Any] | None = None
    status: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("status", mode="before")
    @classmethod
    def _case_status_to_str(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        return str(getattr(v, "value", v))


class GenerateCasesBatchRequest(BaseModel):
    """不传 endpoint_ids 表示该服务下全部 endpoint。"""

    endpoint_ids: list[str] | None = None
    suite_name_prefix: str | None = Field(default=None, max_length=200)
    approve: bool = False
    continue_on_error: bool = True
    limit: int | None = Field(default=None, ge=1, le=2000, description="最多处理多少个 endpoint，省略则全部")
    business_context: str | None = Field(
        default=None,
        max_length=48000,
        description="同上，批量时每个 endpoint 生成均附带该业务说明。",
    )
    scenario_matrix: dict[str, list[str]] | None = Field(
        default=None,
        description="同上，批量生成时每个 endpoint 共用该场景矩阵。",
    )
    scenario_max_combinations: int = Field(
        default=128,
        ge=1,
        le=2000,
        description="同上，场景矩阵最大展开条数。",
    )


class GenerateCasesBatchFailure(BaseModel):
    endpoint_id: str
    code: str
    message: str


class GenerateCasesBatchOut(BaseModel):
    service_id: str
    total: int
    processed: int
    succeeded: int
    failed: int
    suites: list[SuiteOut]
    path_coverages: list[ScenarioPathCoverageOut] = Field(
        default_factory=list,
        description="与 suites 顺序一一对应（成功生成的套件）。",
    )
    failures: list[GenerateCasesBatchFailure]


class RunSuiteRequest(BaseModel):
    target_base_url: str | None = None
    only_approved: bool = False
    generate_reports: bool = True
    # 手动追加到每一步请求的认证头（如 Authorization）。
    # 该字段会合并进 TestCase.steps_json 的 headers 中，且用户提供的同名 header 优先覆盖。
    auth_headers: dict[str, str] | None = None


class TestRunOut(BaseModel):
    id: str
    suite_id: str | None
    trigger: str
    status: str
    target_base_url: str
    started_at: datetime | None
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("status", mode="before")
    @classmethod
    def _run_status_str(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        return str(getattr(v, "value", v))


class RunSuitesBatchRequest(BaseModel):
    """不传 suite_ids 表示该服务下所有套件（至少含一条用例）。"""

    suite_ids: list[str] | None = None
    target_base_url: str | None = None
    only_approved: bool = False
    generate_reports: bool = True


class RunSuitesBatchSkip(BaseModel):
    suite_id: str
    reason: str


class RunSuitesBatchOut(BaseModel):
    service_id: str
    total_suites: int
    runs_started: int
    runs: list[TestRunOut]
    skipped: list[RunSuitesBatchSkip]


class ReportOut(BaseModel):
    id: str
    run_id: str
    format: str
    storage_path: str
    summary_json: dict[str, Any] | None

    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None
