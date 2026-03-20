"""从 URL 或本地路径拉取 OpenAPI 原始文本。"""

from pathlib import Path

import httpx

from app.utils.errors import AppError, ErrorCode


class SwaggerFetcher:
    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    def fetch(self, url_or_path: str, extra_headers: dict[str, str] | None = None) -> tuple[bytes, str | None]:
        """
        返回 (content, etag)。
        本地路径以 file 协议或绝对/相对路径形式传入（非 http 则按本地文件读）。
        """
        headers = dict(extra_headers or {})
        if url_or_path.startswith(("http://", "https://")):
            try:
                with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                    r = client.get(url_or_path, headers=headers)
                    r.raise_for_status()
                    etag = r.headers.get("etag")
                    return r.content, etag
            except httpx.HTTPError as e:
                raise AppError(
                    ErrorCode.SWAGGER_FETCH_FAILED,
                    str(e),
                    retryable=True,
                    details={"url": url_or_path},
                ) from e
        path = url_or_path
        if url_or_path.startswith("file://"):
            path = url_or_path[7:]
        p = Path(path)
        if not p.is_file():
            raise AppError(
                ErrorCode.SWAGGER_FETCH_FAILED,
                f"文件不存在: {path}",
                retryable=False,
            )
        return p.read_bytes(), None
