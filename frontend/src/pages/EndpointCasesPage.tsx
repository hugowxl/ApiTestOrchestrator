import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api/client";
import { BriefReportSummary } from "../components/BriefReportSummary";
import { JsonBlock } from "../components/JsonBlock";

export function EndpointCasesPage() {
  const { serviceId = "", endpointId = "" } = useParams();
  const [endpoint, setEndpoint] = useState<api.EndpointRow | null>(null);
  const [suites, setSuites] = useState<api.SuiteOut[]>([]);
  const [casesBySuite, setCasesBySuite] = useState<Record<string, api.TestCaseOut[]>>({});
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [selectedSuiteId, setSelectedSuiteId] = useState("");
  const [targetBase, setTargetBase] = useState("");
  const [onlyAppr, setOnlyAppr] = useState(false);
  const [genReports, setGenReports] = useState(true);
  const [running, setRunning] = useState(false);

  const [lastRun, setLastRun] = useState<api.TestRunOut | null>(null);
  const [briefSummary, setBriefSummary] = useState<Record<string, unknown> | null>(null);

  const [expandedCase, setExpandedCase] = useState<string | null>(null);

  const loadSuitesAndCases = useCallback(async () => {
    if (!serviceId || !endpointId) return;
    setErr(null);
    setLoading(true);
    try {
      const [eps, su] = await Promise.all([
        api.listEndpoints(serviceId),
        api.listEndpointSuites(endpointId),
      ]);
      const ep = eps.find((e) => e.id === endpointId) || null;
      setEndpoint(ep);
      setSuites(su);
      const entries = await Promise.all(
        su.map(async (s) => {
          const cases = await api.listSuiteCases(s.id);
          return [s.id, cases] as const;
        }),
      );
      const map: Record<string, api.TestCaseOut[]> = {};
      for (const [id, cs] of entries) map[id] = cs;
      setCasesBySuite(map);
    } catch {
      /* 错误已由 api 层弹窗提示 */
    } finally {
      setLoading(false);
    }
  }, [serviceId, endpointId]);

  useEffect(() => {
    loadSuitesAndCases();
  }, [loadSuitesAndCases]);

  useEffect(() => {
    setLastRun(null);
    setBriefSummary(null);
    setExpandedCase(null);
  }, [endpointId]);

  useEffect(() => {
    setSelectedSuiteId((prev) => {
      if (suites.length === 0) return "";
      if (prev && suites.some((s) => s.id === prev)) return prev;
      return suites[0].id;
    });
  }, [suites]);

  const suiteOptions = useMemo(() => suites.map((s) => ({ id: s.id, label: s.name })), [suites]);

  const runSelectedSuite = async () => {
    if (!selectedSuiteId) {
      setErr("请先选择要执行的套件");
      return;
    }
    setRunning(true);
    setErr(null);
    setLastRun(null);
    setBriefSummary(null);
    try {
      const run = await api.runSuite(selectedSuiteId, {
        target_base_url: targetBase.trim() || null,
        only_approved: onlyAppr,
        generate_reports: genReports,
      });
      setLastRun(run);
      if (genReports) {
        const reps = await api.listReports(run.id);
        const jsonRep = reps.find((r) => r.format === "json");
        if (jsonRep?.summary_json) setBriefSummary(jsonRep.summary_json);
        else if (reps[0]?.summary_json) setBriefSummary(reps[0].summary_json as Record<string, unknown>);
      } else {
        setBriefSummary({
          status: run.status,
          passed: 0,
          failed: 0,
          total: 0,
          target_base_url: run.target_base_url,
          cases: [],
          note: "未生成报告（generate_reports=false），仅记录 run 状态",
        });
      }
      await loadSuitesAndCases();
    } catch {
      /* 错误已由 api 层弹窗提示 */
    } finally {
      setRunning(false);
    }
  };

  if (!serviceId || !endpointId) return <p className="err">路由参数不完整</p>;

  return (
    <>
      <p>
        <Link to="/">服务列表</Link>
        {" · "}
        <Link to={`/services/${serviceId}`}>服务详情</Link>
      </p>

      <div className="card">
        <h2>Endpoint</h2>
        {loading && !endpoint ? (
          <p className="muted">加载中…</p>
        ) : endpoint ? (
          <div className="row" style={{ alignItems: "center", gap: "0.75rem" }}>
            <span className={`badge ${endpoint.method.toLowerCase()}`}>{endpoint.method}</span>
            <span className="mono">{endpoint.path}</span>
            {endpoint.operation_id && <span className="muted mono">{endpoint.operation_id}</span>}
          </div>
        ) : (
          <p className="muted">未在列表中找到该 endpoint（可能已删除）</p>
        )}
        <p className="mono" style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
          endpoint_id: {endpointId}
        </p>
        <button type="button" className="btn secondary" style={{ marginTop: "0.5rem" }} onClick={() => loadSuitesAndCases()}>
          刷新套件与用例
        </button>
      </div>

      {err && <p className="err">{err}</p>}

      <div className="card">
        <h2>套件与用例</h2>
        {loading ? (
          <p className="muted">加载中…</p>
        ) : suites.length === 0 ? (
          <p className="muted">该 endpoint 下暂无套件，请先在服务详情中点击「生成用例」。</p>
        ) : (
          suites.map((s) => {
            const cases = casesBySuite[s.id] || [];
            return (
              <div key={s.id} className="suite-block" style={{ marginBottom: "1.25rem", paddingBottom: "1rem", borderBottom: "1px solid var(--border)" }}>
                <div className="row" style={{ alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
                  <strong>{s.name}</strong>
                  <span className="mono muted" style={{ fontSize: "0.8rem" }}>
                    {s.id}
                  </span>
                  <Link to={`/suites/${s.id}`}>套件页</Link>
                </div>
                {cases.length === 0 ? (
                  <p className="muted">无 test_case</p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>名称</th>
                        <th>external_id</th>
                        <th>status</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {cases.map((c) => (
                        <tr key={c.id}>
                          <td>{c.name}</td>
                          <td className="mono">{c.external_id}</td>
                          <td>{c.status}</td>
                          <td>
                            <button type="button" className="btn secondary" onClick={() => setExpandedCase(expandedCase === c.id ? null : c.id)}>
                              {expandedCase === c.id ? "收起" : "steps"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {cases.map(
                  (c) =>
                    expandedCase === c.id && (
                      <JsonBlock key={c.id} data={{ steps_json: c.steps_json, variables_json: c.variables_json }} />
                    ),
                )}
              </div>
            );
          })
        )}
      </div>

      <div className="card">
        <h2>执行用例</h2>
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
          选择套件后执行，对应 <span className="mono">POST /api/v1/suites/&#123;id&#125;/run</span>
        </p>
        <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
          <label>
            套件
            <select value={selectedSuiteId} onChange={(e) => setSelectedSuiteId(e.target.value)} style={{ minWidth: "14rem" }}>
              {suiteOptions.length === 0 ? (
                <option value="">暂无套件</option>
              ) : (
                suiteOptions.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label.slice(0, 60)}
                  </option>
                ))
              )}
            </select>
          </label>
          <label>
            target_base_url
            <input value={targetBase} onChange={(e) => setTargetBase(e.target.value)} placeholder="默认后端 .env" />
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={onlyAppr} onChange={(e) => setOnlyAppr(e.target.checked)} />
            only_approved
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={genReports} onChange={(e) => setGenReports(e.target.checked)} />
            generate_reports
          </label>
          <button type="button" className="btn" disabled={running || !selectedSuiteId} onClick={runSelectedSuite}>
            {running ? "执行中…" : "执行"}
          </button>
        </div>
        {lastRun && (
          <p style={{ marginTop: "0.75rem" }}>
            本次 run: <span className="mono">{lastRun.id}</span> — {lastRun.status}{" "}
            <Link to={`/runs/${lastRun.id}`}>完整报告页</Link>
          </p>
        )}
      </div>

      <div className="card">
        <h2>测试简要报告</h2>
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
          执行且开启 generate_reports 后，由最近一次运行的 JSON 报告摘要生成；完整文件见 run 详情或服务器{" "}
          <span className="mono">data/reports/</span>
        </p>
        {!lastRun && !briefSummary && <p className="muted">尚未在本页执行过，或上次未生成报告。</p>}
        {briefSummary && <BriefReportSummary summary={briefSummary} />}
      </div>
    </>
  );
}
