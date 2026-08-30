from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from ..audit import write_audit
from ..dependencies import DB, require_permissions
from ..models import (
    ApprovalRequest,
    AuditLog,
    Evidence,
    Finding,
    KnowledgeDocument,
    MCPServer,
    Project,
    Role,
    SystemSetting,
    TestRun,
    User,
)
from ..run_events import acquire_sqlite_event_write_lock, append_event
from ..runner import execute_run, get_run_for_update
from ..schemas import (
    ApprovalCreate,
    ApprovalDecision,
    ApprovalResponse,
    AuditLogResponse,
    DashboardSummary,
    KnowledgeCreate,
    KnowledgeResponse,
    Page,
    RoleResponse,
    SettingResponse,
    SettingUpsert,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from ..security import encrypt_json, hash_password
from .auth import user_response
from .common import apply_updates, get_or_404, paginate

router = APIRouter(tags=["审批、知识库、审计与设置"])


def approval_for_update_statement(approval_id: UUID):
    """Build the approval claim used by PostgreSQL decision transactions."""
    return (
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: DB,
    _user: User = Depends(require_permissions("dashboard.read")),
) -> DashboardSummary:
    projects = int(db.scalar(select(func.count(Project.id))) or 0)
    active_runs = int(
        db.scalar(
            select(func.count(TestRun.id)).where(
                TestRun.status.in_(["pending", "queued", "running", "waiting_approval"])
            )
        )
        or 0
    )
    open_findings = int(
        db.scalar(
            select(func.count(Finding.id)).where(
                Finding.status.in_(["open", "confirmed", "retest_required"])
            )
        )
        or 0
    )
    critical_findings = int(
        db.scalar(
            select(func.count(Finding.id)).where(
                Finding.severity == "critical",
                Finding.status.in_(["open", "confirmed", "retest_required"]),
            )
        )
        or 0
    )
    mcp_servers = int(db.scalar(select(func.count(MCPServer.id))) or 0)
    evidence = int(db.scalar(select(func.count(Evidence.id))) or 0)
    recent_runs = list(db.scalars(select(TestRun).order_by(TestRun.created_at.desc()).limit(5)))
    severity_distribution = {
        level: int(db.scalar(select(func.count(Finding.id)).where(Finding.severity == level)) or 0)
        for level in ("critical", "high", "medium", "low", "info")
    }
    return DashboardSummary(
        projects=projects,
        active_runs=active_runs,
        open_findings=open_findings,
        critical_findings=critical_findings,
        mcp_servers=mcp_servers,
        evidence=evidence,
        recent_runs=recent_runs,
        severity_distribution=severity_distribution,
    )


@router.get("/approvals", response_model=Page[ApprovalResponse])
def list_approvals(
    db: DB,
    _user: User = Depends(require_permissions("approvals.read")),
    project_id: UUID | None = None,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[ApprovalResponse]:
    query = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())
    if project_id:
        query = query.where(ApprovalRequest.project_id == project_id)
    if status_filter:
        query = query.where(ApprovalRequest.status == status_filter)
    return paginate(db, query, page, page_size)


@router.post("/approvals", response_model=ApprovalResponse, status_code=201)
def create_approval(
    payload: ApprovalCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("approvals.request")),
) -> ApprovalRequest:
    get_or_404(db, Project, payload.project_id, "项目不存在")
    approval = ApprovalRequest(**payload.model_dump(), requested_by_id=user.id)
    db.add(approval)
    db.flush()
    write_audit(db, request, "approval.request", "approval_request", approval.id, user)
    db.commit()
    db.refresh(approval)
    return approval


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalResponse)
def decide_approval(
    approval_id: UUID,
    payload: ApprovalDecision,
    background_tasks: BackgroundTasks,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("approvals.decide")),
) -> ApprovalRequest:
    # SQLite has no row-level SELECT FOR UPDATE support, so acquire its
    # process-local writer lock before the first read. PostgreSQL uses the two
    # row locks below in the stable approval -> run order.
    acquire_sqlite_event_write_lock(db)
    approval = db.scalar(approval_for_update_statement(approval_id))
    if approval is None:
        raise HTTPException(status_code=404, detail="审批请求不存在")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="审批请求已经处理")
    run = get_run_for_update(db, approval.run_id) if approval.run_id else None
    approval.status = payload.status
    approval.decision_reason = payload.decision_reason
    approval.decided_by_id = user.id
    approval.decided_at = datetime.now(UTC)
    should_start_run = False
    if run and run.status == "waiting_approval" and not run.pause_requested:
        if payload.status == "approved":
            run.status = "queued"
            should_start_run = True
            append_event(
                db,
                run,
                "approval.approved",
                "人工审批通过，测试运行重新入队",
            )
        else:
            run.status = "cancelled"
            run.finished_at = datetime.now(UTC)
            append_event(
                db,
                run,
                "approval.rejected",
                "人工审批拒绝，测试运行已取消",
            )
    write_audit(
        db,
        request,
        "approval.decision",
        "approval_request",
        approval.id,
        user,
        details={"decision": payload.status},
    )
    db.commit()
    db.refresh(approval)
    if should_start_run and run is not None:
        background_tasks.add_task(execute_run, run.id)
    return approval


