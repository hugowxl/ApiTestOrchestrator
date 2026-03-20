"""按 test_case 步骤执行 HTTP，变量替换与 extract 注入上下文。"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime
from typing import Any

import httpx

from app.db.models import TestCase, TestCaseStatus, TestResult, TestRun, TestRunStatus
from app.services.assertion_engine import extract_values, run_assertions
from app.utils.redact import redact_headers, snapshot_safe_dict

_log = logging.getLogger(__name__)
_VAR = re.compile(r"\{\{([^}]+)\}\}")


def substitute_vars(text: str | None, ctx: dict[str, str]) -> str:
    if text is None:
        return ""

    def repl(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        if key in ctx:
            return ctx[key]
        ek = key.upper()
        if ek in os.environ:
            return os.environ[ek]
        return m.group(0)

    return _VAR.sub(repl, str(text))


def substitute_object(obj: Any, ctx: dict[str, str]) -> Any:
    if isinstance(obj, str):
        return substitute_vars(obj, ctx)
    if isinstance(obj, dict):
        return {k: substitute_object(v, ctx) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_object(i, ctx) for i in obj]
    return obj


class TestExecutor:
    def __init__(self, timeout: float = 30.0, *, verify: bool | str = True):
        self._timeout = timeout
        self._verify = verify
        if verify is False:
            _log.warning(
                "EXECUTOR_VERIFY_SSL=false：对被测服务 HTTPS 不校验 TLS 证书，存在中间人风险；优先使用 EXECUTOR_CA_BUNDLE"
            )

    def run_case(
        self,
        client: httpx.Client,
        base_url: str,
        case: TestCase,
        *,
        auth_headers: dict[str, str] | None = None,
    ) -> tuple[bool, int, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        ctx: dict[str, str] = {}
        if case.variables_json:
            for k, v in case.variables_json.items():
                ctx[str(k)] = str(v)

        # 记录该用例在一次 run 中每一步的请求快照，供报告展示完整 URL 与传参。
        req_steps: list[dict[str, Any]] = []
        # 仍保留最后一次响应快照，用于错误定位/前端查看（不用于“完整步骤请求展示”）。
        last_resp_snap: dict[str, Any] | None = None
        t0 = time.perf_counter()

        for step in case.steps_json:
            method = str(step["method"]).upper()
            path = substitute_vars(step["path"], ctx)
            if not path.startswith("/"):
                path = "/" + path
            url = base_url.rstrip("/") + path

            # steps_json 的 headers + 手动注入 auth_headers（同名字段以 auth_headers 优先）。
            step_headers = {str(k): substitute_vars(str(v), ctx) for k, v in (step.get("headers") or {}).items()}
            if auth_headers:
                auth_m = {str(k): substitute_vars(str(v), ctx) for k, v in auth_headers.items()}
                headers = {**step_headers, **auth_m}
            else:
                headers = step_headers
            params = {str(k): substitute_vars(str(v), ctx) for k, v in (step.get("query") or {}).items()}

            body_type = (step.get("body_type") or "none").lower()
            json_body: Any | None = None
            content: str | None = None
            data: dict[str, str] | None = None
            if body_type == "json":
                raw_b = step.get("body")
                json_body = substitute_object(raw_b, ctx) if raw_b is not None else None
            elif body_type == "raw":
                content = substitute_vars(str(step.get("body") or ""), ctx)
            elif body_type == "form":
                fd = step.get("body")
                if isinstance(fd, dict):
                    data = {str(k): substitute_vars(str(v), ctx) for k, v in fd.items()}

            req_step_snap = snapshot_safe_dict(
                {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "query": params,
                    "body_type": body_type,
                    "body": json_body if body_type == "json" else (content if body_type == "raw" else step.get("body")),
                }
            )
            req_steps.append(req_step_snap)

            try:
                if body_type == "json":
                    r = client.request(method, url, headers=headers, params=params, json=json_body)
                elif body_type == "raw":
                    r = client.request(method, url, headers=headers, params=params, content=content)
                elif body_type == "form":
                    r = client.request(method, url, headers=headers, params=params, data=data)
                else:
                    r = client.request(method, url, headers=headers, params=params)
            except httpx.HTTPError as e:
                elapsed = int((time.perf_counter() - t0) * 1000)
                return False, elapsed, {"steps": req_steps}, None, str(e)

            body_text = r.text
            body_json: Any | None = None
            ct = r.headers.get("content-type", "")
            if "json" in ct.lower():
                try:
                    body_json = r.json()
                except Exception:
                    body_json = None

            resp_headers = {k: v for k, v in r.headers.items()}
            last_resp_snap = {
                "status_code": r.status_code,
                "headers": redact_headers(resp_headers),
                "body_preview": body_text[:4000],
            }

            ok, err = run_assertions(
                step.get("assertions"),
                status_code=r.status_code,
                headers=resp_headers,
                body_text=body_text,
                body_json=body_json,
            )
            if not ok:
                elapsed = int((time.perf_counter() - t0) * 1000)
                return False, elapsed, {"steps": req_steps}, last_resp_snap, err

            extracted = extract_values(
                step.get("extract"),
                status_code=r.status_code,
                headers=resp_headers,
                body_json=body_json,
            )
            ctx.update(extracted)

        elapsed = int((time.perf_counter() - t0) * 1000)
        return True, elapsed, {"steps": req_steps}, last_resp_snap, None

    def run_suite(
        self,
        db,
        run: TestRun,
        cases: list[TestCase],
        *,
        only_approved: bool = False,
        auth_headers: dict[str, str] | None = None,
    ) -> TestRun:
        run.status = TestRunStatus.running
        run.started_at = run.started_at or datetime.utcnow()
        db.commit()

        base = run.target_base_url
        passed = failed = 0

        # 与 curl 行为对齐：忽略环境代理（HTTP_PROXY/HTTPS_PROXY），避免中间网关导致 504。
        with httpx.Client(timeout=self._timeout, follow_redirects=True, verify=self._verify, trust_env=False) as client:
            for case in cases:
                if only_approved and case.status != TestCaseStatus.approved:
                    continue
                ok, lat, req_s, resp_s, err = self.run_case(client, base, case, auth_headers=auth_headers)
                tr = TestResult(
                    run_id=run.id,
                    case_id=case.id,
                    passed=ok,
                    latency_ms=lat,
                    request_snapshot=req_s,
                    response_snapshot=resp_s,
                    error_message=err,
                )
                db.add(tr)
                if ok:
                    passed += 1
                else:
                    failed += 1
                db.commit()

        run.finished_at = datetime.utcnow()
        if failed == 0:
            run.status = TestRunStatus.success
        elif passed == 0:
            run.status = TestRunStatus.failed
        else:
            run.status = TestRunStatus.partial
        db.commit()
        db.refresh(run)
        return run
