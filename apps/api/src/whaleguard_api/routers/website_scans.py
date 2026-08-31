from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ..audit import write_audit
from ..dependencies import DB, require_permissions, user_permissions
from ..models import Evidence, Finding, ModelChannel, Project, Report, User, WebsiteScan
from ..reports import generate_report
from ..schemas import Page, WebsiteScanAIRegenerate, WebsiteScanCreate, WebsiteScanResponse
from ..scope_authorization import ensure_temporary_exact_url_scope, normalize_exact_url
from ..scope_guard import ScopeDenied
from ..security import redact
from ..website_scanner import explain_with_model, run_passive_website_scan
from .common import get_or_404, paginate

router = APIRouter(tags=["自有网站体检"])
WEBSITE_SCAN_STALE_AFTER = timedelta(minutes=5)
BEGINNER_SCAN_PROJECT_NAME = "我的网站体检"


def _hash_json(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _beginner_scan_project(db: DB, request: Request, user: User) -> Project:
    if not user.is_superuser and "projects.write" not in user_permissions(user):
        raise HTTPException(status_code=403, detail="自动创建体检项目需要项目管理权限")
    project = db.scalar(
        select(Project)
        .where(
            Project.owner_id == user.id,
            Project.name == BEGINNER_SCAN_PROJECT_NAME,
            Project.status == "active",
        )
        .order_by(Project.created_at)
    )
    if project is not None:
        return project
    project = Project(
        name=BEGINNER_SCAN_PROJECT_NAME,
        description="由新手网站体检向导自动建立，用于隔离授权范围、证据与报告。",
        status="active",
        owner_id=user.id,
        tags=["website-scan", "beginner-wizard"],
    )
    db.add(project)
    db.flush()
    write_audit(
        db,
        request,
        "project.create",
        "project",
        project.id,
        user,
        details={"source": "website_scan_wizard"},
    )
    return project


def _reconcile_stale_scans(db: DB, request: Request, actor: User) -> int:
    """Fail interrupted synchronous scans when a user next reads the scan center."""

    cutoff = datetime.now(UTC) - WEBSITE_SCAN_STALE_AFTER
    stale = list(
        db.scalars(
            select(WebsiteScan).where(
                WebsiteScan.status == "running",
                WebsiteScan.started_at.is_not(None),
                WebsiteScan.started_at < cutoff,
            )
        )
    )
    for scan in stale:
        scan.status = "failed"
        scan.error_summary = "网站体检进程中断或超过恢复窗口；请确认目标状态后重试。"
        scan.score_explanation = "网站体检未完整完成，平台已自动结束遗留任务。"
        scan.completed_at = datetime.now(UTC)
        write_audit(
            db,
            request,
            "website_scan.stale_recovered",
            "website_scan",
            scan.id,
            actor,
            outcome="failed",
            details={"stale_after_seconds": int(WEBSITE_SCAN_STALE_AFTER.total_seconds())},
        )
    if stale:
        db.commit()
    return len(stale)


def _scan_response(db: DB, scan: WebsiteScan) -> WebsiteScanResponse:
    findings = list(
        db.scalars(
            select(Finding)
            .where(Finding.website_scan_id == scan.id)
            .order_by(Finding.created_at, Finding.id)
        )
    )
    evidence = db.scalar(
        select(Evidence)
        .where(Evidence.website_scan_id == scan.id)
        .order_by(Evidence.created_at, Evidence.id)
    )
    report = db.scalar(
        select(Report).where(Report.website_scan_id == scan.id).order_by(Report.created_at.desc())
    )
    return WebsiteScanResponse(
        id=scan.id,
        created_at=scan.created_at,
        updated_at=scan.updated_at,
        project_id=scan.project_id,
        target_url=scan.target_url,
        status=scan.status,
        security_score=scan.security_score,
        score_explanation=scan.score_explanation,
        checks=scan.checks,
        finding_count=len(findings),
        finding_ids=[item.id for item in findings],
        evidence_id=evidence.id if evidence else None,
        report_id=report.id if report else None,
        ai_analysis=scan.ai_analysis or {"status": "not_requested"},
        latency_ms=scan.latency_ms,
        model_channel_id=scan.model_channel_id,
        requested_by_id=scan.requested_by_id,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        error_summary=scan.error_summary,
    )


def _finding_from_check(
    *,
    project_id: UUID,
    scan_id: UUID,
    target_url: str,
    check: dict,
    owner_id: UUID,
) -> Finding:
    return Finding(
        project_id=project_id,
        website_scan_id=scan_id,
        title=f"网站体检：{str(check['name'])[:280]}",
        category=f"website_hardening.{str(check['id'])[:80]}",
        severity=str(check["severity"]),
        confidence="high",
        affected_target=target_url[:300],
        description=(
            f"被动检查观察：{check['explanation']} "
            "该结论来自单次只读请求，仅表示需要复核或加固，不代表已确认可利用漏洞。"
        ),
        reproduction_summary=(
            "在已确认授权范围内对目标发出一条只读 GET 请求，并检查返回状态、"
            "安全响应头及公开 HTML 元数据；未提交表单、未爆破、未利用漏洞。"
        ),
        impact=(
            "若该配置与实际部署一致，可能降低浏览器侧或传输层防护。"
            "实际影响取决于业务、认证方式和其他补偿控制，需要人工确认。"
        ),
        remediation=str(check.get("remediation") or "结合业务场景复核并采用最小化加固配置。"),
        status="open",
        owner_id=owner_id,
        tags=["website-scan", "passive", "hardening", str(check["id"])[:80]],
    )


@router.get("/website-scans", response_model=Page[WebsiteScanResponse])
def list_website_scans(
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("runs.read")),
    project_id: UUID | None = None,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[WebsiteScanResponse]:
    _reconcile_stale_scans(db, request, user)
    query = select(WebsiteScan).order_by(WebsiteScan.created_at.desc())
    if project_id:
        query = query.where(WebsiteScan.project_id == project_id)
    if status_filter:
        query = query.where(WebsiteScan.status == status_filter[:32])
    result = paginate(db, query, page, page_size)
    result.items = [_scan_response(db, item) for item in result.items]
    return result


@router.get("/website-scans/{scan_id}", response_model=WebsiteScanResponse)
def get_website_scan(
    scan_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("runs.read")),
) -> WebsiteScanResponse:
    _reconcile_stale_scans(db, request, user)
    return _scan_response(db, get_or_404(db, WebsiteScan, scan_id, "网站体检记录不存在"))


