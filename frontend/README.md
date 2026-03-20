# API 测试编排 — 前端控制台

与后端 `FastAPI /api/v1` 对齐的简易管理界面（React + Vite + TypeScript）。

## 开发

1. 先启动后端（默认 `http://127.0.0.1:8000`）：
   ```bash
   cd ..
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
2. 安装依赖并启动前端：
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
3. 浏览器打开 **http://127.0.0.1:5173**（Vite 会把 `/api`、`/health` 代理到 8000，一般无需改 CORS）。

## 生产构建

若前端与 API **不同源**，构建时指定后端公开地址：

```bash
set VITE_API_BASE=http://your-api-host:8000
npm run build
```

将 `dist/` 交给 Nginx 等静态托管；同时后端 `.env` 中 **`CORS_ORIGINS`** 需包含前端页面来源。

## 功能对应

| 页面 | 后端 |
|------|------|
| 服务列表 / 注册 | `GET/POST /api/v1/services` |
| 服务详情 | `GET .../stats`、`.../endpoints`、`.../suites`、`POST .../sync`、`.../generate-cases-batch`、`.../run-suites-batch` |
| Endpoint 行「查看用例」 | 进入 `/services/{sid}/endpoints/{eid}`：套件列表、`GET .../test-cases`、执行、`reports` 摘要 |
| Endpoint 行「生成用例」 | `POST /api/v1/endpoints/{id}/generate-cases` |
| 套件详情 | `GET /api/v1/suites/{id}`、`.../test-cases`、`POST .../run` |
| Run 详情 | `GET /api/v1/runs/{id}`、`.../reports` |
