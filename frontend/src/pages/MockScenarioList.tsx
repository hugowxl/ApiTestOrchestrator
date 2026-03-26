import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import * as api from "../api/client";

export function MockScenarioList() {
  const navigate = useNavigate();
  const [list, setList] = useState<api.MockScenarioOut[]>([]);
  const [loading, setLoading] = useState(true);

  /* 手动创建 */
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [creating, setCreating] = useState(false);

  /* LLM 生成 */
  const [llmDesc, setLlmDesc] = useState("");
  const [llmTableHint, setLlmTableHint] = useState(0);
  const [llmRowHint, setLlmRowHint] = useState(5);
  const [generating, setGenerating] = useState(false);

  const load = () => {
    setLoading(true);
    api.listMockScenarios().then(setList).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    if (!name.trim()) return;
    setCreating(true);
    try {
      const s = await api.createMockScenario({ name: name.trim(), description: desc.trim() || null });
      setName("");
      setDesc("");
      navigate(`/mock/${s.id}`);
    } catch { /* api layer handles */ }
    finally { setCreating(false); }
  };

  const handleGenerate = async () => {
    if (!llmDesc.trim()) return;
    setGenerating(true);
    try {
      const res = await api.llmGenerateMockScenario({
        business_description: llmDesc.trim(),
        table_count_hint: llmTableHint,
        rows_per_table_hint: llmRowHint,
      });
      setLlmDesc("");
      navigate(`/mock/${res.scenario.id}`);
    } catch { /* api layer handles */ }
    finally { setGenerating(false); }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确认删除该 Mock 场景？相关数据表和规则将一并删除。")) return;
    try {
      await api.deleteMockScenario(id);
      load();
    } catch { /* api layer handles */ }
  };

  return (
    <>
      {/* 手动创建 */}
      <div className="card">
        <h2>创建 Mock 场景</h2>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label>
            场景名称
            <input value={name} onChange={e => setName(e.target.value)} placeholder="如：购买理财产品" />
          </label>
          <label style={{ flex: 1 }}>
            描述（可选）
            <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="简要描述业务场景" />
          </label>
          <button className="btn" disabled={creating || !name.trim()} onClick={handleCreate}>
            创建
          </button>
        </div>
      </div>

      {/* LLM 生成 */}
      <div className="card">
        <h2>AI 自动生成 Mock 场景</h2>
        <p className="muted" style={{ fontSize: "0.8rem", margin: "0 0 0.5rem" }}>
          描述你的业务场景，大模型将自动设计数据表、示例数据和 API 规则
        </p>
        <label style={{ marginBottom: "0.5rem" }}>
          业务场景描述
          <textarea
            value={llmDesc}
            onChange={e => setLlmDesc(e.target.value)}
            placeholder={"例如：模拟购买理财产品的完整流程，需要包含：\n1. 理财产品列表查询（含产品名称、收益率、风险等级、起购金额等）\n2. 用户账户余额查询\n3. 购买理财产品（扣减余额，生成持仓记录）\n4. 持仓查询"}
            rows={4}
          />
        </label>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label>
            数据表数量提示（0=自动）
            <input
              type="number"
              min={0}
              max={20}
              value={llmTableHint}
              onChange={e => setLlmTableHint(Number(e.target.value))}
              style={{ width: "5rem", minWidth: "auto" }}
            />
          </label>
          <label>
            每表示例行数
            <input
              type="number"
              min={1}
              max={50}
              value={llmRowHint}
              onChange={e => setLlmRowHint(Number(e.target.value))}
              style={{ width: "5rem", minWidth: "auto" }}
            />
          </label>
          <button className="btn" disabled={generating || !llmDesc.trim()} onClick={handleGenerate}>
            {generating ? "生成中…" : "AI 生成"}
          </button>
        </div>
        {generating && <p className="muted" style={{ marginTop: "0.5rem" }}>正在调用大模型生成，请稍候…</p>}
      </div>

      {/* 列表 */}
      <div className="card">
        <h2>Mock 场景列表</h2>
        {loading ? (
          <p className="muted">加载中…</p>
        ) : list.length === 0 ? (
          <p className="muted">暂无 Mock 场景，请创建或 AI 生成。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>描述</th>
                <th>更新时间</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.map(s => (
                <tr key={s.id}>
                  <td><Link to={`/mock/${s.id}`}>{s.name}</Link></td>
                  <td className="muted" style={{ maxWidth: "24rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {s.description || "—"}
                  </td>
                  <td className="mono muted" style={{ whiteSpace: "nowrap" }}>
                    {s.updated_at ? new Date(s.updated_at).toLocaleString() : "—"}
                  </td>
                  <td>
                    <button className="btn secondary" style={{ fontSize: "0.75rem", padding: "0.25rem 0.5rem" }} onClick={() => handleDelete(s.id)}>
                      删除
                    </button>
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
