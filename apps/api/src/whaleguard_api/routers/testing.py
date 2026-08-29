from __future__ import annotations

import asyncio
import json
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select

from ..audit import write_audit
from ..config import get_settings
from ..database import SessionLocal
from ..dependencies import DB, require_permissions
from ..models import (
    AgentTarget,
    ModelChannel,
    Project,
    TestCase,
    TestResult,
    TestRun,
    TestSuite,
    User,
)
from ..runner import append_event, execute_run
from ..schemas import (
    Page,
    TestCaseCreate,
    TestCaseResponse,
    TestResultResponse,
    TestRunCreate,
    TestRunResponse,
    TestSuiteCreate,
    TestSuiteResponse,
    TestSuiteUpdate,
    WorkerEvaluationResult,
)
from .common import apply_updates, get_or_404, paginate

router = APIRouter(tags=["测试用例与运行"])


@router.post("/internal/runs/{run_id}/result", include_in_schema=False)
def accept_worker_result(
    run_id: UUID,
    payload: WorkerEvaluationResult,
    request: Request,
    db: DB,
) -> dict[str, bool]:
    configured = get_settings().worker_token or ""
    supplied = request.headers.get("x-worker-token", "")
    if not configured or not supplied or not secrets.compare_digest(configured, supplied):
        raise HTTPException(status_code=401, detail="Worker 认证失败")
    run = get_or_404(db, TestRun, run_id, "测试运行不存在")
    explanation = dict(run.score_explanation or {})
    worker_results = list(explanation.get("worker_results", []))
    worker_results.append(payload.model_dump())
    explanation["worker_results"] = worker_results[-500:]
    run.score_explanation = explanation
    append_event(
        run,
        "evaluation.completed",
        "RQ worker 完成确定性规则复核",
        worker_security_score=payload.security_score,
    )
    write_audit(
        db,
        request,
        "worker.evaluation_callback",
        "test_run",
        run.id,
        outcome="success",
        details={"security_score": payload.security_score},
    )
    db.commit()
    return {"accepted": True}


@router.get("/test-suites", response_model=Page[TestSuiteResponse])
def list_test_suites(
    db: DB,
    _user: User = Depends(require_permissions("tests.read")),
    project_id: UUID | None = None,
    search: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[TestSuiteResponse]:
    query = select(TestSuite).order_by(TestSuite.updated_at.desc())
    if project_id:
        query = query.where(TestSuite.project_id == project_id)
    if search:
        pattern = f"%{search[:200]}%"
        query = query.where(
            or_(TestSuite.name.ilike(pattern), TestSuite.description.ilike(pattern))
        )
    if enabled is not None:
        query = query.where(TestSuite.enabled.is_(enabled))
    return paginate(db, query, page, page_size)


@router.post("/test-suites", response_model=TestSuiteResponse, status_code=201)
def create_test_suite(
    payload: TestSuiteCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("tests.write")),
) -> TestSuite:
    get_or_404(db, Project, payload.project_id, "项目不存在")
    suite = TestSuite(**payload.model_dump())
    db.add(suite)
    db.flush()
    write_audit(db, request, "test_suite.create", "test_suite", suite.id, user)
    db.commit()
    db.refresh(suite)
    return suite


@router.get("/test-suites/{suite_id}", response_model=TestSuiteResponse)
def get_test_suite(
    suite_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("tests.read")),
) -> TestSuite:
    return get_or_404(db, TestSuite, suite_id, "测试套件不存在")


@router.patch("/test-suites/{suite_id}", response_model=TestSuiteResponse)
def update_test_suite(
    suite_id: UUID,
    payload: TestSuiteUpdate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("tests.write")),
) -> TestSuite:
    suite = get_or_404(db, TestSuite, suite_id, "测试套件不存在")
    apply_updates(suite, payload.model_dump(exclude_unset=True))
    write_audit(db, request, "test_suite.update", "test_suite", suite.id, user)
    db.commit()
    db.refresh(suite)
    return suite