@router.get("/audit-logs", response_model=Page[AuditLogResponse])
def list_audit_logs(
    db: DB,
    _user: User = Depends(require_permissions("audit.read")),
    search: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> Page[AuditLogResponse]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if search:
        pattern = f"%{search[:200]}%"
        query = query.where(
            or_(AuditLog.action.ilike(pattern), AuditLog.resource_type.ilike(pattern))
        )
    if action:
        query = query.where(AuditLog.action == action)
    if outcome:
        query = query.where(AuditLog.outcome == outcome)
    return paginate(db, query, page, page_size)


@router.get("/knowledge", response_model=Page[KnowledgeResponse])
@router.get("/knowledge-documents", response_model=Page[KnowledgeResponse])
def list_knowledge(
    db: DB,
    _user: User = Depends(require_permissions("knowledge.read")),
    project_id: UUID | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[KnowledgeResponse]:
    query = select(KnowledgeDocument).order_by(KnowledgeDocument.updated_at.desc())
    if project_id:
        query = query.where(KnowledgeDocument.project_id == project_id)
    if search:
        pattern = f"%{search[:200]}%"
        query = query.where(
            or_(KnowledgeDocument.title.ilike(pattern), KnowledgeDocument.content.ilike(pattern))
        )
    return paginate(db, query, page, page_size)


@router.post("/knowledge", response_model=KnowledgeResponse, status_code=201)
@router.post("/knowledge-documents", response_model=KnowledgeResponse, status_code=201)
def create_knowledge(
    payload: KnowledgeCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("knowledge.write")),
) -> KnowledgeDocument:
    get_or_404(db, Project, payload.project_id, "项目不存在")
    document = KnowledgeDocument(
        **payload.model_dump(),
        sha256=hashlib.sha256(payload.content.encode("utf-8")).hexdigest(),
        created_by_id=user.id,
    )
    db.add(document)
    db.flush()
    write_audit(db, request, "knowledge.create", "knowledge_document", document.id, user)
    db.commit()
    db.refresh(document)
    return document


@router.delete("/knowledge/{document_id}", status_code=204)
@router.delete("/knowledge-documents/{document_id}", status_code=204)
def delete_knowledge(
    document_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("knowledge.write")),
) -> Response:
    document = get_or_404(db, KnowledgeDocument, document_id, "知识文档不存在")
    write_audit(db, request, "knowledge.delete", "knowledge_document", document.id, user)
    db.delete(document)
    db.commit()
    return Response(status_code=204)


def _setting_response(setting: SystemSetting) -> SettingResponse:
    value = {"masked": True} if setting.is_secret else setting.value
    return SettingResponse(
        id=setting.id,
        created_at=setting.created_at,
        updated_at=setting.updated_at,
        key=setting.key,
        value=value,
        description=setting.description,
        is_secret=setting.is_secret,
        updated_by_id=setting.updated_by_id,
    )


