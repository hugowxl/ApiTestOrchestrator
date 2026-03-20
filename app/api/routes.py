from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    GenerateCasesBatchFailure,
    GenerateCasesBatchOut,
    GenerateCasesBatchRequest,
    GenerateCasesRequest,
    ReportOut,
    RunSuiteRequest,
    RunSuitesBatchOut,
    RunSuitesBatchRequest,
    RunSuitesBatchSkip,
    ServiceCreate,
    ServiceOut,
    SuiteOut,
    SyncJobOut,
    SyncRequest,
    TestCaseOut,
    TestRunOut,
)
from app.config import get_settings
from app.db.models import Endpoint, Report, TargetService, TestCase, TestCaseStatus, TestRun, TestSuite
from app.db.session import get_db
from app.services.llm_test_designer import LLMTestDesigner
from app.services.report_service import persist_reports
from app.services.sync_service import SyncService
from app.services.test_executor import TestExecutor
from app.utils.errors import AppError, ErrorCode
from app.utils.generate_trace import trace_begin, trace_end, tlog
from app.utils.http_exc import http_exception_from_app_error

router = APIRouter()


@router.post("/services", response_model=ServiceOut)
def create_service(body: ServiceCreate, db: Session = Depends(get_db)):
    s = TargetService(name=body.name, base_url=body.base_url, swagger_url=body.swagger_url)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/services", response_model=list[ServiceOut])
def list_services(db: Session = Depends(get_db)):
    return db.execute(select(TargetService)).scalars().all()


@router.get("/endpoints/{endpoint_id}/suites", response_model=list[SuiteOut])
def list_endpoint_suites(endpoint_id: str, db: Session = Depends(get_db)):
    """某 endpoint 下由「单 endpoint 生成」产生的套件列表（endpoint_id 匹配）。"""
    ep = db.get(Endpoint, endpoint_id)
    if not ep:
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "endpoint 不存在"})
    return list(
        db.execute(
            select(TestSuite)
            .where(TestSuite.endpoint_id == endpoint_id)
            .order_by(TestSuite.created_at.desc())
        )
        .scalars()
        .all()
    )


@router.get("/services/{service_id}/endpoints", response_model=list[dict])
def list_endpoints(service_id: str, db: Session = Depends(get_db)):
    rows = db.execute(select(Endpoint).where(Endpoint.service_id == service_id)).scalars().all()
    return [
        {
            "id": r.id,
            "method": r.method,
            "path": r.path,
            "operation_id": r.operation_id,
            "fingerprint": r.fingerprint,
        }
        for r in rows
    ]


@router.get("/services/{service_id}/suites", response_model=list[SuiteOut])
def list_service_suites(service_id: str, db: Session = Depends(get_db)):
    """列出某服务下全部测试套件（含 LLM 生成），用于根据 suite_id 再查用例。"""
    if not db.get(TargetService, service_id):
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "服务不存在"})
    return list(
        db.execute(select(TestSuite).where(TestSuite.service_id == service_id).order_by(TestSuite.created_at.desc()))
        .scalars()
        .all()
    )


@router.get("/suites/{suite_id}", response_model=SuiteOut)
def get_suite(suite_id: str, db: Session = Depends(get_db)):
    s = db.get(TestSuite, suite_id)
    if not s:
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "suite 不存在"})
    return s


@router.get("/suites/{suite_id}/test-cases", response_model=list[TestCaseOut])
def list_suite_test_cases(suite_id: str, db: Session = Depends(get_db)):
    """查看某套件下全部用例（steps_json、variables_json 等）。"""
    if not db.get(TestSuite, suite_id):
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "suite 不存在"})
    return list(
        db.execute(select(TestCase).where(TestCase.suite_id == suite_id).order_by(TestCase.created_at))
        .scalars()
        .all()
    )