@router.delete("/test-suites/{suite_id}", status_code=204)
def delete_test_suite(
    suite_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("tests.write")),
) -> Response:
    suite = get_or_404(db, TestSuite, suite_id, "测试套件不存在")
    has_runs = db.scalar(select(TestRun.id).where(TestRun.suite_id == suite.id).limit(1))
    if has_runs:
        raise HTTPException(status_code=409, detail="测试套件已有运行记录，不能删除")
    write_audit(db, request, "test_suite.delete", "test_suite", suite.id, user)
    db.delete(suite)
    db.commit()
    return Response(status_code=204)


@router.get("/test-suites/{suite_id}/cases", response_model=Page[TestCaseResponse])
def list_test_cases(
    suite_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("tests.read")),
    search: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[TestCaseResponse]:
    get_or_404(db, TestSuite, suite_id, "测试套件不存在")
    query = select(TestCase).where(TestCase.suite_id == suite_id)
    if search:
        pattern = f"%{search[:200]}%"
        query = query.where(or_(TestCase.name.ilike(pattern), TestCase.description.ilike(pattern)))
    if category:
        query = query.where(TestCase.category == category)
    if severity:
        query = query.where(TestCase.severity == severity)
    return paginate(db, query.order_by(TestCase.created_at), page, page_size)


def _create_case(db: DB, suite: TestSuite, payload: TestCaseCreate) -> TestCase:
    exists = db.scalar(
        select(TestCase.id).where(
            TestCase.suite_id == suite.id, TestCase.case_key == payload.case_key
        )
    )
    if exists:
        raise HTTPException(status_code=409, detail=f"测试用例 ID 已存在：{payload.case_key}")
    test_case = TestCase(suite_id=suite.id, **payload.model_dump(by_alias=False))
    db.add(test_case)
    return test_case


@router.post("/test-suites/{suite_id}/cases", response_model=TestCaseResponse, status_code=201)
def create_test_case(
    suite_id: UUID,
    payload: TestCaseCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("tests.write")),
) -> TestCase:
    suite = get_or_404(db, TestSuite, suite_id, "测试套件不存在")
    test_case = _create_case(db, suite, payload)
    db.flush()
    write_audit(db, request, "test_case.create", "test_case", test_case.id, user)
    db.commit()
    db.refresh(test_case)
    return test_case


@router.post(
    "/test-suites/{suite_id}/cases/bulk",
    response_model=list[TestCaseResponse],
    status_code=201,
)
def bulk_create_test_cases(
    suite_id: UUID,
    payload: list[TestCaseCreate],
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("tests.write")),
) -> list[TestCase]:
    if not 1 <= len(payload) <= 500:
        raise HTTPException(status_code=422, detail="批量导入数量必须为 1 到 500")
    suite = get_or_404(db, TestSuite, suite_id, "测试套件不存在")
    created = [_create_case(db, suite, item) for item in payload]
    db.flush()
    write_audit(
        db,
        request,
        "test_case.bulk_create",
        "test_suite",
        suite.id,
        user,
        details={"count": len(created)},
    )
    db.commit()
    for item in created:
        db.refresh(item)
    return created


