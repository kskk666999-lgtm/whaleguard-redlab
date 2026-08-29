from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from sqlalchemy import or_, select

from ..audit import write_audit
from ..config import get_settings
from ..dependencies import DB, require_permissions
from ..models import Evidence, Finding, Project, Report, TestRun, User
from ..reports import generate_report
from ..schemas import (
    EvidenceCreate,
    EvidenceResponse,
    FindingCreate,
    FindingResponse,
    FindingUpdate,
    Page,
    ReportCreate,
    ReportResponse,
)
from ..security import redact
from .common import apply_updates, get_or_404, paginate

router = APIRouter(tags=["Findings、证据与报告"])
ALLOWED_UPLOAD_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "application/json": ".json",
}


def _hash_json(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _validate_upload_content(media_type: str, data: bytes) -> None:
    if not data:
        raise HTTPException(status_code=422, detail="附件不能为空")
    if media_type == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=415, detail="PNG 文件签名无效")
    if media_type == "image/jpeg" and not data.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=415, detail="JPEG 文件签名无效")
    if media_type == "application/pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="PDF 文件签名无效")
    if media_type == "application/json":
        try:
            json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=415, detail="JSON 附件内容无效") from exc
    if media_type == "text/plain":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="文本附件必须使用 UTF-8") from exc
        if "\x00" in text:
            raise HTTPException(status_code=415, detail="文本附件包含二进制空字节")


@router.get("/findings", response_model=Page[FindingResponse])
def list_findings(
    db: DB,
    _user: User = Depends(require_permissions("findings.read")),
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    search: str | None = None,
    severity: str | None = None,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[FindingResponse]:
    query = select(Finding).order_by(Finding.created_at.desc())
    if project_id:
        query = query.where(Finding.project_id == project_id)
    if run_id:
        query = query.where(Finding.run_id == run_id)
    if search:
        pattern = f"%{search[:200]}%"
        query = query.where(or_(Finding.title.ilike(pattern), Finding.description.ilike(pattern)))
    if severity:
        query = query.where(Finding.severity == severity)
    if status_filter:
        query = query.where(Finding.status == status_filter)
    return paginate(db, query, page, page_size)


@router.post("/findings", response_model=FindingResponse, status_code=201)
def create_finding(
    payload: FindingCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("findings.write")),
) -> Finding:
    get_or_404(db, Project, payload.project_id, "项目不存在")
    if payload.run_id:
        run = get_or_404(db, TestRun, payload.run_id, "测试运行不存在")
        if run.project_id != payload.project_id:
            raise HTTPException(status_code=422, detail="测试运行不属于该项目")
    finding = Finding(**payload.model_dump())
    db.add(finding)
    db.flush()
    write_audit(db, request, "finding.create", "finding", finding.id, user)
    db.commit()
    db.refresh(finding)
    return finding


@router.get("/findings/{finding_id}", response_model=FindingResponse)
def get_finding(
    finding_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("findings.read")),
) -> Finding:
    return get_or_404(db, Finding, finding_id, "Finding 不存在")


@router.patch("/findings/{finding_id}", response_model=FindingResponse)
def update_finding(
    finding_id: UUID,
    payload: FindingUpdate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("findings.write")),
) -> Finding:
    finding = get_or_404(db, Finding, finding_id, "Finding 不存在")
    changes = payload.model_dump(exclude_unset=True)
    apply_updates(finding, changes)
    write_audit(
        db,
        request,
        "finding.update",
        "finding",
        finding.id,
        user,
        details={"changed_fields": sorted(changes)},
    )
    db.commit()
    db.refresh(finding)
    return finding


@router.delete("/findings/{finding_id}", status_code=204)
def delete_finding(
    finding_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("findings.delete")),
) -> Response:
    finding = get_or_404(db, Finding, finding_id, "Finding 不存在")
    write_audit(db, request, "finding.delete", "finding", finding.id, user)
    db.delete(finding)
    db.commit()
    return Response(status_code=204)


@router.get("/evidence", response_model=Page[EvidenceResponse])
def list_evidence(
    db: DB,
    _user: User = Depends(require_permissions("evidence.read")),
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    finding_id: UUID | None = None,
    evidence_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[EvidenceResponse]:
    query = select(Evidence).order_by(Evidence.captured_at.desc())
    if project_id:
        query = query.where(Evidence.project_id == project_id)
    if run_id:
        query = query.where(Evidence.run_id == run_id)
    if finding_id:
        query = query.where(Evidence.finding_id == finding_id)
    if evidence_type:
        query = query.where(Evidence.evidence_type == evidence_type)
    return paginate(db, query, page, page_size)


@router.post("/evidence", response_model=EvidenceResponse, status_code=201)
def create_evidence(
    payload: EvidenceCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("evidence.write")),
) -> Evidence:
    get_or_404(db, Project, payload.project_id, "项目不存在")
    if payload.finding_id:
        finding = get_or_404(db, Finding, payload.finding_id, "Finding 不存在")
        if finding.project_id != payload.project_id:
            raise HTTPException(status_code=422, detail="Finding 不属于该项目")
    safe_content = redact(payload.content)
    evidence = Evidence(
        **payload.model_dump(exclude={"content"}),
        content=safe_content,
        sha256=_hash_json(safe_content),
    )
    db.add(evidence)
    db.flush()
    write_audit(db, request, "evidence.create", "evidence", evidence.id, user)
    db.commit()
    db.refresh(evidence)
    return evidence


