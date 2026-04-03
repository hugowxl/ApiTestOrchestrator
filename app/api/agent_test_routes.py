"""Agent 多轮对话测试的 REST API 路由。"""

import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.agent_test_schemas import (
    AgentTargetCreate,
    AgentTargetOut,
    AgentTargetUpdate,
    AgentTestRunDetailOut,
    AgentTestRunOut,
    ConversationTurnCreate,
    ConversationTurnOut,
    ConversationTurnUpdate,
    DiscoverAgentsOut,
    DiscoverAgentsRequest,
    DiscoveredAgent,
    GenerateBranchesRequest,
    GenerateScenarioRequest,
    MockBranchSkillOut,
    MockBranchSkillCreate,
    MockBranchSkillUpdate,
    MockProfileCreate,
    MockProfileOut,
    MockProfileUpdate,
    RunScenarioRequest,
    ScenarioCreate,
    ScenarioDetailOut,
    ScenarioOut,
    TurnResultOut,
)
from app.config import get_settings
from app.db.models import (
    AgentTarget,
    AgentTestRun,
    AgentTestRunStatus,
    ConversationScenario,
    ConversationTurn,
    MockBranchSkill,
    MockProfile,
    TurnResult,
)
from app.db.session import get_db
from app.services.conversation_executor import ConversationExecutor
from app.services.workflow_mock_server import compute_mock_preview
from app.utils.errors import ErrorCode

_log = logging.getLogger(__name__)
router = APIRouter()

_E404 = lambda msg: HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": msg})


# ---------------------------------------------------------------------------
#  AgentTarget CRUD
# ---------------------------------------------------------------------------