@router.get("/runs", response_model=Page[TestRunResponse])
def list_runs(
    db: DB,
    _user: User = Depends(require_permissions("runs.read")),
    project_id: UUID | None = None,
    search: str | None = None,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[TestRunResponse]:
    query = select(TestRun).order_by(TestRun.created_at.desc())
    if project_id:
        query = query.where(TestRun.project_id == project_id)
    if search:
        query = query.where(TestRun.name.ilike(f"%{search[:200]}%"))
    if status_filter:
        query = query.where(TestRun.status == status_filter)
    return paginate(db, query, page, page_size)


@router.post("/runs", response_model=TestRunResponse, status_code=202)
def create_run(
    payload: TestRunCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("runs.execute")),
) -> TestRun:
    get_or_404(db, Project, payload.project_id, "项目不存在")
    suite = get_or_404(db, TestSuite, payload.suite_id, "测试套件不存在")
    if suite.project_id != payload.project_id:
        raise HTTPException(status_code=422, detail="测试套件不属于该项目")
    agent_target_id = payload.agent_target_id
    model_channel_id = payload.model_channel_id
    if payload.target_id and payload.target_type is None:
        raise HTTPException(status_code=422, detail="target_id 必须与 target_type 一起提供")
    if payload.target_id and payload.target_type == "agent":
        agent_target_id = payload.target_id
    elif payload.target_id and payload.target_type == "model":
        model_channel_id = payload.target_id
    elif payload.target_type == "agent" and agent_target_id is None:
        agent_target_id = db.scalar(
            select(AgentTarget.id)
            .where(
                AgentTarget.project_id == payload.project_id,
                AgentTarget.enabled.is_(True),
            )
            .order_by(AgentTarget.created_at)
            .limit(1)
        )
        if agent_target_id is None:
            raise HTTPException(status_code=422, detail="项目没有可用的 Agent")
    elif payload.target_type == "model" and model_channel_id is None:
        model_channel_id = db.scalar(
            select(ModelChannel.id)
            .where(
                or_(
                    ModelChannel.project_id == payload.project_id,
                    ModelChannel.project_id.is_(None),
                ),
                ModelChannel.enabled.is_(True),
            )
            .order_by(ModelChannel.created_at)
            .limit(1)
        )
        if model_channel_id is None:
            raise HTTPException(status_code=422, detail="项目没有可用的模型渠道")
    if agent_target_id and model_channel_id:
        raise HTTPException(status_code=422, detail="一次运行只能选择 Agent 或模型渠道")
    if payload.target_type == "agent" and model_channel_id:
        raise HTTPException(status_code=422, detail="target_type 与模型渠道不匹配")
    if payload.target_type == "model" and agent_target_id:
        raise HTTPException(status_code=422, detail="target_type 与 Agent 不匹配")
    if agent_target_id:
        agent = get_or_404(db, AgentTarget, agent_target_id, "Agent 不存在")
        if agent.project_id != payload.project_id:
            raise HTTPException(status_code=422, detail="Agent 不属于该项目")
        if not agent.enabled:
            raise HTTPException(status_code=422, detail="Agent 已禁用")
    if model_channel_id:
        channel = get_or_404(db, ModelChannel, model_channel_id, "模型渠道不存在")
        if channel.project_id not in {None, payload.project_id}:
            raise HTTPException(status_code=422, detail="模型渠道不属于该项目")
        if not channel.enabled:
            raise HTTPException(status_code=422, detail="模型渠道已禁用")
    if payload.evaluation_mode == "rules_with_llm_judge":
        if payload.judge_model_channel_id is None:
            raise HTTPException(status_code=422, detail="LLM Judge 模式必须指定 Judge 模型渠道")
        judge_channel = get_or_404(
            db, ModelChannel, payload.judge_model_channel_id, "Judge 模型渠道不存在"
        )
        if judge_channel.project_id not in {None, payload.project_id}:
            raise HTTPException(status_code=422, detail="Judge 模型渠道不属于该项目")
        if not judge_channel.enabled:
            raise HTTPException(status_code=422, detail="Judge 模型渠道已禁用")
    elif payload.judge_model_channel_id is not None:
        raise HTTPException(
            status_code=422,
            detail="只有显式选择 rules_with_llm_judge 才能指定 Judge 渠道",
        )
    values = payload.model_dump(
        exclude={"target_type", "target_id", "agent_target_id", "model_channel_id"}
    )
    run = TestRun(
        **values,
        agent_target_id=agent_target_id,
        model_channel_id=model_channel_id,
        requested_by_id=user.id,
        status="queued",
    )
    append_event(run, "run.queued", "测试运行已进入队列")
    db.add(run)
    db.flush()
    write_audit(db, request, "test_run.create", "test_run", run.id, user)
    db.commit()
    db.refresh(run)
    background_tasks.add_task(execute_run, run.id)
    return run


@router.get("/runs/{run_id}", response_model=TestRunResponse)
def get_run(
    run_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("runs.read")),
) -> TestRun:
    return get_or_404(db, TestRun, run_id, "测试运行不存在")


@router.get("/runs/{run_id}/results", response_model=Page[TestResultResponse])
def list_run_results(
    run_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("runs.read")),
    outcome: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> Page[TestResultResponse]:
    get_or_404(db, TestRun, run_id, "测试运行不存在")
    query = select(TestResult).where(TestResult.run_id == run_id)
    if outcome:
        query = query.where(TestResult.outcome == outcome)
    return paginate(db, query.order_by(TestResult.created_at), page, page_size)