@router.post("/services/{service_id}/sync", response_model=SyncJobOut)
def trigger_sync(service_id: str, body: SyncRequest, db: Session = Depends(get_db)):
    if not db.get(TargetService, service_id):
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "服务不存在"})
    sync = SyncService()
    try:
        job = sync.run_sync(db, service_id, swagger_url=body.swagger_url, fetch_headers=body.fetch_headers)
    except AppError as e:
        raise http_exception_from_app_error(e) from e
    return job


@router.post("/endpoints/{endpoint_id}/generate-cases", response_model=SuiteOut)
def generate_cases(endpoint_id: str, body: GenerateCasesRequest, db: Session = Depends(get_db)):
    tok = trace_begin()
    try:
        tlog("GC-01", f"route enter endpoint_id={endpoint_id}")
        tlog("GC-02", "construct LLMTestDesigner")
        designer = LLMTestDesigner()
        tlog("GC-03", "call generate_for_endpoint")
        try:
            suite = designer.generate_for_endpoint(
                db,
                endpoint_id,
                suite_name=body.suite_name,
                approve=body.approve,
            )
        except AppError as e:
            tlog("GC-ERR", f"AppError code={e.code.value} msg={e.message!r}")
            raise http_exception_from_app_error(e) from e
        tlog("GC-99", f"route ok suite_id={suite.id}")
        return suite
    finally:
        trace_end(tok)


@router.post("/services/{service_id}/generate-cases-batch", response_model=GenerateCasesBatchOut)
def generate_cases_batch(
    service_id: str,
    body: GenerateCasesBatchRequest,
    db: Session = Depends(get_db),
):
    if not db.get(TargetService, service_id):
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "服务不存在"})

    if body.endpoint_ids:
        eps: list[Endpoint] = []
        for eid in body.endpoint_ids:
            ep = db.get(Endpoint, eid)
            if not ep or ep.service_id != service_id:
                raise HTTPException(
                    400,
                    detail={
                        "code": ErrorCode.VALIDATION_ERROR.value,
                        "message": f"endpoint 不属于该服务: {eid}",
                    },
                )
            eps.append(ep)
    else:
        eps = list(db.execute(select(Endpoint).where(Endpoint.service_id == service_id)).scalars().all())

    if body.limit is not None:
        eps = eps[: body.limit]

    designer = LLMTestDesigner()
    suites: list[TestSuite] = []
    failures: list[GenerateCasesBatchFailure] = []

    for ep in eps:
        suite_name = None
        if body.suite_name_prefix:
            suite_name = f"{body.suite_name_prefix}-{ep.method}-{ep.path}"[:500]
        try:
            suite = designer.generate_for_endpoint(
                db, ep.id, suite_name=suite_name, approve=body.approve
            )
            suites.append(suite)
        except AppError as e:
            failures.append(
                GenerateCasesBatchFailure(
                    endpoint_id=ep.id, code=e.code.value, message=e.message
                )
            )
            if not body.continue_on_error:
                break
        except Exception as e:
            failures.append(
                GenerateCasesBatchFailure(endpoint_id=ep.id, code="INTERNAL", message=str(e))
            )
            if not body.continue_on_error:
                break

    return GenerateCasesBatchOut(
        service_id=service_id,
        total=len(eps),
        processed=len(suites) + len(failures),
        succeeded=len(suites),
        failed=len(failures),
        suites=suites,
        failures=failures,
    )


