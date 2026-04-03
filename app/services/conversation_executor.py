"""多轮对话执行器：管理会话状态，逐轮发送用户消息并评估 Agent 回复。

支持三种 API 格式：
  - openai_chat:   标准 OpenAI Chat Completions（messages 数组）
  - agent_engine:  DevelopmentAgentEngine /api/v1/agent/execute（session_id 维持多轮）
  - dispatch:      DevelopmentAgentEngine /v1/{project}/agents/{agent}/conversations/{conv}
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.db.models import (
    AgentTarget,
    AgentTestRun,
    AgentTestRunStatus,
    ConversationScenario,
    ConversationTurn,
    TurnResult,
)

_log = logging.getLogger(__name__)
_VAR_RE = re.compile(r"\{\{([^}]+)\}\}")


def _substitute(text: str, ctx: dict[str, str]) -> str:
    def _repl(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        return ctx.get(key, m.group(0))
    return _VAR_RE.sub(_repl, text)


def _safe_json_trunc(obj: Any, max_len: int = 4000) -> Any:
    """将对象序列化后截断，防止 DB 存储爆表。"""
    s = json.dumps(obj, ensure_ascii=False, default=str)
    if len(s) <= max_len:
        return obj
    return json.loads(s[:max_len - 20] + '..."}}')


class ConversationExecutor:
    """执行一个 ConversationScenario 的所有轮次，记录每轮结果。"""

    def __init__(self, timeout: float = 60.0, *, verify: bool | str = True):
        self._timeout = timeout
        self._verify = verify

    # ------------------------------------------------------------------
    #  内部：场景初始化 / 结束
    # ------------------------------------------------------------------

    def _init_scenario(
        self,
        db: Session,
        scenario: ConversationScenario,
        run: AgentTestRun,
        *,
        extra_variables: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], list[dict[str, Any]], str]:
        """公共初始化：标记 running、构建 ctx / history / session_id。"""
        run.status = AgentTestRunStatus.running
        run.started_at = datetime.utcnow()
        db.commit()

        ctx: dict[str, str] = {}
        if scenario.initial_context:
            ctx.update({str(k): str(v) for k, v in scenario.initial_context.items()})
        if extra_variables:
            ctx.update(extra_variables)

        target = scenario.agent_target
        api_format = target.api_format or "openai_chat"
        conversation_history: list[dict[str, Any]] = []
        if api_format == "openai_chat" and target.default_system_prompt:
            conversation_history.append({"role": "system", "content": target.default_system_prompt})

        session_id = f"test-{uuid.uuid4().hex[:12]}"
        return ctx, conversation_history, session_id

    @staticmethod
    def _resolve_mock_base_url(scenario: ConversationScenario) -> str | None:
        """如果场景有活跃的 MockProfile，返回内嵌 Mock 路由的 base URL。

        内嵌路由挂载在主应用 (port 8000) 的 /mock-workflow/{profile_id}/v1/...
        独立 Mock 服务器 (port 30001) 使用 v4 硬编码数据，两者独立。
        """
        profile_id = getattr(scenario, "active_mock_profile_id", None)
        if not profile_id:
            return None
        return f"http://127.0.0.1:8000/mock-workflow/{profile_id}"

    @staticmethod
    def _finalize_run(db: Session, run: AgentTestRun, passed: int, failed: int, total: int) -> None:
        run.total_turns = total
        run.passed_turns = passed
        run.failed_turns = failed
        run.finished_at = datetime.utcnow()
        if failed == 0 and passed > 0:
            run.status = AgentTestRunStatus.passed
        elif passed == 0 and failed > 0:
            run.status = AgentTestRunStatus.failed
        elif passed > 0 and failed > 0:
            run.status = AgentTestRunStatus.partial
        else:
            run.status = AgentTestRunStatus.error
        db.commit()

    def _execute_one_turn(
        self,
        *,
        client: httpx.Client,
        target: AgentTarget,
        chat_url: str,
        model: str | None,
        auth_override: dict[str, Any] | None,
        turn: ConversationTurn,
        conversation_history: list[dict[str, Any]],
        ctx: dict[str, str],
        run: AgentTestRun,
        session_id: str,
        mock_workflow_base_url: str | None = None,
    ) -> TurnResult:
        """根据 api_format 分发到具体的单轮执行方法。"""
        api_format = target.api_format or "openai_chat"
        if api_format == "dispatch":
            return self._execute_turn_dispatch(
                client=client, target=target, auth_override=auth_override,
                turn=turn, ctx=ctx, run=run, conversation_id=session_id,
                mock_workflow_base_url=mock_workflow_base_url,
            )
        elif api_format == "agent_engine":
            return self._execute_turn_agent_engine(
                client=client, target=target, chat_url=chat_url,
                auth_override=auth_override, turn=turn, ctx=ctx,
                run=run, session_id=session_id,
                mock_workflow_base_url=mock_workflow_base_url,
            )
        else:
            return self._execute_turn_openai(
                client=client, target=target, chat_url=chat_url,
                model=model, auth_override=auth_override, turn=turn,
                conversation_history=conversation_history, ctx=ctx, run=run,
            )

    # ------------------------------------------------------------------
    #  公开入口：同步（全部完成后一次返回）
    # ------------------------------------------------------------------

    def run_scenario(
        self,
        db: Session,
        scenario: ConversationScenario,
        run: AgentTestRun,
        *,
        chat_url_override: str | None = None,
        auth_override: dict[str, Any] | None = None,
        model_override: str | None = None,
        extra_variables: dict[str, str] | None = None,
    ) -> AgentTestRun:
        target: AgentTarget = scenario.agent_target
        chat_url = chat_url_override or target.chat_url
        model = model_override or target.model
        mock_url = self._resolve_mock_base_url(scenario)

        ctx, conversation_history, session_id = self._init_scenario(
            db, scenario, run, extra_variables=extra_variables,
        )

        turns = sorted(scenario.turns, key=lambda t: t.turn_index)
        passed = failed = 0

        with httpx.Client(timeout=self._timeout, verify=self._verify, trust_env=False) as client:
            for turn in turns:
                tr = self._execute_one_turn(
                    client=client, target=target, chat_url=chat_url,
                    model=model, auth_override=auth_override, turn=turn,
                    conversation_history=conversation_history, ctx=ctx,
                    run=run, session_id=session_id,
                    mock_workflow_base_url=mock_url,
                )
                db.add(tr)
                db.commit()
                if tr.passed:
                    passed += 1
                else:
                    failed += 1

        self._finalize_run(db, run, passed, failed, len(turns))
        db.refresh(run)
        return run

    # ------------------------------------------------------------------
    #  公开入口：流式（逐轮 yield TurnResult）
    # ------------------------------------------------------------------

    def run_scenario_streaming(
        self,
        db: Session,
        scenario: ConversationScenario,
        run: AgentTestRun,
        *,
        chat_url_override: str | None = None,
        auth_override: dict[str, Any] | None = None,
        model_override: str | None = None,
        extra_variables: dict[str, str] | None = None,
    ):
        """Generator：每完成一轮 yield 该轮 TurnResult，调用方可实时推送给客户端。"""
        target: AgentTarget = scenario.agent_target
        chat_url = chat_url_override or target.chat_url
        model = model_override or target.model
        mock_url = self._resolve_mock_base_url(scenario)

        ctx, conversation_history, session_id = self._init_scenario(
            db, scenario, run, extra_variables=extra_variables,
        )

        turns = sorted(scenario.turns, key=lambda t: t.turn_index)
        passed = failed = 0

        with httpx.Client(timeout=self._timeout, verify=self._verify, trust_env=False) as client:
            for turn in turns:
                tr = self._execute_one_turn(
                    client=client, target=target, chat_url=chat_url,
                    model=model, auth_override=auth_override, turn=turn,
                    conversation_history=conversation_history, ctx=ctx,
                    run=run, session_id=session_id,
                    mock_workflow_base_url=mock_url,
                )
                db.add(tr)
                db.commit()
                if tr.passed:
                    passed += 1
                else:
                    failed += 1
                yield tr

        self._finalize_run(db, run, passed, failed, len(turns))
        db.refresh(run)

    # ------------------------------------------------------------------
    #  Dispatch 格式：/v1/{project}/agents/{agent}/conversations/{conv}
    # ------------------------------------------------------------------

    def _execute_turn_dispatch(
        self,
        *,
        client: httpx.Client,
        target: AgentTarget,
        auth_override: dict[str, Any] | None,
        turn: ConversationTurn,
        ctx: dict[str, str],
        run: AgentTestRun,
        conversation_id: str,
        mock_workflow_base_url: str | None = None,
    ) -> TurnResult:
        user_msg = _substitute(turn.user_message, ctx)
        t0 = time.perf_counter()

        extra = target.extra_config or {}
        project_id = extra.get("project_id", "0")
        agent_id = extra.get("dispatch_agent_id", target.engine_agent_type or "main_planner")
        base_url = (target.engine_base_url or target.chat_url).rstrip("/")

        url = f"{base_url}/v1/{project_id}/agents/{agent_id}/conversations/{conversation_id}"

        body: dict[str, Any] = {
            "input": {"query": user_msg},
            "custom_data": {"inputs": {"query": user_msg}},
            "stream": False,
            "timeout": int(self._timeout),
        }
        dispatch_body_extra = extra.get("dispatch_body", {})
        if isinstance(dispatch_body_extra, dict):
            body.update(dispatch_body_extra)

        headers = self._build_headers(target, auth_override)
        headers["stream"] = "false"
        if mock_workflow_base_url:
            headers["X-Mock-Workflow-Url"] = mock_workflow_base_url

        request_snapshot = {"url": url, "method": "POST", "headers": dict(headers), "body": body}

        try:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            elapsed = int((time.perf_counter() - t0) * 1000)
            _log.warning("Dispatch call failed at turn %d: %s", turn.turn_index, e)
            return TurnResult(
                run_id=run.id, turn_id=turn.id, turn_index=turn.turn_index,
                actual_user_message=user_msg, actual_agent_response=None,
                latency_ms=elapsed, passed=False, error_message=str(e),
                request_snapshot=request_snapshot,
            )

        elapsed = int((time.perf_counter() - t0) * 1000)

        agent_text = self._extract_dispatch_text(data)
        tool_calls = self._extract_tool_calls_from_output(agent_text)

        assertion_results = self._evaluate_assertions(turn, agent_text, tool_calls, ctx)
        all_passed = all(r["passed"] for r in assertion_results) if assertion_results else True
        extracted = self._run_extract(turn.extract, agent_text, tool_calls)
        ctx.update(extracted)

        return TurnResult(
            run_id=run.id, turn_id=turn.id, turn_index=turn.turn_index,
            actual_user_message=user_msg,
            actual_agent_response=agent_text,
            actual_tool_calls=tool_calls,
            latency_ms=elapsed,
            request_snapshot=request_snapshot,
            raw_response=_safe_json_trunc(data),
            passed=all_passed,
            assertion_results=assertion_results,
            extracted_vars=extracted if extracted else None,
            error_message=None,
        )

    @staticmethod
    def _extract_dispatch_text(data: Any) -> str:
        """从 dispatch 响应中提取可读的文本内容。

        支持的响应结构示例：
          { "custom_rsp_data": { "content": "..." } }
          { "output": "...", "result": "..." }
          { "data": { "content": "..." } }
        """
        if isinstance(data, str):
            return data
        if not isinstance(data, dict):
            return str(data)

        # 优先：custom_rsp_data.content（DevelopmentAgentEngine planning_agent 格式）
        crd = data.get("custom_rsp_data")
        if isinstance(crd, dict):
            content = crd.get("content")
            if content and isinstance(content, str):
                return content

        # 一级字段（跳过空字符串 / 空 dict）
        for key in ("output", "result", "content", "response", "data", "data_content"):
            val = data.get(key)
            if val is None:
                continue
            if isinstance(val, str) and val.strip():
                return val
            if isinstance(val, dict) and val:
                inner = val.get("content") or val.get("text") or val.get("output")
                if inner and isinstance(inner, str):
                    return inner

        return json.dumps(data, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------
    #  Agent Engine 格式：/api/v1/agent/execute
    # ------------------------------------------------------------------

    def _execute_turn_agent_engine(
        self,
        *,
        client: httpx.Client,
        target: AgentTarget,
        chat_url: str,
        auth_override: dict[str, Any] | None,
        turn: ConversationTurn,
        ctx: dict[str, str],
        run: AgentTestRun,
        session_id: str,
        mock_workflow_base_url: str | None = None,
    ) -> TurnResult:
        user_msg = _substitute(turn.user_message, ctx)
        t0 = time.perf_counter()

        agent_id = target.engine_agent_id or ""
        user_id = ctx.get("user_id", "test-user")
        body: dict[str, Any] = {
            "agent_id": agent_id,
            "user_id": user_id,
            "session_id": session_id,
            "input": {"query": user_msg},
            "timeout": int(self._timeout),
            "stream": False,
            "session_ended": False,
        }

        headers = self._build_headers(target, auth_override)
        if mock_workflow_base_url:
            headers["X-Mock-Workflow-Url"] = mock_workflow_base_url
        request_snapshot = {"url": chat_url, "method": "POST", "headers": dict(headers), "body": body}

        try:
            resp = client.post(chat_url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            elapsed = int((time.perf_counter() - t0) * 1000)
            _log.warning("Agent Engine call failed at turn %d: %s", turn.turn_index, e)
            return TurnResult(
                run_id=run.id, turn_id=turn.id, turn_index=turn.turn_index,
                actual_user_message=user_msg, actual_agent_response=None,
                latency_ms=elapsed, passed=False, error_message=str(e),
                request_snapshot=request_snapshot,
            )

        elapsed = int((time.perf_counter() - t0) * 1000)

        success = data.get("success", False)
        agent_text = self._extract_dispatch_text(data)
        error = data.get("error")

        if not success and error:
            return TurnResult(
                run_id=run.id, turn_id=turn.id, turn_index=turn.turn_index,
                actual_user_message=user_msg, actual_agent_response=agent_text,
                latency_ms=elapsed, passed=False,
                error_message=f"Agent 返回失败: {error}",
                request_snapshot=request_snapshot,
                raw_response={"success": success, "execution_time": data.get("execution_time")},
            )

        tool_calls = self._extract_tool_calls_from_output(agent_text)
        assertion_results = self._evaluate_assertions(turn, agent_text, tool_calls, ctx)
        all_passed = all(r["passed"] for r in assertion_results) if assertion_results else True
        extracted = self._run_extract(turn.extract, agent_text, tool_calls)
        ctx.update(extracted)

        return TurnResult(
            run_id=run.id, turn_id=turn.id, turn_index=turn.turn_index,
            actual_user_message=user_msg,
            actual_agent_response=agent_text,
            actual_tool_calls=tool_calls,
            latency_ms=elapsed,
            request_snapshot=request_snapshot,
            raw_response={
                "success": success,
                "session_id": data.get("session_id"),
                "execution_time": data.get("execution_time"),
            },
            passed=all_passed,
            assertion_results=assertion_results,
            extracted_vars=extracted if extracted else None,
            error_message=None,
        )

    def _extract_tool_calls_from_output(self, text: str) -> list[dict[str, Any]] | None:
        """从 Agent Engine 的输出文本中识别工具调用信息。"""
        tool_calls: list[dict[str, Any]] = []
        patterns = [
            r"调用(\w+)工具",
            r"工具已调用.*?(\w+)",
            r"(\w+)工具已调用",
            r"tool[_\s]*call[:\s]+(\w+)",
        ]
        for p in patterns:
            for m in re.finditer(p, text, re.IGNORECASE):
                fn = m.group(1)
                if fn and fn not in {tc.get("function") for tc in tool_calls}:
                    tool_calls.append({"function": fn, "arguments": {}})
        return tool_calls if tool_calls else None

    # ------------------------------------------------------------------
    #  OpenAI Chat 格式单轮执行
    # ------------------------------------------------------------------

    def _execute_turn_openai(
        self,
        *,
        client: httpx.Client,
        target: AgentTarget,
        chat_url: str,
        model: str | None,
        auth_override: dict[str, Any] | None,
        turn: ConversationTurn,
        conversation_history: list[dict[str, Any]],
        ctx: dict[str, str],
        run: AgentTestRun,
    ) -> TurnResult:
        user_msg = _substitute(turn.user_message, ctx)
        conversation_history.append({"role": "user", "content": user_msg})
        t0 = time.perf_counter()

        body = self._build_openai_body(conversation_history, target, model)
        headers = self._build_headers(target, auth_override)
        request_snapshot = {"url": chat_url, "method": "POST", "headers": dict(headers), "body": body}

        try:
            resp = client.post(chat_url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            elapsed = int((time.perf_counter() - t0) * 1000)
            _log.warning("Agent call failed at turn %d: %s", turn.turn_index, e)
            return TurnResult(
                run_id=run.id, turn_id=turn.id, turn_index=turn.turn_index,
                actual_user_message=user_msg, actual_agent_response=None,
                latency_ms=elapsed, passed=False, error_message=str(e),
                request_snapshot=request_snapshot,
            )

        elapsed = int((time.perf_counter() - t0) * 1000)
        agent_text, tool_calls = self._parse_openai_response(data)

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": agent_text}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        conversation_history.append(assistant_msg)

        assertion_results = self._evaluate_assertions(turn, agent_text, tool_calls, ctx)
        all_passed = all(r["passed"] for r in assertion_results) if assertion_results else True
        extracted = self._run_extract(turn.extract, agent_text, tool_calls)
        ctx.update(extracted)

        return TurnResult(
            run_id=run.id, turn_id=turn.id, turn_index=turn.turn_index,
            actual_user_message=user_msg,
            actual_agent_response=agent_text,
            actual_tool_calls=tool_calls,
            latency_ms=elapsed,
            request_snapshot=request_snapshot,
            raw_response={
                "status_code": resp.status_code,
                "model": data.get("model"),
                "usage": data.get("usage"),
            },
            passed=all_passed,
            assertion_results=assertion_results,
            extracted_vars=extracted if extracted else None,
            error_message=None,
        )

    # ------------------------------------------------------------------
    #  请求构造
    # ------------------------------------------------------------------

    def _build_openai_body(
        self,
        messages: list[dict[str, Any]],
        target: AgentTarget,
        model: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"messages": messages, "stream": False}
        if model:
            body["model"] = model
        if target.tools_schema:
            body["tools"] = target.tools_schema
        extra = target.extra_config or {}
        if "temperature" in extra:
            body["temperature"] = extra["temperature"]
        return body

    def _build_headers(
        self,
        target: AgentTarget,
        auth_override: dict[str, Any] | None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        cfg = auth_override or target.auth_config or {}
        auth_type = target.auth_type or "bearer"
        if auth_type == "bearer":
            token = cfg.get("token", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            hdr = cfg.get("header", "X-Api-Key")
            val = cfg.get("value", "")
            if val:
                headers[hdr] = val
        return headers

    # ------------------------------------------------------------------
    #  解析 OpenAI Chat Completions 响应
    # ------------------------------------------------------------------

    def _parse_openai_response(
        self, data: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]] | None]:
        choices = data.get("choices", [])
        if not choices:
            return data.get("content", str(data)), None

        msg = choices[0].get("message", {})
        content = msg.get("content") or ""

        raw_tool_calls = msg.get("tool_calls")
        tool_calls: list[dict[str, Any]] | None = None
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                fn = tc.get("function", {})
                args_raw = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except json.JSONDecodeError:
                    args = args_raw
                tool_calls.append({
                    "id": tc.get("id"),
                    "function": fn.get("name"),
                    "arguments": args,
                })
        return content, tool_calls

    # ------------------------------------------------------------------
    #  断言评估
    # ------------------------------------------------------------------

    def _evaluate_assertions(
        self,
        turn: ConversationTurn,
        agent_text: str,
        tool_calls: list[dict[str, Any]] | None,
        ctx: dict[str, str],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        text_lower = (agent_text or "").lower()

        if turn.expected_keywords:
            for kw in turn.expected_keywords:
                found = kw.lower() in text_lower
                results.append({
                    "type": "keyword_present",
                    "expected": kw,
                    "passed": found,
                    "detail": f"关键词 '{kw}' {'出现' if found else '未出现'}在回复中",
                })

        if turn.forbidden_keywords:
            for kw in turn.forbidden_keywords:
                absent = kw.lower() not in text_lower
                results.append({
                    "type": "keyword_absent",
                    "forbidden": kw,
                    "passed": absent,
                    "detail": f"禁止词 '{kw}' {'未出现' if absent else '出现'}在回复中",
                })

        if turn.expected_tool_calls:
            actual_fns = {(tc.get("function") or "") for tc in (tool_calls or [])}
            for exp in turn.expected_tool_calls:
                fn_name = exp.get("function", "")
                called = fn_name in actual_fns
                r: dict[str, Any] = {
                    "type": "tool_called",
                    "expected_function": fn_name,
                    "passed": called,
                    "detail": f"工具 '{fn_name}' {'已调用' if called else '未调用'}",
                }
                if called and "args_contains" in exp:
                    actual_tc = next(
                        (tc for tc in (tool_calls or []) if tc.get("function") == fn_name), None
                    )
                    if actual_tc:
                        args_ok = self._check_args_contains(actual_tc.get("arguments", {}), exp["args_contains"])
                        r["args_match"] = args_ok
                        if not args_ok:
                            r["passed"] = False
                            r["detail"] += f"，但参数不匹配 (期望包含 {exp['args_contains']})"
                results.append(r)

        if turn.assertions:
            for a in turn.assertions:
                atype = a.get("type", "")
                if atype == "response_contains":
                    val = str(a.get("value", ""))
                    found = val.lower() in text_lower
                    results.append({
                        "type": "response_contains",
                        "expected": val,
                        "passed": found,
                        "detail": f"回复{'包含' if found else '不包含'} '{val}'",
                    })
                elif atype == "response_not_empty":
                    ok = bool(agent_text and agent_text.strip())
                    results.append({
                        "type": "response_not_empty",
                        "passed": ok,
                        "detail": f"回复{'非空' if ok else '为空'}",
                    })
                elif atype == "tool_called":
                    fn = str(a.get("function", ""))
                    actual_fns_set = {(tc.get("function") or "") for tc in (tool_calls or [])}
                    ok = fn in actual_fns_set
                    results.append({
                        "type": "tool_called",
                        "expected_function": fn,
                        "passed": ok,
                        "detail": f"工具 '{fn}' {'已调用' if ok else '未调用'}",
                    })
                elif atype == "no_tool_called":
                    ok = not tool_calls
                    results.append({
                        "type": "no_tool_called",
                        "passed": ok,
                        "detail": f"Agent {'未调用' if ok else '调用了'}工具",
                    })
                elif atype == "response_matches_regex":
                    pattern = str(a.get("pattern", ""))
                    ok = bool(re.search(pattern, agent_text or "", re.IGNORECASE))
                    results.append({
                        "type": "response_matches_regex",
                        "pattern": pattern,
                        "passed": ok,
                        "detail": f"正则 '{pattern}' {'匹配' if ok else '不匹配'}",
                    })

        if not results:
            results.append({
                "type": "response_not_empty",
                "passed": bool(agent_text and agent_text.strip()),
                "detail": "默认断言：回复非空",
            })

        return results

    @staticmethod
    def _check_args_contains(actual: Any, expected: dict[str, Any]) -> bool:
        if not isinstance(actual, dict) or not isinstance(expected, dict):
            return False
        for k, v in expected.items():
            if k not in actual:
                return False
            if str(v) != "*" and str(actual[k]) != str(v):
                return False
        return True

    # ------------------------------------------------------------------
    #  从 Agent 回复中提取变量
    # ------------------------------------------------------------------

    def _run_extract(
        self,
        extract_rules: list[dict[str, Any]] | None,
        agent_text: str,
        tool_calls: list[dict[str, Any]] | None,
    ) -> dict[str, str]:
        if not extract_rules:
            return {}
        result: dict[str, str] = {}
        for rule in extract_rules:
            name = rule.get("name", "")
            source = rule.get("from", "response")
            pattern = rule.get("pattern", "")
            if not name:
                continue

            if source == "response" and pattern:
                m = re.search(pattern, agent_text or "")
                if m:
                    result[name] = m.group(1) if m.lastindex else m.group(0)
            elif source == "tool_call":
                fn_name = rule.get("function", "")
                arg_path = rule.get("arg", "")
                if tool_calls and fn_name and arg_path:
                    for tc in tool_calls:
                        if tc.get("function") == fn_name:
                            args = tc.get("arguments", {})
                            if isinstance(args, dict) and arg_path in args:
                                result[name] = str(args[arg_path])
                            break
        return result
