from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Evidence, Finding, Project, Report, TestRun, WebsiteScan


def _safe_plain_text(value: object) -> str:
    """Normalize untrusted prose while retaining readable line breaks."""

    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    sanitized = "".join(
        character
        if character in {"\n", "\t"} or (ord(character) >= 32 and ord(character) != 127)
        else "�"
        for character in text
    )
    return sanitized or "（模型未返回文字内容）"


def _markdown_plain_text_block(value: object) -> str:
    """Render untrusted model prose as an indented Markdown code block.

    Every physical line is indented, so headings, links, images, HTML and
    backtick fences remain inert text under CommonMark-compatible renderers.
    """

    return "\n".join(f"    {line}" for line in _safe_plain_text(value).split("\n"))


def generate_report(db: Session, report: Report) -> Report:
    project = db.get(Project, report.project_id)
    if project is None:
        raise ValueError("项目不存在")
    run = db.get(TestRun, report.run_id) if report.run_id else None
    website_scan = db.get(WebsiteScan, report.website_scan_id) if report.website_scan_id else None
    finding_query = select(Finding).where(Finding.project_id == report.project_id)
    evidence_query = select(Evidence).where(Evidence.project_id == report.project_id)
    if report.run_id:
        finding_query = finding_query.where(Finding.run_id == report.run_id)
        evidence_query = evidence_query.where(Evidence.run_id == report.run_id)
    if report.website_scan_id:
        finding_query = finding_query.where(Finding.website_scan_id == report.website_scan_id)
        evidence_query = evidence_query.where(Evidence.website_scan_id == report.website_scan_id)
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
        "website_scan": (
            {
                "id": str(website_scan.id),
                "target_url": website_scan.target_url,
                "status": website_scan.status,
                "security_score": website_scan.security_score,
                "score_explanation": website_scan.score_explanation,
                "checks": website_scan.checks,
                "ai_analysis": website_scan.ai_analysis,
                "latency_ms": website_scan.latency_ms,
            }
            if website_scan
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
    if website_scan:
        lines.extend(
            [
                f"- 体检目标：{website_scan.target_url}",
                f"- Security Score：{website_scan.security_score}",
                "",
                "## 评分说明",
                "",
                website_scan.score_explanation,
                "",
            ]
        )
        if website_scan.ai_analysis.get("status") == "used":
            lines.extend(
                [
                    "## AI 辅助解读",
                    "",
                    _markdown_plain_text_block(website_scan.ai_analysis.get("summary", "")),
                    "",
                    "> AI 仅解读脱敏规则结果，不参与改写规则评分或确认漏洞。",
                    "",
                ]
            )
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
    displayed_score = (
        run.security_score if run else website_scan.security_score if website_scan else "N/A"
    )
    website_explanation_html = (
        f"<p>{escape(website_scan.score_explanation)}</p>" if website_scan else ""
    )
    ai_html = ""
    if website_scan and website_scan.ai_analysis.get("status") == "used":
        safe_ai_text = _safe_plain_text(website_scan.ai_analysis.get("summary", ""))
        ai_html = (
            "<h2>AI 辅助解读</h2>"
            f'<pre class="ai-summary">{escape(safe_ai_text)}</pre>'
            "<p><small>AI 仅解读脱敏规则结果，不参与改写规则评分或确认漏洞。</small></p>"
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
.ai-summary{{white-space:pre-wrap;overflow-wrap:anywhere;background:#0d1b24;
padding:12px;border:1px solid #29404f}}
</style></head><body><main><h1>{escape(report.name)}</h1>
<p>{escape(project.name)} · {escape(generated_at.isoformat())}</p>
<p class="score">Security Score: {escape(str(displayed_score))}</p>
{website_explanation_html}
{ai_html}
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
