import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api/client";
import { JsonBlock } from "../components/JsonBlock";

export function RunDetail() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<api.TestRunOut | null>(null);
  const [reports, setReports] = useState<api.ReportOut[]>([]);
  const load = useCallback(() => {
    if (!runId) return;
    Promise.all([api.getRun(runId), api.listReports(runId)])
      .then(([r, rep]) => {
        setRun(r);
        setReports(rep);
      })
      .catch(() => {});
  }, [runId]);

  useEffect(() => {
    load();
  }, [load]);

  if (!runId) return <p className="err">缺少 runId</p>;

  return (
    <>
      <p>
        <Link to="/">服务列表</Link>
        {run?.suite_id && (
          <>
            {" · "}
            <Link to={`/suites/${run.suite_id}`}>套件</Link>
          </>
        )}
      </p>

      <div className="card">
        <h2>TestRun</h2>
        {run ? <JsonBlock data={run} /> : <p className="muted">加载中…</p>}
        <button type="button" className="btn secondary" onClick={load} style={{ marginTop: "0.5rem" }}>
          刷新
        </button>
      </div>

      <div className="card">
        <h2>报告</h2>
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
          GET /api/v1/runs/&#123;run_id&#125;/reports — 文件在服务端 storage_path
        </p>
        {reports.length === 0 ? (
          <p className="muted">暂无报告（可能未开启 generate_reports）。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>format</th>
                <th>storage_path</th>
                <th>摘要预览</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id}>
                  <td>{r.format}</td>
                  <td className="mono">{r.storage_path}</td>
                  <td>
                    {r.summary_json ? (
                      <details>
                        <summary>summary_json</summary>
                        <JsonBlock data={r.summary_json} />
                      </details>
                    ) : (
                      "—"
                    )}
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
