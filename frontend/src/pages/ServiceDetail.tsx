import { Fragment, useCallback, useEffect, useState } from "react";
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
  const [batchBusinessContext, setBatchBusinessContext] = useState("");
  const [batchScenarioMatrixJson, setBatchScenarioMatrixJson] = useState("");
  const [batchScenarioMax, setBatchScenarioMax] = useState("128");
  const [batchResult, setBatchResult] = useState<api.GenerateCasesBatchOut | null>(null);

  const [runBase, setRunBase] = useState("");
  const [runOnlyAppr, setRunOnlyAppr] = useState(false);
  const [runReports, setRunReports] = useState(true);
  const [batchRunResult, setBatchRunResult] = useState<api.RunSuitesBatchOut | null>(null);

  /** 各 endpoint「生成用例」：旁路 loading / 成功勾 */
  const [endpointGenUi, setEndpointGenUi] = useState<Record<string, "idle" | "loading" | "done">>({});
  /** 单次生成返回的路径覆盖报告（与 scenario_matrix 对应） */
  const [endpointPathCoverage, setEndpointPathCoverage] = useState<
    Record<string, api.ScenarioPathCoverageOut | undefined>
  >({});
  /** 单接口自定义场景矩阵 JSON；留空则使用上方「批量 LLM 生成」里的共享场景矩阵 */
  const [endpointScenarioMatrixJson, setEndpointScenarioMatrixJson] = useState<Record<string, string>>({});
  const [endpointMatrixOpen, setEndpointMatrixOpen] = useState<Record<string, boolean>>({});
  /** 每接口「测试设计说明」编辑区展开与草稿（保存后写入 DB，生成用例时高优先级注入 LLM） */
  const [endpointNotesOpen, setEndpointNotesOpen] = useState<Record<string, boolean>>({});
  const [endpointNotesDraft, setEndpointNotesDraft] = useState<Record<string, string>>({});
  const [endpointNotesSaving, setEndpointNotesSaving] = useState<string | null>(null);

  const resolveScenarioMatrixJsonText = (endpointId: string) => {
    const local = (endpointScenarioMatrixJson[endpointId] ?? "").trim();
    if (local) return local;
    return batchScenarioMatrixJson.trim();
  };

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
      const scenario_matrix = batchScenarioMatrixJson.trim()
        ? (JSON.parse(batchScenarioMatrixJson) as Record<string, string[]>)
        : null;
      const out = await api.generateCasesBatch(serviceId, {
        suite_name_prefix: batchPrefix.trim() || null,
        approve: batchApprove,
        continue_on_error: batchContinue,
        limit: batchLimit.trim() ? parseInt(batchLimit, 10) : null,
        business_context: batchBusinessContext.trim() || null,
        scenario_matrix,
        scenario_max_combinations: batchScenarioMax.trim() ? parseInt(batchScenarioMax, 10) : 128,
      });
      setBatchResult(out);
      await load();
    } catch (e) {
      if (e instanceof SyntaxError) {
        notifyApiError("场景矩阵须为合法 JSON 对象。", "格式错误");
      }
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

  const toggleEndpointNotes = (row: api.EndpointRow) => {
    setEndpointNotesOpen((m) => {
      const next = !m[row.id];
      if (next) {
        setEndpointNotesDraft((d) => ({ ...d, [row.id]: row.test_design_notes ?? "" }));
      }
      return { ...m, [row.id]: next };
    });
  };

  const saveEndpointNotes = async (endpointId: string) => {
    setEndpointNotesSaving(endpointId);
    try {
      const text = (endpointNotesDraft[endpointId] ?? "").trim();
      await api.patchEndpointNotes(endpointId, { test_design_notes: text || null });
      await load();
    } catch {
      /* api 层已弹窗 */
    } finally {
      setEndpointNotesSaving(null);
    }
  };

  const genOne = async (endpointId: string) => {
    setEndpointGenUi((m) => ({ ...m, [endpointId]: "loading" }));
    try {
      const matrixText = resolveScenarioMatrixJsonText(endpointId);
      const scenario_matrix = matrixText
        ? (JSON.parse(matrixText) as Record<string, string[]>)
        : null;
      const genOut = await api.generateCasesForEndpoint(endpointId, {
        business_context: batchBusinessContext.trim() || null,
        scenario_matrix,
        scenario_max_combinations: batchScenarioMax.trim() ? parseInt(batchScenarioMax, 10) : 128,
      });
      setEndpointPathCoverage((m) => ({ ...m, [endpointId]: genOut.path_coverage }));
      await load();
      setEndpointGenUi((m) => ({ ...m, [endpointId]: "done" }));
    } catch (e) {
      if (e instanceof SyntaxError) {
        notifyApiError("场景矩阵须为合法 JSON 对象。", "格式错误");
      }
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
        <label style={{ marginTop: "0.75rem", display: "block" }}>
          业务说明 business_context（可选，与 OpenAPI 一并传给 LLM；单行生成与批量生成共用）
          <textarea
            value={batchBusinessContext}
            onChange={(e) => setBatchBusinessContext(e.target.value)}
            placeholder="例如：订单状态 draft→paid→shipped；仅 paid 可取消；需先登录拿到 token…"
            rows={5}
            style={{ width: "100%", marginTop: "0.35rem" }}
          />
        </label>
        <label style={{ marginTop: "0.75rem", display: "block" }}>
          场景矩阵 scenario_matrix（可选，JSON 对象；后端自动展开路径组合）
          <textarea
            value={batchScenarioMatrixJson}
            onChange={(e) => setBatchScenarioMatrixJson(e.target.value)}
            placeholder={'{"推荐产品数":["0","1","多个"],"理财卡余额":["足够","不足"],"转账结果":["成功后购买","失败直接退出"]}'}
            rows={5}
            style={{ width: "100%", marginTop: "0.35rem" }}
          />
        </label>
        <label style={{ marginTop: "0.75rem", display: "block", maxWidth: "280px" }}>
          scenario_max_combinations
          <input value={batchScenarioMax} onChange={(e) => setBatchScenarioMax(e.target.value)} />
        </label>
        <p className="muted" style={{ fontSize: "0.8rem", marginTop: "0.5rem", marginBottom: 0 }}>
          批量返回中的 <span className="mono">path_coverages</span> 与 <span className="mono">suites</span> 顺序一一对应。
        </p>
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
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
          「接口说明」保存为当前接口的测试设计补充说明（写入数据库），生成用例时以{" "}
          <strong>★高优先级</strong> 注入大模型；「场景矩阵」若本行为空则沿用上方批量区的共享 JSON；共享{" "}
          <span className="mono">scenario_max_combinations</span> 与{" "}
          <span className="mono">business_context</span>。
        </p>
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
                <Fragment key={e.id}>
                  <tr>
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
                            aria-expanded={endpointNotesOpen[e.id] === true}
                            onClick={() => toggleEndpointNotes(e)}
                          >
                            {endpointNotesOpen[e.id] ? "收起接口说明" : "接口说明"}
                          </button>
                          <button
                            type="button"
                            className="btn secondary"
                            aria-expanded={endpointMatrixOpen[e.id] === true}
                            onClick={() =>
                              setEndpointMatrixOpen((m) => ({ ...m, [e.id]: !m[e.id] }))
                            }
                          >
                            {endpointMatrixOpen[e.id] ? "收起场景矩阵" : "场景矩阵"}
                          </button>
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
                  {endpointNotesOpen[e.id] && (
                    <tr className="endpoint-notes-row">
                      <td colSpan={4} style={{ paddingTop: "0.35rem", borderTop: "none" }}>
                        <label style={{ display: "block" }}>
                          <span className="mono">test_design_notes</span>（★高优先级注入 LLM，限 16000 字）
                          <textarea
                            value={endpointNotesDraft[e.id] ?? ""}
                            onChange={(ev) =>
                              setEndpointNotesDraft((d) => ({ ...d, [e.id]: ev.target.value }))
                            }
                            placeholder="例如：本接口由 Agent 调用；需覆盖 token 过期、重复提交、下游超时；关键断言在响应 JSON 的 code 字段…"
                            rows={6}
                            style={{ width: "100%", marginTop: "0.35rem" }}
                          />
                        </label>
                        <div className="row" style={{ marginTop: "0.5rem", gap: "0.5rem", alignItems: "center" }}>
                          <button
                            type="button"
                            className="btn"
                            disabled={endpointNotesSaving === e.id}
                            onClick={() => saveEndpointNotes(e.id)}
                          >
                            {endpointNotesSaving === e.id ? "保存中…" : "保存到服务端"}
                          </button>
                          {e.test_design_notes ? (
                            <span className="muted" style={{ fontSize: "0.8rem" }}>
                              已保存 {e.test_design_notes.length} 字（刷新后见最新）
                            </span>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  )}
                  {endpointMatrixOpen[e.id] && (
                    <tr className="endpoint-matrix-row">
                      <td colSpan={4} style={{ paddingTop: "0.35rem", borderTop: "none" }}>
                        <label style={{ display: "block" }}>
                          本接口 <span className="mono">scenario_matrix</span>（JSON 对象；留空则用批量区共享矩阵）
                          <textarea
                            value={endpointScenarioMatrixJson[e.id] ?? ""}
                            onChange={(ev) =>
                              setEndpointScenarioMatrixJson((m) => ({
                                ...m,
                                [e.id]: ev.target.value,
                              }))
                            }
                            placeholder='{"维度A":["值1","值2"],"维度B":["x","y"]}'
                            rows={5}
                            style={{ width: "100%", marginTop: "0.35rem", fontFamily: "ui-monospace, monospace" }}
                          />
                        </label>
                        {!endpointScenarioMatrixJson[e.id]?.trim() && batchScenarioMatrixJson.trim() ? (
                          <p className="muted" style={{ fontSize: "0.8rem", margin: "0.35rem 0 0" }}>
                            本行为空：点击「生成用例」时将使用上方批量区已填写的共享场景矩阵。
                          </p>
                        ) : null}
                      </td>
                    </tr>
                  )}
                  {endpointPathCoverage[e.id] && (
                    <tr className="path-coverage-row">
                      <td colSpan={4} style={{ paddingTop: 0, borderTop: "none" }}>
                        <p className="muted" style={{ fontSize: "0.85rem", margin: "0.25rem 0 0.5rem" }}>
                          路径覆盖报告（用例 name 是否包含 path-NNN）
                          {endpointPathCoverage[e.id]!.enabled
                            ? ` — ${endpointPathCoverage[e.id]!.covered_paths.length}/${endpointPathCoverage[e.id]!.expanded_paths_count}（ratio ${endpointPathCoverage[e.id]!.coverage_ratio}）`
                            : " — 未使用场景矩阵"}
                        </p>
                        <JsonBlock data={endpointPathCoverage[e.id]} />
                      </td>
                    </tr>
                  )}
                </Fragment>
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