@router.post("/website-scans/{scan_id}/ai-analysis", response_model=WebsiteScanResponse)
def regenerate_website_scan_ai_analysis(
    scan_id: UUID,
    payload: WebsiteScanAIRegenerate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("runs.execute", "models.test")),
) -> WebsiteScanResponse:
    """Regenerate only the optional explanation; never request the target again."""

    scan = get_or_404(db, WebsiteScan, scan_id, "网站体检记录不存在")
    if scan.status != "completed" or scan.security_score is None or not scan.checks:
        raise HTTPException(status_code=409, detail="规则体检尚未完成，不能重新生成 AI 解读")
    channel_id = payload.model_channel_id or scan.model_channel_id
    if channel_id is None:
        raise HTTPException(status_code=422, detail="请选择一个已连接的模型渠道")
    channel = get_or_404(db, ModelChannel, channel_id, "模型渠道不存在")
    if not channel.enabled:
        raise HTTPException(status_code=409, detail="模型渠道已禁用")
    if channel.project_id not in {None, scan.project_id}:
        raise HTTPException(status_code=422, detail="模型渠道不属于该体检项目或全局渠道")

    scan.ai_analysis = explain_with_model(
        db,
        channel=channel,
        project_id=scan.project_id,
        target_url=scan.target_url,
        checks=scan.checks,
        security_score=scan.security_score,
        request_id=getattr(request.state, "request_id", None),
    )
    scan.model_channel_id = channel.id
    write_audit(
        db,
        request,
        "website_scan.ai_analysis.regenerate",
        "website_scan",
        scan.id,
        user,
        outcome="success" if scan.ai_analysis.get("status") == "used" else "failed",
        details={
            "model_channel_id": str(channel.id),
            "ai_status": scan.ai_analysis.get("status"),
            "failure_reason": scan.ai_analysis.get("failure_reason"),
            "target_requested_again": False,
        },
    )
    db.commit()
    db.refresh(scan)
    return _scan_response(db, scan)


