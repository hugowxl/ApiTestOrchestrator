import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api/client";

type Tab = "tables" | "rules" | "test" | "mappings";

export function MockScenarioDetail() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const [data, setData] = useState<api.MockScenarioDetailOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("tables");

  const load = useCallback(() => {
    if (!scenarioId) return;
    setLoading(true);
    api.getMockScenario(scenarioId).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [scenarioId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <p className="muted" style={{ padding: "1rem" }}>加载中…</p>;
  if (!data) return <p className="err" style={{ padding: "1rem" }}>场景未找到</p>;

  return (
    <>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <Link to="/mock" style={{ fontSize: "0.8rem" }}>← 返回列表</Link>
            <h2 style={{ margin: "0.25rem 0 0" }}>{data.name}</h2>
            {data.description && <p className="muted" style={{ margin: "0.25rem 0 0", fontSize: "0.85rem" }}>{data.description}</p>}
          </div>
          <div className="mock-stats">
            <span className="badge">{data.tables.length} 张数据表</span>
            <span className="badge">{data.api_rules.length} 条 API 规则</span>
          </div>
        </div>
      </div>

      <div className="mock-tabs">
        <button className={`mock-tab ${tab === "tables" ? "active" : ""}`} onClick={() => setTab("tables")}>数据表管理</button>
        <button className={`mock-tab ${tab === "rules" ? "active" : ""}`} onClick={() => setTab("rules")}>API 规则</button>
        <button className={`mock-tab ${tab === "test" ? "active" : ""}`} onClick={() => setTab("test")}>接口测试</button>
        <button className={`mock-tab ${tab === "mappings" ? "active" : ""}`} onClick={() => setTab("mappings")}>接口映射</button>
      </div>

      {tab === "tables" && <TablesPanel scenarioId={data.id} tables={data.tables} onRefresh={load} />}
      {tab === "rules" && <RulesPanel scenarioId={data.id} rules={data.api_rules} tables={data.tables} onRefresh={load} />}
      {tab === "test" && <TestPanel scenarioId={data.id} rules={data.api_rules} onReset={load} />}
      {tab === "mappings" && <MappingsPanel scenarioId={data.id} tables={data.tables} />}
    </>
  );
}

/* ===== Tables Panel ===== */

function TablesPanel({ scenarioId, tables, onRefresh }: {
  scenarioId: string;
  tables: api.MockDataTableOut[];
  onRefresh: () => void;
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [importJson, setImportJson] = useState("");
  const [importMode, setImportMode] = useState(false);

  const handleDelete = async (id: string) => {
    if (!confirm("确认删除此数据表？")) return;
    try { await api.deleteMockTable(id); onRefresh(); } catch {}
  };

  const handleImport = async () => {
    if (!importJson.trim()) return;
    try {
      const parsed = JSON.parse(importJson);
      if (!parsed.table_name) { alert("JSON 需包含 table_name 字段"); return; }
      await api.createMockTable(scenarioId, {
        table_name: parsed.table_name,
        description: parsed.description || null,
        schema_json: parsed.schema_json || parsed.schema || [],
        rows_json: parsed.rows_json || parsed.rows || [],
      });
      setImportJson("");
      setImportMode(false);
      onRefresh();
    } catch (e) {
      if (e instanceof SyntaxError) alert("JSON 格式错误");
    }
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
        <h2 style={{ margin: 0 }}>数据表 ({tables.length})</h2>
        <div className="row">
          <button className="btn secondary" onClick={() => { setImportMode(!importMode); setShowAdd(false); }}>
            {importMode ? "取消导入" : "JSON 导入"}
          </button>
          <button className="btn" onClick={() => { setShowAdd(!showAdd); setImportMode(false); }}>
            {showAdd ? "取消" : "新建数据表"}
          </button>
        </div>
      </div>

      {importMode && (
        <div className="mock-form-section">
          <label>
            粘贴 JSON（含 table_name, schema_json, rows_json）
            <textarea value={importJson} onChange={e => setImportJson(e.target.value)} rows={8}
              placeholder={'{\n  "table_name": "products",\n  "description": "理财产品表",\n  "schema_json": [\n    {"name": "id", "type": "string", "description": "产品ID"}\n  ],\n  "rows_json": [\n    {"id": "P001", "name": "稳健型理财"}\n  ]\n}'}
            />
          </label>
          <button className="btn" onClick={handleImport} style={{ marginTop: "0.5rem" }}>导入</button>
        </div>
      )}

      {showAdd && <AddTableForm scenarioId={scenarioId} onDone={() => { setShowAdd(false); onRefresh(); }} />}

      {tables.length === 0 ? (
        <p className="muted">暂无数据表</p>
      ) : (
        tables.map(t => (
          <div key={t.id} className="mock-table-card">
            {editId === t.id ? (
              <EditTableForm table={t} onDone={() => { setEditId(null); onRefresh(); }} onCancel={() => setEditId(null)} />
            ) : (
              <>
                <div className="mock-table-header">
                  <div>
                    <strong>{t.table_name}</strong>
                    {t.description && <span className="muted" style={{ marginLeft: "0.5rem", fontSize: "0.8rem" }}>{t.description}</span>}
                    <span className="badge" style={{ marginLeft: "0.5rem" }}>{t.rows_json.length} 行</span>
                  </div>
                  <div className="row">
                    <button className="btn secondary" style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }} onClick={() => setEditId(t.id)}>编辑</button>
                    <button className="btn secondary" style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }} onClick={() => handleDelete(t.id)}>删除</button>
                  </div>
                </div>
                {t.schema_json.length > 0 && (
                  <div className="mock-schema-bar">
                    {t.schema_json.map((c: api.ColumnDef, i: number) => (
                      <span key={i} className="mock-col-tag" title={c.description || ""}>
                        {c.name} <span className="muted">({c.type})</span>
                      </span>
                    ))}
                  </div>
                )}
                {t.rows_json.length > 0 && (
                  <div className="mock-data-preview">
                    <table>
                      <thead>
                        <tr>
                          {t.schema_json.length > 0
                            ? t.schema_json.map((c: api.ColumnDef) => <th key={c.name}>{c.name}</th>)
                            : Object.keys(t.rows_json[0]).map(k => <th key={k}>{k}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {t.rows_json.slice(0, 10).map((row, ri) => {
                          const cols = t.schema_json.length > 0
                            ? t.schema_json.map((c: api.ColumnDef) => c.name)
                            : Object.keys(t.rows_json[0]);
                          return (
                            <tr key={ri}>
                              {cols.map(k => <td key={k} className="mono">{String(row[k] ?? "")}</td>)}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    {t.rows_json.length > 10 && <p className="muted" style={{ fontSize: "0.75rem" }}>显示前 10 行，共 {t.rows_json.length} 行</p>}
                  </div>
                )}
              </>
            )}
          </div>
        ))
      )}
    </div>
  );
}

function AddTableForm({ scenarioId, onDone }: { scenarioId: string; onDone: () => void }) {
  const [tableName, setTableName] = useState("");
  const [description, setDescription] = useState("");
  const [colsText, setColsText] = useState("");
  const [rowsText, setRowsText] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!tableName.trim()) return;
    setSaving(true);
    try {
      let schema: api.ColumnDef[] = [];
      let rows: Record<string, unknown>[] = [];
      if (colsText.trim()) {
        try { schema = JSON.parse(colsText); } catch { alert("列定义 JSON 格式错误"); setSaving(false); return; }
      }
      if (rowsText.trim()) {
        try { rows = JSON.parse(rowsText); } catch { alert("数据行 JSON 格式错误"); setSaving(false); return; }
      }
      await api.createMockTable(scenarioId, {
        table_name: tableName.trim(),
        description: description.trim() || null,
        schema_json: schema,
        rows_json: rows,
      });
      onDone();
    } catch {}
    finally { setSaving(false); }
  };

  return (
    <div className="mock-form-section">
      <div className="row" style={{ marginBottom: "0.5rem" }}>
        <label>
          表名
          <input value={tableName} onChange={e => setTableName(e.target.value)} placeholder="如 products" />
        </label>
        <label style={{ flex: 1 }}>
          描述
          <input value={description} onChange={e => setDescription(e.target.value)} placeholder="如 理财产品表" />
        </label>
      </div>
      <label>
        列定义 JSON（可选）
        <textarea value={colsText} onChange={e => setColsText(e.target.value)} rows={3}
          placeholder={'[{"name":"id","type":"string","description":"产品ID"},{"name":"name","type":"string"}]'}
        />
      </label>
      <label>
        数据行 JSON（可选）
        <textarea value={rowsText} onChange={e => setRowsText(e.target.value)} rows={3}
          placeholder={'[{"id":"P001","name":"稳健型理财"},{"id":"P002","name":"进取型理财"}]'}
        />
      </label>
      <button className="btn" disabled={saving || !tableName.trim()} onClick={handleSave} style={{ marginTop: "0.5rem" }}>
        {saving ? "保存中…" : "保存"}
      </button>
    </div>
  );
}

function EditTableForm({ table, onDone, onCancel }: { table: api.MockDataTableOut; onDone: () => void; onCancel: () => void }) {
  const [tableName, setTableName] = useState(table.table_name);
  const [description, setDescription] = useState(table.description || "");
  const [rowsText, setRowsText] = useState(JSON.stringify(table.rows_json, null, 2));
  const [schemaText, setSchemaText] = useState(JSON.stringify(table.schema_json, null, 2));
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      let schema: api.ColumnDef[] | undefined;
      let rows: Record<string, unknown>[] | undefined;
      if (schemaText.trim()) {
        try { schema = JSON.parse(schemaText); } catch { alert("列定义 JSON 格式错误"); setSaving(false); return; }
      }
      if (rowsText.trim()) {
        try { rows = JSON.parse(rowsText); } catch { alert("数据行 JSON 格式错误"); setSaving(false); return; }
      }
      await api.updateMockTable(table.id, {
        table_name: tableName.trim() || undefined,
        description: description.trim() || null,
        schema_json: schema,
        rows_json: rows,
      });
      onDone();
    } catch {}
    finally { setSaving(false); }
  };

  return (
    <div className="mock-form-section">
      <div className="row" style={{ marginBottom: "0.5rem" }}>
        <label>
          表名
          <input value={tableName} onChange={e => setTableName(e.target.value)} />
        </label>
        <label style={{ flex: 1 }}>
          描述
          <input value={description} onChange={e => setDescription(e.target.value)} />
        </label>
      </div>
      <label>
        列定义 JSON
        <textarea value={schemaText} onChange={e => setSchemaText(e.target.value)} rows={4} />
      </label>
      <label>
        数据行 JSON
        <textarea value={rowsText} onChange={e => setRowsText(e.target.value)} rows={8} />
      </label>
      <div className="row" style={{ marginTop: "0.5rem" }}>
        <button className="btn" disabled={saving} onClick={handleSave}>{saving ? "保存中…" : "保存"}</button>
        <button className="btn secondary" onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}

/* ===== Rules Panel ===== */

function RulesPanel({ scenarioId, rules, tables, onRefresh }: {
  scenarioId: string;
  rules: api.MockApiRuleOut[];
  tables: api.MockDataTableOut[];
  onRefresh: () => void;
}) {
  const [showAdd, setShowAdd] = useState(false);

  const handleDelete = async (id: string) => {
    if (!confirm("确认删除此规则？")) return;
    try { await api.deleteMockRule(id); onRefresh(); } catch {}
  };

  const methodColors: Record<string, string> = {
    GET: "get", POST: "post", PUT: "put", PATCH: "put", DELETE: "delete",
  };

  const tableNameById = Object.fromEntries(tables.map(t => [t.id, t.table_name]));

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
        <h2 style={{ margin: 0 }}>API 规则 ({rules.length})</h2>
        <button className="btn" onClick={() => setShowAdd(!showAdd)}>{showAdd ? "取消" : "新建规则"}</button>
      </div>

      {showAdd && <AddRuleForm scenarioId={scenarioId} tables={tables} onDone={() => { setShowAdd(false); onRefresh(); }} />}

      {rules.length === 0 ? (
        <p className="muted">暂无 API 规则</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>方法</th>
              <th>路径</th>
              <th>操作</th>
              <th>关联表</th>
              <th>主键字段</th>
              <th>描述</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rules.map(r => (
              <tr key={r.id}>
                <td><span className={`badge ${methodColors[r.method] || ""}`}>{r.method}</span></td>
                <td className="mono">{r.path}</td>
                <td><span className="badge">{r.action}</span></td>
                <td>{r.table_id ? tableNameById[r.table_id] || r.table_id : "—"}</td>
                <td className="mono">{r.key_field || "—"}</td>
                <td className="muted">{r.description || "—"}</td>
                <td>
                  <button className="btn secondary" style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }} onClick={() => handleDelete(r.id)}>删除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {scenarioId && rules.length > 0 && (
        <div style={{ marginTop: "1rem", padding: "0.75rem", background: "var(--bg)", borderRadius: "6px", border: "1px solid var(--border)" }}>
          <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--muted)" }}>
            Mock 服务基地址：<code className="mono" style={{ color: "var(--accent)" }}>
              {window.location.origin}/mock-server/{scenarioId}
            </code>
          </p>
          <p style={{ margin: "0.25rem 0 0", fontSize: "0.75rem", color: "var(--muted)" }}>
            使用示例：GET {window.location.origin}/mock-server/{scenarioId}{rules[0]?.path || "/api/example"}
          </p>
        </div>
      )}
    </div>
  );
}

function AddRuleForm({ scenarioId, tables, onDone }: {
  scenarioId: string;
  tables: api.MockDataTableOut[];
  onDone: () => void;
}) {
  const [method, setMethod] = useState("GET");
  const [path, setPath] = useState("");
  const [description, setDescription] = useState("");
  const [action, setAction] = useState("list");
  const [tableId, setTableId] = useState("");
  const [keyField, setKeyField] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!path.trim()) return;
    setSaving(true);
    try {
      await api.createMockRule(scenarioId, {
        table_id: tableId || null,
        method,
        path: path.trim(),
        description: description.trim() || null,
        action,
        key_field: keyField.trim() || null,
      });
      onDone();
    } catch {}
    finally { setSaving(false); }
  };

  return (
    <div className="mock-form-section">
      <div className="row" style={{ marginBottom: "0.5rem", flexWrap: "wrap" }}>
        <label>
          HTTP 方法
          <select value={method} onChange={e => setMethod(e.target.value)} style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "6px", padding: "0.45rem 0.6rem", color: "var(--text)" }}>
            {["GET", "POST", "PUT", "PATCH", "DELETE"].map(m => <option key={m}>{m}</option>)}
          </select>
        </label>
        <label style={{ flex: 1 }}>
          路径
          <input value={path} onChange={e => setPath(e.target.value)} placeholder="/api/products 或 /api/products/{id}" />
        </label>
        <label>
          操作类型
          <select value={action} onChange={e => setAction(e.target.value)} style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "6px", padding: "0.45rem 0.6rem", color: "var(--text)" }}>
            {["list", "get_by_id", "create", "update", "delete", "custom"].map(a => <option key={a}>{a}</option>)}
          </select>
        </label>
      </div>
      <div className="row" style={{ marginBottom: "0.5rem" }}>
        <label>
          关联数据表
          <select value={tableId} onChange={e => setTableId(e.target.value)} style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "6px", padding: "0.45rem 0.6rem", color: "var(--text)" }}>
            <option value="">不关联</option>
            {tables.map(t => <option key={t.id} value={t.id}>{t.table_name}</option>)}
          </select>
        </label>
        <label>
          主键字段（get_by_id/update/delete 时使用）
          <input value={keyField} onChange={e => setKeyField(e.target.value)} placeholder="如 id, product_id" />
        </label>
        <label style={{ flex: 1 }}>
          描述
          <input value={description} onChange={e => setDescription(e.target.value)} placeholder="查询所有理财产品" />
        </label>
      </div>
      <button className="btn" disabled={saving || !path.trim()} onClick={handleSave} style={{ marginTop: "0.25rem" }}>
        {saving ? "保存中…" : "保存规则"}
      </button>
    </div>
  );
}

