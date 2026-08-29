from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_, select

from ..audit import write_audit
from ..dependencies import DB, require_permissions
from ..models import AuthorizationScope, Project, User
from ..schemas import (
    Page,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    ScopeCreate,
    ScopeResponse,
    ScopeUpdate,
)
from .common import apply_updates, get_or_404, paginate

router = APIRouter(tags=["项目与授权范围"])


def _validate_scope(target_type: str, target_value: str) -> str:
    value = target_value.strip()
    try:
        if target_type == "ip":
            return str(ipaddress.ip_address(value))
        if target_type == "cidr":
            return str(ipaddress.ip_network(value, strict=False))
        if target_type == "url":
            parsed = urlsplit(value)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                raise ValueError
            if parsed.username or parsed.password:
                raise ValueError
            return value
        if target_type == "domain":
            domain = value.lower().rstrip(".")
            candidate = domain[2:] if domain.startswith("*.") else domain
            if not candidate or "/" in candidate or ":" in candidate or " " in candidate:
                raise ValueError
            candidate.encode("idna")
            return domain
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="授权目标格式无效") from exc
    raise HTTPException(status_code=422, detail="不支持的授权目标类型")


@router.get("/projects", response_model=Page[ProjectResponse])
def list_projects(
    db: DB,
    _user: User = Depends(require_permissions("projects.read")),
    search: str | None = None,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[ProjectResponse]:
    query = select(Project).order_by(Project.updated_at.desc())
    if search:
        pattern = f"%{search[:200]}%"
        query = query.where(or_(Project.name.ilike(pattern), Project.description.ilike(pattern)))
    if status_filter:
        query = query.where(Project.status == status_filter)
    return paginate(db, query, page, page_size)


@router.post("/projects", response_model=ProjectResponse, status_code=201)
def create_project(
    payload: ProjectCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("projects.write")),
) -> Project:
    project = Project(**payload.model_dump(), owner_id=user.id)
    db.add(project)
    db.flush()
    write_audit(db, request, "project.create", "project", project.id, user)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("projects.read")),
) -> Project:
    return get_or_404(db, Project, project_id, "项目不存在")


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("projects.write")),
) -> Project:
    project = get_or_404(db, Project, project_id, "项目不存在")
    apply_updates(project, payload.model_dump(exclude_unset=True))
    write_audit(db, request, "project.update", "project", project.id, user)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("projects.delete")),
) -> Response:
    project = get_or_404(db, Project, project_id, "项目不存在")
    write_audit(
        db,
        request,
        "project.delete",
        "project",
        project.id,
        user,
        details={"name": project.name},
    )
    db.delete(project)
    db.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/scopes", response_model=Page[ScopeResponse])
def list_scopes(
    project_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("scopes.read")),
    search: str | None = None,
    authorized: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[ScopeResponse]:
    get_or_404(db, Project, project_id, "项目不存在")
    query = select(AuthorizationScope).where(AuthorizationScope.project_id == project_id)
    if search:
        pattern = f"%{search[:200]}%"
        query = query.where(
            or_(
                AuthorizationScope.name.ilike(pattern),
                AuthorizationScope.target_value.ilike(pattern),
            )
        )
    if authorized is not None:
        query = query.where(AuthorizationScope.is_authorized.is_(authorized))
    return paginate(db, query.order_by(AuthorizationScope.updated_at.desc()), page, page_size)


@router.post("/projects/{project_id}/scopes", response_model=ScopeResponse, status_code=201)
def create_scope(
    project_id: UUID,
    payload: ScopeCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("scopes.write")),
) -> AuthorizationScope:
    get_or_404(db, Project, project_id, "项目不存在")
    values = payload.model_dump()
    values["target_value"] = _validate_scope(payload.target_type, payload.target_value)
    if payload.expires_at and payload.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="授权到期时间必须晚于当前时间")
    if payload.is_authorized:
        values.update(confirmed_by_id=user.id, authorized_at=datetime.now(UTC))
    scope = AuthorizationScope(project_id=project_id, **values)
    db.add(scope)
    db.flush()
    write_audit(
        db,
        request,
        "scope.create",
        "authorization_scope",
        scope.id,
        user,
        details={"target_type": scope.target_type, "target_value": scope.target_value},
    )
    db.commit()
    db.refresh(scope)
    return scope


@router.patch("/scopes/{scope_id}", response_model=ScopeResponse)
def update_scope(
    scope_id: UUID,
    payload: ScopeUpdate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("scopes.write")),
) -> AuthorizationScope:
    scope = get_or_404(db, AuthorizationScope, scope_id, "授权范围不存在")
    values = payload.model_dump(exclude_unset=True)
    if "target_value" in values:
        values["target_value"] = _validate_scope(scope.target_type, values["target_value"])
    if values.get("is_authorized") is True:
        values.update(confirmed_by_id=user.id, authorized_at=datetime.now(UTC))
    elif values.get("is_authorized") is False:
        values.update(confirmed_by_id=None, authorized_at=None)
    apply_updates(scope, values)
    write_audit(db, request, "scope.update", "authorization_scope", scope.id, user)
    db.commit()
    db.refresh(scope)
    return scope


@router.delete("/scopes/{scope_id}", status_code=204)
def delete_scope(
    scope_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("scopes.write")),
) -> Response:
    scope = get_or_404(db, AuthorizationScope, scope_id, "授权范围不存在")
    write_audit(db, request, "scope.delete", "authorization_scope", scope.id, user)
    db.delete(scope)
    db.commit()
    return Response(status_code=204)