@router.post("/website-scans", response_model=WebsiteScanResponse, status_code=201)
def create_website_scan(
    payload: WebsiteScanCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("runs.execute", "scopes.write")),
) -> WebsiteScanResponse:
    channel = None
    if payload.model_channel_id:
        channel = get_or_404(db, ModelChannel, payload.model_channel_id, "模型渠道不存在")
        if not channel.enabled:
            raise HTTPException(status_code=409, detail="模型渠道已禁用")

    if payload.project_id:
        project = get_or_404(db, Project, payload.project_id, "项目不存在")
    elif channel is not None and channel.project_id is not None:
        project = get_or_404(db, Project, channel.project_id, "模型渠道所属项目不存在")
    else:
        project = _beginner_scan_project(db, request, user)
    if project.status != "active":
        raise HTTPException(status_code=409, detail="归档项目不能运行网站体检")
    try:
        target_url = normalize_exact_url(str(payload.target_url))
    except ScopeDenied as exc:
        write_audit(
            db,
            request,
            "website_scan.request_rejected",
            "project",
            project.id,
            user,
            outcome="blocked",
            details={"reason": str(exc)[:300]},
        )
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)[:300]) from exc
    if channel is not None:
        if channel.project_id not in {None, project.id}:
            raise HTTPException(status_code=422, detail="模型渠道不属于该项目或全局渠道")

    scan = WebsiteScan(
        project_id=project.id,
        target_url=target_url,
        status="running",
        ai_analysis={"status": "not_requested"},
        model_channel_id=channel.id if channel else None,
        requested_by_id=user.id,
        started_at=datetime.now(UTC),
    )
    db.add(scan)
    db.flush()
    host = urlsplit(target_url).hostname or "target"
    scope, created = ensure_temporary_exact_url_scope(
        db,
        project_id=project.id,
        target_url=target_url,
        actor=user,
        name=f"一键网站体检授权：{host}",
        notes="由用户在网站体检页面明确确认；仅授权该精确 URL 路径，24 小时后自动到期。",
        lifetime=timedelta(hours=24),
    )
    write_audit(
        db,
        request,
        "website_scan.scope_confirmed",
        "authorization_scope",
        scope.id,
        user,
        details={
            "target_url": target_url,
            "expires_at": scope.expires_at.isoformat() if scope.expires_at else None,
            "created": created,
            "website_scan_id": str(scan.id),
        },
    )
    write_audit(
        db,
        request,
        "website_scan.run",
        "website_scan",
        scan.id,
        user,
        outcome="started",
        details={
            "target_url": target_url,
            "model_channel_id": str(scan.model_channel_id) if scan.model_channel_id else None,
            "safety_level": payload.safety_level,
        },
    )
    db.commit()
    request_id = getattr(request.state, "request_id", None)
    stage = "passive_rules"
    try:
        assessment = run_passive_website_scan(
            db,
            target_url=target_url,
            project_id=project.id,
            request_id=request_id,
        )
        scan.checks = assessment["checks"]
        scan.security_score = assessment["security_score"]
        scan.score_explanation = assessment["score_explanation"]
        scan.latency_ms = assessment["latency_ms"]
        for check in scan.checks:
            if check["status"] in {"warning", "failed"} and check["severity"] != "info":
                db.add(
                    _finding_from_check(
                        project_id=scan.project_id,
                        scan_id=scan.id,
                        target_url=target_url,
                        check=check,
                        owner_id=user.id,
                    )
                )
        safe_evidence = redact(assessment["evidence"])
        evidence = Evidence(
            project_id=scan.project_id,
            website_scan_id=scan.id,
            evidence_type="http_observation",
            title="网站体检脱敏 HTTP 观察证据",
            content=safe_evidence,
            request_id=request_id,
            response_summary=(
                f"单次只读 GET 完成；HTTP {safe_evidence['status_code']}；"
                "未保存响应正文、Cookie 值或凭据。"
            ),
            sha256=_hash_json(safe_evidence),
        )
        db.add(evidence)
        db.flush()
        if channel:
            stage = "ai_explanation"
            scan.ai_analysis = explain_with_model(
                db,
                channel=channel,
                project_id=scan.project_id,
                target_url=target_url,
                checks=scan.checks,
                security_score=scan.security_score,
                request_id=request_id,
            )
        scan.status = "completed"
        scan.completed_at = datetime.now(UTC)
        db.flush()
        if payload.generate_report:
            stage = "report_generation"
            report = Report(
                project_id=scan.project_id,
                website_scan_id=scan.id,
                name=f"网站体检报告 - {host}"[:240],
                formats=["html", "markdown", "json"],
                generated_by_id=user.id,
            )
            db.add(report)
            db.flush()
            generate_report(db, report)
        write_audit(
            db,
            request,
            "website_scan.run",
            "website_scan",
            scan.id,
            user,
            details={
                "status": scan.status,
                "security_score": scan.security_score,
                "ai_status": scan.ai_analysis.get("status"),
            },
        )
        db.commit()
        db.refresh(scan)
        return _scan_response(db, scan)
    except ScopeDenied as exc:
        scan.status = "failed"
        scan.error_summary = str(exc)[:500]
        scan.score_explanation = "Scope Guard 拒绝了目标，未完成网站体检。"
        scan.completed_at = datetime.now(UTC)
        write_audit(
            db,
            request,
            "website_scan.run",
            "website_scan",
            scan.id,
            user,
            outcome="blocked",
            details={"reason": scan.error_summary},
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail=f"Scope Guard 已阻止请求：{str(exc)[:300]}",
        ) from exc
    except httpx.HTTPError as exc:
        scan.status = "failed"
        scan.error_summary = "目标连接失败或返回无效响应。"
        scan.score_explanation = "目标连接失败，未完成网站体检。"
        scan.completed_at = datetime.now(UTC)
        write_audit(
            db,
            request,
            "website_scan.run",
            "website_scan",
            scan.id,
            user,
            outcome="failed",
            details={"error_type": type(exc).__name__},
        )
        db.commit()
        raise HTTPException(status_code=502, detail="目标连接失败，网站体检未完成") from exc
    except Exception as exc:
        db.rollback()
        failed_scan = db.get(WebsiteScan, scan.id)
        if failed_scan is not None:
            failed_scan.status = "failed"
            failed_scan.error_summary = "网站体检内部步骤失败；未保存异常细节。"
            failed_scan.score_explanation = "网站体检未完整完成，请稍后重试或查看审计日志。"
            failed_scan.completed_at = datetime.now(UTC)
            write_audit(
                db,
                request,
                "website_scan.run",
                "website_scan",
                failed_scan.id,
                user,
                outcome="failed",
                details={"stage": stage},
            )
            db.commit()
        raise HTTPException(status_code=500, detail="网站体检内部步骤失败，请稍后重试") from exc
