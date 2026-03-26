/** 与 FastAPI 后端 /api/v1 对齐；开发环境依赖 Vite proxy，生产可设 VITE_API_BASE */

import { notifyApiError } from "./apiErrorBus";

const base = (): string => (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

export type ApiRequestOptions = {
  /** 为 true 时不弹出全局错误框（仍 throw） */
  silent?: boolean;
};

async function parseError(res: Response): Promise<string> {
  const t = await res.text();
  try {
    const j = JSON.parse(t) as { detail?: unknown; message?: string };
    if (typeof j.message === "string") return j.message;
    if (j.detail && typeof j.detail === "object" && j.detail !== null && "message" in j.detail) {
      return String((j.detail as { message: string }).message);
    }
    if (typeof j.detail === "string") return j.detail;
    return t.slice(0, 500);
  } catch {
    return t.slice(0, 500) || res.statusText;
  }
}

export async function api<T>(path: string, init?: RequestInit, opts?: ApiRequestOptions): Promise<T> {
  const silent = opts?.silent === true;
  const report = (msg: string, title?: string) => {
    if (!silent) notifyApiError(msg, title);
  };

  const url = `${base()}${path.startsWith("/") ? path : `/${path}`}`;
  const headers: HeadersInit = {
    Accept: "application/json",
    ...(init?.body ? { "Content-Type": "application/json" } : {}),
    ...init?.headers,
  };

  let res: Response;
  try {
    res = await fetch(url, { ...init, headers });
  } catch (e) {
    const detail = e instanceof Error ? e.message : String(e);
    const msg = `网络异常，无法完成请求：${detail}`;
    report(msg);
    throw new Error(msg);
  }

  if (!res.ok) {
    const body = await parseError(res);
    const msg = `HTTP ${res.status}：${body}`;
    report(msg);
    throw new Error(msg);
  }

  if (res.status === 204) return undefined as T;

  try {
    return (await res.json()) as T;
  } catch (e) {
    const detail = e instanceof Error ? e.message : String(e);
    const msg = `响应不是合法 JSON：${detail}`;
    report(msg);
    throw new Error(msg);
  }
}

export type ServiceOut = {
  id: string;
  name: string;
  base_url: string;
  swagger_url: string | null;
};

export type EndpointRow = {
  id: string;
  method: string;
  path: string;
  operation_id: string | null;
  fingerprint: string;
  /** 测试设计者对当前接口的补充说明，生成用例时高优先级注入 LLM */
  test_design_notes?: string | null;
};

export type SuiteOut = {
  id: string;
  service_id: string;
  endpoint_id: string | null;
  name: string;
  snapshot_id: string | null;
  created_at?: string | null;
};

/** 场景 path-NNN 在用例 name 中的覆盖统计 */
export type ScenarioPathCoverageOut = {
  enabled: boolean;
  expected_paths: string[];
  covered_paths: string[];
  missing_paths: string[];
  total_cartesian_combinations: number;
  expanded_paths_count: number;
  truncated: boolean;
  coverage_ratio: number;
  path_labels: Record<string, string>;
};

export type GenerateCasesOut = {
  suite: SuiteOut;
  path_coverage: ScenarioPathCoverageOut;
};

export type TestCaseOut = {
  id: string;
  suite_id: string;
  external_id: string;
  name: string;
  priority: number;
  tags: unknown;
  steps_json: unknown[];
  variables_json: Record<string, unknown> | null;
  status: string;
  created_at?: string | null;
};

export type SyncJobOut = {
  id: string;
  service_id: string;
  snapshot_id: string | null;
  status: string;
  error_code: string | null;
  error_message: string | null;
  endpoints_added: number;
  endpoints_updated: number;
  endpoints_unchanged: number;
};

export type TestRunOut = {
  id: string;
  suite_id: string | null;
  trigger: string;
  status: string;
  target_base_url: string;
  started_at: string | null;
  finished_at: string | null;
};

export type ReportOut = {
  id: string;
  run_id: string;
  format: string;
  storage_path: string;
  summary_json: Record<string, unknown> | null;
};

export type GenerateCasesBatchOut = {
  service_id: string;
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  suites: SuiteOut[];
  path_coverages: ScenarioPathCoverageOut[];
  failures: { endpoint_id: string; code: string; message: string }[];
};

export type RunSuitesBatchOut = {
  service_id: string;
  total_suites: number;
  runs_started: number;
  runs: TestRunOut[];
  skipped: { suite_id: string; reason: string }[];
};

// ---------------------------------------------------------------------------
//  Mock 数据平台
// ---------------------------------------------------------------------------

export type ColumnDef = {
  name: string;
  type: string;
  description?: string | null;
};

export type MockDataTableOut = {
  id: string;
  scenario_id: string;
  table_name: string;
  description: string | null;
  schema_json: ColumnDef[];
  rows_json: Record<string, unknown>[];
  created_at?: string | null;
  updated_at?: string | null;
};

export type MockApiRuleOut = {
  id: string;
  scenario_id: string;
  table_id: string | null;
  method: string;
  path: string;
  description: string | null;
  action: string;
  key_field: string | null;
  response_template_json: Record<string, unknown> | null;
  created_at?: string | null;
};

export type MockScenarioOut = {
  id: string;
  name: string;
  description: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type MockScenarioDetailOut = MockScenarioOut & {
  tables: MockDataTableOut[];
  api_rules: MockApiRuleOut[];
};

export type MockLLMGenerateOut = {
  scenario: MockScenarioOut;
  tables_created: number;
  rules_created: number;
};

export type MockScenarioResetOut = {
  scenario_id: string;
  reset_tables: number;
};

export type MockTableStateUpdate = {
  table_id?: string | null;
  table_name?: string | null;
  rows_json: unknown[];
};

export type MockEndpointMappingOut = {
  id: string;
  scenario_id: string;
  method: string;
  path: string;
  action: string;
  table_id: string | null;
  key_field: string | null;
  required_body_fields: string[];
  response_template_json: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export const listMockScenarios = () =>
  api<MockScenarioOut[]>("/api/v1/mock/scenarios");

export const createMockScenario = (body: { name: string; description?: string | null }) =>
  api<MockScenarioOut>("/api/v1/mock/scenarios", { method: "POST", body: JSON.stringify(body) });

export const getMockScenario = (id: string) =>
  api<MockScenarioDetailOut>(`/api/v1/mock/scenarios/${id}`);

export const deleteMockScenario = (id: string) =>
  api<void>(`/api/v1/mock/scenarios/${id}`, { method: "DELETE" });

export const createMockTable = (
  scenarioId: string,
  body: {
    table_name: string;
    description?: string | null;
    schema_json?: ColumnDef[];
    rows_json?: Record<string, unknown>[];
  },
) =>
  api<MockDataTableOut>(`/api/v1/mock/scenarios/${scenarioId}/tables`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateMockTable = (
  tableId: string,
  body: {
    table_name?: string;
    description?: string | null;
    schema_json?: ColumnDef[];
    rows_json?: Record<string, unknown>[];
  },
) =>
  api<MockDataTableOut>(`/api/v1/mock/tables/${tableId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteMockTable = (tableId: string) =>
  api<void>(`/api/v1/mock/tables/${tableId}`, { method: "DELETE" });

export const createMockRule = (
  scenarioId: string,
  body: {
    table_id?: string | null;
    method: string;
    path: string;
    description?: string | null;
    action: string;
    key_field?: string | null;
    response_template_json?: Record<string, unknown> | null;
  },
) =>
  api<MockApiRuleOut>(`/api/v1/mock/scenarios/${scenarioId}/rules`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateMockRule = (
  ruleId: string,
  body: {
    table_id?: string | null;
    method?: string;
    path?: string;
    description?: string | null;
    action?: string;
    key_field?: string | null;
  },
) =>
  api<MockApiRuleOut>(`/api/v1/mock/rules/${ruleId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteMockRule = (ruleId: string) =>
  api<void>(`/api/v1/mock/rules/${ruleId}`, { method: "DELETE" });

export const llmGenerateMockScenario = (body: {
  business_description: string;
  table_count_hint?: number;
  rows_per_table_hint?: number;
}) =>
  api<MockLLMGenerateOut>("/api/v1/mock/scenarios/generate", {
    method: "POST",
    body: JSON.stringify(body),
  });

// ---------------------------------------------------------------------------
//  Mock 运行时数据：state / reset
// ---------------------------------------------------------------------------

export const resetMockScenario = (scenarioId: string) =>
  api<MockScenarioResetOut>(`/api/v1/mock/scenarios/${scenarioId}/reset`, { method: "POST" });

export const updateMockScenarioState = (
  scenarioId: string,
  body: { tables: MockTableStateUpdate[] },
) => api<{
  scenario_id: string;
  updated_tables: MockDataTableOut[];
}>(`/api/v1/mock/scenarios/${scenarioId}/state`, {
  method: "PATCH",
  body: JSON.stringify(body),
});

// ---------------------------------------------------------------------------
//  Mock Endpoint Mapping（把运行时 Mock 映射到生产风格 URL）
// ---------------------------------------------------------------------------

export const listMockEndpointMappings = (scenarioId: string) =>
  api<MockEndpointMappingOut[]>(`/api/v1/mock/scenarios/${scenarioId}/mappings`);

export const createMockEndpointMapping = (
  scenarioId: string,
  body: {
    method: string;
    path: string;
    action: string;
    table_id?: string | null;
    key_field?: string | null;
    required_body_fields?: string[];
    response_template_json?: Record<string, unknown> | null;
  },
) =>
  api<MockEndpointMappingOut>(`/api/v1/mock/scenarios/${scenarioId}/mappings`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateMockEndpointMapping = (
  mappingId: string,
  body: {
    method?: string | null;
    path?: string | null;
    action?: string | null;
    table_id?: string | null;
    key_field?: string | null;
    required_body_fields?: string[] | null;
    response_template_json?: Record<string, unknown> | null;
  },
) =>
  api<MockEndpointMappingOut>(`/api/v1/mock/mappings/${mappingId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteMockEndpointMapping = (mappingId: string) =>
  api<void>(`/api/v1/mock/mappings/${mappingId}`, { method: "DELETE" });

// ---------------------------------------------------------------------------

export const health = () => api<{ status: string }>("/health", undefined, { silent: true });

export const listServices = () => api<ServiceOut[]>("/api/v1/services");

export const createService = (body: { name: string; base_url: string; swagger_url?: string | null }) =>
  api<ServiceOut>("/api/v1/services", { method: "POST", body: JSON.stringify(body) });

export const serviceStats = (serviceId: string) =>
  api<{ service_id: string; endpoint_count: number }>(`/api/v1/services/${serviceId}/stats`);

export const listEndpoints = (serviceId: string) =>
  api<EndpointRow[]>(`/api/v1/services/${serviceId}/endpoints`);

export const patchEndpointNotes = (endpointId: string, body: { test_design_notes?: string | null }) =>
  api<EndpointRow>(`/api/v1/endpoints/${endpointId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const listServiceSuites = (serviceId: string) =>
  api<SuiteOut[]>(`/api/v1/services/${serviceId}/suites`);

export const triggerSync = (serviceId: string, body: { swagger_url?: string | null; fetch_headers?: Record<string, string> | null }) =>
  api<SyncJobOut>(`/api/v1/services/${serviceId}/sync`, { method: "POST", body: JSON.stringify(body) });

export const generateCasesBatch = (
  serviceId: string,
  body: {
    endpoint_ids?: string[] | null;
    suite_name_prefix?: string | null;
    approve?: boolean;
    continue_on_error?: boolean;
    limit?: number | null;
    /** 产品/业务说明，与 OpenAPI 一并传给 LLM */
    business_context?: string | null;
    /** 场景矩阵：key=变量，value=可选值数组 */
    scenario_matrix?: Record<string, string[]> | null;
    scenario_max_combinations?: number;
  },
) =>
  api<GenerateCasesBatchOut>(`/api/v1/services/${serviceId}/generate-cases-batch`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const runSuitesBatch = (
  serviceId: string,
  body: {
    suite_ids?: string[] | null;
    target_base_url?: string | null;
    only_approved?: boolean;
    generate_reports?: boolean;
  },
) =>
  api<RunSuitesBatchOut>(`/api/v1/services/${serviceId}/run-suites-batch`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const generateCasesForEndpoint = (
  endpointId: string,
  body: {
    suite_name?: string | null;
    approve?: boolean;
    business_context?: string | null;
    scenario_matrix?: Record<string, string[]> | null;
    scenario_max_combinations?: number;
  } = {},
) =>
  api<GenerateCasesOut>(`/api/v1/endpoints/${endpointId}/generate-cases`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listEndpointSuites = (endpointId: string) =>
  api<SuiteOut[]>(`/api/v1/endpoints/${endpointId}/suites`);

export const getSuite = (suiteId: string) => api<SuiteOut>(`/api/v1/suites/${suiteId}`);

export const listSuiteCases = (suiteId: string) =>
  api<TestCaseOut[]>(`/api/v1/suites/${suiteId}/test-cases`);

export const runSuite = (
  suiteId: string,
  body: {
    target_base_url?: string | null;
    only_approved?: boolean;
    generate_reports?: boolean;
    auth_headers?: Record<string, string> | null;
  },
) =>
  api<TestRunOut>(`/api/v1/suites/${suiteId}/run`, { method: "POST", body: JSON.stringify(body) });

export const getRun = (runId: string) => api<TestRunOut>(`/api/v1/runs/${runId}`);

export const listReports = (runId: string) => api<ReportOut[]>(`/api/v1/runs/${runId}/reports`);
