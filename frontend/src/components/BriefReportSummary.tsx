/** 与后端 report summary_json（build_summary）对齐的简要展示 */

import { Fragment } from "react";

type RequestStep = {
  method?: string;
  url?: string;
  query?: Record<string, string>;
  headers?: Record<string, string>;
  body_type?: string;
  body?: unknown;
};

type CaseRow = {
  name?: string;
  passed?: boolean;
  latency_ms?: number;
  error?: string | null;
  case_id?: string;
  /** 方法 + 含查询串的完整 URL，与报告 JSON/HTML 一致 */
  request_method_url?: string | null;
  /** Body / Headers 等摘要 */
  request_params_summary?: string | null;
  request_steps?: RequestStep[];
  request_summary?: string;
};

const BODY_PREVIEW_MAX = 800;

function bodyPreview(body: unknown, maxChars: number): string {
  if (body == null) return "";
  let text: string;
  try {
    text = typeof body === "object" ? JSON.stringify(body, null, 2) : String(body);
  } catch {
    text = String(body);
  }
  return text.length > maxChars ? text.slice(0, maxChars) + "…" : text;
}

function formatStepsPlain(steps: RequestStep[], maxBody = BODY_PREVIEW_MAX): string {
  const lines: string[] = [];
  steps.forEach((st, idx) => {
    const m = st.method ?? "?";
    const url = st.url ?? "—";
    lines.push(`${idx + 1}) ${m} ${url}`);
    const q = st.query && typeof st.query === "object" ? st.query : {};
    if (Object.keys(q).length) lines.push(`   query: ${JSON.stringify(q)}`);
    const h = st.headers && typeof st.headers === "object" ? st.headers : {};
    if (Object.keys(h).length) lines.push(`   headers: ${JSON.stringify(h)}`);
    const bt = st.body_type ?? "none";
    if (bt !== "none") {
      const body = bodyPreview(st.body, maxBody);
      if (body) {
        lines.push(`   body_type: ${bt}`);
        for (const bl of body.split("\n")) lines.push(`   ${bl}`);
      }
    }
  });
  return lines.length ? lines.join("\n") : "—";
}

function requestDetailText(c: CaseRow): string {
  if (typeof c.request_summary === "string" && c.request_summary.trim()) return c.request_summary;
  if (c.request_steps?.length) return formatStepsPlain(c.request_steps);
  return "—";
}

function hasRequestDetails(c: CaseRow): boolean {
  return Boolean(c.request_steps?.length || (typeof c.request_summary === "string" && c.request_summary));
}

export function BriefReportSummary({ summary }: { summary: Record<string, unknown> | null | undefined }) {
  if (!summary || typeof summary !== "object") return <p className="muted">暂无摘要</p>;

  const passed = Number(summary.passed ?? 0);
  const failed = Number(summary.failed ?? 0);
  const total = Number(summary.total ?? 0);
  const status = String(summary.status ?? "—");
  const target = String(summary.target_base_url ?? "—");
  const cases = (Array.isArray(summary.cases) ? summary.cases : []) as CaseRow[];
  const note = typeof summary.note === "string" ? summary.note : null;

  return (
    <div className="brief-report">
      {note && <p className="muted" style={{ marginBottom: "0.75rem" }}>{note}</p>}
      <div className="brief-report-stats row" style={{ gap: "1rem", marginBottom: "0.75rem" }}>
        <span>
          状态: <strong>{status}</strong>
        </span>
        <span className="ok-msg">通过 {passed}</span>
        <span style={{ color: "var(--bad)" }}>失败 {failed}</span>
        <span>合计 {total}</span>
        <span className="muted mono" style={{ fontSize: "0.8rem" }}>
          {target}
        </span>
      </div>
      {cases.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>用例</th>
              <th>结果</th>
              <th>耗时(ms)</th>
              <th>请求（方法+完整URL）</th>
              <th>传参</th>
              <th>错误</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c, i) => {
              const first = c.request_steps?.[0];
              const derivedMethodUrl =
                c.request_method_url ??
                (first ? `${first.method ?? "?"} ${first.url ?? "—"}` : null);
              const derivedParams =
                c.request_params_summary ??
                (c.request_summary?.trim()
                  ? c.request_summary
                  : c.request_steps?.length
                    ? formatStepsPlain(c.request_steps, 400)
                    : null);
              return (
                <Fragment key={c.case_id || String(i)}>
                  <tr>
                    <td>{c.name || c.case_id || "—"}</td>
                    <td>{c.passed ? <span className="ok-msg">PASS</span> : <span style={{ color: "var(--bad)" }}>FAIL</span>}</td>
                    <td>{c.latency_ms ?? "—"}</td>
                    <td
                      className="mono"
                      style={{ fontSize: "0.75rem", maxWidth: "18rem", wordBreak: "break-all", verticalAlign: "top" }}
                    >
                      {derivedMethodUrl ?? "—"}
                    </td>
                    <td
                      className="mono"
                      style={{ fontSize: "0.75rem", maxWidth: "20rem", whiteSpace: "pre-wrap", wordBreak: "break-word", verticalAlign: "top" }}
                    >
                      {derivedParams ?? "—"}
                    </td>
                    <td className="mono" style={{ fontSize: "0.8rem", maxWidth: "24rem", wordBreak: "break-word" }}>
                      {c.error || "—"}
                    </td>
                  </tr>
                  {hasRequestDetails(c) && (
                    <tr>
                      <td colSpan={6} style={{ paddingTop: "0.25rem", verticalAlign: "top" }}>
                        <details>
                          <summary style={{ cursor: "pointer", userSelect: "none" }}>请求 URL / 传参</summary>
                          <pre className="mono" style={{ fontSize: "0.75rem", whiteSpace: "pre-wrap" }}>
                            {requestDetailText(c)}
                          </pre>
                        </details>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
