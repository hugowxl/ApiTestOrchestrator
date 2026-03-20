"""通过 LangChain ChatOpenAI 调用 OpenAI 兼容 Chat Completions。"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.utils.errors import AppError, ErrorCode
from app.utils.generate_trace import tlog
from app.utils.redact import redact_headers

_log = logging.getLogger(__name__)
_LLM_LOG_BODY_MAX_CHARS = 64000


def _ai_message_text(msg: AIMessage) -> str:
    c = msg.content
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for p in c:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
            else:
                parts.append(str(p))
        return "".join(parts)
    return str(c)


class LLMClient:
    def __init__(self) -> None:
        s = get_settings()
        self._api_key = s.llm_api_key
        self._base = s.llm_base_url.rstrip("/")
        self._model = s.llm_model
        self._timeout_sec = float(s.llm_timeout_seconds)
        self._timeout = httpx.Timeout(self._timeout_sec)
        ca = (s.llm_ca_bundle or "").strip()
        if ca:
            self._verify: bool | str = ca
        else:
            self._verify = s.llm_verify_ssl
            if not s.llm_verify_ssl:
                _log.warning(
                    "LLM_VERIFY_SSL=false：LLM 请求不校验 TLS 证书，存在中间人风险；生产环境优先使用 LLM_CA_BUNDLE 指定公司根证书"
                )

        # 共享 httpx 客户端（TLS/超时策略）；ChatOpenAI 每次 chat_json 再建，以便正确传入 model_kwargs
        # （invoke/bind 传 model_kwargs 会被错误透传到 Completions.create，见 langchain-openai + openai SDK）
        self._http_client = httpx.Client(timeout=self._timeout, verify=self._verify)

    def __del__(self) -> None:
        try:
            hc = getattr(self, "_http_client", None)
            if hc is not None and not hc.is_closed:
                hc.close()
        except Exception:
            pass

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        use_json_object_mode: bool = True,
    ) -> str:
        if not self._api_key:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "未设置 LLM_API_KEY", retryable=False)

        tlog("GC-30", "LLMClient.chat_json enter (LangChain ChatOpenAI)")
        api_url = f"{self._base}/chat/completions"
        body: dict[str, Any] = {
            "model": self._model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        if use_json_object_mode:
            body["response_format"] = {"type": "json_object"}

        body_json = json.dumps(body, ensure_ascii=False)
        if len(body_json) > _LLM_LOG_BODY_MAX_CHARS:
            body_preview = body_json[:_LLM_LOG_BODY_MAX_CHARS] + f"... [truncated, total_json_chars={len(body_json)}]"
        else:
            body_preview = body_json

        _log.info("LLM api_url=%s", api_url)
        _log.info("LLM request headers=%s", redact_headers({"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}))
        _log.info("LLM request body=%s", body_preview)
        _log.info(
            "LLM request meta model=%s user_chars=%d system_chars=%d timeout_s=%s (langchain)",
            self._model,
            len(user),
            len(system),
            self._timeout_sec,
        )

        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        model_kw: dict[str, Any] = {}
        if use_json_object_mode:
            model_kw["response_format"] = {"type": "json_object"}

        chat_kw: dict[str, Any] = {
            "model": self._model,
            "api_key": self._api_key,
            "base_url": self._base,
            "http_client": self._http_client,
            "temperature": temperature,
            "max_retries": 0,
            "streaming": False,
            "timeout": self._timeout_sec,
        }
        if model_kw:
            chat_kw["model_kwargs"] = model_kw
        chat = ChatOpenAI(**chat_kw)

        try:
            tlog("GC-31", "LangChain invoke start (阻塞点至返回见 GC-32)")
            ai = chat.invoke(messages)
            tlog("GC-32", "LangChain invoke returned")
            if not isinstance(ai, AIMessage):
                raise AppError(
                    ErrorCode.LLM_REQUEST_FAILED,
                    f"非 AIMessage: {type(ai).__name__}",
                    retryable=False,
                )
            choice = _ai_message_text(ai)
            tlog("GC-33", "AIMessage content extracted")
            _log.info("LLM response preview=%s", (choice[:2000] if choice else ""))
        except AppError:
            raise
        except httpx.HTTPError as e:
            raise AppError(ErrorCode.LLM_REQUEST_FAILED, str(e), retryable=True) from e
        except Exception as e:
            msg = str(e)
            name = type(e).__name__
            retryable = (
                "429" in msg
                or "503" in msg
                or "502" in msg
                or "timeout" in msg.lower()
                or "Timeout" in name
                or "Connect" in name
            )
            if "401" in msg or "Authentication" in name or "Permission" in name:
                retryable = False
            raise AppError(ErrorCode.LLM_REQUEST_FAILED, f"{name}: {msg}", retryable=retryable) from e

        if not isinstance(choice, str):
            raise AppError(ErrorCode.LLM_INVALID_JSON, "模型 content 非字符串", retryable=False)
        tlog("GC-34", f"chat_json return content_len={len(choice)}")
        return choice.strip()

    @staticmethod
    def parse_json_strict(text: str) -> Any:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise AppError(
                ErrorCode.LLM_INVALID_JSON,
                f"非合法 JSON: {e}",
                retryable=True,
                details={"snippet": text[:400]},
            ) from e
