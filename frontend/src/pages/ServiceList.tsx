import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import * as api from "../api/client";

export function ServiceList() {
  const [list, setList] = useState<api.ServiceOut[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [swaggerUrl, setSwaggerUrl] = useState("");
  const [creating, setCreating] = useState(false);

  const load = () => {
    setErr(null);
    setLoading(true);
    api
      .listServices()
      .then(setList)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    if (!name.trim() || !baseUrl.trim()) {
      setErr("请填写服务名称与 base_url");
      return;
    }
    setCreating(true);
    setErr(null);
    try {
      await api.createService({
        name: name.trim(),
        base_url: baseUrl.trim(),
        swagger_url: swaggerUrl.trim() || null,
      });
      setName("");
      setBaseUrl("");
      setSwaggerUrl("");
      await load();
    } catch {
      /* 错误已由 api 层弹窗提示 */
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      <div className="card">
        <h2>注册服务</h2>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label>
            名称
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="my-api" />
          </label>
          <label>
            base_url（被测运行时根地址）
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://localhost:8080" />
          </label>
          <label>
            swagger_url（可选）
            <input
              value={swaggerUrl}
              onChange={(e) => setSwaggerUrl(e.target.value)}
              placeholder="https://.../openapi.json"
            />
          </label>
          <button type="button" className="btn" disabled={creating} onClick={create}>
            创建
          </button>
        </div>
      </div>

      <div className="card">
        <h2>服务列表</h2>
        {err && <p className="err">{err}</p>}
        {loading ? (
          <p className="muted">加载中…</p>
        ) : list.length === 0 ? (
          <p className="muted">暂无服务，请先注册。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>base_url</th>
                <th>swagger_url</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td className="mono">{s.base_url}</td>
                  <td className="mono">{s.swagger_url || "—"}</td>
                  <td>
                    <Link to={`/services/${s.id}`}>管理</Link>
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
