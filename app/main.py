from contextlib import asynccontextmanager
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from app.api.agent_test_routes import router as agent_test_router
from app.api.mock_routes import mock_mapped_server_router
from app.api.mock_routes import mock_server_router
from app.api.mock_routes import router as mock_router
from app.api.routes import router
from app.services.workflow_mock_server import router as workflow_mock_router
from app.api.schemas import ErrorBody
from app.config import get_settings
from app.db.session import init_db
from app.logging_setup import apply_forced_log_levels, flush_log_handlers, setup_file_logging
from app.utils.errors import AppError
from app.utils.http_exc import http_exception_from_app_error
from app.utils.redact import redact_for_log

settings = get_settings()
# 在 import 阶段即挂载文件 Handler，避免首批请求早于 lifespan 时无文件日志
setup_file_logging(settings)

req_log = logging.getLogger("app.request")
err_log = logging.getLogger("app.errors")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 清除 settings 缓存，确保 .env 变更在 uvicorn reload 时生效
    get_settings.cache_clear()
    # uvicorn 可能在 load 时 dictConfig，再强制一遍级别，保证 Postman/任意客户端请求必进 root.log
    setup_file_logging(get_settings())
    apply_forced_log_levels(get_settings())
    init_db()
    from app.services.workflow_mock_server import start_standalone_mock_server
    start_standalone_mock_server()
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

_cors_raw = (settings.cors_origins or "").strip()
_cors_list = [o.strip() for o in _cors_raw.split(",") if o.strip()]
if _cors_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def log_request_response(request: Request, call_next):
    """每条进入 FastAPI 的 HTTP 请求均写入 root.log（成功/失败/异常均记录）。"""
    rid = uuid.uuid4().hex[:12]
    path_qs = request.url.path
    if request.url.query:
        path_qs = f"{path_qs}?{request.url.query}"
    client = request.client.host if request.client else "-"
    req_log.info("[%s] --> %s %s client=%s", rid, request.method, path_qs, client)
    flush_log_handlers()

    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        req_log.error(
            "[%s] !! %s %s 未返回响应: %s: %s (%.1fms)",
            rid,
            request.method,
            path_qs,
            type(e).__name__,
            e,
            ms,
        )
        flush_log_handlers()
        raise

    ms = (time.perf_counter() - t0) * 1000
    req_log.info(
        "[%s] <-- %s %s -> %s (%.1fms)",
        rid,
        request.method,
        path_qs,
        response.status_code,
        ms,
    )
    flush_log_handlers()
    # 漏写 /api/v1 时 Starlette 立即 404，易被误认为「接口挂了」；加响应头便于 Postman / 抓包辨认
    if response.status_code == 404:
        p = request.url.path
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and not p.startswith("/api/v1"):
            if not p.startswith(("/docs", "/redoc", "/openapi.json")):
                response.headers["X-API-Hint"] = (
                    "Use path prefix /api/v1, e.g. POST /api/v1/services/{service_id}/generate-cases-batch"
                )
    return response


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    http = http_exception_from_app_error(exc)
    return JSONResponse(status_code=http.status_code, content=http.detail)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    body = ErrorBody(
        code="VALIDATION_ERROR",
        message=redact_for_log(str(exc)),
        retryable=False,
        details={"errors": exc.errors()},
    )
    return JSONResponse(status_code=422, content=body.model_dump())


@app.exception_handler(ResponseValidationError)
async def response_validation_handler(request: Request, exc: ResponseValidationError):
    err_log.exception(
        "响应模型校验失败 %s %s | errors=%s",
        request.method,
        request.url.path,
        exc.errors(),
    )
    flush_log_handlers()
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "RESPONSE_VALIDATION_ERROR",
                "message": "返回数据无法序列化为声明的 response_model",
                "errors": exc.errors(),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    err_log.exception("未处理异常 %s %s | %s", request.method, request.url.path, type(exc).__name__)
    flush_log_handlers()
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "INTERNAL",
                "message": str(exc),
                "exception_type": type(exc).__name__,
            }
        },
    )


app.include_router(router, prefix="/api/v1")
app.include_router(mock_router, prefix="/api/v1")
app.include_router(agent_test_router, prefix="/api/v1")
app.include_router(mock_server_router)
app.include_router(mock_mapped_server_router)
app.include_router(workflow_mock_router)


@app.get("/health")
def health():
    return {"status": "ok"}