@router.post("/services/{service_id}/run-suites-batch", response_model=RunSuitesBatchOut)
def run_suites_batch(
    service_id: str,
    body: RunSuitesBatchRequest,
    db: Session = Depends(get_db),
):
    if not db.get(TargetService, service_id):
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "服务不存在"})

    skipped: list[RunSuitesBatchSkip] = []

    if body.suite_ids:
        total_suites = len(body.suite_ids)
        suites: list[TestSuite] = []
        for sid in body.suite_ids:
            s = db.get(TestSuite, sid)
            if not s or s.service_id != service_id:
                skipped.append(
                    RunSuitesBatchSkip(suite_id=sid, reason="套件不存在或不属于该服务")
                )
                continue
            suites.append(s)
    else:
        suites = list(
            db.execute(select(TestSuite).where(TestSuite.service_id == service_id)).scalars().all()
        )
        total_suites = len(suites)
    settings = get_settings()
    base = body.target_base_url or settings.default_target_base_url
    ex = TestExecutor(timeout=settings.http_timeout_seconds, verify=settings.executor_tls_verify())
    runs: list[TestRun] = []

    for suite in suites:
        cases = list(db.execute(select(TestCase).where(TestCase.suite_id == suite.id)).scalars().all())
        if not cases:
            skipped.append(RunSuitesBatchSkip(suite_id=suite.id, reason="套件下无用例"))
            continue
        to_run = [c for c in cases if (not body.only_approved or c.status == TestCaseStatus.approved)]
        if not to_run:
            skipped.append(
                RunSuitesBatchSkip(suite_id=suite.id, reason="only_approved=true 且无已审批用例")
            )
            continue

        run = TestRun(suite_id=suite.id, trigger="api_batch", target_base_url=base)
        db.add(run)
        db.commit()
        db.refresh(run)

        try:
            ex.run_suite(db, run, to_run, only_approved=False)
        except Exception:
            db.refresh(run)
        else:
            db.refresh(run)

        if body.generate_reports:
            try:
                persist_reports(db, run)
            except Exception:
                pass
        runs.append(run)

    return RunSuitesBatchOut(
        service_id=service_id,
        total_suites=total_suites,
        runs_started=len(runs),
        runs=runs,
        skipped=skipped,
    )


@router.post("/suites/{suite_id}/run", response_model=TestRunOut)
def run_suite(suite_id: str, body: RunSuiteRequest, db: Session = Depends(get_db)):
    suite = db.get(TestSuite, suite_id)
    if not suite:
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "suite 不存在"})

    settings = get_settings()
    base = body.target_base_url or settings.default_target_base_url

    cases = list(db.execute(select(TestCase).where(TestCase.suite_id == suite_id)).scalars().all())
    if not cases:
        raise HTTPException(400, detail={"code": ErrorCode.VALIDATION_ERROR.value, "message": "套件下无用例"})

    to_run = [c for c in cases if (not body.only_approved or c.status == TestCaseStatus.approved)]
    if not to_run:
        raise HTTPException(
            400,
            detail={
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": "only_approved=true 时没有可执行的已审批用例",
            },
        )

    run = TestRun(suite_id=suite.id, trigger="api", target_base_url=base)
    db.add(run)
    db.commit()
    db.refresh(run)

    ex = TestExecutor(timeout=settings.http_timeout_seconds, verify=settings.executor_tls_verify())
    try:
        ex.run_suite(db, run, to_run, only_approved=False, auth_headers=body.auth_headers)
    except Exception as e:
        raise HTTPException(500, detail={"code": ErrorCode.EXECUTION_FAILED.value, "message": str(e)}) from e

    db.refresh(run)
    if body.generate_reports:
        persist_reports(db, run)

    return run


@router.get("/runs/{run_id}", response_model=TestRunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    r = db.get(TestRun, run_id)
    if not r:
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "run 不存在"})
    return r


@router.get("/runs/{run_id}/reports", response_model=list[ReportOut])
def list_reports(run_id: str, db: Session = Depends(get_db)):
    if not db.get(TestRun, run_id):
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "run 不存在"})
    return db.execute(select(Report).where(Report.run_id == run_id)).scalars().all()


@router.get("/services/{service_id}/stats")
def service_stats(service_id: str, db: Session = Depends(get_db)):
    if not db.get(TargetService, service_id):
        raise HTTPException(404, detail={"code": ErrorCode.NOT_FOUND.value, "message": "服务不存在"})
    n = db.execute(
        select(func.count()).select_from(Endpoint).where(Endpoint.service_id == service_id)
    ).scalar_one()
    return {"service_id": service_id, "endpoint_count": int(n or 0)}
