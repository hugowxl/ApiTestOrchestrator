import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api/client";
import { JsonBlock } from "../components/JsonBlock";

export function SuiteDetail() {
  const { suiteId = "" } = useParams();
  const [suite, setSuite] = useState<api.SuiteOut | null>(null);
  const [cases, setCases] = useState<api.TestCaseOut[]>([]);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const [targetBase, setTargetBase] = useState("");
  const [onlyAppr, setOnlyAppr] = useState(false);
  const [genReports, setGenReports] = useState(true);
  const [lastRun, setLastRun] = useState<api.TestRunOut | null>(null);
  const [authHeadersJson, setAuthHeadersJson] = useState<string>("{}");
  const [authHeadersErr, setAuthHeadersErr] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!suiteId) return;
    Promise.all([api.getSuite(suiteId), api.listSuiteCases(suiteId)])
      .then(([su, cs]) => {
        setSuite(su);
        setCases(cs);
      })
      .catch(() => {});
  }, [suiteId]);

  useEffect(() => {
    load();
  }, [load]);

  const run = async () => {
    setBusy(true);
    setLastRun(null);
    try {
      setAuthHeadersErr(null);
      const raw = authHeadersJson.trim();
      let authHeaders: Record<string, string> | null = null;
      if (raw) {
        try {
          const parsed = JSON.parse(raw);
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            throw new Error("认证请求头必须是 JSON 对象");
          }
          authHeaders = parsed as Record<string, string>;
        } catch (e) {
          if (e instanceof Error) setAuthHeadersErr(e.message);
          return;
        }
      }

      const r = await api.runSuite(suiteId, {
        target_base_url: targetBase.trim() || null,
        only_approved: onlyAppr,
        generate_reports: genReports,
        auth_headers: authHeaders,
      });
      setLastRun(r);
    } catch (e) {
      /* 错误已由 api 层弹窗提示 */
    } finally {
      setBusy(false);
    }
  };

  if (!suiteId) return <p className="err">缺少 suiteId</p>;

  return (
    <>
      <p>
        <Link to="/">服务列表</Link>
        {suite && (
          <>
            {" · "}
            <Link to={`/services/${suite.service_id}`}>服务详情</Link>
          </>
        )}
      </p>

      <div className="card">
        <h2>套件</h2>
        {suite ? (
          <JsonBlock data={suite} />
        ) : (
          <p className="muted">加载中…</p>
        )}
      </div>

      <div className="card">
        <h2>执行套件</h2>
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
          POST /api/v1/suites/&#123;suite_id&#125;/run
        </p>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label>
            target_base_url
            <input value={targetBase} onChange={(e) => setTargetBase(e.target.value)} placeholder="默认后端 DEFAULT_TARGET_BASE_URL" />
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={onlyAppr} onChange={(e) => setOnlyAppr(e.target.checked)} />
            only_approved
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={genReports} onChange={(e) => setGenReports(e.target.checked)} />
            generate_reports
          </label>
          <button type="button" className="btn" disabled={busy} onClick={run}>
            执行
          </button>
        </div>
        <div className="row" style={{ alignItems: "flex-start", marginTop: "0.75rem" }}>
          <label style={{ flex: 1 }}>
            认证请求头（JSON）
            <textarea
              value={authHeadersJson}
              onChange={(e) => setAuthHeadersJson(e.target.value)}
              placeholder='{"Authorization":"Bearer <token>"}'
            />
          </label>
        </div>
        {authHeadersErr && <p className="err">{authHeadersErr}</p>}
        {lastRun && (
          <p style={{ marginTop: "0.75rem" }}>
            <span className="ok-msg">完成: {lastRun.status}</span> —{" "}
            <Link to={`/runs/${lastRun.id}`}>查看 run / 报告</Link>
          </p>
        )}
      </div>

      <div className="card">
        <h2>用例列表</h2>
        <button type="button" className="btn secondary" onClick={load} style={{ marginBottom: "0.75rem" }}>
          刷新用例
        </button>
        {cases.length === 0 ? (
          <p className="muted">暂无 test_case。</p>
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
                    <button type="button" className="btn secondary" onClick={() => setExpanded(expanded === c.id ? null : c.id)}>
                      {expanded === c.id ? "收起" : "steps_json"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {expanded &&
          cases
            .filter((c) => c.id === expanded)
            .map((c) => (
              <div key={c.id}>
                <JsonBlock data={{ steps_json: c.steps_json, variables_json: c.variables_json, tags: c.tags }} />
              </div>
            ))}
      </div>
    </>
  );
}
