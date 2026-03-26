"""Mock 数据平台：管理场景/数据表/API规则 + Mock 服务器。"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.mock_schemas import (
    MockApiRuleCreate,
    MockApiRuleOut,
    MockApiRuleUpdate,
    MockDataTableCreate,
    MockDataTableOut,
    MockDataTableUpdate,
    MockEndpointMappingCreate,
    MockEndpointMappingOut,
    MockEndpointMappingUpdate,
    MockLLMGenerateOut,
    MockLLMGenerateRequest,
    MockScenarioCreate,
    MockScenarioDetailOut,
    MockScenarioOut,
    MockScenarioResetOut,
    MockScenarioStateUpdateOut,
    MockScenarioStateUpdateRequest,
)
from app.db.models import (
    MockApiRule,
    MockDataTable,
    MockDataTableRuntimeState,
    MockEndpointMapping,
    MockScenario,
)
from app.db.session import get_db
from app.services.mock_llm_designer import MockLLMDesigner
from app.utils.errors import AppError, ErrorCode
from app.utils.http_exc import http_exception_from_app_error

router = APIRouter()

_404_scenario = {"code": ErrorCode.NOT_FOUND.value, "message": "场景不存在"}
_404_table = {"code": ErrorCode.NOT_FOUND.value, "message": "数据表不存在"}
_404_rule = {"code": ErrorCode.NOT_FOUND.value, "message": "API 规则不存在"}


# ===== MockScenario CRUD =====


@router.post("/mock/scenarios", response_model=MockScenarioOut)
def create_scenario(body: MockScenarioCreate, db: Session = Depends(get_db)):
    s = MockScenario(name=body.name, description=body.description)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/mock/scenarios", response_model=list[MockScenarioOut])
def list_scenarios(db: Session = Depends(get_db)):
    return list(
        db.execute(select(MockScenario).order_by(MockScenario.updated_at.desc())).scalars().all()
    )


@router.get("/mock/scenarios/{scenario_id}", response_model=MockScenarioDetailOut)
def get_scenario(scenario_id: str, db: Session = Depends(get_db)):
    s = db.get(MockScenario, scenario_id)
    if not s:
        raise HTTPException(404, detail=_404_scenario)
    tables = list(
        db.execute(
            select(MockDataTable).where(MockDataTable.scenario_id == scenario_id)
        ).scalars().all()
    )
    table_ids = [t.id for t in tables]
    runtime_rows_by_table_id: dict[str, list[Any]] = {}
    if table_ids:
        runtime_rows = list(
            db.execute(
                select(MockDataTableRuntimeState).where(
                    MockDataTableRuntimeState.table_id.in_(table_ids)
                )
            ).scalars().all()
        )
        runtime_rows_by_table_id = {r.table_id: r.rows_json for r in runtime_rows}
    rules = list(
        db.execute(
            select(MockApiRule).where(MockApiRule.scenario_id == scenario_id)
        ).scalars().all()
    )
    tables_out: list[MockDataTableOut] = []
    for t in tables:
        t_out = MockDataTableOut.model_validate(t)
        if t.id in runtime_rows_by_table_id:
            t_out.rows_json = runtime_rows_by_table_id[t.id]
        tables_out.append(t_out)

    return MockScenarioDetailOut(
        id=s.id,
        name=s.name,
        description=s.description,
        created_at=s.created_at,
        updated_at=s.updated_at,
        tables=tables_out,
        api_rules=[MockApiRuleOut.model_validate(r) for r in rules],
    )


@router.delete("/mock/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str, db: Session = Depends(get_db)):
    s = db.get(MockScenario, scenario_id)
    if not s:
        raise HTTPException(404, detail=_404_scenario)

    # 先清理运行时 overlay，避免外键约束失败（mock_data_table -> runtime_state）
    table_ids = list(
        db.execute(select(MockDataTable.id).where(MockDataTable.scenario_id == scenario_id)).scalars().all()
    )
    if table_ids:
        db.execute(delete(MockDataTableRuntimeState).where(MockDataTableRuntimeState.table_id.in_(table_ids)))

    # 再清理映射（mock_endpoint_mapping -> mock_data_table / mock_scenario 外键）
    db.execute(delete(MockEndpointMapping).where(MockEndpointMapping.scenario_id == scenario_id))

    db.delete(s)
    db.commit()


# ===== MockDataTable CRUD =====


@router.post("/mock/scenarios/{scenario_id}/tables", response_model=MockDataTableOut)
def create_table(scenario_id: str, body: MockDataTableCreate, db: Session = Depends(get_db)):
    if not db.get(MockScenario, scenario_id):
        raise HTTPException(404, detail=_404_scenario)
    schema_dicts = [c.model_dump() for c in body.schema_json]
    tbl = MockDataTable(
        scenario_id=scenario_id,
        table_name=body.table_name,
        description=body.description,
        schema_json=schema_dicts,
        rows_json=body.rows_json,
        reset_rows_json=body.rows_json,
    )
    db.add(tbl)
    db.commit()
    db.refresh(tbl)
    return tbl


@router.get("/mock/scenarios/{scenario_id}/tables", response_model=list[MockDataTableOut])
def list_tables(scenario_id: str, db: Session = Depends(get_db)):
    if not db.get(MockScenario, scenario_id):
        raise HTTPException(404, detail=_404_scenario)
    tables = list(
        db.execute(
            select(MockDataTable).where(MockDataTable.scenario_id == scenario_id)
        ).scalars().all()
    )
    table_ids = [t.id for t in tables]
    runtime_rows_by_table_id: dict[str, list[Any]] = {}
    if table_ids:
        runtime_rows = list(
            db.execute(
                select(MockDataTableRuntimeState).where(
                    MockDataTableRuntimeState.table_id.in_(table_ids)
                )
            ).scalars().all()
        )
        runtime_rows_by_table_id = {r.table_id: r.rows_json for r in runtime_rows}

    tables_out: list[MockDataTableOut] = []
    for t in tables:
        t_out = MockDataTableOut.model_validate(t)
        if t.id in runtime_rows_by_table_id:
            t_out.rows_json = runtime_rows_by_table_id[t.id]
        tables_out.append(t_out)
    return tables_out


@router.put("/mock/tables/{table_id}", response_model=MockDataTableOut)
def update_table(table_id: str, body: MockDataTableUpdate, db: Session = Depends(get_db)):
    tbl = db.get(MockDataTable, table_id)
    if not tbl:
        raise HTTPException(404, detail=_404_table)
    if body.table_name is not None:
        tbl.table_name = body.table_name
    if body.description is not None:
        tbl.description = body.description
    if body.schema_json is not None:
        tbl.schema_json = [c.model_dump() for c in body.schema_json]
    if body.rows_json is not None:
        tbl.rows_json = body.rows_json
        # 设计侧的 rows_json 变更视作“最初版本”更新；reset 回到该快照
        tbl.reset_rows_json = body.rows_json
    db.commit()
    db.refresh(tbl)
    return tbl


@router.delete("/mock/tables/{table_id}", status_code=204)
def delete_table(table_id: str, db: Session = Depends(get_db)):
    tbl = db.get(MockDataTable, table_id)
    if not tbl:
        raise HTTPException(404, detail=_404_table)

    # 先清理运行时 overlay，避免外键约束失败
    db.execute(delete(MockDataTableRuntimeState).where(MockDataTableRuntimeState.table_id == table_id))

    # 清理映射中引用该表的记录
    db.execute(delete(MockEndpointMapping).where(MockEndpointMapping.table_id == table_id))
    db.delete(tbl)
    db.commit()


# ===== MockApiRule CRUD =====


@router.post("/mock/scenarios/{scenario_id}/rules", response_model=MockApiRuleOut)
def create_rule(scenario_id: str, body: MockApiRuleCreate, db: Session = Depends(get_db)):
    if not db.get(MockScenario, scenario_id):
        raise HTTPException(404, detail=_404_scenario)
    if body.table_id and not db.get(MockDataTable, body.table_id):
        raise HTTPException(400, detail={"code": "VALIDATION_ERROR", "message": "关联的数据表不存在"})
    rule = MockApiRule(
        scenario_id=scenario_id,
        table_id=body.table_id,
        method=body.method,
        path=body.path,
        description=body.description,
        action=body.action,
        key_field=body.key_field,
        response_template_json=body.response_template_json,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/mock/scenarios/{scenario_id}/rules", response_model=list[MockApiRuleOut])
def list_rules(scenario_id: str, db: Session = Depends(get_db)):
    if not db.get(MockScenario, scenario_id):
        raise HTTPException(404, detail=_404_scenario)
    return list(
        db.execute(
            select(MockApiRule).where(MockApiRule.scenario_id == scenario_id)
        ).scalars().all()
    )


@router.put("/mock/rules/{rule_id}", response_model=MockApiRuleOut)
def update_rule(rule_id: str, body: MockApiRuleUpdate, db: Session = Depends(get_db)):
    rule = db.get(MockApiRule, rule_id)
    if not rule:
        raise HTTPException(404, detail=_404_rule)
    for field in ("table_id", "method", "path", "description", "action", "key_field", "response_template_json"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(rule, field, val)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/mock/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.get(MockApiRule, rule_id)
    if not rule:
        raise HTTPException(404, detail=_404_rule)
    db.delete(rule)
    db.commit()


# ===== Endpoint Mapping CRUD =====

_404_mapping = {"code": ErrorCode.NOT_FOUND.value, "message": "映射不存在"}


@router.post("/mock/scenarios/{scenario_id}/mappings", response_model=MockEndpointMappingOut)
def create_mapping(scenario_id: str, body: MockEndpointMappingCreate, db: Session = Depends(get_db)):
    if not db.get(MockScenario, scenario_id):
        raise HTTPException(404, detail=_404_scenario)

    if body.table_id:
        tbl = db.get(MockDataTable, body.table_id)
        if not tbl or tbl.scenario_id != scenario_id:
            raise HTTPException(
                400,
                detail={"code": ErrorCode.VALIDATION_ERROR.value, "message": "关联的数据表不存在或不属于该场景"},
            )

    m = MockEndpointMapping(
        scenario_id=scenario_id,
        method=body.method.upper(),
        path=body.path,
        action=body.action,
        table_id=body.table_id,
        key_field=body.key_field,
        required_body_fields=body.required_body_fields or [],
        response_template_json=body.response_template_json,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.get("/mock/scenarios/{scenario_id}/mappings", response_model=list[MockEndpointMappingOut])
def list_mappings(scenario_id: str, db: Session = Depends(get_db)):
    if not db.get(MockScenario, scenario_id):
        raise HTTPException(404, detail=_404_scenario)
    return list(
        db.execute(
            select(MockEndpointMapping).where(MockEndpointMapping.scenario_id == scenario_id).order_by(
                MockEndpointMapping.updated_at.desc()
            )
        ).scalars().all()
    )


@router.put("/mock/mappings/{mapping_id}", response_model=MockEndpointMappingOut)
def update_mapping(mapping_id: str, body: MockEndpointMappingUpdate, db: Session = Depends(get_db)):
    m = db.get(MockEndpointMapping, mapping_id)
    if not m:
        raise HTTPException(404, detail=_404_mapping)

    if body.table_id is not None:
        if body.table_id:
            tbl = db.get(MockDataTable, body.table_id)
            if not tbl or tbl.scenario_id != m.scenario_id:
                raise HTTPException(
                    400,
                    detail={"code": ErrorCode.VALIDATION_ERROR.value, "message": "关联的数据表不存在或不属于该场景"},
                )
            m.table_id = body.table_id
        else:
            m.table_id = None

    for field in (
        "method",
        "path",
        "action",
        "key_field",
        "required_body_fields",
        "response_template_json",
    ):
        val = getattr(body, field, None)
        if val is None:
            continue
        if field == "method":
            setattr(m, field, (val or "").upper())
        else:
            setattr(m, field, val)

    db.commit()
    db.refresh(m)
    return m


@router.delete("/mock/mappings/{mapping_id}", status_code=204)
def delete_mapping(mapping_id: str, db: Session = Depends(get_db)):
    m = db.get(MockEndpointMapping, mapping_id)
    if not m:
        raise HTTPException(404, detail=_404_mapping)
    db.delete(m)
    db.commit()


# ===== Mock 运行时数据：state 更新 / reset =====


@router.patch("/mock/scenarios/{scenario_id}/state", response_model=MockScenarioStateUpdateOut)
def update_scenario_state(
    scenario_id: str,
    body: MockScenarioStateUpdateRequest,
    db: Session = Depends(get_db),
):
    scenario = db.get(MockScenario, scenario_id)
    if not scenario:
        raise HTTPException(404, detail=_404_scenario)

    if not body.tables:
        return MockScenarioStateUpdateOut(scenario_id=scenario_id, updated_tables=[])

    updated: list[MockDataTable] = []
    updated_rows_by_table_id: dict[str, list[Any]] = {}

    for t in body.tables:
        tbl: MockDataTable | None = None

        if t.table_id:
            tbl = db.get(MockDataTable, t.table_id)
            if not tbl or tbl.scenario_id != scenario_id:
                raise HTTPException(
                    400,
                    detail={"code": ErrorCode.VALIDATION_ERROR.value, "message": "table_id 不存在或不属于该场景"},
                )
        elif t.table_name:
            tbl = (
                db.execute(
                    select(MockDataTable).where(
                        MockDataTable.scenario_id == scenario_id,
                        MockDataTable.table_name == t.table_name,
                    )
                )
                .scalars()
                .first()
            )
            if not tbl:
                raise HTTPException(
                    400,
                    detail={"code": ErrorCode.VALIDATION_ERROR.value, "message": "table_name 不存在或不属于该场景"},
                )
        else:
            raise HTTPException(
                400,
                detail={"code": ErrorCode.VALIDATION_ERROR.value, "message": "每项 tables 需提供 table_id 或 table_name（二选一）"},
            )

        runtime_state = db.get(MockDataTableRuntimeState, tbl.id)
        new_rows = list(t.rows_json or [])
        if not runtime_state:
            runtime_state = MockDataTableRuntimeState(table_id=tbl.id, rows_json=new_rows)
            db.add(runtime_state)
        else:
            runtime_state.rows_json = new_rows

        updated.append(tbl)
        updated_rows_by_table_id[tbl.id] = new_rows

    db.commit()
    for u in updated:
        db.refresh(u)

    updated_out: list[MockDataTableOut] = []
    for tbl in updated:
        t_out = MockDataTableOut.model_validate(tbl)
        # state 接口只覆盖运行时数据：返回值展示的是运行时 rows_json
        t_out.rows_json = updated_rows_by_table_id.get(tbl.id, tbl.rows_json or [])
        updated_out.append(t_out)

    return MockScenarioStateUpdateOut(scenario_id=scenario_id, updated_tables=updated_out)


@router.post("/mock/scenarios/{scenario_id}/reset", response_model=MockScenarioResetOut)
def reset_scenario_data(scenario_id: str, db: Session = Depends(get_db)):
    scenario = db.get(MockScenario, scenario_id)
    if not scenario:
        raise HTTPException(404, detail=_404_scenario)

    tables = list(db.execute(select(MockDataTable).where(MockDataTable.scenario_id == scenario_id)).scalars().all())

    reset_count = 0
    for tbl in tables:
        reset_val = tbl.reset_rows_json
        if reset_val is None:
            # 旧库容错：如果列尚未回填，则用当前 rows_json 作为“最初版本”
            reset_val = tbl.rows_json

        runtime_state = db.get(MockDataTableRuntimeState, tbl.id)
        if not runtime_state:
            runtime_state = MockDataTableRuntimeState(table_id=tbl.id, rows_json=list(reset_val or []))
            db.add(runtime_state)
        else:
            runtime_state.rows_json = list(reset_val or [])

        reset_count += 1

    db.commit()
    return MockScenarioResetOut(scenario_id=scenario_id, reset_tables=reset_count)


# ===== LLM 自动生成 =====


@router.post("/mock/scenarios/generate", response_model=MockLLMGenerateOut)
def llm_generate_scenario(body: MockLLMGenerateRequest, db: Session = Depends(get_db)):
    designer = MockLLMDesigner()
    try:
        scenario, tc, rc = designer.generate_scenario(
            db,
            body.business_description,
            table_count_hint=body.table_count_hint,
            rows_per_table_hint=body.rows_per_table_hint,
        )
    except AppError as e:
        raise http_exception_from_app_error(e) from e
    return MockLLMGenerateOut(
        scenario=MockScenarioOut.model_validate(scenario),
        tables_created=tc,
        rules_created=rc,
    )


# ===== Mock 服务器（动态路由） =====


def _path_pattern_to_regex(path_pattern: str) -> re.Pattern[str]:
    """将 /api/products/{id} 转换为正则表达式，提取路径参数。"""
    parts = path_pattern.strip("/").split("/")
    regex_parts: list[str] = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            param_name = part[1:-1]
            regex_parts.append(f"(?P<{param_name}>[^/]+)")
        else:
            regex_parts.append(re.escape(part))
    return re.compile("^" + "/".join(regex_parts) + "$")


def _match_rule(
    rules: list[MockApiRule], method: str, sub_path: str
) -> tuple[MockApiRule, dict[str, str]] | None:
    """从规则列表中找到匹配请求的规则。"""
    sub_path = sub_path.strip("/")
    for rule in rules:
        if rule.method.upper() != method.upper():
            continue
        rule_path = rule.path.strip("/")
        pattern = _path_pattern_to_regex(rule_path)
        m = pattern.match(sub_path)
        if m:
            return rule, m.groupdict()
    return None


def _execute_action(
    rule: MockApiRule,
    path_params: dict[str, str],
    body: Any,
    db: Session,
) -> tuple[int, Any]:
    """根据 action 类型对数据表执行 CRUD 操作，返回 (status_code, response_body)。"""
    if not rule.table_id:
        if rule.response_template_json:
            return 200, rule.response_template_json
        return 200, {"message": "ok"}

    tbl = db.get(MockDataTable, rule.table_id)
    if not tbl:
        return 404, {"error": "关联数据表不存在"}

    runtime_state = db.get(MockDataTableRuntimeState, tbl.id)
    # 运行时覆盖优先：避免直接修改设计侧 `MockDataTable.rows_json`。
    base_rows: list[dict[str, Any]] = list(tbl.rows_json or [])
    rows: list[dict[str, Any]] = list(runtime_state.rows_json or []) if runtime_state else base_rows

    if rule.action == "list":
        return 200, {"data": rows, "total": len(rows)}

    if rule.action == "get_by_id":
        key = rule.key_field or "id"
        lookup = path_params.get(key) or path_params.get("id") or ""
        for row in rows:
            if str(row.get(key, "")) == lookup:
                return 200, {"data": row}
        return 404, {"error": f"{key}={lookup} 未找到"}

    if rule.action == "create":
        if not isinstance(body, dict):
            return 400, {"error": "请求体必须是 JSON 对象"}
        key = rule.key_field or "id"
        if key not in body:
            body[key] = str(uuid.uuid4())[:8]
        rows.append(body)
        if not runtime_state:
            runtime_state = MockDataTableRuntimeState(table_id=tbl.id, rows_json=list(rows))
            db.add(runtime_state)
        else:
            runtime_state.rows_json = list(rows)
        db.commit()
        return 201, {"data": body}

    if rule.action == "update":
        key = rule.key_field or "id"
        lookup = path_params.get(key) or path_params.get("id") or ""
        if not isinstance(body, dict):
            return 400, {"error": "请求体必须是 JSON 对象"}
        for i, row in enumerate(rows):
            if str(row.get(key, "")) == lookup:
                rows[i] = {**row, **body}
                if not runtime_state:
                    runtime_state = MockDataTableRuntimeState(table_id=tbl.id, rows_json=list(rows))
                    db.add(runtime_state)
                else:
                    runtime_state.rows_json = list(rows)
                db.commit()
                return 200, {"data": rows[i]}
        return 404, {"error": f"{key}={lookup} 未找到"}

    if rule.action == "delete":
        key = rule.key_field or "id"
        lookup = path_params.get(key) or path_params.get("id") or ""
        new_rows = [r for r in rows if str(r.get(key, "")) != lookup]
        if len(new_rows) == len(rows):
            return 404, {"error": f"{key}={lookup} 未找到"}
        if not runtime_state:
            runtime_state = MockDataTableRuntimeState(table_id=tbl.id, rows_json=list(new_rows))
            db.add(runtime_state)
        else:
            runtime_state.rows_json = list(new_rows)
        db.commit()
        return 200, {"message": "已删除", "deleted_key": lookup}

    if rule.response_template_json:
        return 200, rule.response_template_json
    return 200, {"data": rows}


# ---------------------------------------------------------------------------
#  Mock Server Router - 独立 APIRouter 挂载到 /mock-server/{scenario_id}
# ---------------------------------------------------------------------------

mock_server_router = APIRouter()


@mock_server_router.api_route(
    "/mock-server/{scenario_id}/{sub_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def mock_server_handler(
    scenario_id: str,
    sub_path: str,
    request: Request,
    db: Session = Depends(get_db),
):
    scenario = db.get(MockScenario, scenario_id)
    if not scenario:
        return JSONResponse(status_code=404, content={"error": "Mock 场景不存在"})

    rules = list(
        db.execute(
            select(MockApiRule).where(MockApiRule.scenario_id == scenario_id)
        ).scalars().all()
    )

    match = _match_rule(rules, request.method, sub_path)
    if not match:
        return JSONResponse(
            status_code=404,
            content={
                "error": "未匹配到 Mock API 规则",
                "method": request.method,
                "path": f"/{sub_path}",
            },
        )

    rule, path_params = match

    body: Any = None
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.json()
        except Exception:
            body = None

    status, resp = _execute_action(rule, path_params, body, db)
    return JSONResponse(status_code=status, content=resp)


# ---------------------------------------------------------------------------
#  Mock Mapped Server Router - 映射到类似生产环境的外部 URL
# ---------------------------------------------------------------------------

mock_mapped_server_router = APIRouter()


def _match_endpoint_mapping(
    mappings: list[MockEndpointMapping],
    method: str,
    sub_path: str,
) -> tuple[MockEndpointMapping, dict[str, str]] | None:
    sub_path = sub_path.strip("/")
    for m in mappings:
        if m.method.upper() != method.upper():
            continue
        m_path = m.path.strip("/")
        pattern = _path_pattern_to_regex(m_path)
        mm = pattern.match(sub_path)
        if mm:
            return m, mm.groupdict()
    return None


def _execute_mapping_action(
    mapping: MockEndpointMapping,
    path_params: dict[str, str],
    body: Any,
    db: Session,
) -> tuple[int, Any]:
    """根据 EndpointMapping.action 执行读写运行时 overlay，返回 (status_code, response_body)。"""
    if not mapping.table_id:
        if mapping.response_template_json is not None:
            return 200, mapping.response_template_json
        return 200, {"message": "ok"}

    tbl = db.get(MockDataTable, mapping.table_id)
    if not tbl:
        return 404, {"error": "关联数据表不存在"}

    runtime_state = db.get(MockDataTableRuntimeState, tbl.id)
    base_rows: list[dict[str, Any]] = list(tbl.rows_json or [])
    rows: list[dict[str, Any]] = list(runtime_state.rows_json or []) if runtime_state else base_rows

    # required_body_fields 只对 create/update/custom 进行校验
    if mapping.action in ("create", "update", "custom") and mapping.required_body_fields:
        required = list(mapping.required_body_fields or [])
        if not isinstance(body, dict):
            return 400, {"error": "请求体必须是 JSON 对象", "required_body_fields": required}
        missing = [f for f in required if f not in body]
        if missing:
            return 400, {"error": "请求体缺少必填字段", "missing_fields": missing}

    if mapping.action == "list":
        return 200, {"data": rows, "total": len(rows)}

    if mapping.action == "get_by_id":
        key = mapping.key_field or "id"
        lookup = path_params.get(key) or path_params.get("id") or ""
        for row in rows:
            if str(row.get(key, "")) == lookup:
                return 200, {"data": row}
        return 404, {"error": f"{key}={lookup} 未找到"}

    if mapping.action == "create":
        if not isinstance(body, dict):
            return 400, {"error": "请求体必须是 JSON 对象"}
        key = mapping.key_field or "id"
        if key not in body:
            body[key] = str(uuid.uuid4())[:8]
        rows.append(body)
        if not runtime_state:
            runtime_state = MockDataTableRuntimeState(table_id=tbl.id, rows_json=list(rows))
            db.add(runtime_state)
        else:
            runtime_state.rows_json = list(rows)
        db.commit()
        return 201, {"data": body}

    if mapping.action == "update":
        if not isinstance(body, dict):
            return 400, {"error": "请求体必须是 JSON 对象"}
        key = mapping.key_field or "id"
        lookup = path_params.get(key) or path_params.get("id") or ""
        for i, row in enumerate(rows):
            if str(row.get(key, "")) == lookup:
                rows[i] = {**row, **body}
                if not runtime_state:
                    runtime_state = MockDataTableRuntimeState(table_id=tbl.id, rows_json=list(rows))
                    db.add(runtime_state)
                else:
                    runtime_state.rows_json = list(rows)
                db.commit()
                return 200, {"data": rows[i]}
        return 404, {"error": f"{key}={lookup} 未找到"}

    if mapping.action == "delete":
        key = mapping.key_field or "id"
        lookup = path_params.get(key) or path_params.get("id") or ""
        new_rows = [r for r in rows if str(r.get(key, "")) != lookup]
        if len(new_rows) == len(rows):
            return 404, {"error": f"{key}={lookup} 未找到"}
        if not runtime_state:
            runtime_state = MockDataTableRuntimeState(table_id=tbl.id, rows_json=list(new_rows))
            db.add(runtime_state)
        else:
            runtime_state.rows_json = list(new_rows)
        db.commit()
        return 200, {"message": "已删除", "deleted_key": lookup}

    if mapping.action == "custom":
        # custom：如果配置了 response_template_json，就直接返回；否则给一个缺省 ok
        if mapping.response_template_json is not None:
            return 200, mapping.response_template_json
        return 200, {"message": "ok"}

    return 400, {"error": f"不支持的 action: {mapping.action}"}


@mock_mapped_server_router.api_route(
    "/mock-mapped/{scenario_id}/{sub_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def mock_mapped_server_handler(
    scenario_id: str,
    sub_path: str,
    request: Request,
    db: Session = Depends(get_db),
):
    scenario = db.get(MockScenario, scenario_id)
    if not scenario:
        return JSONResponse(status_code=404, content={"error": "Mock 场景不存在"})

    mappings = list(
        db.execute(
            select(MockEndpointMapping).where(MockEndpointMapping.scenario_id == scenario_id)
        ).scalars().all()
    )

    match = _match_endpoint_mapping(mappings, request.method, sub_path)
    if not match:
        return JSONResponse(
            status_code=404,
            content={
                "error": "未匹配到 Mock 映射 API",
                "method": request.method,
                "path": f"/{sub_path}",
            },
        )

    mapping, path_params = match

    body: Any = None
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.json()
        except Exception:
            body = None
    elif request.method == "DELETE":
        # DELETE 通常没 body：允许但不强制
        try:
            body = await request.json()
        except Exception:
            body = None

    status, resp = _execute_mapping_action(mapping, path_params, body, db)
    return JSONResponse(status_code=status, content=resp)
