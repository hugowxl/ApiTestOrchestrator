import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { notifyApiError } from "../api/apiErrorBus";
import * as api from "../api/client";
import { JsonBlock } from "../components/JsonBlock";

export function ServiceDetail() {
  const { serviceId = "" } = useParams();
  const [stats, setStats] = useState<{ endpoint_count: number } | null>(null);
  const [endpoints, setEndpoints] = useState<api.EndpointRow[]>([]);
  const [suites, setSuites] = useState<api.SuiteOut[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const [syncSwaggerUrl, setSyncSwaggerUrl] = useState("");
  const [syncHeadersJson, setSyncHeadersJson] = useState("");
  const [lastSync, setLastSync] = useState<api.SyncJobOut | null>(null);

  const [batchPrefix, setBatchPrefix] = useState("");
  const [batchLimit, setBatchLimit] = useState("");
  const [batchApprove, setBatchApprove] = useState(false);
  const [batchContinue, setBatchContinue] = useState(true);
  const [batchResult, setBatchResult] = useState<api.GenerateCasesBatchOut | null>(null);

  const [runBase, setRunBase] = useState("");
  const [runOnlyAppr, setRunOnlyAppr] = useState(false);
  const [runReports, setRunReports] = useState(true);
  const [batchRunResult, setBatchRunResult] = useState<api.RunSuitesBatchOut | null>(null);

  /** 各 endpoint「生成用例」：旁路 loading / 成功勾 */
  const [endpointGenUi, setEndpointGenUi] = useState<Record<string, "idle" | "loading" | "done">>({});

  const load = useCallback(() => {
    if (!serviceId) return;
    Promise.all([
      api.serviceStats(serviceId),
      api.listEndpoints(serviceId),
      api.listServiceSuites(serviceId),
    ])
      .then(([st, ep, su]) => {
        setStats(st);
        setEndpoints(ep);
        setSuites(su);
      })
      .catch(() => {});
  }, [serviceId]);

  useEffect(() => {
    load();
  }, [load]);

  const doSync = async () => {
    setBusy("sync");
    try {
      let fetch_headers: Record<string, string> | null = null;
      if (syncHeadersJson.trim()) {
        fetch_headers = JSON.parse(syncHeadersJson) as Record<string, string>;
      }
      const job = await api.triggerSync(serviceId, {
        swagger_url: syncSwaggerUrl.trim() || null,
        fetch_headers,
      });
      setLastSync(job);
      await load();
    } catch (e) {
      if (e instanceof SyntaxError) {
        notifyApiError("同步请求头须为合法 JSON 对象。", "格式错误");
      }
      /* 其余错误（含接口）已由 api 层弹窗提示 */
    } finally {
      setBusy(null);
    }
  };

  const doBatchGen = async () => {
    setBusy("batch-gen");
    setBatchResult(null);
    try {
      const out = await api.generateCasesBatch(serviceId, {
        suite_name_prefix: batchPrefix.trim() || null,
        approve: batchApprove,
        continue_on_error: batchContinue,
        limit: batchLimit.trim() ? parseInt(batchLimit, 10) : null,
      });
      setBatchResult(out);
      await load();
    } catch {
      /* 错误已由 api 层弹窗提示 */
    } finally {
      setBusy(null);
    }
  };

  const doBatchRun = async () => {
    setBusy("batch-run");
    setBatchRunResult(null);
    try {
      const out = await api.runSuitesBatch(serviceId, {
        target_base_url: runBase.trim() || null,
        only_approved: runOnlyAppr,
        generate_reports: runReports,
      });
      setBatchRunResult(out);
    } catch {
      /* 错误已由 api 层弹窗提示 */
    } finally {
      setBusy(null);
    }
  };

  const genOne = async (endpointId: string) => {
    setEndpointGenUi((m) => ({ ...m, [endpointId]: "loading" }));
    try {
      await api.generateCasesForEndpoint(endpointId, {});
      await load();
      setEndpointGenUi((m) => ({ ...m, [endpointId]: "done" }));
    } catch {
      setEndpointGenUi((m) => ({ ...m, [endpointId]: "idle" }));
    }
  };

  if (!serviceId) return <p className="err">缺少 serviceId</p>;

  return (
    <>
      <p>
        <Link to="/">← 服务列表</Link>
      </p>

      <div className="card">
        <h2>概览</h2>
        <p>
          service_id: <span className="mono">{serviceId}</span>
        </p>
        {stats && <p>Endpoint 数量: {stats.endpoint_count}</p>}
        <button type="button" className="btn secondary" onClick={load}>
          刷新
        </button>
      </div>

      <div className="card">
        <h2>同步 Swagger</h2>
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
          POST /api/v1/services/&#123;id&#125;/sync
        </p>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label>
            swagger_url（可选覆盖）
            <input value={syncSwaggerUrl} onChange={(e) => setSyncSwaggerUrl(e.target.value)} />
          </label>
          <button type="button" className="btn" disabled={busy === "sync"} onClick={doSync}>
            触发同步
          </button>
        </div>
        <label style={{ marginTop: "0.75rem" }}>
          fetch_headers JSON（可选）
          <textarea value={syncHeadersJson} onChange={(e) => setSyncHeadersJson(e.target.value)} placeholder='{"Authorization":"Bearer ..."}' />
        </label>
        {lastSync && (
          <div style={{ marginTop: "0.75rem" }}>
            <p className="ok-msg">同步任务: {lastSync.status}</p>
            <JsonBlock data={lastSync} />
          </div>
        )}
      </div>

      <div className="card">
        <h2>批量 LLM 生成用例</h2>
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
          POST /api/v1/services/&#123;id&#125;/generate-cases-batch
        </p>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label>
            suite_name_prefix
            <input value={batchPrefix} onChange={(e) => setBatchPrefix(e.target.value)} />
          </label>
          <label>
            limit
            <input value={batchLimit} onChange={(e) => setBatchLimit(e.target.value)} placeholder="空=全部" />
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={batchApprove} onChange={(e) => setBatchApprove(e.target.checked)} />
            approve
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={batchContinue} onChange={(e) => setBatchContinue(e.target.checked)} />
            continue_on_error
          </label>
          <button type="button" className="btn" disabled={busy === "batch-gen"} onClick={doBatchGen}>
            批量生成
          </button>
        </div>
        {batchResult && (
          <div style={{ marginTop: "0.75rem" }}>
            <p>
              成功 {batchResult.succeeded} / 失败 {batchResult.failed} / 合计 {batchResult.total}
            </p>
            <JsonBlock data={batchResult} />
          </div>
        )}
      </div>

      <div className="card">
        <h2>批量执行套件</h2>
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
          POST /api/v1/services/&#123;id&#125;/run-suites-batch（不传 suite_ids = 全部套件）
        </p>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label>
            target_base_url
            <input value={runBase} onChange={(e) => setRunBase(e.target.value)} placeholder="默认读后端 .env" />
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={runOnlyAppr} onChange={(e) => setRunOnlyAppr(e.target.checked)} />
            only_approved
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={runReports} onChange={(e) => setRunReports(e.target.checked)} />
            generate_reports
          </label>
          <button type="button" className="btn" disabled={busy === "batch-run"} onClick={doBatchRun}>
            批量执行
          </button>
        </div>
        {batchRunResult && (
          <div style={{ marginTop: "0.75rem" }}>
            <p>
              runs_started: {batchRunResult.runs_started}，skipped: {batchRunResult.skipped.length}
            </p>
            <JsonBlock data={batchRunResult} />
            {batchRunResult.runs.map((r) => (
              <p key={r.id}>
                <Link to={`/runs/${r.id}`}>查看 run {r.id.slice(0, 8)}…</Link> — {r.status}
              </p>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h2>Endpoints</h2>
        {endpoints.length === 0 ? (
          <p className="muted">暂无 endpoint，请先同步 Swagger。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>方法</th>
                <th>path</th>
                <th>operationId</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {endpoints.map((e) => (
                <tr key={e.id}>
                  <td>
                    <span className={`badge ${e.method.toLowerCase()}`}>{e.method}</span>
                  </td>
                  <td className="mono">{e.path}</td>
                  <td className="mono">{e.operation_id || "—"}</td>
                  <td>
                    <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                      <Link to={`/services/${serviceId}/endpoints/${e.id}`}>查看用例</Link>
                      <span className="gen-case-actions">
                        <button
                          type="button"
                          className="btn secondary"
                          disabled={endpointGenUi[e.id] === "loading"}
                          onClick={() => genOne(e.id)}
                        >
                          生成用例
                        </button>
                        {endpointGenUi[e.id] === "loading" && (
                          <span className="gen-status" title="正在生成…" aria-live="polite" aria-label="正在生成用例">
                            <span className="icon-spinner" />
                          </span>
                        )}
                        {endpointGenUi[e.id] === "done" && (
                          <span className="gen-status gen-status--done" title="生成完成" aria-label="生成完成">
                            ✓
                          </span>
                        )}
                      </span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>测试套件</h2>
        {suites.length === 0 ? (
          <p className="muted">暂无套件。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>suite_id</th>
                <th>endpoint_id</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {suites.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td className="mono">{s.id}</td>
                  <td className="mono">{s.endpoint_id || "—"}</td>
                  <td>
                    <Link to={`/suites/${s.id}`}>用例与执行</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
