# Mock 数据平台接口文档

> 说明：本项目的 Mock 分为两部分：
> 1) **管理接口**（`/api/v1/mock/...`）用于创建/编辑“场景、数据表、API 规则”
> 2) **Mock 服务器接口**（`/mock-server/{scenarioId}/...`）用于按规则对“运行时数据(JSON)”做增删改查

---

## 0. 基础路径

- 管理 API 基地址：`http://<host>:<port>/api/v1`
- Mock Server 基地址：`http://<host>:<port>/mock-server/{scenarioId}`

其中 `{scenarioId}` 为 `mock_scenario.id`。

---

## 1. Mock 场景管理（MockScenario）

### 1.1 创建场景

- `POST /api/v1/mock/scenarios`
- Body：
  ```json
  { "name": "场景名称", "description": null }
  ```
- Response：`MockScenarioOut`
  ```json
  { "id": "xxx", "name": "xxx", "description": null, "created_at": "..." , "updated_at": "..." }
  ```

### 1.2 列出场景

- `GET /api/v1/mock/scenarios`
- Response：`MockScenarioOut[]`

### 1.3 获取场景详情（包含表与规则）

- `GET /api/v1/mock/scenarios/{scenarioId}`
- Response：`MockScenarioDetailOut`
  - `tables`: `MockDataTableOut[]`
  - `api_rules`: `MockApiRuleOut[]`

> 关键点：`tables[].rows_json` 展示的是**运行时 overlay 视图**（若你使用了 state/reset，会反映 overlay 结果）。

### 1.4 删除场景

- `DELETE /api/v1/mock/scenarios/{scenarioId}`
- 状态码：`204`

---

## 2. Mock 数据表管理（MockDataTable）

### 2.1 创建数据表

- `POST /api/v1/mock/scenarios/{scenarioId}/tables`
- Body：`MockDataTableCreate`
  ```json
  {
    "table_name": "user_balance",
    "description": null,
    "schema_json": [
      { "name": "id", "type": "string" },
      { "name": "balance", "type": "number" }
    ],
    "rows_json": [
      { "id": "u1", "balance": 100 }
    ]
  }
  ```
- Response：`MockDataTableOut`

### 2.2 列出数据表

- `GET /api/v1/mock/scenarios/{scenarioId}/tables`
- Response：`MockDataTableOut[]`

### 2.3 更新数据表（设计侧基准与 reset 快照）

- `PUT /api/v1/mock/tables/{tableId}`
- Body：`MockDataTableUpdate`（可选字段）
  ```json
  {
    "table_name": "user_balance",
    "description": "可选",
    "schema_json": [],
    "rows_json": [{ "id": "u1", "balance": 120 }]
  }
  ```
- Response：`MockDataTableOut`

> 说明：这里会同时更新设计侧基准 `rows_json` 与该表的 `reset_rows_json` 快照。

### 2.4 删除数据表

- `DELETE /api/v1/mock/tables/{tableId}`
- 状态码：`204`

---

## 3. API 规则管理（MockApiRule）

规则用于决定：当请求 `mock-server/{scenarioId}/{sub_path}` 时，如何命中并对哪张表执行哪种动作。

### 3.1 创建规则

- `POST /api/v1/mock/scenarios/{scenarioId}/rules`
- Body：`MockApiRuleCreate`
  ```json
  {
    "table_id": "可选(不填表示该规则不关联数据表)",
    "method": "GET",
    "path": "/api/users/{user_id}/balance",
    "description": null,
    "action": "get_by_id",
    "key_field": "user_id",
    "response_template_json": null
  }
  ```

### 3.2 列出规则

- `GET /api/v1/mock/scenarios/{scenarioId}/rules`
- Response：`MockApiRuleOut[]`

### 3.3 更新规则

- `PUT /api/v1/mock/rules/{ruleId}`
- Body：`MockApiRuleUpdate`（可选字段）

### 3.4 删除规则

- `DELETE /api/v1/mock/rules/{ruleId}`
- 状态码：`204`

---

## 4. Mock Server 运行时接口（按规则 CRUD）

### 4.1 路径匹配与占位符

- URL：`/mock-server/{scenarioId}/{sub_path}`
- `sub_path` 必须和规则 `MockApiRule.path` 匹配
- `path` 支持 `{param}` 占位符（例如 `/api/orders/{order_id}`）

### 4.2 动作（action）含义

当规则关联了某张表（`rule.table_id != null`）时：

1. `action: list`
   - 返回 `200`
   - 响应：
     ```json
     { "data": [ ...rows ], "total": 3 }
     ```

2. `action: get_by_id`
   - `key = rule.key_field or "id"`
   - 用路径参数中 `key`（或默认 `id`）作为 lookup
   - 找到：`200 { "data": { ...row } }`
   - 找不到：`404 { "error": "key=lookup 未找到" }`

