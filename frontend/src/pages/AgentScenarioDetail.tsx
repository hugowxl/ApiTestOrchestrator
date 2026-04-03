import { useEffect, useState, useRef } from "react";
import { useLocation, useParams, Link, useNavigate } from "react-router-dom";
import * as api from "../api/client";

type Tab = "turns" | "runs" | "run-detail" | "mock-profiles";

export function AgentScenarioDetail() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [scenario, setScenario] = useState<api.ScenarioDetailOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("turns");

  /* 添加轮次 */
  const [userMsg, setUserMsg] = useState("");
  const [intent, setIntent] = useState("");
  const [keywords, setKeywords] = useState("");
  const [forbidden, setForbidden] = useState("");
  const [adding, setAdding] = useState(false);

  /* 流式执行 */
  const [running, setRunning] = useState(false);
  const [streamTurns, setStreamTurns] = useState<api.TurnResultOut[]>([]);
  const [streamProgress, setStreamProgress] = useState("");
  const [streamSummary, setStreamSummary] = useState<api.SSERunFinished | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  /* 同步执行结果（查看历史详情时） */
  const [runResult, setRunResult] = useState<api.AgentTestRunDetailOut | null>(null);

  /* 执行历史 */
  const [runs, setRuns] = useState<api.AgentTestRunOut[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  /* 查看某次执行的详情 */
  const [viewRun, setViewRun] = useState<api.AgentTestRunDetailOut | null>(null);

  const load = () => {
    if (!scenarioId) return;
    setLoading(true);
    api.getScenario(scenarioId).then(setScenario).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, [scenarioId]);

  // 支持从 URL 直接跳转到指定页签，例如：
  // /agent-test/scenarios/{id}?tab=mock-profiles
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const t = params.get("tab");
    if (!t) return;
    const allow: Tab[] = ["turns", "runs", "run-detail", "mock-profiles"];
    if (allow.includes(t as Tab)) setTab(t as Tab);
  }, [location.search, scenarioId]);

  const loadRuns = () => {
    if (!scenarioId) return;
    setRunsLoading(true);
    api.listScenarioRuns(scenarioId).then(setRuns).catch(() => {}).finally(() => setRunsLoading(false));
  };
  useEffect(() => { if (tab === "runs") loadRuns(); }, [tab, scenarioId]);

  const handleAddTurn = async () => {
    if (!scenarioId || !userMsg.trim()) return;
    setAdding(true);
    try {
      const nextIdx = (scenario?.turns?.length ?? 0);
      await api.addTurn(scenarioId, {
        turn_index: nextIdx,
        user_message: userMsg.trim(),
        expected_intent: intent.trim() || null,
        expected_keywords: keywords.trim() ? keywords.split(",").map(s => s.trim()).filter(Boolean) : null,
        forbidden_keywords: forbidden.trim() ? forbidden.split(",").map(s => s.trim()).filter(Boolean) : null,
        assertions: [{ type: "response_not_empty" }],
      });
      setUserMsg(""); setIntent(""); setKeywords(""); setForbidden("");
      load();
    } catch {}
    finally { setAdding(false); }
  };

  const handleDeleteTurn = async (turnId: string) => {
    if (!confirm("确认删除该轮次？")) return;
    try { await api.deleteTurn(turnId); load(); } catch {}
  };

  /* 编辑轮次 */
  const [editingTurnId, setEditingTurnId] = useState<string | null>(null);
  const [editFields, setEditFields] = useState<{
    user_message: string;
    expected_intent: string;
    expected_keywords: string;
    forbidden_keywords: string;
  }>({ user_message: "", expected_intent: "", expected_keywords: "", forbidden_keywords: "" });
  const [saving, setSaving] = useState(false);

  const startEdit = (t: api.ConversationTurnOut) => {
    setEditingTurnId(t.id);
    setEditFields({
      user_message: t.user_message,
      expected_intent: t.expected_intent || "",
      expected_keywords: (t.expected_keywords ?? []).join(", "),
      forbidden_keywords: (t.forbidden_keywords ?? []).join(", "),
    });
  };
  const cancelEdit = () => { setEditingTurnId(null); };
  const handleSaveEdit = async () => {
    if (!editingTurnId) return;
    setSaving(true);
    try {
      await api.updateTurn(editingTurnId, {
        user_message: editFields.user_message,
        expected_intent: editFields.expected_intent || null,
        expected_keywords: editFields.expected_keywords.trim()
          ? editFields.expected_keywords.split(",").map(s => s.trim()).filter(Boolean)
          : null,
        forbidden_keywords: editFields.forbidden_keywords.trim()
          ? editFields.forbidden_keywords.split(",").map(s => s.trim()).filter(Boolean)
          : null,
      });
      setEditingTurnId(null);
      load();
    } catch {}
    finally { setSaving(false); }
  };

  /* 单轮执行 */
  const [singleExecId, setSingleExecId] = useState<string | null>(null);
  const [singleExecResult, setSingleExecResult] = useState<api.TurnResultOut | null>(null);
  const [singleExecLoading, setSingleExecLoading] = useState(false);

  const handleExecSingleTurn = async (turnId: string) => {
    setSingleExecId(turnId);
    setSingleExecResult(null);
    setSingleExecLoading(true);
    try {
      const result = await api.executeSingleTurn(turnId);
      setSingleExecResult(result);
    } catch {}
    finally { setSingleExecLoading(false); }
  };

  const handleRun = () => {
    if (!scenarioId) return;
    setRunning(true);
    setRunResult(null);
    setStreamTurns([]);
    setStreamProgress("正在启动测试…");
    setStreamSummary(null);
    setViewRun(null);
    setTab("run-detail");

    const ctrl = api.runScenarioStream(scenarioId, {
      onStarted(e) {
        setStreamProgress(`正在执行第 1/${e.total_turns} 轮…`);
      },
      onTurn(tr) {
        setStreamTurns(prev => {
          const next = [...prev, tr];
          const total = scenario?.turns.length ?? next.length;
          if (next.length < total) {
            setStreamProgress(`正在执行第 ${next.length + 1}/${total} 轮…`);
          } else {
            setStreamProgress("所有轮次已完成，等待汇总…");
          }
          return next;
        });
      },
      onFinished(summary) {
        setStreamSummary(summary);
        setStreamProgress("");
        setRunning(false);
        loadRuns();
      },
      onError(msg) {
        setStreamProgress(`执行出错: ${msg}`);
        setRunning(false);
      },
    });
    abortRef.current = ctrl;
  };

  const handleCancelRun = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setRunning(false);
    setStreamProgress("已取消执行");
  };

  const handleViewRun = async (runId: string) => {
    try {
      const detail = await api.getAgentTestRun(runId);
      setStreamTurns([]);
      setStreamSummary(null);
      setStreamProgress("");
      setViewRun(detail);
      setTab("run-detail");
    } catch {}
  };

  const handleDeleteScenario = async () => {
    if (!scenarioId) return;
    if (!confirm("确认删除该 Agent 测试场景？")) return;
    try {
      await api.deleteScenario(scenarioId);
      navigate("/agent-test");
    } catch {}
  };

  /* Mock Profiles */
  const [mockProfiles, setMockProfiles] = useState<api.MockProfileOut[]>([]);
  const [mockLoading, setMockLoading] = useState(false);
  const [mpName, setMpName] = useState("");
  const [mpDesc, setMpDesc] = useState("");
  const [mpJson, setMpJson] = useState("{}");
  const [mpSaving, setMpSaving] = useState(false);
  const [mpEditId, setMpEditId] = useState<string | null>(null);
  const [mpEditName, setMpEditName] = useState("");
  const [mpEditDesc, setMpEditDesc] = useState("");
  const [mpEditJson, setMpEditJson] = useState("");
  const [mpEditSaving, setMpEditSaving] = useState(false);
  const [branchDesc, setBranchDesc] = useState("");
  const [branchMax, setBranchMax] = useState(3);
  const [branchTurns, setBranchTurns] = useState(5);
  const [branchGenerating, setBranchGenerating] = useState(false);
  const [branchResult, setBranchResult] = useState<{ created_scenarios: number; created_profiles: number } | null>(null);
  const [branchSkills, setBranchSkills] = useState<api.MockBranchSkillOut[]>([]);
  const [branchSkillsLoading, setBranchSkillsLoading] = useState(false);
  const [branchSkillId, setBranchSkillId] = useState<string | null>(null); // null = 默认 SYSTEM_PROMPT

  const loadMockProfiles = () => {
    if (!scenarioId) return;
    setMockLoading(true);
    api.listMockProfiles(scenarioId).then(setMockProfiles).catch(() => {}).finally(() => setMockLoading(false));
  };
  useEffect(() => { loadMockProfiles(); }, [scenarioId]);
  useEffect(() => { if (tab === "mock-profiles") loadMockProfiles(); }, [tab]);

  useEffect(() => {
    setBranchSkillsLoading(true);
    api.listMockBranchSkills()
      .then(setBranchSkills)
      .catch(() => setBranchSkills([]))
      .finally(() => setBranchSkillsLoading(false));
  }, []);

  const handleCreateProfile = async () => {
    if (!scenarioId || !mpName.trim()) return;
    setMpSaving(true);
    try {
      let pd: Record<string, unknown> = {};
      try { pd = JSON.parse(mpJson); } catch { /* keep empty */ }
      await api.createMockProfile(scenarioId, { name: mpName.trim(), description: mpDesc.trim() || undefined, profile_data: pd });
      setMpName(""); setMpDesc(""); setMpJson("{}");
      loadMockProfiles();
    } catch {}
    finally { setMpSaving(false); }
  };

  const handleActivateProfile = async (profileId: string) => {
    try { await api.activateMockProfile(profileId); loadMockProfiles(); load(); } catch {}
  };

  const handleDeleteProfile = async (profileId: string) => {
    if (!confirm("确认删除该 Mock Profile？")) return;
    try { await api.deleteMockProfile(profileId); loadMockProfiles(); load(); } catch {}
  };

  const startEditProfile = (p: api.MockProfileOut) => {
    setMpEditId(p.id);
    setMpEditName(p.name);
    setMpEditDesc(p.description || "");
    setMpEditJson(JSON.stringify(p.profile_data, null, 2));
  };

  const handleSaveEditProfile = async () => {
    if (!mpEditId) return;
    setMpEditSaving(true);
    try {
      let pd: Record<string, unknown> = {};
      try { pd = JSON.parse(mpEditJson); } catch { /* keep old */ }
      await api.updateMockProfile(mpEditId, { name: mpEditName, description: mpEditDesc || null, profile_data: pd });
      setMpEditId(null);
      loadMockProfiles();
    } catch {}
    finally { setMpEditSaving(false); }
  };

  if (loading) return <div className="card"><p className="muted">加载中…</p></div>;
  if (!scenario) return <div className="card"><p className="err">场景不存在</p></div>;

  const isStreaming = running || streamTurns.length > 0;
  const activeRunDetail = viewRun || runResult;
  const showRunTab = isStreaming || activeRunDetail;

  return (
    <>
      {/* 场景信息 */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <Link to="/agent-test" style={{ fontSize: "0.8rem" }}>← 返回列表</Link>
            <h2 style={{ margin: "0.25rem 0 0" }}>{scenario.name}</h2>
            {scenario.description && <p className="muted" style={{ margin: "0.25rem 0 0", fontSize: "0.85rem" }}>{scenario.description}</p>}
          </div>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <button
              className="btn secondary"
              style={{ fontSize: "0.8rem", padding: "0.2rem 0.6rem", color: "var(--bad)" }}
              onClick={handleDeleteScenario}
              disabled={running}
              title={running ? "执行中不可删除" : "删除场景"}
            >
              删除场景
            </button>
            <span className="muted" style={{ fontSize: "0.8rem" }}>
              {scenario.turns.length} 轮对话
            </span>
            {running ? (
              <button className="btn" style={{ background: "#c0392b" }} onClick={handleCancelRun}>
                取消执行
              </button>
            ) : (
              <button className="btn" disabled={scenario.turns.length === 0} onClick={handleRun}>
                执行测试
              </button>
            )}
          </div>
        </div>
        {scenario.agent_target && (
          <p className="muted" style={{ fontSize: "0.78rem", margin: "0.5rem 0 0" }}>
            Agent: {scenario.agent_target.name} | {scenario.agent_target.chat_url}
            {scenario.agent_target.model ? ` | ${scenario.agent_target.model}` : ""}
            {scenario.active_mock_profile_id && mockProfiles.length > 0 && (() => {
              const active = mockProfiles.find(p => p.id === scenario.active_mock_profile_id);
              return active ? ` | Mock: ${active.name}` : "";
            })()}
          </p>
        )}
      </div>

      {/* Tabs */}
      <div className="mock-tabs">
        <button className={`mock-tab ${tab === "turns" ? "active" : ""}`} onClick={() => setTab("turns")}>轮次编排</button>
        <button className={`mock-tab ${tab === "mock-profiles" ? "active" : ""}`} onClick={() => setTab("mock-profiles")}>Mock 数据配置</button>
        <button className={`mock-tab ${tab === "runs" ? "active" : ""}`} onClick={() => setTab("runs")}>执行历史</button>
        {showRunTab && (
          <button className={`mock-tab ${tab === "run-detail" ? "active" : ""}`} onClick={() => setTab("run-detail")}>
            {isStreaming && !activeRunDetail
              ? (running ? "执行中…" : (streamSummary ? `执行详情 (${streamSummary.status})` : "执行详情"))
              : `执行详情 (${activeRunDetail?.status ?? ""})`}
          </button>
        )}
      </div>

      {/* Tab: 轮次编排 */}
      {tab === "turns" && (
        <>
          {/* 添加轮次 */}
          <div className="card">
            <h2>添加对话轮次</h2>
            <label style={{ marginBottom: "0.5rem" }}>
              用户消息（支持 {"{{变量}}"} 引用）
              <textarea value={userMsg} onChange={e => setUserMsg(e.target.value)}
                placeholder="如：我想买点基金，有什么推荐的吗？" rows={2} />
            </label>
            <div className="row" style={{ alignItems: "flex-end" }}>
              <label>
                期望意图（可选）
                <input value={intent} onChange={e => setIntent(e.target.value)} placeholder="如：fund_inquiry" />
              </label>
              <label style={{ flex: 1 }}>
                期望关键词（逗号分隔）
                <input value={keywords} onChange={e => setKeywords(e.target.value)} placeholder="如：基金,推荐,风险" />
              </label>
              <label style={{ flex: 1 }}>
                禁止关键词（逗号分隔）
                <input value={forbidden} onChange={e => setForbidden(e.target.value)} placeholder="如：股票,期货" />
              </label>
              <button className="btn" disabled={adding || !userMsg.trim()} onClick={handleAddTurn}>添加</button>
            </div>
          </div>

          {/* 轮次列表 */}
          <div className="card">
            <h2>对话轮次 ({scenario.turns.length})</h2>
            {scenario.turns.length === 0 ? (
              <p className="muted">暂无轮次，请添加。</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                {scenario.turns.map((t, idx) => {
                  const isEditing = editingTurnId === t.id;
                  const isExecTarget = singleExecId === t.id;
                  return (
                    <div key={t.id} className="mock-table-card">
                      <div className="mock-table-header">
                        <div>
                          <span className="badge" style={{ marginRight: "0.5rem" }}>轮 {idx}</span>
                          <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                            {t.expected_intent ? `意图: ${t.expected_intent}` : ""}
                          </span>
                        </div>
                        <div style={{ display: "flex", gap: "0.3rem" }}>
                          {!isEditing && (
                            <>
                              <button className="btn secondary" style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem" }}
                                onClick={() => startEdit(t)}>编辑</button>
                              <button className="btn secondary" style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem" }}
                                disabled={singleExecLoading}
                                onClick={() => handleExecSingleTurn(t.id)}>
                                {singleExecLoading && isExecTarget ? "执行中…" : "单独执行"}
                              </button>
                              <button className="btn secondary" style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem", color: "var(--bad)" }}
                                onClick={() => handleDeleteTurn(t.id)}>删除</button>
                            </>
                          )}
                        </div>
                      </div>

                      {isEditing ? (
                        <div style={{ padding: "0.5rem 0", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
                          <label style={{ fontSize: "0.82rem" }}>
                            用户消息
                            <textarea
                              value={editFields.user_message}
                              onChange={e => setEditFields(f => ({ ...f, user_message: e.target.value }))}
                              rows={3}
                              style={{ marginTop: "0.2rem" }}
                            />
                          </label>
                          <div className="row" style={{ alignItems: "flex-end", gap: "0.5rem" }}>
                            <label style={{ flex: 1, fontSize: "0.82rem" }}>
                              期望意图
                              <input
                                value={editFields.expected_intent}
                                onChange={e => setEditFields(f => ({ ...f, expected_intent: e.target.value }))}
                              />
                            </label>
                            <label style={{ flex: 1, fontSize: "0.82rem" }}>
                              期望关键词（逗号分隔）
                              <input
                                value={editFields.expected_keywords}
                                onChange={e => setEditFields(f => ({ ...f, expected_keywords: e.target.value }))}
                              />
                            </label>
                            <label style={{ flex: 1, fontSize: "0.82rem" }}>
                              禁止关键词（逗号分隔）
                              <input
                                value={editFields.forbidden_keywords}
                                onChange={e => setEditFields(f => ({ ...f, forbidden_keywords: e.target.value }))}
                              />
                            </label>
                          </div>
                          <div style={{ display: "flex", gap: "0.4rem", justifyContent: "flex-end", marginTop: "0.2rem" }}>
                            <button className="btn secondary" onClick={cancelEdit} disabled={saving}>取消</button>
                            <button className="btn" onClick={handleSaveEdit} disabled={saving || !editFields.user_message.trim()}>
                              {saving ? "保存中…" : "保存"}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div style={{ padding: "0.5rem 0" }}>
                          <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", marginBottom: "0.35rem" }}>
                            <span style={{ background: "var(--accent-dim)", color: "#fff", padding: "0.1rem 0.4rem", borderRadius: "4px", fontSize: "0.72rem", flexShrink: 0 }}>
                              用户
                            </span>
                            <span style={{ fontSize: "0.85rem", whiteSpace: "pre-wrap" }}>{t.user_message}</span>
                          </div>
                          <div className="mock-schema-bar">
                            {t.expected_keywords?.map((kw, i) => (
                              <span key={i} className="mock-col-tag" style={{ color: "var(--ok)" }}>✓ {kw}</span>
                            ))}
                            {t.forbidden_keywords?.map((kw, i) => (
                              <span key={i} className="mock-col-tag" style={{ color: "var(--bad)" }}>✗ {kw}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* 单轮执行结果 */}
                      {isExecTarget && singleExecResult && (
                        <div style={{ borderTop: "1px solid var(--border)", marginTop: "0.25rem", paddingTop: "0.4rem" }}>
                          <TurnCard tr={singleExecResult} />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}

      {/* Tab: 执行历史 */}
      {tab === "runs" && (
        <div className="card">
          <h2>执行历史</h2>
          {runsLoading ? <p className="muted">加载中…</p> : runs.length === 0 ? (
            <p className="muted">暂无执行记录</p>
          ) : (
            <table>
              <thead>
                <tr><th>状态</th><th>通过/失败/总数</th><th>开始时间</th><th>结束时间</th><th></th></tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.id}>
                    <td><StatusBadge status={r.status} /></td>
                    <td>
                      <span style={{ color: "var(--ok)" }}>{r.passed_turns}</span>
                      {" / "}
                      <span style={{ color: "var(--bad)" }}>{r.failed_turns}</span>
                      {" / "}
                      {r.total_turns}
                    </td>
                    <td className="mono muted">{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                    <td className="mono muted">{r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}</td>
                    <td>
                      <button className="btn secondary" style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }}
                        onClick={() => handleViewRun(r.id)}>详情</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Tab: 执行详情（流式 / 历史） */}
      {tab === "run-detail" && (
        isStreaming && !activeRunDetail ? (
          <StreamRunView
            turns={streamTurns}
            progress={streamProgress}
            summary={streamSummary}
            running={running}
          />
        ) : activeRunDetail ? (
          <RunDetailView run={activeRunDetail} />
        ) : null
      )}

      {/* Tab: Mock 数据配置 */}
      {tab === "mock-profiles" && (
        <>
          {/* 新建 Profile */}
          <div className="card">
            <h2>新建 Mock Profile</h2>
            <div className="row" style={{ alignItems: "flex-end", gap: "0.5rem", marginBottom: "0.5rem" }}>
              <label style={{ flex: 1 }}>
                名称
                <input value={mpName} onChange={e => setMpName(e.target.value)} placeholder="如：余额不足需转账" />
              </label>
              <label style={{ flex: 2 }}>
                描述（可选）
                <input value={mpDesc} onChange={e => setMpDesc(e.target.value)} placeholder="基金卡余额1000，储蓄卡余额30000" />
              </label>
            </div>
            <label>
              Profile Data（JSON）
              <textarea value={mpJson} onChange={e => setMpJson(e.target.value)} rows={6}
                style={{ fontFamily: "monospace", fontSize: "0.82rem" }}
                placeholder='{"wealth_recommend": {...}, "balance_query": {...}, "transfer": {...}, "wealth_purchase": {...}}' />
            </label>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "0.5rem" }}>
              <button className="btn" disabled={mpSaving || !mpName.trim()} onClick={handleCreateProfile}>
                {mpSaving ? "创建中…" : "创建"}
              </button>
            </div>
          </div>

          {/* LLM 一键生成测试分支 */}
          <div className="card">
            <h2>LLM 一键生成测试分支</h2>
            <p className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.5rem" }}>
              根据业务描述自动生成多个 MockProfile + 对应的多轮对话测试场景，覆盖不同业务路径。
            </p>
            <label>
              业务场景描述
              <textarea value={branchDesc} onChange={e => setBranchDesc(e.target.value)} rows={3}
                placeholder="如：购买理财产品场景，用户有基金卡和储蓄卡，当基金卡余额不足时需从储蓄卡转账再购买" />
            </label>
            <div className="row" style={{ gap: "0.5rem", marginTop: "0.5rem", alignItems: "flex-end" }}>
              <label style={{ flex: 1 }}>
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
            </div>
            <div className="row" style={{ gap: "0.5rem", marginTop: "0.5rem", alignItems: "flex-end" }}>
              <label style={{ flex: 1 }}>
                分支数
                <input type="number" value={branchMax} min={1} max={10}
                  onChange={e => setBranchMax(Math.max(1, Math.min(10, Number(e.target.value))))} />
              </label>
              <label style={{ flex: 1 }}>
                每分支最大轮次
                <input type="number" value={branchTurns} min={2} max={20}
                  onChange={e => setBranchTurns(Math.max(2, Math.min(20, Number(e.target.value))))} />
              </label>
              <button className="btn" disabled={branchGenerating || !branchDesc.trim()} onClick={async () => {
                if (!scenarioId) return;
                setBranchGenerating(true);
                setBranchResult(null);
                try {
                  const res = await api.generateBranches(scenarioId, {
                    business_description: branchDesc,
                    max_branches: branchMax,
                    max_turns_per_branch: branchTurns,
                    skill_id: branchSkillId,
                  });
                  setBranchResult(res);
                  loadMockProfiles();
                } catch {}
                finally { setBranchGenerating(false); }
              }}>
                {branchGenerating ? "生成中…" : "生成分支"}
              </button>
            </div>
            {branchResult && (
              <p style={{ marginTop: "0.5rem", color: "var(--ok)" }}>
                已生成 {branchResult.created_scenarios} 个场景、{branchResult.created_profiles} 个 MockProfile。
                请到 Agent 详情页查看新生成的场景。
              </p>
            )}
          </div>

          {/* Profile 列表 */}
          <div className="card">
            <h2>Mock Profiles ({mockProfiles.length})</h2>
            {mockLoading ? <p className="muted">加载中…</p> : mockProfiles.length === 0 ? (
              <p className="muted">暂无 Mock Profile，请创建或通过 LLM 自动生成。</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                {mockProfiles.map(p => {
                  const isEditing = mpEditId === p.id;
                  return (
                    <div key={p.id} className="mock-table-card" style={{
                      borderLeft: p.is_active ? "3px solid var(--ok)" : "3px solid var(--border)",
                    }}>
                      <div className="mock-table-header">
                        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                          <strong>{p.name}</strong>
                          {p.is_active && <span className="badge" style={{ color: "var(--ok)", borderColor: "var(--ok)" }}>激活</span>}
                        </div>
                        {!isEditing && (
                          <div style={{ display: "flex", gap: "0.3rem" }}>
                            {!p.is_active && (
                              <button className="btn secondary" style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem" }}
                                onClick={() => handleActivateProfile(p.id)}>激活</button>
                            )}
                            <button className="btn secondary" style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem" }}
                              onClick={() => startEditProfile(p)}>编辑</button>
                            <button className="btn secondary" style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem", color: "var(--bad)" }}
                              onClick={() => handleDeleteProfile(p.id)}>删除</button>
                          </div>
                        )}
                      </div>
                      {p.description && !isEditing && (
                        <p className="muted" style={{ fontSize: "0.82rem", margin: "0.25rem 0 0" }}>{p.description}</p>
                      )}
                      {isEditing ? (
                        <div style={{ padding: "0.5rem 0", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
                          <div className="row" style={{ gap: "0.5rem" }}>
                            <label style={{ flex: 1 }}>
                              名称
                              <input value={mpEditName} onChange={e => setMpEditName(e.target.value)} />
                            </label>
                            <label style={{ flex: 2 }}>
                              描述
                              <input value={mpEditDesc} onChange={e => setMpEditDesc(e.target.value)} />
                            </label>
                          </div>
                          <label>
                            Profile Data（JSON）
                            <textarea value={mpEditJson} onChange={e => setMpEditJson(e.target.value)} rows={8}
                              style={{ fontFamily: "monospace", fontSize: "0.82rem" }} />
                          </label>
                          <div style={{ display: "flex", gap: "0.4rem", justifyContent: "flex-end" }}>
                            <button className="btn secondary" onClick={() => setMpEditId(null)} disabled={mpEditSaving}>取消</button>
                            <button className="btn" onClick={handleSaveEditProfile} disabled={mpEditSaving || !mpEditName.trim()}>
                              {mpEditSaving ? "保存中…" : "保存"}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <MockWorkflowPreviewPanel
                            key={`mock-prev-${p.id}-${p.updated_at ?? ""}-${p.created_at ?? ""}`}
                            profileId={p.id}
                          />
                          <CollapsibleJson label="Profile Data" data={p.profile_data} />
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    passed: "var(--ok)", failed: "var(--bad)", partial: "var(--warn)",
    running: "var(--accent)", pending: "var(--muted)", error: "var(--bad)",
  };
  return (
    <span className="badge" style={{ color: colors[status] || "var(--muted)", borderColor: colors[status] }}>
      {status}
    </span>
  );
}

function MockWorkflowPreviewPanel({ profileId }: { profileId: string }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<api.WorkflowMockPreviewOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (data) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api.getMockWorkflowPreview(profileId, { silent: true })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setErr(e.message || "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, profileId, data]);

  return (
    <div style={{ marginTop: "0.45rem" }}>
      <button
        type="button"
        className="btn secondary"
        style={{ fontSize: "0.72rem", padding: "0.15rem 0.5rem" }}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "▼" : "▶"} Mock 数据一览（推荐产品 · 卡余额 · 购买默认）
      </button>
      {open && loading && <p className="muted" style={{ fontSize: "0.8rem", margin: "0.35rem 0 0" }}>加载中…</p>}
      {open && err && (
        <p style={{ color: "var(--bad)", fontSize: "0.8rem", margin: "0.35rem 0 0" }}>{err}</p>
      )}
      {open && data && !loading && (
        <div
          style={{
            marginTop: "0.45rem",
            display: "grid",
            gap: "0.65rem",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
          }}
        >
          <div
            style={{
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "0.5rem 0.6rem",
              fontSize: "0.78rem",
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>推荐 / 筛选卡号</div>
            <p className="muted" style={{ margin: "0 0 0.35rem" }}>
              bankCardNumber: <span className="mono">{data.wealth_recommend.bankCardNumber}</span>
            </p>
            {data.wealth_recommend.products.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>无解析后的产品行（请检查 productList 格式）</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.74rem" }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: "0.2rem" }}>代码</th>
                      <th style={{ textAlign: "left", padding: "0.2rem" }}>名称</th>
                      <th style={{ textAlign: "left", padding: "0.2rem" }}>收益</th>
                      <th style={{ textAlign: "left", padding: "0.2rem" }}>风险</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.wealth_recommend.products.map((row, i) => (
                      <tr key={i}>
                        <td className="mono" style={{ padding: "0.2rem" }}>{String(row.productCode ?? "—")}</td>
                        <td style={{ padding: "0.2rem" }}>{String(row.productName ?? "—")}</td>
                        <td style={{ padding: "0.2rem" }}>{String(row.profitValue ?? row.profit ?? "—")}</td>
                        <td style={{ padding: "0.2rem" }}>{String(row.riskLevel ?? "—")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div
            style={{
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "0.5rem 0.6rem",
              fontSize: "0.78rem",
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>用户余额（Mock）</div>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.74rem" }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left", padding: "0.2rem" }}>卡号（掩码）</th>
                    <th style={{ textAlign: "right", padding: "0.2rem" }}>CNY 余额</th>
                  </tr>
                </thead>
                <tbody>
                  {data.balance_query.cards.map((c) => (
                    <tr key={c.card_tail}>
                      <td className="mono" style={{ padding: "0.2rem" }}>{c.masked_number}</td>
                      <td style={{ padding: "0.2rem", textAlign: "right" }}>
                        {c.balance_cny.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div
            style={{
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "0.5rem 0.6rem",
              fontSize: "0.78rem",
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>理财购买默认</div>
            <ul style={{ margin: 0, paddingLeft: "1.1rem", lineHeight: 1.55 }}>
              <li>产品：{data.wealth_purchase.default_product_name}（{data.wealth_purchase.default_product_code}）</li>
              <li>默认金额：{data.wealth_purchase.default_amount} 元</li>
              <li>申购结果：{data.wealth_purchase.default_purchase_status}</li>
              <li>确认份额：{data.wealth_purchase.default_confirmed_shares}</li>
              <li>订单前缀：{data.wealth_purchase.order_id_prefix}</li>
              {data.wealth_purchase.fail_cause ? (
                <li style={{ color: "var(--warn)" }}>失败原因：{data.wealth_purchase.fail_cause}</li>
              ) : null}
            </ul>
          </div>

          <div
            style={{
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "0.5rem 0.6rem",
              fontSize: "0.78rem",
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>转账默认</div>
            <ul style={{ margin: 0, paddingLeft: "1.1rem", lineHeight: 1.55 }}>
              <li>默认金额：{data.transfer.default_amount} 元</li>
              <li>状态：{data.transfer.default_status}</li>
              {data.transfer.fail_cause ? <li>失败原因：{data.transfer.fail_cause}</li> : null}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

function CollapsibleJson({ label, data }: { label: string; data: unknown }) {
  const [open, setOpen] = useState(false);
  if (!data) return null;
  return (
    <div style={{ marginTop: "0.35rem" }}>
      <button
        className="btn secondary"
        style={{ fontSize: "0.72rem", padding: "0.15rem 0.5rem" }}
        onClick={() => setOpen(!open)}
      >
        {open ? "▼" : "▶"} {label}
      </button>
      {open && (
        <pre style={{
          margin: "0.25rem 0 0", padding: "0.5rem",
          background: "var(--bg)", border: "1px solid var(--border)",
          borderRadius: "4px", fontSize: "0.75rem", lineHeight: 1.45,
          maxHeight: "300px", overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all",
        }}>
          {typeof data === "string" ? data : JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}

function TurnCard({ tr }: { tr: api.TurnResultOut }) {
  return (
    <div className="card" style={{
      borderLeft: `3px solid ${tr.passed ? "var(--ok)" : "var(--bad)"}`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
        <span className="badge">轮 {tr.turn_index}</span>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span className="mono muted" style={{ fontSize: "0.75rem" }}>{tr.latency_ms}ms</span>
          <StatusBadge status={tr.passed ? "passed" : "failed"} />
        </div>
      </div>

      {tr.request_snapshot && (
        <div style={{
          background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "4px",
          padding: "0.35rem 0.6rem", marginBottom: "0.5rem", fontSize: "0.78rem",
        }}>
          <span className="mono" style={{ fontWeight: 600 }}>
            {tr.request_snapshot.method || "POST"}
          </span>
          {" "}
          <span className="mono muted" style={{ wordBreak: "break-all" }}>
            {tr.request_snapshot.url}
          </span>
        </div>
      )}

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", marginBottom: "0.5rem" }}>
        <span style={{ background: "var(--accent-dim)", color: "#fff", padding: "0.15rem 0.5rem", borderRadius: "6px", fontSize: "0.75rem", flexShrink: 0 }}>
          用户
        </span>
        <div style={{ fontSize: "0.85rem", lineHeight: 1.5 }}>{tr.actual_user_message}</div>
      </div>

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", marginBottom: "0.5rem" }}>
        <span style={{ background: "var(--ok)", color: "#000", padding: "0.15rem 0.5rem", borderRadius: "6px", fontSize: "0.75rem", flexShrink: 0 }}>
          Agent
        </span>
        <div style={{ fontSize: "0.85rem", lineHeight: 1.5, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {tr.actual_agent_response || <span className="muted">(无回复)</span>}
        </div>
      </div>

      {tr.actual_tool_calls && tr.actual_tool_calls.length > 0 && (
        <div style={{ marginBottom: "0.5rem" }}>
          <span className="muted" style={{ fontSize: "0.75rem" }}>工具调用:</span>
          {(tr.actual_tool_calls as Array<{ function?: string; arguments?: unknown }>).map((tc, i) => (
            <div key={i} className="json-block" style={{ maxHeight: "120px", marginTop: "0.25rem", fontSize: "0.78rem" }}>
              <strong>{tc.function || "unknown"}</strong>
              <pre style={{ margin: "0.25rem 0 0" }}>{JSON.stringify(tc.arguments, null, 2)}</pre>
            </div>
          ))}
        </div>
      )}

      {tr.assertion_results && tr.assertion_results.length > 0 && (
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: "0.4rem" }}>
          {tr.assertion_results.map((a, i) => (
            <div key={i} style={{ display: "flex", gap: "0.35rem", alignItems: "center", fontSize: "0.78rem", padding: "0.1rem 0" }}>
              <span style={{ color: a.passed ? "var(--ok)" : "var(--bad)", fontWeight: 600, width: "1rem", textAlign: "center" }}>
                {a.passed ? "✓" : "✗"}
              </span>
              <span className="muted">[{a.type}]</span>
              <span>{a.detail}</span>
            </div>
          ))}
        </div>
      )}

      {tr.error_message && (
        <p className="err" style={{ marginTop: "0.35rem" }}>{tr.error_message}</p>
      )}

      {tr.extracted_vars && Object.keys(tr.extracted_vars).length > 0 && (
        <div style={{ marginTop: "0.35rem" }}>
          <span className="muted" style={{ fontSize: "0.75rem" }}>提取变量:</span>
          <div className="mock-schema-bar">
            {Object.entries(tr.extracted_vars).map(([k, v]) => (
              <span key={k} className="mock-col-tag">{k}={String(v)}</span>
            ))}
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {tr.request_snapshot && (
          <>
            <CollapsibleJson label="请求 Headers" data={tr.request_snapshot.headers} />
            <CollapsibleJson label="请求 Body" data={tr.request_snapshot.body} />
          </>
        )}
        <CollapsibleJson label="原始响应" data={tr.raw_response} />
      </div>
    </div>
  );
}

function RunDetailView({ run }: { run: api.AgentTestRunDetailOut }) {
  return (
    <>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>
            执行结果 <StatusBadge status={run.status} />
          </h2>
          <span className="muted" style={{ fontSize: "0.8rem" }}>
            通过 <span style={{ color: "var(--ok)" }}>{run.passed_turns}</span>
            {" "}失败 <span style={{ color: "var(--bad)" }}>{run.failed_turns}</span>
            {" "}共 {run.total_turns} 轮
          </span>
        </div>
      </div>
      {run.turn_results.map((tr) => (
        <TurnCard key={tr.id} tr={tr} />
      ))}
    </>
  );
}

function StreamRunView({ turns, progress, summary, running }: {
  turns: api.TurnResultOut[];
  progress: string;
  summary: api.SSERunFinished | null;
  running: boolean;
}) {
  return (
    <>
      {/* 汇总头 */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>
            {summary ? (
              <>执行结果 <StatusBadge status={summary.status} /></>
            ) : (
              <>实时执行 {running && <span className="pulse-dot" />}</>
            )}
          </h2>
          {summary ? (
            <span className="muted" style={{ fontSize: "0.8rem" }}>
              通过 <span style={{ color: "var(--ok)" }}>{summary.passed_turns}</span>
              {" "}失败 <span style={{ color: "var(--bad)" }}>{summary.failed_turns}</span>
              {" "}共 {summary.total_turns} 轮
            </span>
          ) : (
            <span className="muted" style={{ fontSize: "0.8rem" }}>
              已完成 {turns.length} 轮
            </span>
          )}
        </div>
        {progress && (
          <p style={{ margin: "0.4rem 0 0", fontSize: "0.82rem", color: "var(--accent)" }}>{progress}</p>
        )}
      </div>

      {/* 逐轮结果卡片 */}
      {turns.map((tr, i) => (
        <TurnCard key={tr.id || `stream-${i}`} tr={tr} />
      ))}

      {/* 等待下一轮的骨架占位 */}
      {running && (
        <div className="card" style={{ borderLeft: "3px solid var(--border)", opacity: 0.5 }}>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <span className="badge">轮 {turns.length + 1}</span>
            <span className="muted" style={{ fontSize: "0.82rem" }}>等待 Agent 响应…</span>
          </div>
        </div>
      )}
    </>
  );
}