@router.post("/agent-test/targets", response_model=AgentTargetOut)
def create_agent_target(body: AgentTargetCreate, db: Session = Depends(get_db)):
    t = AgentTarget(
        name=body.name,
        chat_url=body.chat_url,
        api_format=body.api_format,
        model=body.model,
        auth_type=body.auth_type,
        auth_config=body.auth_config,
        tools_schema=body.tools_schema,
        default_system_prompt=body.default_system_prompt,
        engine_agent_id=body.engine_agent_id,
        engine_agent_type=body.engine_agent_type,
        engine_base_url=body.engine_base_url,
        agent_description=body.agent_description,
        agent_tools=body.agent_tools,
        extra_config=body.extra_config,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.get("/agent-test/targets", response_model=list[AgentTargetOut])
def list_agent_targets(db: Session = Depends(get_db)):
    return list(db.execute(select(AgentTarget).order_by(AgentTarget.created_at.desc())).scalars().all())


@router.get("/agent-test/targets/{target_id}", response_model=AgentTargetOut)
def get_agent_target(target_id: str, db: Session = Depends(get_db)):
    t = db.get(AgentTarget, target_id)
    if not t:
        raise _E404("Agent target 不存在")
    return t


@router.put("/agent-test/targets/{target_id}", response_model=AgentTargetOut)
def update_agent_target(target_id: str, body: AgentTargetUpdate, db: Session = Depends(get_db)):
    t = db.get(AgentTarget, target_id)
    if not t:
        raise _E404("Agent target 不存在")
    for field in ("name", "chat_url", "model", "auth_type", "auth_config", "tools_schema", "default_system_prompt", "extra_config"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(t, field, val)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/agent-test/targets/{target_id}", status_code=204)
def delete_agent_target(target_id: str, db: Session = Depends(get_db)):
    t = db.get(AgentTarget, target_id)
    if not t:
        raise _E404("Agent target 不存在")
    db.delete(t)
    db.commit()


# ---------------------------------------------------------------------------
#  ConversationScenario CRUD
# ---------------------------------------------------------------------------


@router.post("/agent-test/scenarios", response_model=ScenarioDetailOut)
def create_scenario(body: ScenarioCreate, db: Session = Depends(get_db)):
    if not db.get(AgentTarget, body.agent_target_id):
        raise _E404("Agent target 不存在")
    sc = ConversationScenario(
        agent_target_id=body.agent_target_id,
        name=body.name,
        description=body.description,
        tags=body.tags,
        initial_context=body.initial_context,
        max_turns=body.max_turns,
    )
    db.add(sc)
    db.flush()
    if body.turns:
        for t in body.turns:
            db.add(ConversationTurn(
                scenario_id=sc.id,
                turn_index=t.turn_index,
                user_message=t.user_message,
                expected_intent=t.expected_intent,
                expected_tool_calls=t.expected_tool_calls,
                expected_keywords=t.expected_keywords,
                forbidden_keywords=t.forbidden_keywords,
                assertions=t.assertions,
                extract=t.extract,
            ))
    db.commit()
    db.refresh(sc)
    return _scenario_detail(sc)


@router.get("/agent-test/targets/{target_id}/scenarios", response_model=list[ScenarioOut])
def list_scenarios(target_id: str, db: Session = Depends(get_db)):
    if not db.get(AgentTarget, target_id):
        raise _E404("Agent target 不存在")
    return list(
        db.execute(
            select(ConversationScenario)
            .where(ConversationScenario.agent_target_id == target_id)
            .order_by(ConversationScenario.created_at.desc())
        ).scalars().all()
    )


@router.get("/agent-test/scenarios/{scenario_id}", response_model=ScenarioDetailOut)
def get_scenario(scenario_id: str, db: Session = Depends(get_db)):
    sc = db.get(ConversationScenario, scenario_id)
    if not sc:
        raise _E404("场景不存在")
    return _scenario_detail(sc)


@router.delete("/agent-test/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str, db: Session = Depends(get_db)):
    sc = db.get(ConversationScenario, scenario_id)
    if not sc:
        raise _E404("场景不存在")
    db.delete(sc)
    db.commit()


# ---------------------------------------------------------------------------
#  ConversationTurn CRUD
# ---------------------------------------------------------------------------


@router.post("/agent-test/scenarios/{scenario_id}/turns", response_model=ConversationTurnOut)
def add_turn(scenario_id: str, body: ConversationTurnCreate, db: Session = Depends(get_db)):
    sc = db.get(ConversationScenario, scenario_id)
    if not sc:
        raise _E404("场景不存在")
    t = ConversationTurn(
        scenario_id=sc.id,
        turn_index=body.turn_index,
        user_message=body.user_message,
        expected_intent=body.expected_intent,
        expected_tool_calls=body.expected_tool_calls,
        expected_keywords=body.expected_keywords,
        forbidden_keywords=body.forbidden_keywords,
        assertions=body.assertions,
        extract=body.extract,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.put("/agent-test/turns/{turn_id}", response_model=ConversationTurnOut)
def update_turn(turn_id: str, body: ConversationTurnUpdate, db: Session = Depends(get_db)):
    t = db.get(ConversationTurn, turn_id)
    if not t:
        raise _E404("轮次不存在")
    for field in ("turn_index", "user_message", "expected_intent", "expected_tool_calls", "expected_keywords", "forbidden_keywords", "assertions", "extract"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(t, field, val)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/agent-test/turns/{turn_id}", status_code=204)
def delete_turn(turn_id: str, db: Session = Depends(get_db)):
    t = db.get(ConversationTurn, turn_id)
    if not t:
        raise _E404("轮次不存在")
    db.delete(t)
    db.commit()


@router.post("/agent-test/turns/{turn_id}/execute", response_model=TurnResultOut)
def execute_single_turn(turn_id: str, body: RunScenarioRequest, db: Session = Depends(get_db)):
    """独立执行某一轮对话（不依赖上下文，使用新 session）。"""
    turn = db.get(ConversationTurn, turn_id)
    if not turn:
        raise _E404("轮次不存在")

    scenario: ConversationScenario = turn.scenario
    target: AgentTarget = scenario.agent_target

    run = AgentTestRun(scenario_id=scenario.id, config_override={
        "chat_url_override": body.chat_url_override,
        "model_override": body.model_override,
        "single_turn_id": turn_id,
    })
    db.add(run)
    db.commit()
    db.refresh(run)

    run.status = AgentTestRunStatus.running
    run.started_at = __import__("datetime").datetime.utcnow()
    db.commit()

    settings = get_settings()
    executor = ConversationExecutor(
        timeout=float(settings.http_timeout_seconds),
        verify=settings.executor_tls_verify(),
    )

    chat_url = body.chat_url_override or target.chat_url
    model = body.model_override or target.model
    api_format = target.api_format or "openai_chat"

    ctx: dict[str, str] = {}
    if scenario.initial_context:
        ctx.update({str(k): str(v) for k, v in scenario.initial_context.items()})
    if body.extra_variables:
        ctx.update(body.extra_variables)

    conversation_history: list[dict[str, Any]] = []
    if api_format == "openai_chat" and target.default_system_prompt:
        conversation_history.append({"role": "system", "content": target.default_system_prompt})

    session_id = f"single-{__import__('uuid').uuid4().hex[:12]}"
    # 独立执行单轮时，不走 ConversationExecutor.run_scenario/run_scenario_streaming，
    # 这里需要手动把 active_mock_profile_id 绑定到 mock-server 的 conversation_id，
    # 让 Mock 服务读取 Mock 数据一览里激活的 profile 而不是硬编码默认值。
    if scenario.active_mock_profile_id:
        from app.services.workflow_mock_server import set_mock_profile_for_conversation
        set_mock_profile_for_conversation(session_id, scenario.active_mock_profile_id)

    try:
        with httpx.Client(
            timeout=float(settings.http_timeout_seconds),
            verify=settings.executor_tls_verify(),
            trust_env=False,
        ) as client:
            tr = executor._execute_one_turn(
                client=client, target=target, chat_url=chat_url,
                model=model, auth_override=body.auth_override, turn=turn,
                conversation_history=conversation_history, ctx=ctx,
                run=run, session_id=session_id,
            )
            db.add(tr)
            db.commit()
    except Exception as e:
        run.status = AgentTestRunStatus.error
        run.finished_at = __import__("datetime").datetime.utcnow()
        db.commit()
        raise HTTPException(500, detail={"code": "EXECUTION_FAILED", "message": str(e)}) from e

    run.total_turns = 1
    run.passed_turns = 1 if tr.passed else 0
    run.failed_turns = 0 if tr.passed else 1
    run.finished_at = __import__("datetime").datetime.utcnow()
    run.status = AgentTestRunStatus.passed if tr.passed else AgentTestRunStatus.failed
    db.commit()

    db.refresh(tr)
    return tr


# ---------------------------------------------------------------------------
#  执行场景
# ---------------------------------------------------------------------------


@router.post("/agent-test/scenarios/{scenario_id}/run", response_model=AgentTestRunDetailOut)
def run_scenario(scenario_id: str, body: RunScenarioRequest, db: Session = Depends(get_db)):
    sc = db.get(ConversationScenario, scenario_id)
    if not sc:
        raise _E404("场景不存在")
    if not sc.turns:
        raise HTTPException(400, detail={"code": "VALIDATION_ERROR", "message": "场景无轮次定义"})

    run = AgentTestRun(scenario_id=sc.id, config_override={
        "chat_url_override": body.chat_url_override,
        "model_override": body.model_override,
    })
    db.add(run)
    db.commit()
    db.refresh(run)

    settings = get_settings()
    executor = ConversationExecutor(
        timeout=float(settings.http_timeout_seconds),
        verify=settings.executor_tls_verify(),
    )
    try:
        executor.run_scenario(
            db, sc, run,
            chat_url_override=body.chat_url_override,
            auth_override=body.auth_override,
            model_override=body.model_override,
            extra_variables=body.extra_variables,
        )
    except Exception as e:
        run.status = "error"
        run.finished_at = __import__("datetime").datetime.utcnow()
        db.commit()
        raise HTTPException(500, detail={"code": "EXECUTION_FAILED", "message": str(e)}) from e

    db.refresh(run)
    return _run_detail(db, run)


# ---------------------------------------------------------------------------
#  流式执行：SSE 逐轮推送
# ---------------------------------------------------------------------------


def _sse_event(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/agent-test/scenarios/{scenario_id}/run-stream")
def run_scenario_stream(scenario_id: str, body: RunScenarioRequest, db: Session = Depends(get_db)):
    sc = db.get(ConversationScenario, scenario_id)
    if not sc:
        raise _E404("场景不存在")
    if not sc.turns:
        raise HTTPException(400, detail={"code": "VALIDATION_ERROR", "message": "场景无轮次定义"})

    run = AgentTestRun(scenario_id=sc.id, config_override={
        "chat_url_override": body.chat_url_override,
        "model_override": body.model_override,
    })
    db.add(run)
    db.commit()
    db.refresh(run)

    settings = get_settings()
    executor = ConversationExecutor(
        timeout=float(settings.http_timeout_seconds),
        verify=settings.executor_tls_verify(),
    )

    total_turns = len(sc.turns)

    def generate():
        yield _sse_event("run_started", {
            "run_id": run.id,
            "scenario_id": sc.id,
            "total_turns": total_turns,
        })

        try:
            for tr in executor.run_scenario_streaming(
                db, sc, run,
                chat_url_override=body.chat_url_override,
                auth_override=body.auth_override,
                model_override=body.model_override,
                extra_variables=body.extra_variables,
            ):
                yield _sse_event("turn_completed", TurnResultOut.model_validate(tr).model_dump(mode="json"))
        except Exception as e:
            _log.exception("Streaming execution error")
            yield _sse_event("error", {"message": str(e)})

        db.refresh(run)
        yield _sse_event("run_finished", {
            "run_id": run.id,
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "total_turns": run.total_turns,
            "passed_turns": run.passed_turns,
            "failed_turns": run.failed_turns,
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
#  查看执行结果
# ---------------------------------------------------------------------------


@router.get("/agent-test/scenarios/{scenario_id}/runs", response_model=list[AgentTestRunOut])
def list_scenario_runs(scenario_id: str, db: Session = Depends(get_db)):
    sc = db.get(ConversationScenario, scenario_id)
    if not sc:
        raise _E404("场景不存在")
    return list(
        db.execute(
            select(AgentTestRun)
            .where(AgentTestRun.scenario_id == scenario_id)
            .order_by(AgentTestRun.started_at.desc())
        ).scalars().all()
    )


@router.get("/agent-test/runs/{run_id}", response_model=AgentTestRunDetailOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(AgentTestRun, run_id)
    if not run:
        raise _E404("执行记录不存在")
    return _run_detail(db, run)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _scenario_detail(sc: ConversationScenario) -> dict:
    return ScenarioDetailOut(
        id=sc.id,
        agent_target_id=sc.agent_target_id,
        name=sc.name,
        description=sc.description,
        tags=sc.tags,
        initial_context=sc.initial_context,
        max_turns=sc.max_turns,
        created_at=sc.created_at,
        updated_at=sc.updated_at,
        turns=[ConversationTurnOut.model_validate(t) for t in sorted(sc.turns, key=lambda x: x.turn_index)],
        agent_target=AgentTargetOut.model_validate(sc.agent_target),
    ).model_dump()


def _run_detail(db: Session, run: AgentTestRun) -> dict:
    from app.api.agent_test_schemas import TurnResultOut
    trs = list(
        db.execute(
            select(TurnResult).where(TurnResult.run_id == run.id).order_by(TurnResult.turn_index)
        ).scalars().all()
    )
    sc = run.scenario
    return AgentTestRunDetailOut(
        id=run.id,
        scenario_id=run.scenario_id,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        total_turns=run.total_turns,
        passed_turns=run.passed_turns,
        failed_turns=run.failed_turns,
        started_at=run.started_at,
        finished_at=run.finished_at,
        turn_results=[TurnResultOut.model_validate(tr) for tr in trs],
        scenario=ScenarioOut.model_validate(sc) if sc else None,
    ).model_dump()


# ---------------------------------------------------------------------------
#  Agent 发现：连接 DevelopmentAgentEngine 拉取可用 Agent
# ---------------------------------------------------------------------------

def _try_get_json(c: httpx.Client, url: str) -> Any:
    """尝试 GET 请求并返回 JSON，失败返回 None。"""
    try:
        resp = c.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        _log.debug("GET %s failed", url, exc_info=True)
        return None


def _fetch_engine_agents(base: str) -> list[dict]:
    """连接 DevelopmentAgentEngine，组合多个接口获取 Agent 完整信息。

    自动尝试多种路径模式以兼容不同版本的 Agent Engine：
    - /api/v1/agent/configs  or  /api/v1/agents/configs   → 完整配置
    - /api/v1/agent/health   or  /api/v1/agents/health    → 运行状态
    - /api/v1/agent/list     or  /api/v1/agents/list      → ID 列表（兜底）
    """
    with httpx.Client(timeout=15, trust_env=False) as c:
        configs: list[dict] = []
        health_map: dict[str, dict] = {}

        # 1) 尝试获取完整配置（优先用复数路径）
        for path in ["/api/v1/agents/configs", "/api/v1/agent/configs"]:
            data = _try_get_json(c, f"{base}{path}")
            if data and isinstance(data, list):
                configs = [x for x in data if isinstance(x, dict)]
                if configs:
                    break

        # 2) 补充健康状态
        for path in ["/api/v1/agents/health", "/api/v1/agent/health"]:
            data = _try_get_json(c, f"{base}{path}")
            if data and isinstance(data, list):
                for h in data:
                    if isinstance(h, dict) and h.get("agent_id"):
                        health_map[h["agent_id"]] = h
                break

        # 3) 兜底：如果 configs 为空，从 list 端点获取 ID
        if not configs:
            for path in ["/api/v1/agents/list", "/api/v1/agent/list"]:
                data = _try_get_json(c, f"{base}{path}")
                if data and isinstance(data, list):
                    for item in data:
                        if isinstance(item, str):
                            configs.append({"agent_id": item})
                        elif isinstance(item, dict):
                            configs.append(item)
                    if configs:
                        break

        # 如果所有路径都失败了，尝试 OpenAPI 文档发现
        if not configs:
            openapi = _try_get_json(c, f"{base}/openapi.json")
            if openapi:
                raise HTTPException(502, detail={
                    "code": "DISCOVERY_EMPTY",
                    "message": "Agent Engine 可达但未找到活跃 Agent。请确认引擎已启动并加载了 Agent。",
                })
            raise HTTPException(502, detail={
                "code": "DISCOVERY_FAILED",
                "message": f"无法从 {base} 获取 Agent 列表，已尝试多种路径。",
            })

        results: list[dict] = []
        for cfg in configs:
            aid = cfg.get("agent_id") or cfg.get("agent_config_id", "")
            type_name = cfg.get("agent_type_name", "")
            desc = cfg.get("description", "")
            h = health_map.get(aid, {})
            results.append({
                "agent_id": aid,
                "agent_type_name": type_name or h.get("agent_type_name", ""),
                "description": desc,
                "status": h.get("status", ""),
            })
        return results


@router.post("/agent-test/discover", response_model=DiscoverAgentsOut)
def discover_agents(body: DiscoverAgentsRequest):
    base = body.engine_base_url.rstrip("/")
    try:
        items = _fetch_engine_agents(base)
    except Exception as e:
        _log.warning("Agent discovery failed: %s", e)
        raise HTTPException(502, detail={
            "code": "DISCOVERY_FAILED",
            "message": f"无法连接 Agent Engine: {e}",
        }) from e

    agents = [
        DiscoveredAgent(
            agent_id=it["agent_id"],
            agent_type_name=it.get("agent_type_name", ""),
            description=it.get("description", ""),
            status=it.get("status", ""),
        )
        for it in items if it.get("agent_id")
    ]
    return DiscoverAgentsOut(engine_base_url=base, agents=agents)


@router.post("/agent-test/discover/import", response_model=list[AgentTargetOut])
def import_discovered_agents(body: DiscoverAgentsRequest, db: Session = Depends(get_db)):
    """发现并批量导入 Agent 为 AgentTarget（已存在则跳过）。

    每个 Agent 同时创建两种测试端点：
    - agent_engine 格式（/api/v1/agent/execute）
    - dispatch 格式（/v1/{project}/agents/{type}/conversations/{conv}）
    """
    base = body.engine_base_url.rstrip("/")
    execute_url = f"{base}/api/v1/agent/execute"

    try:
        items = _fetch_engine_agents(base)
    except Exception as e:
        raise HTTPException(502, detail={"code": "DISCOVERY_FAILED", "message": str(e)}) from e

    created: list[AgentTarget] = []
    for item in items:
        agent_id = item.get("agent_id", "")
        type_name = item.get("agent_type_name", "")
        if not agent_id:
            continue
        desc = item.get("description", "")

        # --- agent_engine 格式 ---
        existing_ae = db.execute(
            select(AgentTarget).where(
                AgentTarget.engine_agent_id == agent_id,
                AgentTarget.api_format == "agent_engine",
            )
        ).scalars().first()
        if not existing_ae:
            t = AgentTarget(
                name=f"{type_name or agent_id}",
                chat_url=execute_url,
                api_format="agent_engine",
                auth_type="none",
                engine_agent_id=agent_id,
                engine_agent_type=type_name,
                engine_base_url=base,
                agent_description=desc,
            )
            db.add(t)
            created.append(t)

        # --- dispatch 格式 ---
        existing_dp = db.execute(
            select(AgentTarget).where(
                AgentTarget.engine_agent_id == agent_id,
                AgentTarget.api_format == "dispatch",
            )
        ).scalars().first()
        if not existing_dp:
            t2 = AgentTarget(
                name=f"{type_name or agent_id} (dispatch)",
                chat_url=base,
                api_format="dispatch",
                auth_type="none",
                engine_agent_id=agent_id,
                engine_agent_type=type_name,
                engine_base_url=base,
                agent_description=desc,
                extra_config={
                    "project_id": "0",
                    "dispatch_agent_id": type_name or agent_id,
                },
            )
            db.add(t2)
            created.append(t2)

    db.commit()
    for t in created:
        db.refresh(t)
    return created


# ---------------------------------------------------------------------------
#  LLM 自动生成多轮对话测试场景
# ---------------------------------------------------------------------------

@router.post("/agent-test/targets/{target_id}/generate-scenario", response_model=ScenarioDetailOut)
def generate_scenario(
    target_id: str,
    body: GenerateScenarioRequest,
    db: Session = Depends(get_db),
):
    target = db.get(AgentTarget, target_id)
    if not target:
        raise _E404("Agent target 不存在")

    from app.services.llm_client import LLMClient
    llm = LLMClient()

    tools_desc = ""
    if target.agent_tools:
        tools_desc = "\n".join(
            f"- {t.get('name', t.get('function', '?'))}: {t.get('description', '')}"
            for t in target.agent_tools
        )
    elif target.tools_schema:
        tools_desc = "\n".join(
            f"- {t.get('function', {}).get('name', '?')}: {t.get('function', {}).get('description', '')}"
            for t in target.tools_schema
        )

    system = """你是 AI Agent 自动化测试专家。用户会描述一个 Agent 的能力和要测试的业务场景，你需要设计一个多轮对话测试剧本。

必须只输出一个 JSON 对象，不要 Markdown 围栏。

【输出结构】
{
  "scenario_name": "场景名称",
  "description": "场景描述",
  "initial_context": {"user_id": "test-user"},
  "turns": [
    {
      "turn_index": 0,
      "user_message": "用户消息",
      "expected_keywords": ["期望回复包含的关键词"],
      "forbidden_keywords": ["回复不应出现的关键词"],
      "assertions": [{"type": "response_not_empty"}]
    }
  ]
}

【断言类型】
- response_not_empty: 回复非空
- response_contains: 回复包含指定文本 (需要 value 字段)
- tool_called: 期望调用某工具 (需要 function 字段)
- no_tool_called: 不应调用工具
- response_matches_regex: 正则匹配 (需要 pattern 字段)

【设计原则】
1. 每轮对话要体现业务推进（意图逐步明确）
2. 测试正常流程和异常分支
3. 用 {{变量}} 引用前面轮次提取的数据
4. 关键词断言要务实，不要过于宽泛"""

    agent_info = f"Agent 名称: {target.name}\n"
    if target.agent_description:
        agent_info += f"Agent 描述: {target.agent_description}\n"
    if target.engine_agent_type:
        agent_info += f"Agent 类型: {target.engine_agent_type}\n"
    if tools_desc:
        agent_info += f"\n可用工具:\n{tools_desc}\n"
    if target.default_system_prompt:
        prompt_preview = target.default_system_prompt[:2000]
        agent_info += f"\n系统提示词 (前2000字):\n{prompt_preview}\n"

    focus = ""
    if body.focus_tools:
        focus = f"\n重点测试工具: {', '.join(body.focus_tools)}"

    user_prompt = f"""【Agent 信息】
{agent_info}
【测试场景】
{body.business_description}
{focus}
【要求】
- 设计 {body.max_turns} 轮对话
- 每轮 user_message 要自然、口语化
- 设计合理的断言验证 Agent 行为"""

    try:
        raw = llm.chat_json(system, user_prompt, use_json_object_mode=True)
        data = llm.parse_json_strict(raw)
    except Exception as e:
        raise HTTPException(502, detail={"code": "LLM_FAILED", "message": str(e)}) from e

    sc_name = data.get("scenario_name", body.business_description[:100])
    sc = ConversationScenario(
        agent_target_id=target.id,
        name=sc_name,
        description=data.get("description", ""),
        initial_context=data.get("initial_context"),
        max_turns=body.max_turns,
        tags=["auto-generated"],
    )
    db.add(sc)
    db.flush()

    for t in data.get("turns", []):
        db.add(ConversationTurn(
            scenario_id=sc.id,
            turn_index=t.get("turn_index", 0),
            user_message=t.get("user_message", ""),
            expected_intent=t.get("expected_intent"),
            expected_tool_calls=t.get("expected_tool_calls"),
            expected_keywords=t.get("expected_keywords"),
            forbidden_keywords=t.get("forbidden_keywords"),
            assertions=t.get("assertions", [{"type": "response_not_empty"}]),
            extract=t.get("extract"),
        ))
    db.commit()
    db.refresh(sc)
    return _scenario_detail(sc)


# ---------------------------------------------------------------------------
#  MockProfile CRUD
# ---------------------------------------------------------------------------


@router.post("/agent-test/scenarios/{scenario_id}/mock-profiles", response_model=MockProfileOut)
def create_mock_profile(scenario_id: str, body: MockProfileCreate, db: Session = Depends(get_db)):
    sc = db.get(ConversationScenario, scenario_id)
    if not sc:
        raise _E404("场景不存在")
    mp = MockProfile(
        scenario_id=scenario_id,
        name=body.name,
        description=body.description,
        profile_data=body.profile_data,
        is_active=body.is_active,
    )
    db.add(mp)
    if body.is_active:
        _deactivate_others(db, scenario_id, exclude_id=mp.id)
        sc.active_mock_profile_id = mp.id
    db.commit()
    db.refresh(mp)
    return mp


@router.get("/agent-test/scenarios/{scenario_id}/mock-profiles", response_model=list[MockProfileOut])
def list_mock_profiles(scenario_id: str, db: Session = Depends(get_db)):
    sc = db.get(ConversationScenario, scenario_id)
    if not sc:
        raise _E404("场景不存在")
    return db.scalars(
        select(MockProfile).where(MockProfile.scenario_id == scenario_id).order_by(MockProfile.created_at)
    ).all()


@router.put("/agent-test/mock-profiles/{profile_id}", response_model=MockProfileOut)
def update_mock_profile(profile_id: str, body: MockProfileUpdate, db: Session = Depends(get_db)):
    mp = db.get(MockProfile, profile_id)
    if not mp:
        raise _E404("MockProfile 不存在")
    for field in ("name", "description", "profile_data", "is_active"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(mp, field, val)
    if body.is_active is True:
        _deactivate_others(db, mp.scenario_id, exclude_id=mp.id)
        sc = db.get(ConversationScenario, mp.scenario_id)
        if sc:
            sc.active_mock_profile_id = mp.id
    db.commit()
    db.refresh(mp)
    return mp


@router.delete("/agent-test/mock-profiles/{profile_id}", status_code=204)
def delete_mock_profile(profile_id: str, db: Session = Depends(get_db)):
    mp = db.get(MockProfile, profile_id)
    if not mp:
        raise _E404("MockProfile 不存在")
    sc = db.get(ConversationScenario, mp.scenario_id)
    if sc and sc.active_mock_profile_id == mp.id:
        sc.active_mock_profile_id = None
    db.delete(mp)
    db.commit()


@router.post("/agent-test/mock-profiles/{profile_id}/activate", response_model=MockProfileOut)
def activate_mock_profile(profile_id: str, db: Session = Depends(get_db)):
    mp = db.get(MockProfile, profile_id)
    if not mp:
        raise _E404("MockProfile 不存在")
    _deactivate_others(db, mp.scenario_id, exclude_id=mp.id)
    mp.is_active = True
    sc = db.get(ConversationScenario, mp.scenario_id)
    if sc:
        sc.active_mock_profile_id = mp.id
    db.commit()
    db.refresh(mp)
    return mp


@router.get("/agent-test/mock-profiles/{profile_id}/workflow-preview")
def get_mock_workflow_preview(profile_id: str, db: Session = Depends(get_db)):
    """工作流 Mock 合并后的理财/余额/转账/购买数据快照（供前端展示）。"""
    mp = db.get(MockProfile, profile_id)
    if not mp:
        raise _E404("MockProfile 不存在")
    data = compute_mock_preview(mp.profile_data or {})
    return {"profile_id": profile_id, **data}


def _deactivate_others(db: Session, scenario_id: str, *, exclude_id: str) -> None:
    others = db.scalars(
        select(MockProfile).where(
            MockProfile.scenario_id == scenario_id,
            MockProfile.id != exclude_id,
            MockProfile.is_active == True,  # noqa: E712
        )
    ).all()
    for o in others:
        o.is_active = False


# ---------------------------------------------------------------------------
#  Mock 分支生成器 Skills
# ---------------------------------------------------------------------------


@router.get("/agent-test/mock-branch-skills", response_model=list[MockBranchSkillOut])
def list_mock_branch_skills(db: Session = Depends(get_db)):
    """
    返回用于 LLM 一键生成测试分支的可选 Skill（系统提示词）。
    若数据库为空则自动创建默认 Skill。
    """
    from app.services.mock_branch_designer import ensure_default_mock_branch_skill

    ensure_default_mock_branch_skill(db)
    return (
        db.scalars(select(MockBranchSkill).order_by(MockBranchSkill.created_at.desc())).all()
    )


@router.post("/agent-test/mock-branch-skills", response_model=MockBranchSkillOut)
def create_mock_branch_skill(body: MockBranchSkillCreate, db: Session = Depends(get_db)):
    """
    创建一个用于 LLM 一键生成测试分支的系统提示词 Skill。
    """
    existing = db.query(MockBranchSkill).filter(MockBranchSkill.name == body.name).first()
    if existing:
        raise HTTPException(409, detail={"code": "DUPLICATE", "message": "Skill 名称已存在"})

    skill = MockBranchSkill(
        name=body.name.strip(),
        description=body.description,
        system_prompt=body.system_prompt,
        enabled=bool(body.enabled),
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@router.put("/agent-test/mock-branch-skills/{skill_id}", response_model=MockBranchSkillOut)
def update_mock_branch_skill(skill_id: str, body: MockBranchSkillUpdate, db: Session = Depends(get_db)):
    skill = db.get(MockBranchSkill, skill_id)
    if not skill:
        raise _E404("Skill 不存在")

    for field in ("name", "description", "system_prompt", "enabled"):
        val = getattr(body, field, None)
        # Pydantic 里未传的字段值为 None；这里直接用 val is not None 判断
        if val is not None:
            setattr(skill, field, val)

    if body.name is not None:
        skill.name = body.name.strip()

    db.commit()
    db.refresh(skill)
    return skill


@router.delete("/agent-test/mock-branch-skills/{skill_id}", status_code=204)
def delete_mock_branch_skill(skill_id: str, db: Session = Depends(get_db)):
    skill = db.get(MockBranchSkill, skill_id)
    if not skill:
        raise _E404("Skill 不存在")
    db.delete(skill)
    db.commit()


# ---------------------------------------------------------------------------
#  LLM 分支生成
# ---------------------------------------------------------------------------


@router.post("/agent-test/scenarios/{scenario_id}/generate-branches")
def generate_branches_endpoint(
    scenario_id: str,
    body: GenerateBranchesRequest,
    db: Session = Depends(get_db),
):
    from app.services.mock_branch_designer import generate_branches
    from app.services.mock_branch_designer import ensure_default_mock_branch_skill

    sc = db.get(ConversationScenario, scenario_id)
    if not sc:
        raise _E404("场景不存在")

    if body.skill_id:
        skill = db.get(MockBranchSkill, body.skill_id)
        if not skill or not skill.enabled:
            raise _E404("Skill 不存在或已禁用")
        system_prompt = skill.system_prompt
    else:
        system_prompt = ensure_default_mock_branch_skill(db).system_prompt

    try:
        result = generate_branches(
            db, sc,
            business_description=body.business_description,
            max_branches=body.max_branches,
            max_turns_per_branch=body.max_turns_per_branch,
            system_prompt=system_prompt,
        )
    except Exception as e:
        raise HTTPException(502, detail={"code": "LLM_FAILED", "message": str(e)}) from e
    return result
