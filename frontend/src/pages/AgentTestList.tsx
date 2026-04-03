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

  /* LLM 一键生成测试分支（Mock） */
  const [branchScenarioId, setBranchScenarioId] = useState("");
  const [branchDesc, setBranchDesc] = useState("");
  const [branchMax, setBranchMax] = useState(3);
  const [branchTurns, setBranchTurns] = useState(5);
  const [branchSkillId, setBranchSkillId] = useState<string | null>(null);
  const [branchGenerating, setBranchGenerating] = useState(false);
  const [branchSkills, setBranchSkills] = useState<api.MockBranchSkillOut[]>([]);
  const [branchSkillsLoading, setBranchSkillsLoading] = useState(false);
  const [branchResult, setBranchResult] = useState<{ created_scenarios: number; created_profiles: number } | null>(null);

  const load = () => {
    setLoading(true);
    api.listAgentTargets().then(setTargets).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    setBranchSkillsLoading(true);
    api.listMockBranchSkills()
      .then(setBranchSkills)
      .catch(() => setBranchSkills([]))
      .finally(() => setBranchSkillsLoading(false));
  }, []);

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

  const handleDeleteScenario = async (targetId: string, scenarioId: string) => {
    if (!confirm("确认删除该 Agent 测试场景？")) return;
    try {
      await api.deleteScenario(scenarioId);
      const list = await api.listScenarios(targetId);
      setScenarios(list);
    } catch { /* handled */ }
  };

  const openMockProfiles = (scenarioId: string) => {
    navigate(`/agent-test/scenarios/${scenarioId}?tab=mock-profiles`);
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

  const handleGenerateBranches = async () => {
    if (!branchScenarioId || !branchDesc.trim()) return;
    setBranchGenerating(true);
    setBranchResult(null);
    try {
      const res = await api.generateBranches(branchScenarioId, {
        business_description: branchDesc.trim(),
        max_branches: branchMax,
        max_turns_per_branch: branchTurns,
        skill_id: branchSkillId,
      });
      setBranchResult(res);
      setBranchDesc("");
    } catch {}
    finally { setBranchGenerating(false); }
  };

  const buildScenarioRows = (list: api.ScenarioOut[]) => {
    const byParent = new Map<string, api.ScenarioOut[]>();
    const roots: api.ScenarioOut[] = [];
    for (const s of list) {
      const pid = s.parent_scenario_id;
      if (!pid) {
        roots.push(s);
      } else {
        const arr = byParent.get(pid) ?? [];
        arr.push(s);
        byParent.set(pid, arr);
      }
    }
    roots.sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
    for (const arr of byParent.values()) {
      arr.sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
    }
    const rows: Array<{ s: api.ScenarioOut; level: number }> = [];
    const pushTree = (node: api.ScenarioOut, level: number) => {
      rows.push({ s: node, level });
      const children = byParent.get(node.id) ?? [];
      for (const c of children) pushTree(c, level + 1);
    };
    for (const r of roots) pushTree(r, 0);
    // 兼容历史数据：parent 指向不存在的场景时，仍展示
    const known = new Set(rows.map(x => x.s.id));
    const dangling = list.filter(s => !known.has(s.id));
    for (const d of dangling) rows.push({ s: d, level: 0 });
    return rows;
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
                          <div style={{ marginBottom: "0.35rem" }}>
                            <strong style={{ fontSize: "0.85rem" }}>LLM 一键生成测试分支（Mock）</strong>
                          </div>
                          <label style={{ marginBottom: "0.35rem" }}>
                            业务场景描述
                            <textarea
                              value={branchDesc}
                              onChange={e => setBranchDesc(e.target.value)}
                              placeholder={"例如：购买理财产品场景，推荐多只产品，仅选择其中一只购买；覆盖余额充足/不足/转账失败路径"}
                              rows={3}
                            />
                          </label>
                          <div className="row" style={{ alignItems: "flex-end", gap: "0.5rem", flexWrap: "wrap" }}>
                            <label style={{ minWidth: "14rem" }}>
                              选择场景
                              <select value={branchScenarioId} onChange={e => setBranchScenarioId(e.target.value)}>
                                <option value="">请选择场景</option>
                                {buildScenarioRows(scenarios).map(({ s, level }) => (
                                  <option key={s.id} value={s.id}>
                                    {`${"　".repeat(level)}${level > 0 ? "└ " : ""}${s.name}`}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label style={{ minWidth: "12rem" }}>
                              注入场景 Skill
                              <select
                                value={branchSkillId ?? ""}
                                onChange={e => setBranchSkillId(e.target.value ? e.target.value : null)}
                                disabled={branchSkillsLoading}
                              >
                                <option value="">默认（内置 SYSTEM_PROMPT）</option>
                                {branchSkills.map(s => (
                                  <option key={s.id} value={s.id} disabled={!s.enabled}>
                                    {!s.enabled ? `禁用：${s.name}` : s.name}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label>
                              分支数
                              <input type="number" min={1} max={10} value={branchMax}
                                onChange={e => setBranchMax(Math.max(1, Math.min(10, Number(e.target.value))))}
                                style={{ width: "5rem", minWidth: "auto" }} />
                            </label>
                            <label>
                              每分支最大轮次
                              <input type="number" min={2} max={20} value={branchTurns}
                                onChange={e => setBranchTurns(Math.max(2, Math.min(20, Number(e.target.value))))}
                                style={{ width: "5rem", minWidth: "auto" }} />
                            </label>
                            <button className="btn" disabled={branchGenerating || !branchScenarioId || !branchDesc.trim()} onClick={handleGenerateBranches}>
                              {branchGenerating ? "生成中…" : "生成分支"}
                            </button>
                          </div>
                          {branchResult && (
                            <p style={{ marginTop: "0.5rem", color: "var(--ok)" }}>
                              已生成 {branchResult.created_scenarios} 个场景、{branchResult.created_profiles} 个 MockProfile。
                            </p>
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
                              <tr><th>场景名称</th><th>描述</th><th>标签</th><th>创建时间</th><th>操作</th></tr>
                            </thead>
                            <tbody>
                              {buildScenarioRows(scenarios).map(({ s, level }) => (
                                <tr key={s.id}>
                                  <td>
                                    <Link to={`/agent-test/scenarios/${s.id}`}>
                                      {`${"　".repeat(level)}${level > 0 ? "└ " : ""}${s.name}`}
                                    </Link>
                                  </td>
                                  <td className="muted" style={{ maxWidth: "16rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                    {s.description || "—"}
                                  </td>
                                  <td>
                                    {s.tags?.map((tag, i) => <span key={i} className="badge" style={{ marginRight: "0.25rem" }}>{tag}</span>)}
                                  </td>
                                  <td className="mono muted">{s.created_at ? new Date(s.created_at).toLocaleString() : "—"}</td>
                                  <td>
                                    <button
                                      className="btn secondary"
                                      style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem", marginRight: "0.35rem" }}
                                      onClick={() => openMockProfiles(s.id)}
                                    >
                                      Mock 配置
                                    </button>
                                    <button
                                      className="btn secondary"
                                      style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem", color: "var(--bad)" }}
                                      onClick={() => handleDeleteScenario(t.id, s.id)}
                                    >
                                      删除
                                    </button>
                                  </td>
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