/* ===== Test Panel ===== */

function TestPanel({
  scenarioId,
  rules,
  onReset,
}: {
  scenarioId: string;
  rules: api.MockApiRuleOut[];
  onReset: () => void;
}) {
  const [method, setMethod] = useState("GET");
  const [path, setPath] = useState("");
  const [reqBody, setReqBody] = useState("");
  const [response, setResponse] = useState<{ status: number; body: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [resetting, setResetting] = useState(false);

  const doRequest = async () => {
    if (!path.trim()) return;
    setLoading(true);
    setResponse(null);
    const url = `/mock-server/${scenarioId}${path.startsWith("/") ? path : `/${path}`}`;
    try {
      const init: RequestInit = { method };
      if (reqBody.trim() && ["POST", "PUT", "PATCH"].includes(method)) {
        init.headers = { "Content-Type": "application/json" };
        init.body = reqBody;
      }
      const res = await fetch(url, init);
      const text = await res.text();
      let formatted = text;
      try { formatted = JSON.stringify(JSON.parse(text), null, 2); } catch {}
      setResponse({ status: res.status, body: formatted });
    } catch (e) {
      setResponse({ status: 0, body: `请求失败：${e instanceof Error ? e.message : String(e)}` });
    } finally { setLoading(false); }
  };

  return (
    <div className="card">
      <h2 style={{ margin: "0 0 0.5rem" }}>接口测试</h2>
      <p className="muted" style={{ fontSize: "0.8rem", margin: "0 0 0.75rem" }}>
        直接调用 Mock 服务器的 API，实时查看响应
      </p>

      <div className="row" style={{ marginBottom: "0.75rem", justifyContent: "flex-end" }}>
        <button
          type="button"
          className="btn secondary"
          disabled={resetting || loading}
          onClick={async () => {
            if (!confirm("确认重置该 Mock 场景的运行时数据到最初版本？")) return;
            setResetting(true);
            try {
              await api.resetMockScenario(scenarioId);
              onReset();
              setResponse(null);
            } catch {
              // api 层会弹窗提示错误
            } finally {
              setResetting(false);
            }
          }}
        >
          {resetting ? "重置中…" : "Reset 数据"}
        </button>
      </div>

      {rules.length > 0 && (
        <div style={{ marginBottom: "0.75rem" }}>
          <p style={{ fontSize: "0.8rem", color: "var(--muted)", margin: "0 0 0.35rem" }}>快捷选择：</p>
          <div className="row" style={{ flexWrap: "wrap", gap: "0.35rem" }}>
            {rules.map(r => (
              <button
                key={r.id}
                className="btn secondary"
                style={{ fontSize: "0.7rem", padding: "0.2rem 0.45rem" }}
                onClick={() => { setMethod(r.method); setPath(r.path); }}
              >
                <span className={`badge ${r.method.toLowerCase()}`} style={{ marginRight: "0.25rem" }}>{r.method}</span>
                {r.path}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="row" style={{ alignItems: "flex-end", marginBottom: "0.5rem" }}>
        <label>
          方法
          <select value={method} onChange={e => setMethod(e.target.value)} style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "6px", padding: "0.45rem 0.6rem", color: "var(--text)" }}>
            {["GET", "POST", "PUT", "PATCH", "DELETE"].map(m => <option key={m}>{m}</option>)}
          </select>
        </label>
        <label style={{ flex: 1 }}>
          路径
          <input value={path} onChange={e => setPath(e.target.value)} placeholder="/api/products" />
        </label>
        <button className="btn" disabled={loading || !path.trim()} onClick={doRequest}>
          {loading ? "请求中…" : "发送请求"}
        </button>
      </div>

      {["POST", "PUT", "PATCH"].includes(method) && (
        <label>
          请求体 JSON
          <textarea value={reqBody} onChange={e => setReqBody(e.target.value)} rows={4}
            placeholder={'{"name": "新产品", "rate": "3.5%"}'}
          />
        </label>
      )}

      {response && (
        <div style={{ marginTop: "0.75rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.35rem" }}>
            <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>响应</span>
            <span className={`badge ${response.status >= 200 && response.status < 300 ? "post" : "delete"}`}>
              {response.status || "ERR"}
            </span>
          </div>
          <pre className="json-block" style={{ maxHeight: "400px" }}>{response.body}</pre>
        </div>
      )}
    </div>
  );
}

/* ===== Mappings Panel ===== */

function MappingsPanel({
  scenarioId,
  tables,
}: {
  scenarioId: string;
  tables: api.MockDataTableOut[];
}) {
  const [mappings, setMappings] = useState<api.MockEndpointMappingOut[]>([]);
  const [loading, setLoading] = useState(true);

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const [method, setMethod] = useState("POST");
  const [path, setPath] = useState("");
  const [action, setAction] = useState("update");
  const [tableId, setTableId] = useState<string>("");
  const [keyField, setKeyField] = useState("");
  const [requiredBodyFieldsText, setRequiredBodyFieldsText] = useState("");
  const [responseTemplateJsonText, setResponseTemplateJsonText] = useState("");

  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    if (!scenarioId) return;
    setLoading(true);
    api
      .listMockEndpointMappings(scenarioId)
      .then(setMappings)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [scenarioId]);

  useEffect(() => {
    load();
  }, [load]);

  const tableNameById = Object.fromEntries(tables.map((t) => [t.id, t.table_name]));

  const parseRequiredBodyFields = (text: string): string[] => {
    const normalized = text.trim().replace(/\r\n/g, "\n").replace(/\n/g, ",");
    if (!normalized) return [];
    return normalized
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  };

  const resetForm = () => {
    setEditingId(null);
    setMethod("POST");
    setPath("");
    setAction("update");
    setTableId("");
    setKeyField("");
    setRequiredBodyFieldsText("");
    setResponseTemplateJsonText("");
  };

  const handleEdit = (m: api.MockEndpointMappingOut) => {
    setEditingId(m.id);
    setMethod(m.method || "POST");
    setPath(m.path || "");
    setAction(m.action || "update");
    setTableId(m.table_id || "");
    setKeyField(m.key_field || "");
    setRequiredBodyFieldsText((m.required_body_fields || []).join(", "));
    setResponseTemplateJsonText(m.response_template_json ? JSON.stringify(m.response_template_json, null, 2) : "");
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确认删除此接口映射？")) return;
    try {
      await api.deleteMockEndpointMapping(id);
      resetForm();
      setShowForm(false);
      load();
    } catch {}
  };

  const handleSave = async () => {
    if (!path.trim()) return;
    setSaving(true);
    try {
      let responseTemplateJson: Record<string, unknown> | null = null;
      if (action === "custom" && responseTemplateJsonText.trim()) {
        responseTemplateJson = JSON.parse(responseTemplateJsonText) as Record<string, unknown>;
      }

      const body = {
        method,
        path: path.trim(),
        action,
        table_id: tableId ? tableId : null,
        key_field: keyField.trim() ? keyField.trim() : null,
        required_body_fields: parseRequiredBodyFields(requiredBodyFieldsText),
        response_template_json: action === "custom" ? responseTemplateJson : null,
      };

      if (editingId) {
        await api.updateMockEndpointMapping(editingId, body);
      } else {
        await api.createMockEndpointMapping(scenarioId, body);
      }

      resetForm();
      setShowForm(false);
      load();
    } catch (e) {
      if (e instanceof SyntaxError) alert("response_template_json 不是合法 JSON");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
        <h2 style={{ margin: 0 }}>接口映射（{mappings.length}）</h2>
        <button
          className="btn"
          onClick={() => {
            resetForm();
            setShowForm(true);
          }}
        >
          {showForm ? "取消" : "新建映射"}
        </button>
      </div>

      <div style={{ marginBottom: "0.75rem" }}>
        <p className="muted" style={{ fontSize: "0.8rem", margin: "0 0 0.35rem" }}>
          映射后接口基地址：
        </p>
        <code className="mono" style={{ color: "var(--accent)" }}>
          {window.location.origin}/mock-mapped/{scenarioId}
        </code>
      </div>

      {showForm && (
        <div className="mock-form-section">
          <div className="row" style={{ marginBottom: "0.5rem", flexWrap: "wrap" }}>
            <label>
              HTTP 方法
              <select value={method} onChange={(e) => setMethod(e.target.value)} style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "6px", padding: "0.45rem 0.6rem", color: "var(--text)" }}>
                {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </label>
            <label style={{ flex: 1 }}>
              生产路径（用于匹配）
              <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="/api/users/{user_id}/balance" />
            </label>
          </div>

          <div className="row" style={{ marginBottom: "0.5rem", flexWrap: "wrap" }}>
            <label>
              动作 action
              <select value={action} onChange={(e) => setAction(e.target.value)} style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "6px", padding: "0.45rem 0.6rem", color: "var(--text)" }}>
                {["list", "get_by_id", "create", "update", "delete", "custom"].map((a) => (
                  <option key={a}>{a}</option>
                ))}
              </select>
            </label>
            <label>
              关联数据表（可选）
              <select value={tableId} onChange={(e) => setTableId(e.target.value)} style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "6px", padding: "0.45rem 0.6rem", color: "var(--text)" }}>
                <option value="">不关联（custom 或仅返回模板）</option>
                {tables.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.table_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              主键字段（{`{param}`} 对应） 
              <input value={keyField} onChange={(e) => setKeyField(e.target.value)} placeholder="如 id, user_id, account_id" />
            </label>
          </div>

          <label style={{ marginBottom: "0.5rem" }}>
            body 必填字段（逗号分隔；仅对 create/update/custom 校验）
            <textarea value={requiredBodyFieldsText} onChange={(e) => setRequiredBodyFieldsText(e.target.value)} rows={3} placeholder="例如：balance, holdings" />
          </label>

          {action === "custom" && (
            <label style={{ marginBottom: "0.5rem" }}>
              custom response_template_json（可选）
              <textarea value={responseTemplateJsonText} onChange={(e) => setResponseTemplateJsonText(e.target.value)} rows={6} placeholder='{"code":0,"message":"ok"}' />
            </label>
          )}

          <div className="row" style={{ marginTop: "0.5rem" }}>
            <button className="btn" disabled={saving || !path.trim()} onClick={handleSave}>
              {saving ? "保存中…" : editingId ? "保存修改" : "保存映射"}
            </button>
            <button
              className="btn secondary"
              disabled={saving}
              onClick={() => {
                resetForm();
                setShowForm(false);
              }}
            >
              取消
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="muted">加载中…</p>
      ) : mappings.length === 0 ? (
        <p className="muted">暂无接口映射。可新建后把路径映射到 Mock Server。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>方法</th>
              <th>路径</th>
              <th>action</th>
              <th>关联表</th>
              <th>必填 body 字段</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {mappings.map((m) => {
              const fullUrl = `${window.location.origin}/mock-mapped/${scenarioId}${m.path.startsWith("/") ? m.path : `/${m.path}`}`;
              return (
                <tr key={m.id}>
                  <td>
                    <span className={`badge ${m.method.toLowerCase()}`}>{m.method}</span>
                  </td>
                  <td className="mono" title={fullUrl}>
                    {m.path}
                  </td>
                  <td>
                    <span className="badge">{m.action}</span>
                  </td>
                  <td>{m.table_id ? tableNameById[m.table_id] || m.table_id : "—"}</td>
                  <td className="muted" style={{ maxWidth: "22rem" }}>
                    {m.required_body_fields && m.required_body_fields.length > 0 ? m.required_body_fields.join(", ") : "—"}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="btn secondary" style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem", marginRight: "0.35rem" }} onClick={() => handleEdit(m)}>
                      编辑
                    </button>
                    <button className="btn secondary" style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }} onClick={() => handleDelete(m.id)}>
                      删除
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
