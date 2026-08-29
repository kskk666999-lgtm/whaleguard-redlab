from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Evidence, Finding, Project, Report, TestRun


def generate_report(db: Session, report: Report) -> Report:
    project = db.get(Project, report.project_id)
    if project is None:
        raise ValueError("项目不存在")
    run = db.get(TestRun, report.run_id) if report.run_id else None
    finding_query = select(Finding).where(Finding.project_id == report.project_id)
    evidence_query = select(Evidence).where(Evidence.project_id == report.project_id)
    if report.run_id:
        finding_query = finding_query.where(Finding.run_id == report.run_id)
        evidence_query = evidence_query.where(Evidence.run_id == report.run_id)
    findings = list(db.scalars(finding_query.order_by(Finding.created_at)))
    evidence = list(db.scalars(evidence_query.order_by(Evidence.created_at)))
    generated_at = datetime.now(UTC)
    payload = {
        "schema_version": "1.0",
        "report_id": str(report.id),
        "project": {"id": str(project.id), "name": project.name},
        "run": (
            {
                "id": str(run.id),
                "name": run.name,
                "status": run.status,
                "security_score": run.security_score,
                "score_explanation": run.score_explanation,
            }
            if run
            else None
        ),
        "summary": {
            "finding_count": len(findings),
            "evidence_count": len(evidence),
            "severity": {
                level: sum(1 for finding in findings if finding.severity == level)
                for level in ("critical", "high", "medium", "low", "info")
            },
        },
        "findings": [
            {
                "id": str(finding.id),
                "title": finding.title,
                "category": finding.category,
                "severity": finding.severity,
                "confidence": finding.confidence,
                "affected_target": finding.affected_target,
                "description": finding.description,
                "impact": finding.impact,
                "remediation": finding.remediation,
                "status": finding.status,
            }
            for finding in findings
        ],
        "evidence": [
            {
                "id": str(item.id),
                "type": item.evidence_type,
                "title": item.title,
                "sha256": item.sha256,
                "captured_at": item.captured_at.isoformat(),
            }
            for item in evidence
        ],
        "generated_at": generated_at.isoformat(),
        "notice": "仅用于本地、自有系统或已明确授权目标的安全评估。",
    }
    lines = [
        f"# {report.name}",
        "",
        f"- 项目：{project.name}",
        f"- 生成时间：{generated_at.isoformat()}",
        f"- Findings：{len(findings)}",
        f"- Evidence：{len(evidence)}",
    ]
    if run:
        lines.extend([f"- Security Score：{run.security_score}", ""])
    lines.extend(["## Findings", ""])
    if not findings:
        lines.append("当前范围内没有 Finding。")
    for index, finding in enumerate(findings, start=1):
        lines.extend(
            [
                f"### {index}. {finding.title}",
                "",
                f"- 严重性：{finding.severity}",
                f"- 置信度：{finding.confidence}",
                f"- 状态：{finding.status}",
                "",
                finding.description,
                "",
                f"**影响：** {finding.impact}",
                "",
                f"**修复建议：** {finding.remediation}",
                "",
            ]
        )
    markdown = "\n".join(lines)
    finding_rows = (
        "".join(
            "<tr>"
            f"<td>{escape(item.title)}</td>"
            f"<td>{escape(item.severity)}</td>"
            f"<td>{escape(item.confidence)}</td>"
            f"<td>{escape(item.status)}</td>"
            f"<td>{escape(item.remediation)}</td>"
            "</tr>"
            for item in findings
        )
        or '<tr><td colspan="5">当前范围内没有 Finding。</td></tr>'
    )
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(report.name)}</title><style>
body{{font-family:system-ui,sans-serif;background:#081018;color:#dce7ef;margin:0;padding:32px}}
main{{max-width:1100px;margin:auto}}h1{{color:#5eead4}}.score{{font-size:2rem;font-weight:700}}
table{{width:100%;border-collapse:collapse}}
th,td{{border:1px solid #29404f;padding:10px;text-align:left}}
th{{background:#102533}}small{{color:#91a4b2}}
</style></head><body><main><h1>{escape(report.name)}</h1>
<p>{escape(project.name)} · {escape(generated_at.isoformat())}</p>
<p class="score">Security Score: {escape(str(run.security_score if run else "N/A"))}</p>
<p>Findings: {len(findings)} · Evidence: {len(evidence)}</p>
<h2>Findings</h2><table><thead><tr><th>标题</th><th>严重性</th><th>置信度</th><th>状态</th><th>修复建议</th></tr></thead>
<tbody>{finding_rows}</tbody></table><p><small>{escape(payload["notice"])}</small></p>
</main></body></html>"""
    report.content_json = json.loads(json.dumps(payload, ensure_ascii=False))
    report.content_markdown = markdown
    report.content_html = html
    report.status = "generated"
    report.generated_at = generated_at
    return report
