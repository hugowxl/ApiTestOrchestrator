"""Swagger 同步：快照、哈希、endpoint upsert。"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Endpoint, SwaggerSnapshot, SyncJob, SyncJobStatus, TargetService
from app.services.openapi_normalizer import load_spec, normalize_spec
from app.services.swagger_fetcher import SwaggerFetcher
from app.utils.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)


def _content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _finalize_job_failed(
    db: Session,
    job_id: str,
    *,
    error_code: str,
    error_message: str,
) -> None:
    """在 rollback 之后单独更新 sync_job，避免会话处于 failed 状态时二次 commit 报错。"""
    j = db.get(SyncJob, job_id)
    if not j:
        return
    j.status = SyncJobStatus.failed
    j.error_code = error_code
    j.error_message = (error_message or "")[:65000]
    j.finished_at = datetime.utcnow()
    try:
        db.commit()
    except SQLAlchemyError:
        logger.exception("finalize_job_failed commit 失败 job_id=%s", job_id)
        db.rollback()


class SyncService:
    def __init__(self, fetcher: SwaggerFetcher | None = None):
        if fetcher is not None:
            self._fetcher = fetcher
        else:
            self._fetcher = SwaggerFetcher(timeout=get_settings().http_timeout_seconds)

    def run_sync(
        self,
        db: Session,
        service_id: str,
        swagger_url: str | None = None,
        fetch_headers: dict[str, str] | None = None,
    ) -> SyncJob:
        svc = db.get(TargetService, service_id)
        if not svc:
            raise AppError(ErrorCode.NOT_FOUND, "服务不存在", details={"service_id": service_id})

        url = swagger_url or svc.swagger_url
        if not url:
            raise AppError(ErrorCode.SWAGGER_FETCH_FAILED, "未配置 swagger_url", retryable=False)

        job = SyncJob(service_id=service_id, status=SyncJobStatus.running, started_at=datetime.utcnow())
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

        try:
            raw, etag = self._fetcher.fetch(url, fetch_headers)
            chash = _content_hash(raw)

            latest = db.execute(
                select(SwaggerSnapshot)
                .where(SwaggerSnapshot.service_id == service_id)
                .order_by(SwaggerSnapshot.fetched_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            total_eps = db.execute(
                select(func.count()).select_from(Endpoint).where(Endpoint.service_id == service_id)
            ).scalar_one()

            if latest and latest.content_hash == chash:
                j = db.get(SyncJob, job_id)
                assert j is not None
                j.status = SyncJobStatus.success
                j.snapshot_id = latest.id
                j.endpoints_added = 0
                j.endpoints_updated = 0
                j.endpoints_unchanged = int(total_eps or 0)
                j.finished_at = datetime.utcnow()
                db.commit()
                db.refresh(j)
                return j

            spec = load_spec(raw)
            items = normalize_spec(spec)

            snap = SwaggerSnapshot(
                service_id=service_id,
                content_hash=chash,
                etag=etag,
                raw_spec_json=raw.decode("utf-8", errors="replace"),
            )
            db.add(snap)
            db.flush()

            added = updated = unchanged = 0
            for it in items:
                fp = it["fingerprint"]
                existing = db.execute(
                    select(Endpoint).where(
                        Endpoint.service_id == service_id,
                        Endpoint.method == it["method"],
                        Endpoint.path == it["path"],
                    )
                ).scalar_one_or_none()
                if existing:
                    if existing.fingerprint == fp:
                        unchanged += 1
                    else:
                        updated += 1
                    existing.spec_json = it["spec_json"]
                    existing.snapshot_id = snap.id
                    existing.operation_id = it["operation_id"]
                    existing.fingerprint = fp
                    existing.updated_at = datetime.utcnow()
                else:
                    ep = Endpoint(
                        service_id=service_id,
                        snapshot_id=snap.id,
                        method=it["method"],
                        path=it["path"],
                        operation_id=it["operation_id"],
                        spec_json=it["spec_json"],
                        fingerprint=fp,
                    )
                    db.add(ep)
                    added += 1

            svc.swagger_url = url
            j = db.get(SyncJob, job_id)
            assert j is not None
            j.snapshot_id = snap.id
            j.status = SyncJobStatus.success
            j.endpoints_added = added
            j.endpoints_updated = updated
            j.endpoints_unchanged = unchanged
            j.finished_at = datetime.utcnow()
            db.commit()
            db.refresh(j)
            return j

        except AppError as e:
            db.rollback()
            _finalize_job_failed(db, job_id, error_code=e.code.value, error_message=e.message)
            raise

        except IntegrityError as e:
            logger.exception("sync 唯一约束/外键冲突 service_id=%s", service_id)
            db.rollback()
            msg = str(e.orig) if hasattr(e, "orig") and e.orig else str(e)
            _finalize_job_failed(db, job_id, error_code=ErrorCode.SYNC_CONFLICT.value, error_message=msg)
            raise AppError(
                ErrorCode.SYNC_CONFLICT,
                f"同步与数据库约束冲突: {msg}",
                retryable=False,
                details={"hint": "MySQL 下 path 前缀唯一可能导致两条长 path 前 700 字符相同而冲突"},
            ) from e

        except SQLAlchemyError as e:
            logger.exception("sync 数据库错误 service_id=%s", service_id)
            db.rollback()
            msg = str(e.orig) if hasattr(e, "orig") and e.orig else str(e)
            _finalize_job_failed(db, job_id, error_code=ErrorCode.SYNC_DB_ERROR.value, error_message=msg)
            hint = "常见于字段过长、max_allowed_packet、连接超时等"
            if "raw_spec_json" in msg or "Data too long" in msg:
                hint = (
                    "OpenAPI 全文超过 MySQL TEXT(64KB) 限制：请在库中把 swagger_snapshot.raw_spec_json "
                    "改为 LONGTEXT（见 README 中的 ALTER TABLE），或重新由 ORM 建表。"
                )
            raise AppError(
                ErrorCode.SYNC_DB_ERROR,
                f"同步写入数据库失败: {msg}",
                retryable=False,
                details={"hint": hint},
            ) from e

        except Exception as e:
            logger.exception("sync 未预期错误 service_id=%s", service_id)
            db.rollback()
            _finalize_job_failed(db, job_id, error_code="INTERNAL", error_message=str(e))
            raise AppError(
                ErrorCode.SYNC_FAILED,
                f"同步失败: {e}",
                retryable=False,
            ) from e