3. `action: create`
   - 请求体必须为 JSON 对象
   - 若 `body` 未包含 `key`，后端会自动生成一个 8 位字符串 key
   - 返回 `201 { "data": <createdBody> }`

4. `action: update`
   - 请求体必须为 JSON 对象
   - 用 lookup 匹配 row 并合并更新
   - 找到：`200 { "data": <updatedRow> }`
   - 找不到：`404`

5. `action: delete`
   - 返回 `200 { "message": "已删除", "deleted_key": "<lookup>" }`
   - 未找到：`404`

6. `action: custom`
   - 当前实现：如果 `response_template_json` 存在，则直接返回它（`200`）
   - 否则：若有关联表，则返回 `200 { "data": rows }`

### 4.3 数据读写来源（本次重点）

本次要求“修改操作不改大模型生成的那串基准 JSON”，因此实际数据读写遵循：

- 读：优先使用 **运行时 overlay** 的 `rows_json`
- 写：`create/update/delete` 只写 overlay
- 设计侧基准表（`mock_data_table.rows_json`）不被运行时 CRUD 覆盖

（overlay 来自 `mock_data_table_runtime_state`。）

---

## 5. 运行时覆盖：state / reset（给外部测试直接改 JSON）

### 5.1 外部修改运行时数据

- `PATCH /api/v1/mock/scenarios/{scenarioId}/state`
- Body：`MockScenarioStateUpdateRequest`
  ```json
  {
    "tables": [
      {
        "table_name": "user_balance",
        "rows_json": [{ "id": "u1", "balance": 50 }]
      },
      {
        "table_id": "tableId-xxx",
        "rows_json": [{ "product_id": "P001", "amount": 10 }]
      }
    ]
  }
  ```
- Response：`MockScenarioStateUpdateOut`
  ```json
  { "scenario_id": "xxx", "updated_tables": [ ...MockDataTableOut ] }
  ```

> 说明：此接口只更新 overlay，不改设计侧基准 JSON。

### 5.2 Reset 回最初版本

- `POST /api/v1/mock/scenarios/{scenarioId}/reset`
- Response：`MockScenarioResetOut`
  ```json
  { "scenario_id": "xxx", "reset_tables": 3 }
  ```

> 最初版本来源：每张表的 `reset_rows_json` 快照（在创建表时初始化，或你在 `PUT /mock/tables/{tableId}` 时同步更新）。

---

## 6. 建议的测试流程（以“买理财场景”为例）

1. 查场景：
   - `GET /api/v1/mock/scenarios/{scenarioId}` 获取需要覆盖的 `table_name`
2. 覆盖运行时余额/持仓：
   - `PATCH /api/v1/mock/scenarios/{scenarioId}/state`
3. 调用业务 Mock Server 接口：
   - `GET/POST ... /mock-server/{scenarioId}/<规则path>`
4. 测试结束恢复：
   - `POST /api/v1/mock/scenarios/{scenarioId}/reset`

---

## 7. Endpoint Mapping（接口映射到生产风格 URL）

当你希望把“修改个人存款/个人持仓”等接口映射到类似生产环境的 URL 上进行测试，可以使用 Endpoint Mapping。

### 7.1 管理接口（CRUD）

- 创建映射：
  - `POST /api/v1/mock/scenarios/{scenarioId}/mappings`
  - Body：
    ```json
    {
      "method": "POST|GET|PUT|PATCH|DELETE",
      "path": "/api/deposits/{account_id}",
      "action": "list|get_by_id|create|update|delete|custom",
      "table_id": "可选：关联哪张 mock_data_table",
      "key_field": "用于 get_by_id/update/delete 的路径参数名",
      "required_body_fields": ["amount", "holdings"],
      "response_template_json": null
    }
    ```

- 列出映射：
  - `GET /api/v1/mock/scenarios/{scenarioId}/mappings`

- 更新映射：
  - `PUT /api/v1/mock/mappings/{mappingId}`

- 删除映射：
  - `DELETE /api/v1/mock/mappings/{mappingId}`

### 7.2 映射后的 Mock Server 执行入口

- Base：
  - `http://<host>:<port>/mock-mapped/{scenarioId}`
- 完整 URL：
  - `/{mock-mapped}/{scenarioId}{mapping.path}`

URL 匹配规则：
- 根据 `method + path` 命中映射
- `path` 支持 `{param}` 占位符，例如 `/api/deposits/{account_id}`

body 必填校验：
- `required_body_fields` 仅对 `create/update/custom` 校验
- 当请求体缺少这些字段，后端返回 `400`，并给出缺失字段列表

数据读写来源：
- 读/写都作用在运行时 overlay（不覆盖大模型生成的设计侧基准 JSON）


