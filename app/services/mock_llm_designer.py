"""调用 LLM 自动生成 Mock 业务数据表、示例数据和 API 规则。"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import MockApiRule, MockDataTable, MockScenario
from app.services.llm_client import LLMClient
from app.utils.errors import AppError, ErrorCode

_log = logging.getLogger(__name__)

SYSTEM_MOCK_DESIGN = """你是 Mock 数据平台设计专家。用户会描述一个业务场景，你需要根据描述生成完整的 Mock 数据方案。

你必须只输出一个 JSON 对象，不要 Markdown 代码围栏，不要前后说明文字。

【输出结构必须严格符合下列契约】
{
  "scenario_name": "场景名称（简短）",
  "scenario_description": "场景描述（1-3句话）",
  "tables": [
    {
      "table_name": "英文表名（snake_case）",
      "description": "表的中文描述",
      "schema": [
        {"name": "字段名", "type": "string|number|boolean", "description": "字段描述"}
      ],
      "rows": [
        {"字段名": "示例值", ...}
      ]
    }
  ],
  "api_rules": [
    {
      "method": "GET|POST|PUT|DELETE",
      "path": "/api/路径（可含 {id} 占位符）",
      "description": "接口描述",
      "action": "list|get_by_id|create|update|delete",
      "table_name": "关联的表名",
      "key_field": "主键字段名（get_by_id/update/delete 时必填）"
    }
  ]
}

【要求】
1. 数据表设计要贴合业务场景，字段命名使用 snake_case
2. 每张表至少包含一个可作为主键的唯一标识字段（如 id, product_id 等）
3. 示例数据要真实可信、多样化（中文内容）
4. API 规则要覆盖常见的 CRUD 操作
5. path 中的路径参数用 {param_name} 表示
6. 所有数据值必须是字符串、数字或布尔值，不要嵌套对象"""


def _build_user_prompt(
    business_description: str,
    *,
    table_count_hint: int = 0,
    rows_per_table_hint: int = 5,
) -> str:
    parts = [f"【业务场景描述】\n{business_description}"]
    if table_count_hint > 0:
        parts.append(f"请设计约 {table_count_hint} 张数据表。")
    parts.append(f"每张表请提供约 {rows_per_table_hint} 行示例数据。")
    parts.append("请根据以上业务场景，设计完整的 Mock 数据方案（含数据表、示例数据和 API 规则）。")
    return "\n\n".join(parts)


class MockLLMDesigner:
    def __init__(self, llm: LLMClient | None = None):
        self._llm = llm or LLMClient()

    def generate_scenario(
        self,
        db: Session,
        business_description: str,
        *,
        table_count_hint: int = 0,
        rows_per_table_hint: int = 5,
    ) -> tuple[MockScenario, int, int]:
        """
        根据业务描述调用 LLM 生成 Mock 场景。
        返回 (scenario, tables_created, rules_created)。
        """
        user_prompt = _build_user_prompt(
            business_description,
            table_count_hint=table_count_hint,
            rows_per_table_hint=rows_per_table_hint,
        )

        raw = self._llm.chat_json(SYSTEM_MOCK_DESIGN, user_prompt, use_json_object_mode=True)
        try:
            data = self._llm.parse_json_strict(raw)
        except AppError:
            raise

        if not isinstance(data, dict):
            raise AppError(ErrorCode.LLM_INVALID_JSON, "LLM 返回非 JSON 对象", retryable=True)

        return self._persist(db, data)

    def _persist(
        self,
        db: Session,
        data: dict[str, Any],
    ) -> tuple[MockScenario, int, int]:
        scenario = MockScenario(
            name=str(data.get("scenario_name", "未命名场景"))[:255],
            description=str(data.get("scenario_description", ""))[:4000] or None,
        )
        db.add(scenario)
        db.flush()

        table_name_to_id: dict[str, str] = {}
        tables_created = 0

        for t in data.get("tables", []):
            if not isinstance(t, dict):
                continue
            tname = str(t.get("table_name", f"table_{tables_created + 1}"))[:255]
            schema = t.get("schema", [])
            if not isinstance(schema, list):
                schema = []
            rows = t.get("rows", [])
            if not isinstance(rows, list):
                rows = []

            tbl = MockDataTable(
                scenario_id=scenario.id,
                table_name=tname,
                description=str(t.get("description", ""))[:4000] or None,
                schema_json=schema,
                rows_json=rows,
                reset_rows_json=rows,
            )
            db.add(tbl)
            db.flush()
            table_name_to_id[tname] = tbl.id
            tables_created += 1

        rules_created = 0
        for r in data.get("api_rules", []):
            if not isinstance(r, dict):
                continue
            method = str(r.get("method", "GET")).upper()
            if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                method = "GET"
            path = str(r.get("path", "/"))[:2048]
            action = str(r.get("action", "list"))
            if action not in ("list", "get_by_id", "create", "update", "delete", "custom"):
                action = "custom"

            ref_table = str(r.get("table_name", ""))
            table_id = table_name_to_id.get(ref_table)

            rule = MockApiRule(
                scenario_id=scenario.id,
                table_id=table_id,
                method=method,
                path=path,
                description=str(r.get("description", ""))[:512] or None,
                action=action,
                key_field=str(r.get("key_field", "")) or None,
            )
            db.add(rule)
            rules_created += 1

        db.commit()
        db.refresh(scenario)
        return scenario, tables_created, rules_created
