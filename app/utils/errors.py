from enum import StrEnum


class ErrorCode(StrEnum):
    SWAGGER_FETCH_FAILED = "SWAGGER_FETCH_FAILED"
    SWAGGER_PARSE_FAILED = "SWAGGER_PARSE_FAILED"
    SYNC_DB_ERROR = "SYNC_DB_ERROR"
    SYNC_FAILED = "SYNC_FAILED"
    SYNC_CONFLICT = "SYNC_CONFLICT"
    LLM_NOT_CONFIGURED = "LLM_NOT_CONFIGURED"
    LLM_REQUEST_FAILED = "LLM_REQUEST_FAILED"
    LLM_INVALID_JSON = "LLM_INVALID_JSON"
    LLM_SCHEMA_VALIDATION_FAILED = "LLM_SCHEMA_VALIDATION_FAILED"
    NOT_FOUND = "NOT_FOUND"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str, retryable: bool = False, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
