import { useEffect, useState } from "react";
import * as api from "../api/client";

export function MockBranchSkillPage() {
  const [skills, setSkills] = useState<api.MockBranchSkillOut[]>([]);
  const [loading, setLoading] = useState(false);

  const [createName, setCreateName] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [createEnabled, setCreateEnabled] = useState(true);
  const [createPrompt, setCreatePrompt] = useState("");
  const [creating, setCreating] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editEnabled, setEditEnabled] = useState(true);
  const [editPrompt, setEditPrompt] = useState("");
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    api
      .listMockBranchSkills()
      .then(setSkills)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const startEdit = (s: api.MockBranchSkillOut) => {
    setEditingId(s.id);
    setEditName(s.name);
    setEditDesc(s.description ?? "");
    setEditEnabled(s.enabled);
    setEditPrompt(s.system_prompt ?? "");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditName("");
    setEditDesc("");
    setEditEnabled(true);
    setEditPrompt("");
  };

  // 该页面允许直接查看/编辑 system_prompt。

  const handleCreate = async () => {
    if (!createName.trim() || !createPrompt.trim()) return;
    setCreating(true);
    try {
      await api.createMockBranchSkill({
        name: createName.trim(),
        description: createDesc.trim() || null,
        system_prompt: createPrompt,
        enabled: createEnabled,
      });
      setCreateName("");
      setCreateDesc("");
      setCreateEnabled(true);
      setCreatePrompt("");
      load();
    } catch {}
    finally {
      setCreating(false);
    }
  };

  const handleSave = async () => {
    if (!editingId) return;
    if (!editName.trim()) return;
    setSaving(true);
    try {
      await api.updateMockBranchSkill(editingId, {
        name: editName.trim(),
        description: editDesc.trim() || null,
        enabled: editEnabled,
        // system_prompt 在当前 Out 没回传时可能是空；如需编辑可直接改 editPrompt 并确保 Out 包含 system_prompt
        system_prompt: editPrompt.trim() ? editPrompt : null,
      });
      cancelEdit();
      load();
    } catch {}
    finally {
      setSaving(false);
    }
  };

  const handleDelete = async (skillId: string) => {
    if (!confirm("确认删除该 Skill？")) return;
    try {
      await api.deleteMockBranchSkill(skillId);
      load();
    } catch {}
  };

  return (
    <>
      <div className="card">
        <h2>Mock 分支生成器 Skill 管理</h2>
        <p className="muted" style={{ fontSize: "0.82rem" }}>
          用于一键生成测试分支时的 LLM 系统提示词。你可以新增/禁用/删除/编辑（需 system_prompt 回显支持）。
        </p>
      </div>

      <div className="card">
        <h2>创建 Skill</h2>
        <div className="row" style={{ gap: "0.5rem", alignItems: "flex-end", flexWrap: "wrap" }}>
          <label style={{ flex: 1 }}>
            名称
            <input value={createName} onChange={(e) => setCreateName(e.target.value)} placeholder="如：理财购买专用提示词" />
          </label>
          <label style={{ flex: 1 }}>
            启用
            <select value={createEnabled ? "1" : "0"} onChange={(e) => setCreateEnabled(e.target.value === "1")}>
              <option value="1">启用</option>
              <option value="0">禁用</option>
            </select>
          </label>
        </div>
        <label>
          描述（可选）
          <input value={createDesc} onChange={(e) => setCreateDesc(e.target.value)} placeholder="备注" />
        </label>
        <label>
          system_prompt
          <textarea
            value={createPrompt}
            onChange={(e) => setCreatePrompt(e.target.value)}
            rows={8}
            style={{ fontFamily: "monospace", fontSize: "0.82rem" }}
          />
        </label>
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "0.5rem" }}>
          <button className="btn" disabled={creating || !createName.trim() || !createPrompt.trim()} onClick={handleCreate}>
            {creating ? "创建中…" : "创建"}
          </button>
        </div>
      </div>

      <div className="card">
        <h2>Skill 列表</h2>
        {loading ? (
          <p className="muted">加载中…</p>
        ) : skills.length === 0 ? (
          <p className="muted">暂无 Skill</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {skills.map((s) => {
              const isEditing = editingId === s.id;
              return (
                <div
                  key={s.id}
                  className="mock-table-card"
                  style={{ borderLeft: s.enabled ? "3px solid var(--ok)" : "3px solid var(--border)", padding: "0.75rem" }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.25rem" }}>
                        <strong>{s.name}</strong>
                        {s.enabled ? (
                          <span className="badge" style={{ color: "var(--ok)", borderColor: "var(--ok)" }}>启用</span>
                        ) : (
                          <span className="badge">禁用</span>
                        )}
                      </div>
                      {s.description ? <p className="muted" style={{ margin: "0 0 0.35rem" }}>{s.description}</p> : null}
                      <div className="mono muted" style={{ fontSize: "0.75rem" }}>
                        created: {s.created_at ? new Date(s.created_at).toLocaleString() : "—"}
                      </div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                      {!isEditing ? (
                        <>
                          <button className="btn secondary" style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem" }} onClick={() => startEdit(s)}>
                            编辑
                          </button>
                          <button className="btn secondary" style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem", color: "var(--bad)" }} onClick={() => handleDelete(s.id)}>
                            删除
                          </button>
                        </>
                      ) : (
                        <>
                          <button className="btn secondary" style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem" }} onClick={cancelEdit} disabled={saving}>
                            取消
                          </button>
                          <button className="btn" style={{ fontSize: "0.7rem", padding: "0.15rem 0.4rem" }} onClick={handleSave} disabled={saving}>
                            {saving ? "保存中…" : "保存"}
                          </button>
                        </>
                      )}
                    </div>
                  </div>

                  {isEditing ? (
                    <div style={{ marginTop: "0.6rem", display: "flex", flexDirection: "column", gap: "0.55rem" }}>
                      <label>
                        名称
                        <input value={editName} onChange={(e) => setEditName(e.target.value)} />
                      </label>
                      <label>
                        描述
                        <input value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
                      </label>
                      <label>
                        启用
                        <select value={editEnabled ? "1" : "0"} onChange={(e) => setEditEnabled(e.target.value === "1")}>
                          <option value="1">启用</option>
                          <option value="0">禁用</option>
                        </select>
                      </label>
                      <label>
                        system_prompt（如需编辑，请直接填写）
                        <textarea value={editPrompt} onChange={(e) => setEditPrompt(e.target.value)} rows={6} style={{ fontFamily: "monospace", fontSize: "0.82rem" }} />
                      </label>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}