@router.get("/settings", response_model=Page[SettingResponse])
def list_settings(
    db: DB,
    _user: User = Depends(require_permissions("settings.read")),
    page: int = 1,
    page_size: int = 100,
) -> Page[SettingResponse]:
    result = paginate(db, select(SystemSetting).order_by(SystemSetting.key), page, page_size)
    result.items = [_setting_response(item) for item in result.items]
    return result


@router.put("/settings/{key}", response_model=SettingResponse)
def upsert_setting(
    key: str,
    payload: SettingUpsert,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("settings.write")),
) -> SettingResponse:
    if not 1 <= len(key) <= 160 or not all(char.isalnum() or char in "._-" for char in key):
        raise HTTPException(status_code=422, detail="设置键格式无效")
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    stored_value = payload.value
    if payload.is_secret:
        token = encrypt_json(payload.value)
        stored_value = {"encrypted": token.decode("ascii") if token else ""}
    if setting is None:
        setting = SystemSetting(key=key)
        db.add(setting)
    setting.value = stored_value
    setting.description = payload.description
    setting.is_secret = payload.is_secret
    setting.updated_by_id = user.id
    db.flush()
    write_audit(
        db,
        request,
        "system_setting.update",
        "system_setting",
        setting.id,
        user,
        details={"key": key, "is_secret": payload.is_secret},
    )
    db.commit()
    db.refresh(setting)
    return _setting_response(setting)


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(
    db: DB,
    _user: User = Depends(require_permissions("users.read")),
) -> list[RoleResponse]:
    roles = list(
        db.scalars(select(Role).options(selectinload(Role.permissions)).order_by(Role.name))
    )
    return [
        RoleResponse(
            id=role.id,
            created_at=role.created_at,
            updated_at=role.updated_at,
            name=role.name,
            description=role.description,
            permissions=sorted(item.code for item in role.permissions),
        )
        for role in roles
    ]


@router.get("/users", response_model=Page[UserResponse])
def list_users(
    db: DB,
    _user: User = Depends(require_permissions("users.read")),
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[UserResponse]:
    query = select(User).options(selectinload(User.roles).selectinload(Role.permissions))
    if search:
        pattern = f"%{search[:200]}%"
        query = query.where(or_(User.username.ilike(pattern), User.email.ilike(pattern)))
    result = paginate(db, query.order_by(User.created_at), page, page_size)
    result.items = [user_response(item) for item in result.items]
    return result


def _load_roles(db: DB, role_names: list[str]) -> list[Role]:
    roles = list(db.scalars(select(Role).where(Role.name.in_(role_names))))
    if len({role.name for role in roles}) != len(set(role_names)):
        raise HTTPException(status_code=422, detail="包含不存在的角色")
    return roles


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    db: DB,
    actor: User = Depends(require_permissions("users.write")),
) -> UserResponse:
    exists = db.scalar(
        select(User.id).where(or_(User.username == payload.username, User.email == payload.email))
    )
    if exists:
        raise HTTPException(status_code=409, detail="用户名或邮箱已存在")
    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        roles=_load_roles(db, payload.role_names),
    )
    db.add(user)
    db.flush()
    write_audit(db, request, "user.create", "user", user.id, actor)
    db.commit()
    db.refresh(user)
    return user_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    request: Request,
    db: DB,
    actor: User = Depends(require_permissions("users.write")),
) -> UserResponse:
    user = get_or_404(db, User, user_id, "用户不存在")
    values = payload.model_dump(exclude_unset=True, exclude={"role_names"})
    if user.id == actor.id and values.get("is_active") is False:
        raise HTTPException(status_code=409, detail="不能禁用当前登录用户")
    apply_updates(user, values)
    if payload.role_names is not None:
        user.roles = _load_roles(db, payload.role_names)
    write_audit(db, request, "user.update", "user", user.id, actor)
    db.commit()
    db.refresh(user)
    return user_response(user)
