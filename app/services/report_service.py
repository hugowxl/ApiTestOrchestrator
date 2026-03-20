"""汇总 test_run 结果并生成 HTML / Markdown / JSON 报告。"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Report, TestCase, TestResult, TestRun


def _full_url(url: Any, query: Any) -> str:
    u = str(url or "").strip() or "—"
    if not isinstance(query, dict) or not query:
        return u
    pairs: list[tuple[str, str]] = []
    for key, val in query.items():
        k = str(key)
        if isinstance(val, (list, tuple)):
            for item in val:
                if isinstance(item, (dict, list)):
                    pairs.append((k, json.dumps(item, ensure_ascii=False)))
                else:
                    pairs.append((k, str(item)))
        elif isinstance(val, (dict, list)):
            pairs.append((k, json.dumps(val, ensure_ascii=False)))
        else:
            pairs.append((k, str(val)))
    encoded = urlencode(pairs)
    sep = "&" if "?" in u else "?"
    return f"{u}{sep}{encoded}"


def _enrich_step(d: dict[str, Any]) -> dict[str, Any]:
    d["full_url"] = _full_url(d.get("url"), d.get("query"))
    return d


def _reports_root() -> Path:
    root = Path(__file__).resolve().parents[2] / "data" / "reports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _request_steps_from_snapshot(snapshot: Any) -> list[dict[str, Any]]:
    """从 TestResult.request_snapshot 取出每步完整 URL 与传参（与执行器写入结构一致）。"""
    if not snapshot or not isinstance(snapshot, dict):
        return []
    steps = snapshot.get("steps")
    if not isinstance(steps, list):
        # 兼容旧数据：request_snapshot 直接是单步快照（含 method/url/query/headers/body_type/body）
        if any(k in snapshot for k in ("method", "url")):
            q = snapshot.get("query")
            h = snapshot.get("headers")
            return [
                _enrich_step(
                    {
                        "method": snapshot.get("method"),
                        "url": snapshot.get("url"),
                        "query": q if isinstance(q, dict) else {},
                        "headers": h if isinstance(h, dict) else {},
                        "body_type": snapshot.get("body_type") or "none",
                        "body": snapshot.get("body"),
                    },
                ),
            ]
        return []
    out: list[dict[str, Any]] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        q = s.get("query")
        h = s.get("headers")
        out.append(
            _enrich_step(
                {
                    "method": s.get("method"),
                    "url": s.get("url"),
                    "query": q if isinstance(q, dict) else {},
                    "headers": h if isinstance(h, dict) else {},
                    "body_type": s.get("body_type") or "none",
                    "body": s.get("body"),
                },
            ),
        )
    return out


def _body_preview(body: Any, max_chars: int = 800) -> str:
    if body is None:
        return ""
    try:
        text = json.dumps(body, ensure_ascii=False, indent=2) if isinstance(body, (dict, list)) else str(body)
    except (TypeError, ValueError):
        text = str(body)
    if len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def _format_steps_plain(steps: list[dict[str, Any]], *, max_body: int = 800) -> str:
    """纯文本多行摘要。"""
    lines: list[str] = []
    for i, st in enumerate(steps, 1):
        m = st.get("method") or "?"
        url = st.get("full_url") or st.get("url") or "—"
        lines.append(f"{i}) {m} {url}")
        q = st.get("query") or {}
        if q:
            lines.append(f"   query: {json.dumps(q, ensure_ascii=False)}")
        h = st.get("headers") or {}
        if h:
            lines.append(f"   headers: {json.dumps(h, ensure_ascii=False)}")
        bt = st.get("body_type") or "none"
        if bt != "none":
            body = _body_preview(st.get("body"), max_body)
            if body:
                lines.append(f"   body_type: {bt}")
                for bl in body.split("\n"):
                    lines.append(f"   {bl}")
    return "\n".join(lines) if lines else "—"


def _format_params_plain(steps: list[dict[str, Any]], *, max_body: int = 800) -> str:
    """query / headers / body only per step (no method/URL line)."""
    lines: list[str] = []
    for i, st in enumerate(steps, 1):
        chunk: list[str] = []
        q = st.get("query") or {}
        if q:
            chunk.append(f"query: {json.dumps(q, ensure_ascii=False)}")
        h = st.get("headers") or {}
        if h:
            chunk.append(f"headers: {json.dumps(h, ensure_ascii=False)}")
        bt = st.get("body_type") or "none"
        if bt != "none":
            body = _body_preview(st.get("body"), max_body)
            if body:
                chunk.append(f"body_type: {bt}")
                chunk.extend(body.split("\n"))
        if not chunk:
            continue
        for j, line in enumerate(chunk):
            prefix = f"{i}) " if j == 0 else "   "
            lines.append(f"{prefix}{line}")
    return "\n".join(lines) if lines else "—"


def build_summary(db: Session, run: TestRun) -> dict:
    rows = db.execute(select(TestResult).where(TestResult.run_id == run.id)).scalars().all()
    passed = sum(1 for r in rows if r.passed)
    failed = sum(1 for r in rows if not r.passed)
    cases: list[dict[str, Any]] = []
    for r in rows:
        tc = db.get(TestCase, r.case_id)
        name = tc.name if tc else r.case_id
        request_steps = _request_steps_from_snapshot(r.request_snapshot)
        first = request_steps[0] if request_steps else None
        request_method_url = (
            f"{first.get('method') or '?'} {first.get('full_url') or first.get('url') or '—'}"
            if first
            else None
        )
        request_params_summary = (
            _format_params_plain(request_steps) if request_steps else None
        )
        cases.append(
            {
                "case_id": r.case_id,
                "passed": r.passed,
                "latency_ms": r.latency_ms,
                "error": r.error_message,
                "name": name,
                "request_steps": request_steps,
                "request_method_url": request_method_url,
                "request_params_summary": request_params_summary,
                "request_summary": _format_steps_plain(request_steps),
            },
        )

    return {
        "run_id": run.id,
        "suite_id": run.suite_id,
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "target_base_url": run.target_base_url,
        "total": len(rows),
        "passed": passed,
        "failed": failed,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "cases": cases,
    }


def render_html(summary: dict) -> str:
    rows = summary.get("cases") or []
    trs = []
    for c in rows:
        steps = c.get("request_steps") or []
        if steps:
            parts = []
            for st in steps:
                display_url = st.get("full_url") or st.get("url") or ""
                url = _esc(str(display_url))
                m = _esc(str(st.get("method") or ""))
                q = st.get("query") or {}
                h = st.get("headers") or {}
                bt = _esc(str(st.get("body_type") or "none"))
                body_prev = _esc(_body_preview(st.get("body"), 1200))
                qj = _esc(json.dumps(q, ensure_ascii=False)) if q else ""
                hj = _esc(json.dumps(h, ensure_ascii=False)) if h else ""
                blk = f'<div class="step"><strong>{m}</strong> <code class="url">{url}</code>'
                if q:
                    blk += f'<div class="sub">query: <code>{qj}</code></div>'
                if h:
                    blk += f'<div class="sub">headers: <code>{hj}</code></div>'
                if bt != "none" and body_prev:
                    blk += f'<div class="sub">body_type: {bt}</div><pre class="body">{body_prev}</pre>'
                blk += "</div>"
                parts.append(blk)
            req_html = '<div class="req">' + "".join(parts) + "</div>"
        else:
            req_html = "<span class='muted'>—</span>"

        trs.append(
            f"<tr><td>{_esc(str(c.get('name','')))}</td><td>{'PASS' if c.get('passed') else 'FAIL'}</td>"
            f"<td>{c.get('latency_ms','')}</td><td class='req-cell'>{req_html}</td>"
            f"<td>{_esc(str(c.get('error') or ''))}</td></tr>",
        )
    body = "\n".join(trs) if trs else "<tr><td colspan='5'>无结果</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/><title>Test Run {summary.get('run_id')}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; vertical-align: top; }}
th {{ background: #f5f5f5; }}
.req-cell {{ max-width: 36rem; }}
.req .step {{ margin-bottom: 0.75rem; padding-bottom: 0.5rem; border-bottom: 1px dashed #ddd; }}
.req .step:last-child {{ border-bottom: none; }}
code.url {{ word-break: break-all; font-size: 0.85rem; }}
.sub {{ font-size: 0.8rem; margin-top: 0.25rem; color: #333; }}
pre.body {{ margin: 0.25rem 0 0; font-size: 0.75rem; max-height: 14rem; overflow: auto; background: #f9f9f9; padding: 0.5rem; }}
.muted {{ color: #888; }}
</style></head><body>
<h1>测试运行报告</h1>
<p>Run: {_esc(str(summary.get('run_id')))} | 通过: {summary.get('passed')} | 失败: {summary.get('failed')} | 合计: {summary.get('total')}</p>
<p>target_base_url: <code>{_esc(str(summary.get('target_base_url') or ''))}</code></p>
<table><thead><tr><th>用例</th><th>结果</th><th>耗时(ms)</th><th>请求（完整 URL 与传参）</th><th>错误</th></tr></thead>
<tbody>{body}</tbody></table>
</body></html>"""


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_markdown(summary: dict) -> str:
    lines = [
        f"# 测试运行 {summary.get('run_id')}",
        "",
        f"- target_base_url: `{summary.get('target_base_url')}`",
        f"- 通过: {summary.get('passed')}  失败: {summary.get('failed')}  合计: {summary.get('total')}",
        "",
    ]
    for c in summary.get("cases") or []:
        name = c.get("name", "")
        ok = "PASS" if c.get("passed") else "FAIL"
        lat = c.get("latency_ms", "")
        err = str(c.get("error") or "").replace("|", "\\|")
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"- **结果**: {ok}  |  **耗时(ms)**: {lat}")
        lines.append(f"- **错误**: {err or '—'}")
        lines.append("")
        lines.append("**请求**")
        lines.append("")
        lines.append("```")
        lines.append(_format_steps_plain(c.get("request_steps") or [], max_body=2000))
        lines.append("```")
        lines.append("")
    if not summary.get("cases"):
        lines.append("_无结果_")
    return "\n".join(lines)


def persist_reports(db: Session, run: TestRun, formats: list[str] | None = None) -> list[Report]:
    formats = formats or ["json", "html", "markdown"]
    summary = build_summary(db, run)
    base = _reports_root() / run.id
    base.mkdir(parents=True, exist_ok=True)
    out: list[Report] = []

    if "json" in formats:
        p = base / "report.json"
        p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        r = Report(run_id=run.id, format="json", storage_path=str(p.resolve()), summary_json=summary)
        db.add(r)
        out.append(r)

    if "html" in formats:
        p = base / "report.html"
        p.write_text(render_html(summary), encoding="utf-8")
        r = Report(run_id=run.id, format="html", storage_path=str(p.resolve()), summary_json=summary)
        db.add(r)
        out.append(r)

    if "markdown" in formats:
        p = base / "report.md"
        p.write_text(render_markdown(summary), encoding="utf-8")
        r = Report(run_id=run.id, format="markdown", storage_path=str(p.resolve()), summary_json=summary)
        db.add(r)
        out.append(r)

    db.commit()
    for r in out:
        db.refresh(r)
    return out
