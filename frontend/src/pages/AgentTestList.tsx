import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import * as api from "../api/client";

export function AgentTestList() {
  const navigate = useNavigate();
  const [targets, setTargets] = useState<api.AgentTargetOut[]>([]);
  const [loading, setLoading] = useState(true);

  /* 创建 Agent Target */
  const [name, setName] = useState("");
  const [chatUrl, setChatUrl] = useState("");
  const [model, setModel] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [apiFormat, setApiFormat] = useState("agent_engine");
  const [dispatchProjectId, setDispatchProjectId] = useState("0");
  const [dispatchAgentId, setDispatchAgentId] = useState("main_planner");
  const [creating, setCreating] = useState(false);

  /* Agent 发现 */
  const [discoverUrl, setDiscoverUrl] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [importing, setImporting] = useState(false);
  const [discovered, setDiscovered] = useState<api.DiscoveredAgent[]>([]);

  /* 展开 target → 场景列表 */
  const [expanded, setExpanded] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState<api.ScenarioOut[]>([]);
  const [scenariosLoading, setScenariosLoading] = useState(false);

  /* 快速创建场景 */
  const [scName, setScName] = useState("");
  const [scDesc, setScDesc] = useState("");
  const [scCreating, setScCreating] = useState(false);

  /* LLM 生成场景 */
  const [genDesc, setGenDesc] = useState("");
  const [genTurns, setGenTurns] = useState(5);
  const [genTargetId, setGenTargetId] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const load = () => {
    setLoading(true);
    api.listAgentTargets().then(setTargets).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const handleCreateTarget = async () => {
    if (!name.trim() || !chatUrl.trim()) return;
    setCreating(true);
    try {
      const extra: Record<string, unknown> = {};
      if (apiFormat === "dispatch") {
        extra.project_id = dispatchProjectId.trim() || "0";
        extra.dispatch_agent_id = dispatchAgentId.trim() || "main_planner";
      }
      await api.createAgentTarget({
        name: name.trim(),
        chat_url: chatUrl.trim(),
        api_format: apiFormat,
        engine_base_url: apiFormat !== "openai_chat" ? chatUrl.trim() : null,
        engine_agent_type: apiFormat === "dispatch" ? dispatchAgentId.trim() : null,
        model: model.trim() || null,
        auth_type: authToken.trim() ? "bearer" : "none",
        auth_config: authToken.trim() ? { token: authToken.trim() } : null,
        extra_config: Object.keys(extra).length > 0 ? extra : null,
      });
      setName(""); setChatUrl(""); setModel(""); setAuthToken("");
      load();
    } catch { /* handled */ }
    finally { setCreating(false); }
  };

  const handleDeleteTarget = async (id: string) => {
    if (!confirm("确认删除该 Agent Target？")) return;
    try { await api.deleteAgentTarget(id); load(); } catch {}
  };

  const handleDiscover = async () => {
    if (!discoverUrl.trim()) return;
    setDiscovering(true);
    setDiscovered([]);
    try {
      const res = await api.discoverAgents({ engine_base_url: discoverUrl.trim() });
      setDiscovered(res.agents);
    } catch {}
    finally { setDiscovering(false); }
  };

  const handleImport = async () => {
    if (!discoverUrl.trim()) return;
    setImporting(true);
    try {
      const imported = await api.importDiscoveredAgents({ engine_base_url: discoverUrl.trim() });
      setDiscovered([]);
      load();
      if (imported.length === 0) alert("所有 Agent 已存在，无新增导入。");
    } catch {}
    finally { setImporting(false); }
  };

  const toggleExpand = async (id: string) => {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    setGenTargetId(null);
    setScenariosLoading(true);
    try {
      const list = await api.listScenarios(id);
      setScenarios(list);
    } catch { setScenarios([]); }
    finally { setScenariosLoading(false); }
  };

  const handleCreateScenario = async (targetId: string) => {
    if (!scName.trim()) return;
    setScCreating(true);
    try {
      const sc = await api.createScenario({
        agent_target_id: targetId,
        name: scName.trim(),
        description: scDesc.trim() || null,
      });
      setScName(""); setScDesc("");
      navigate(`/agent-test/scenarios/${sc.id}`);
    } catch {}
    finally { setScCreating(false); }
  };

  const handleGenerate = async (targetId: string) => {
    if (!genDesc.trim()) return;
    setGenerating(true);
    try {
      const sc = await api.generateScenario(targetId, {
        business_description: genDesc.trim(),
        max_turns: genTurns,
      });
      setGenDesc("");
      setGenTargetId(null);
      navigate(`/agent-test/scenarios/${sc.id}`);
    } catch {}
    finally { setGenerating(false); }
  };

  return (
    <>
      {/* Agent 发现 */}
      <div className="card">
        <h2>从 Agent Engine 发现并导入</h2>
        <p className="muted" style={{ fontSize: "0.8rem", margin: "0 0 0.5rem" }}>
          连接运行中的 DevelopmentAgentEngine，自动发现可用的 Agent 并一键导入
        </p>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label style={{ flex: 1 }}>
            Agent Engine 地址
            <input value={discoverUrl} onChange={e => setDiscoverUrl(e.target.value)}
              placeholder="如: http://localhost:8080" />
          </label>
          <button className="btn" disabled={discovering || !discoverUrl.trim()} onClick={handleDiscover}>
            {discovering ? "发现中…" : "发现 Agent"}
          </button>
          {discovered.length > 0 && (
            <button className="btn" disabled={importing} onClick={handleImport}>
              {importing ? "导入中…" : `一键导入 (${discovered.length})`}
            </button>
          )}
        </div>
        {discovered.length > 0 && (
          <table style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>
            <thead><tr><th>Agent ID</th><th>类型</th><th>描述</th><th>状态</th></tr></thead>
            <tbody>
              {discovered.map((a, i) => (
                <tr key={i}>
                  <td className="mono">{a.agent_id}</td>
                  <td>{a.agent_type_name}</td>
                  <td className="muted">{a.description || "—"}</td>
                  <td><span className="badge">{a.status || "—"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 手动创建 Agent Target */}
      <div className="card">
        <h2>手动注册 Agent 端点</h2>
        <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
          <label>
            协议
            <select value={apiFormat} onChange={e => setApiFormat(e.target.value)}>
              <option value="dispatch">Dispatch（/v1/.../conversations）</option>
              <option value="agent_engine">Agent Engine（/api/v1/agent/execute）</option>
              <option value="openai_chat">OpenAI Chat Completions</option>
            </select>
          </label>
          <label>
            名称
            <input value={name} onChange={e => setName(e.target.value)} placeholder="如：理财顾问Agent" />
          </label>
          <label style={{ flex: 1 }}>
            {apiFormat === "dispatch" ? "引擎基地址" : "API URL"}
            <input value={chatUrl} onChange={e => setChatUrl(e.target.value)}
              placeholder={apiFormat === "dispatch"
                ? "如: http://127.0.0.1:8000"
                : apiFormat === "agent_engine"
                ? "如: http://127.0.0.1:8000/api/v1/agent/execute"
                : "如: https://api.openai.com/v1/chat/completions"} />
          </label>
          {apiFormat === "dispatch" && (
            <>
              <label>
                Project ID
                <input value={dispatchProjectId} onChange={e => setDispatchProjectId(e.target.value)}
                  placeholder="0" style={{ minWidth: "5rem" }} />
              </label>
              <label>
                Agent ID (路径)
                <input value={dispatchAgentId} onChange={e => setDispatchAgentId(e.target.value)}
                  placeholder="main_planner" style={{ minWidth: "8rem" }} />
              </label>
            </>
          )}
          {apiFormat !== "dispatch" && (
            <label>
              模型
              <input value={model} onChange={e => setModel(e.target.value)} placeholder="可选" style={{ minWidth: "6rem" }} />
            </label>
          )}
          <label>
            Token
            <input value={authToken} onChange={e => setAuthToken(e.target.value)} placeholder="可选" style={{ minWidth: "6rem" }} />
          </label>
          <button className="btn" disabled={creating || !name.trim() || !chatUrl.trim()} onClick={handleCreateTarget}>
            注册
          </button>
        </div>
        {apiFormat === "dispatch" && (
          <p className="muted" style={{ fontSize: "0.75rem", margin: "0.5rem 0 0" }}>
            将调用 <code>POST {chatUrl || "http://..."}/v1/{dispatchProjectId}/agents/{dispatchAgentId}/conversations/&#123;conv_id&#125;</code>
          </p>
        )}
      </div>

      {/* Agent Target 列表 */}
      <div className="card">
        <h2>Agent 端点列表</h2>
        {loading ? (
          <p className="muted">加载中…</p>
        ) : targets.length === 0 ? (
          <p className="muted">暂无 Agent 端点。可从 Agent Engine 发现导入，或手动注册。</p>
        ) : (
          <table>
            <thead>
              <tr><th>名称</th><th>类型</th><th>协议</th><th>URL</th><th>更新时间</th><th></th></tr>
            </thead>
            <tbody>
              {targets.map(t => (
                <>
                  <tr key={t.id}>
                    <td>
                      <button className="btn secondary" style={{ fontSize: "0.8rem", padding: "0.2rem 0.5rem" }}
                        onClick={() => toggleExpand(t.id)}>
                        {expanded === t.id ? "▼" : "▶"} {t.name}
                      </button>
                    </td>
                    <td><span className="badge">{t.engine_agent_type || t.api_format}</span></td>
                    <td><span className="badge">{t.api_format}</span></td>
                    <td className="mono muted" style={{ maxWidth: "16rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {t.chat_url}
                    </td>
                    <td className="mono muted" style={{ whiteSpace: "nowrap" }}>
                      {t.updated_at ? new Date(t.updated_at).toLocaleString() : "—"}
                    </td>
                    <td>
                      <button className="btn secondary" style={{ fontSize: "0.75rem", padding: "0.25rem 0.5rem" }}
                        onClick={() => handleDeleteTarget(t.id)}>删除</button>
                    </td>
                  </tr>
                  {expanded === t.id && (
                    <tr key={`${t.id}-exp`}>
                      <td colSpan={6} style={{ background: "var(--bg)", padding: "0.75rem 1rem" }}>
                        {/* AI 生成场景 */}
                        <div className="mock-form-section" style={{ marginBottom: "0.75rem" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.35rem" }}>
                            <strong style={{ fontSize: "0.85rem" }}>AI 自动生成测试场景</strong>
                            {genTargetId !== t.id ? (
                              <button className="btn secondary" style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }}
                                onClick={() => setGenTargetId(t.id)}>展开</button>
                            ) : (
                              <button className="btn secondary" style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }}
                                onClick={() => setGenTargetId(null)}>收起</button>
                            )}
                          </div>
                          {genTargetId === t.id && (
                            <>
                              <label style={{ marginBottom: "0.35rem" }}>
                                业务场景描述
                                <textarea value={genDesc} onChange={e => setGenDesc(e.target.value)}
                                  placeholder={"例如：测试理财Agent的基金推荐与购买完整流程\n1. 用户咨询理财产品\n2. 用户指定风险偏好后获得推荐\n3. 用户选择产品并购买"}
                                  rows={3} />
                              </label>
                              <div className="row" style={{ alignItems: "flex-end" }}>
                                <label>
                                  对话轮数
                                  <input type="number" min={2} max={20} value={genTurns}
                                    onChange={e => setGenTurns(Number(e.target.value))} style={{ width: "5rem", minWidth: "auto" }} />
                                </label>
                                <button className="btn" disabled={generating || !genDesc.trim()} onClick={() => handleGenerate(t.id)}>
                                  {generating ? "生成中…" : "AI 生成"}
                                </button>
                              </div>
                              {generating && <p className="muted" style={{ margin: "0.5rem 0 0" }}>正在调用大模型生成测试场景…</p>}
                            </>
                          )}
                        </div>

                        {/* 手动创建场景 */}
                        <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end", marginBottom: "0.75rem", flexWrap: "wrap" }}>
                          <label>
                            场景名称
                            <input value={scName} onChange={e => setScName(e.target.value)} placeholder="如：新客户购买基金流程" />
                          </label>
                          <label style={{ flex: 1 }}>
                            描述（可选）
                            <input value={scDesc} onChange={e => setScDesc(e.target.value)} placeholder="场景描述" />
                          </label>
                          <button className="btn secondary" disabled={scCreating || !scName.trim()} onClick={() => handleCreateScenario(t.id)}>
                            手动创建
                          </button>
                        </div>

                        {/* 场景列表 */}
                        {scenariosLoading ? (
                          <p className="muted" style={{ margin: 0 }}>加载场景…</p>
                        ) : scenarios.length === 0 ? (
                          <p className="muted" style={{ margin: 0 }}>暂无测试场景</p>
                        ) : (
                          <table style={{ fontSize: "0.8rem" }}>
                            <thead>
                              <tr><th>场景名称</th><th>描述</th><th>标签</th><th>创建时间</th></tr>
                            </thead>
                            <tbody>
                              {scenarios.map(s => (
                                <tr key={s.id}>
                                  <td><Link to={`/agent-test/scenarios/${s.id}`}>{s.name}</Link></td>
                                  <td className="muted" style={{ maxWidth: "16rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                    {s.description || "—"}
                                  </td>
                                  <td>
                                    {s.tags?.map((tag, i) => <span key={i} className="badge" style={{ marginRight: "0.25rem" }}>{tag}</span>)}
                                  </td>
                                  <td className="mono muted">{s.created_at ? new Date(s.created_at).toLocaleString() : "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
