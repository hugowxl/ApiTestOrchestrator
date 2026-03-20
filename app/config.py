from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "api-test-orchestrator"
    debug: bool = False

    # 文件日志：D:/applog/<log_project_name 或 app_name>/root.log
    log_applog_base: str = "D:/applog"
    """应用日志根目录，其下为按项目分目录。"""
    log_project_name: str = ""
    """子目录名；为空则使用 app_name（非法路径字符会被替换）。"""

    database_url: str = "sqlite:///./data/app.db"

    default_target_base_url: str = "http://localhost:8080"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    # PEM 路径：与公司代理根证书一起校验（优先于 llm_verify_ssl）
    llm_ca_bundle: str = ""
    # false = 不校验 LLM HTTPS 证书（仅排障，生产优先用 llm_ca_bundle）
    llm_verify_ssl: bool = False
    # 仅 LLM 请求；生成用例常慢于执行 HTTP，与 HTTP_TIMEOUT_SECONDS 分开
    llm_timeout_seconds: float = 120.0

    http_timeout_seconds: float = 30.0
    # 逗号分隔；供浏览器直连后端（非 Vite 代理）时使用
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # 执行用例时访问「被测服务」的 HTTPS；与 LLM 的 llm_* 相互独立
    executor_ca_bundle: str = ""
    executor_verify_ssl: bool = True

    def executor_tls_verify(self) -> bool | str:
        ca = (self.executor_ca_bundle or "").strip()
        if ca:
            return ca
        return self.executor_verify_ssl


@lru_cache
def get_settings() -> Settings:
    return Settings()
