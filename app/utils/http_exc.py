from fastapi import HTTPException

from app.api.schemas import ErrorBody
from app.utils.errors import AppError, ErrorCode


def http_exception_from_app_error(e: AppError) -> HTTPException:
    status = 404 if e.code == ErrorCode.NOT_FOUND else 400
    if e.code == ErrorCode.SYNC_CONFLICT:
        status = 409
    elif e.code in (ErrorCode.SYNC_DB_ERROR, ErrorCode.SYNC_FAILED):
        status = 500
    if e.code in (ErrorCode.LLM_REQUEST_FAILED, ErrorCode.SWAGGER_FETCH_FAILED) and e.retryable:
        status = 503
    detail = ErrorBody(
        code=e.code.value, message=e.message, retryable=e.retryable, details=e.details
    ).model_dump()
    return HTTPException(status_code=status, detail=detail)