@router.post("/evidence/upload", response_model=EvidenceResponse, status_code=201)
async def upload_evidence(
    request: Request,
    db: DB,
    project_id: UUID,
    title: str,
    file: UploadFile = File(...),
    finding_id: UUID | None = None,
    run_id: UUID | None = None,
    user: User = Depends(require_permissions("evidence.write")),
) -> Evidence:
    get_or_404(db, Project, project_id, "项目不存在")
    if finding_id:
        finding = get_or_404(db, Finding, finding_id, "Finding 不存在")
        if finding.project_id != project_id:
            raise HTTPException(status_code=422, detail="Finding 不属于该项目")
    if run_id:
        run = get_or_404(db, TestRun, run_id, "测试运行不存在")
        if run.project_id != project_id:
            raise HTTPException(status_code=422, detail="测试运行不属于该项目")
    settings = get_settings()
    media_type = (file.content_type or "").lower()
    if media_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=415, detail="不支持的附件类型")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="附件超过大小限制")
    _validate_upload_content(media_type, data)
    original = Path(file.filename or "attachment").name
    safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(original).stem)[:80] or "attachment"
    filename = f"{uuid4()}-{safe_stem}{ALLOWED_UPLOAD_TYPES[media_type]}"
    root = Path(settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / filename).resolve()
    if root not in target.parents:
        raise HTTPException(status_code=400, detail="附件路径无效")
    target.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    evidence = Evidence(
        project_id=project_id,
        finding_id=finding_id,
        run_id=run_id,
        evidence_type="screenshot" if media_type.startswith("image/") else "attachment",
        title=title[:240],
        content={"original_filename": original, "size": len(data)},
        request_id=getattr(request.state, "request_id", None),
        attachment_path=filename,
        media_type=media_type,
        sha256=digest,
    )
    db.add(evidence)
    db.flush()
    write_audit(
        db,
        request,
        "evidence.upload",
        "evidence",
        evidence.id,
        user,
        details={"media_type": media_type, "size": len(data), "sha256": digest},
    )
    db.commit()
    db.refresh(evidence)
    return evidence


@router.get("/evidence/{evidence_id}", response_model=EvidenceResponse)
def get_evidence(
    evidence_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("evidence.read")),
) -> Evidence:
    return get_or_404(db, Evidence, evidence_id, "证据不存在")


@router.get("/evidence/{evidence_id}/attachment")
def download_evidence_attachment(
    evidence_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("evidence.read")),
):
    evidence = get_or_404(db, Evidence, evidence_id, "证据不存在")
    if not evidence.attachment_path or not evidence.media_type:
        raise HTTPException(status_code=404, detail="证据没有附件")
    root = Path(get_settings().upload_dir).resolve()
    target = (root / evidence.attachment_path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="附件不存在")
    if hashlib.sha256(target.read_bytes()).hexdigest() != evidence.sha256:
        raise HTTPException(status_code=409, detail="附件完整性校验失败")
    write_audit(db, request, "evidence.download", "evidence", evidence.id, user)
    db.commit()
    return FileResponse(
        target,
        media_type=evidence.media_type,
        filename=Path(evidence.attachment_path).name,
    )


@router.get("/reports", response_model=Page[ReportResponse])
def list_reports(
    db: DB,
    _user: User = Depends(require_permissions("reports.read")),
    project_id: UUID | None = None,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[ReportResponse]:
    query = select(Report).order_by(Report.updated_at.desc())
    if project_id:
        query = query.where(Report.project_id == project_id)
    if status_filter:
        query = query.where(Report.status == status_filter)
    return paginate(db, query, page, page_size)


@router.post("/reports", response_model=ReportResponse, status_code=201)
def create_report(
    payload: ReportCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("reports.write")),
) -> Report:
    get_or_404(db, Project, payload.project_id, "项目不存在")
    report = Report(**payload.model_dump(), generated_by_id=user.id)
    db.add(report)
    db.flush()
    write_audit(db, request, "report.create", "report", report.id, user)
    db.commit()
    db.refresh(report)
    return report


@router.get("/reports/{report_id}", response_model=ReportResponse)
def get_report(
    report_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("reports.read")),
) -> Report:
    return get_or_404(db, Report, report_id, "报告不存在")


@router.post("/reports/{report_id}/generate", response_model=ReportResponse)
def build_report(
    report_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("reports.write")),
) -> Report:
    report = get_or_404(db, Report, report_id, "报告不存在")
    generate_report(db, report)
    write_audit(db, request, "report.generate", "report", report.id, user)
    db.commit()
    db.refresh(report)
    return report


@router.get("/reports/{report_id}/download")
def download_report(
    report_id: UUID,
    request: Request,
    db: DB,
    format: str = "html",
    user: User = Depends(require_permissions("reports.export")),
):
    report = get_or_404(db, Report, report_id, "报告不存在")
    if report.status != "generated":
        raise HTTPException(status_code=409, detail="报告尚未生成")
    write_audit(
        db,
        request,
        "report.export",
        "report",
        report.id,
        user,
        details={"format": format},
    )
    db.commit()
    headers = {"Content-Disposition": f'attachment; filename="whaleguard-{report.id}.{format}"'}
    if format == "html" and report.content_html is not None:
        return HTMLResponse(report.content_html, headers=headers)
    if format == "markdown" and report.content_markdown is not None:
        headers["Content-Disposition"] = f'attachment; filename="whaleguard-{report.id}.md"'
        return PlainTextResponse(
            report.content_markdown, media_type="text/markdown", headers=headers
        )
    if format == "json":
        headers["Content-Disposition"] = f'attachment; filename="whaleguard-{report.id}.json"'
        return JSONResponse(report.content_json, headers=headers)
    raise HTTPException(status_code=422, detail="不支持的报告格式")
