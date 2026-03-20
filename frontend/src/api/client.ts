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
};

export type SuiteOut = {
  id: string;
  service_id: string;
  endpoint_id: string | null;
  name: string;
  snapshot_id: string | null;
  created_at?: string | null;
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
  failures: { endpoint_id: string; code: string; message: string }[];
};

export type RunSuitesBatchOut = {
  service_id: string;
  total_suites: number;
  runs_started: number;
  runs: TestRunOut[];
  skipped: { suite_id: string; reason: string }[];
};

export const health = () => api<{ status: string }>("/health", undefined, { silent: true });

export const listServices = () => api<ServiceOut[]>("/api/v1/services");

export const createService = (body: { name: string; base_url: string; swagger_url?: string | null }) =>
  api<ServiceOut>("/api/v1/services", { method: "POST", body: JSON.stringify(body) });

export const serviceStats = (serviceId: string) =>
  api<{ service_id: string; endpoint_count: number }>(`/api/v1/services/${serviceId}/stats`);

export const listEndpoints = (serviceId: string) =>
  api<EndpointRow[]>(`/api/v1/services/${serviceId}/endpoints`);

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
  body: { suite_name?: string | null; approve?: boolean } = {},
) =>
  api<SuiteOut>(`/api/v1/endpoints/${endpointId}/generate-cases`, {
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