@router.post("/runs/{run_id}/pause", response_model=TestRunResponse)
def pause_run(
    run_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("runs.execute")),
) -> TestRun:
    run = get_or_404(db, TestRun, run_id, "测试运行不存在")
    if run.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="当前状态不能暂停")
    run.pause_requested = True
    run.status = "waiting_approval"
    append_event(run, "run.pause_requested", "已请求暂停")
    write_audit(db, request, "test_run.pause", "test_run", run.id, user)
    db.commit()
    db.refresh(run)
    return run


@router.post("/runs/{run_id}/resume", response_model=TestRunResponse, status_code=202)
def resume_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("runs.execute")),
) -> TestRun:
    run = get_or_404(db, TestRun, run_id, "测试运行不存在")
    if run.status != "waiting_approval" or not run.pause_requested:
        raise HTTPException(status_code=409, detail="当前运行不处于暂停状态")
    run.pause_requested = False
    run.status = "queued"
    append_event(run, "run.resumed", "测试运行已恢复并重新入队")
    write_audit(db, request, "test_run.resume", "test_run", run.id, user)
    db.commit()
    db.refresh(run)
    background_tasks.add_task(execute_run, run.id)
    return run


@router.post("/runs/{run_id}/cancel", response_model=TestRunResponse)
def cancel_run(
    run_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("runs.execute")),
) -> TestRun:
    run = get_or_404(db, TestRun, run_id, "测试运行不存在")
    if run.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="当前状态不能取消")
    run.cancellation_requested = True
    run.status = "cancelled"
    run.finished_at = datetime.now(UTC)
    append_event(run, "run.cancelled", "测试运行已取消")
    write_audit(db, request, "test_run.cancel", "test_run", run.id, user)
    db.commit()
    db.refresh(run)
    return run


@router.post("/runs/{run_id}/retry", response_model=TestRunResponse, status_code=202)
def retry_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("runs.execute")),
) -> TestRun:
    old = get_or_404(db, TestRun, run_id, "测试运行不存在")
    if old.status not in {"failed", "cancelled", "completed"}:
        raise HTTPException(status_code=409, detail="仅失败、取消或完成的运行可以重试")
    if old.attempt > old.max_retries:
        raise HTTPException(status_code=409, detail="已达到最大重试次数")
    retry = TestRun(
        project_id=old.project_id,
        suite_id=old.suite_id,
        agent_target_id=old.agent_target_id,
        model_channel_id=old.model_channel_id,
        evaluation_mode=old.evaluation_mode,
        judge_model_channel_id=old.judge_model_channel_id,
        name=f"{old.name}（重试 {old.attempt + 1}）",
        status="queued",
        max_concurrency=old.max_concurrency,
        timeout_seconds=old.timeout_seconds,
        attempt=old.attempt + 1,
        max_retries=old.max_retries,
        requested_by_id=user.id,
    )
    append_event(retry, "run.queued", "重试任务已进入队列", retried_from=str(old.id))
    db.add(retry)
    db.flush()
    write_audit(
        db,
        request,
        "test_run.retry",
        "test_run",
        retry.id,
        user,
        details={"retried_from": str(old.id)},
    )
    db.commit()
    db.refresh(retry)
    background_tasks.add_task(execute_run, retry.id)
    return retry


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("runs.read")),
) -> StreamingResponse:
    get_or_404(db, TestRun, run_id, "测试运行不存在")

    async def event_generator():
        last_sequence = 0
        idle_count = 0
        while idle_count < 3600:
            with SessionLocal() as stream_db:
                run = stream_db.get(TestRun, run_id)
                if run is None:
                    yield 'event: error\ndata: {"detail":"run not found"}\n\n'
                    return
                events = [
                    event
                    for event in (run.event_log or [])
                    if int(event.get("sequence", 0)) > last_sequence
                ]
                for event in events:
                    last_sequence = int(event.get("sequence", last_sequence))
                    event_name = event.get("event", "message")
                    event_data = json.dumps(event, ensure_ascii=False)
                    yield f"id: {last_sequence}\nevent: {event_name}\ndata: {event_data}\n\n"
                if run.status in {"completed", "failed", "cancelled"}:
                    yield f"event: end\ndata: {json.dumps({'status': run.status})}\n\n"
                    return
            idle_count += 1
            if idle_count % 20 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
