from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from .model_adapter import ModelAdapterError, invoke_chat_completion, parse_structured_output
from .models import ModelChannel
from .schemas import WebsiteScanAIStructuredOutput
from .scope_guard import guarded_request

MAX_WEBSITE_RESPONSE_BYTES = 1024 * 1024
WEBSITE_MODEL_TIMEOUT_SECONDS = 45
RequestSender = Callable[..., httpx.Response]

_AI_FAILURE_MESSAGES = {
    "channel_unavailable": "所选 AI 渠道不可用；规则体检结果仍然有效。",
    "invalid_response": "AI 响应结构无法验证；规则体检结果仍然有效。",
    "provider_error": "AI 服务拒绝请求或暂时不可用；规则体检结果仍然有效。",
    "scope_denied": "AI 请求未通过授权范围校验；规则体检结果仍然有效。",
    "structured_output": "AI 已响应，但返回格式不符合分析约定；规则体检结果仍然有效。",
    "timeout": "AI 请求超时；规则体检结果仍然有效。",
    "transport_error": "AI 连接失败；规则体检结果仍然有效。",
}


def _render_ai_summary(output: WebsiteScanAIStructuredOutput) -> str:
    priorities = "\n".join(
        f"{index}. {item}" for index, item in enumerate(output.priorities, start=1)
    )
    return (f"{output.summary}\n\n优先修复：\n{priorities}\n\n观察局限：{output.limitations}")[
        :20_000
    ]


def _degraded_ai_analysis(channel: ModelChannel, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ModelAdapterError):
        reason = exc.code if exc.code in _AI_FAILURE_MESSAGES else "invalid_response"
    elif isinstance(exc, httpx.TimeoutException):
        reason = "timeout"
    elif isinstance(exc, httpx.HTTPError):
        reason = "transport_error"
    else:
        reason = "invalid_response"
    return {
        "status": "degraded",
        "model": channel.model,
        "failure_reason": reason,
        "error": _AI_FAILURE_MESSAGES[reason],
    }


class _PassiveHTMLInspector(HTMLParser):
    def __init__(self, target_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.target_url = target_url
        self.password_input = False
        self.cross_origin_form = False
        self.mixed_content = False
        target = urlsplit(target_url)
        self._origin = (target.scheme.lower(), (target.hostname or "").lower(), target.port)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "input" and attributes.get("type", "").lower() == "password":
            self.password_input = True
        if tag.lower() == "form" and attributes.get("action"):
            action = urlsplit(urljoin(self.target_url, attributes["action"]))
            if action.scheme.lower() in {"http", "https"}:
                action_origin = (
                    action.scheme.lower(),
                    (action.hostname or "").lower(),
                    action.port,
                )
                self.cross_origin_form = self.cross_origin_form or action_origin != self._origin
        for attribute in ("src", "href", "action"):
            value = attributes.get(attribute, "").strip().lower()
            if self._origin[0] == "https" and value.startswith("http://"):
                self.mixed_content = True


def _check(
    check_id: str,
    name: str,
    status: str,
    severity: str,
    explanation: str,
    remediation: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": check_id,
        "name": name,
        "status": status,
        "severity": severity,
        "explanation": explanation,
    }
    if remediation:
        value["remediation"] = remediation
    return value


def _security_header_checks(response: httpx.Response, is_https: bool) -> list[dict[str, Any]]:
    headers = response.headers
    checks = []
    policies = (
        (
            "content_security_policy",
            "内容安全策略（CSP）",
            "content-security-policy",
            "配置与业务资源匹配的 Content-Security-Policy，并逐步收紧脚本来源。",
        ),
        (
            "content_type_options",
            "内容类型嗅探防护",
            "x-content-type-options",
            "返回 X-Content-Type-Options: nosniff。",
        ),
        (
            "referrer_policy",
            "来源信息最小化",
            "referrer-policy",
            "按业务需要配置 Referrer-Policy，例如 strict-origin-when-cross-origin。",
        ),
        (
            "permissions_policy",
            "浏览器能力权限策略",
            "permissions-policy",
            "通过 Permissions-Policy 关闭页面不需要的浏览器能力。",
        ),
    )
    for check_id, name, header, remediation in policies:
        present = bool(headers.get(header, "").strip())
        checks.append(
            _check(
                check_id,
                name,
                "passed" if present else "warning",
                "low" if not present else "info",
                f"响应中{'已观察到' if present else '未观察到'} {header}。"
                "缺失仅表示加固机会，不等同于已确认可利用漏洞。",
                None if present else remediation,
            )
        )
    frame_protected = bool(headers.get("x-frame-options", "").strip()) or bool(
        re.search(r"(?:^|;)\s*frame-ancestors\b", headers.get("content-security-policy", ""), re.I)
    )
    checks.append(
        _check(
            "frame_protection",
            "页面嵌入防护",
            "passed" if frame_protected else "warning",
            "low" if not frame_protected else "info",
            "响应中已观察到页面嵌入限制。"
            if frame_protected
            else "未观察到 X-Frame-Options 或 CSP frame-ancestors；这是一项点击劫持加固提示。",
            None
            if frame_protected
            else "配置 CSP frame-ancestors，或在兼容场景下使用 X-Frame-Options。",
        )
    )
    if is_https:
        hsts = bool(headers.get("strict-transport-security", "").strip())
        checks.append(
            _check(
                "hsts",
                "HTTPS 强制策略（HSTS）",
                "passed" if hsts else "warning",
                "low" if not hsts else "info",
                "HTTPS 响应中已观察到 HSTS。"
                if hsts
                else "HTTPS 响应中未观察到 HSTS；这是一项传输层加固提示。",
                None
                if hsts
                else (
                    "确认全站 HTTPS 后配置 Strict-Transport-Security，"
                    "并谨慎评估 includeSubDomains。"
                ),
            )
        )
    else:
        checks.append(
            _check(
                "hsts",
                "HTTPS 强制策略（HSTS）",
                "info",
                "info",
                "HTTP 页面不适用 HSTS 响应检查。",
            )
        )
    return checks


def _cookie_check(response: httpx.Response, is_https: bool) -> dict[str, Any]:
    cookies = response.headers.get_list("set-cookie")
    if not cookies:
        return _check(
            "cookie_attributes",
            "Cookie 安全属性",
            "info",
            "info",
            "本次响应没有设置 Cookie。",
        )
    missing_secure = 0
    missing_http_only = 0
    missing_same_site = 0
    for raw in cookies:
        attributes = {part.strip().split("=", 1)[0].lower() for part in raw.split(";")[1:]}
        missing_secure += int(is_https and "secure" not in attributes)
        missing_http_only += int("httponly" not in attributes)
        missing_same_site += int("samesite" not in attributes)
    insecure = missing_secure + missing_http_only + missing_same_site
    if not insecure:
        return _check(
            "cookie_attributes",
            "Cookie 安全属性",
            "passed",
            "info",
            f"本次响应设置了 {len(cookies)} 个 Cookie，"
            "均观察到适用的 Secure、HttpOnly 和 SameSite 属性。",
        )
    return _check(
        "cookie_attributes",
        "Cookie 安全属性",
        "warning",
        "medium" if missing_secure or missing_http_only else "low",
        f"仅按属性统计：{len(cookies)} 个 Cookie 中，缺少 Secure={missing_secure}、"
        f"HttpOnly={missing_http_only}、SameSite={missing_same_site}。"
        "未保存 Cookie 名称或值。",
        "按用途逐个设置 Secure、HttpOnly 与合适的 SameSite 属性；确认业务兼容性后再上线。",
    )


def _passive_html_checks(target_url: str, response: httpx.Response) -> list[dict[str, Any]]:
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and b"<html" not in response.content[:2048].lower():
        return [
            _check(
                "html_forms",
                "HTML 表单与混合内容",
                "info",
                "info",
                "响应不是 HTML，本项未执行内容分析。",
            )
        ]
    inspector = _PassiveHTMLInspector(target_url)
    try:
        inspector.feed(response.text)
    except (UnicodeError, ValueError):
        return [
            _check(
                "html_forms",
                "HTML 表单与混合内容",
                "info",
                "info",
                "HTML 无法安全解析，本项未形成结论。",
            )
        ]
    is_https = urlsplit(target_url).scheme.lower() == "https"
    checks = []
    cleartext_password = inspector.password_input and not is_https
    checks.append(
        _check(
            "cleartext_password_form",
            "明文密码表单",
            "warning" if cleartext_password else "passed",
            "medium" if cleartext_password else "info",
            "在 HTTP 页面观察到密码输入框；这可能使凭据缺少传输保护。"
            if cleartext_password
            else "未观察到通过明文 HTTP 承载密码输入框。",
            "将登录页及其所有资源和提交地址迁移到 HTTPS。" if cleartext_password else None,
        )
    )
    checks.append(
        _check(
            "cross_origin_form",
            "跨来源表单提交",
            "warning" if inspector.cross_origin_form else "passed",
            "medium" if inspector.cross_origin_form else "info",
            "观察到表单提交地址跨来源；需要人工确认该第三方接收方是否为业务预期。"
            if inspector.cross_origin_form
            else "未观察到跨来源的 HTTP/HTTPS 表单提交。",
            "核对表单 action；非必要时改为同源提交，并对必要的第三方流转进行告知和保护。"
            if inspector.cross_origin_form
            else None,
        )
    )
    checks.append(
        _check(
            "mixed_content",
            "HTTPS 页面混合内容",
            "warning" if inspector.mixed_content else "passed",
            "low" if inspector.mixed_content else "info",
            "HTTPS 页面中观察到 http:// 资源或提交地址。"
            if inspector.mixed_content
            else "未观察到显式 http:// 混合内容引用。",
            "将资源和提交地址升级到 HTTPS，或使用经过确认的相对 URL。"
            if inspector.mixed_content
            else None,
        )
    )
    return checks


def run_passive_website_scan(
    db: Session,
    *,
    target_url: str,
    project_id: UUID,
    request_id: str | None = None,
    request_sender: RequestSender | None = None,
) -> dict[str, Any]:
    """Perform one bounded, read-only GET and derive conservative observations."""

    sender = request_sender or guarded_request
    started = time.perf_counter()
    response = sender(
        db,
        "GET",
        target_url,
        project_id,
        headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"},
        timeout=20,
        max_redirects=0,
        request_id=request_id,
        max_response_bytes=MAX_WEBSITE_RESPONSE_BYTES,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    is_https = urlsplit(target_url).scheme.lower() == "https"
    if 200 <= response.status_code < 400:
        availability_status, availability_severity = "passed", "info"
    elif 400 <= response.status_code < 500:
        availability_status, availability_severity = "warning", "medium"
    else:
        availability_status, availability_severity = "failed", "medium"
    checks = [
        _check(
            "availability",
            "站点可达性",
            availability_status,
            availability_severity,
            f"目标返回 HTTP {response.status_code}，本次只发出一条只读 GET 请求。",
            "检查服务状态、反向代理与应用日志。" if availability_status != "passed" else None,
        ),
        _check(
            "https_transport",
            "HTTPS 传输保护",
            "passed" if is_https else "warning",
            "medium" if not is_https else "info",
            "目标使用 HTTPS。"
            if is_https
            else "目标使用 HTTP；这表示传输未加密，不代表平台尝试了中间人攻击。",
            None if is_https else "为正式环境启用 HTTPS，并将 HTTP 安全重定向到 HTTPS。",
        ),
    ]
    checks.extend(_security_header_checks(response, is_https))
    checks.append(_cookie_check(response, is_https))
    server_value = response.headers.get("server", "")
    powered_by = response.headers.get("x-powered-by", "")
    version_disclosed = bool(re.search(r"\d", server_value) or powered_by.strip())
    checks.append(
        _check(
            "server_version_disclosure",
            "服务端版本信息暴露",
            "warning" if version_disclosed else "passed",
            "low" if version_disclosed else "info",
            "响应头中观察到可能帮助技术指纹识别的产品或版本信息。"
            if version_disclosed
            else "未观察到明显的服务端版本信息。",
            "在不影响运维的前提下隐藏精确版本标识，并依赖及时补丁而非仅隐藏指纹。"
            if version_disclosed
            else None,
        )
    )
    checks.extend(_passive_html_checks(target_url, response))
    penalty = {"critical": 30, "high": 20, "medium": 12, "low": 5, "info": 0}
    deductions = sum(
        penalty.get(str(item["severity"]), 0)
        for item in checks
        if item["status"] in {"warning", "failed"}
    )
    score = float(max(0, 100 - deductions))
    warning_count = sum(item["status"] in {"warning", "failed"} for item in checks)
    explanation = (
        f"规则体检得分 {score:.0f}/100：共执行 {len(checks)} 项只读检查，"
        f"观察到 {warning_count} 项需要复核或加固。分数按已观察到的配置风险扣分；"
        "它不是漏洞可利用性的证明，也不替代人工渗透测试。"
    )
    evidence = {
        "target_url": target_url,
        "method": "GET",
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "response_bytes": len(response.content),
        "body_sha256": hashlib.sha256(response.content).hexdigest(),
        "content_type": response.headers.get("content-type", "")[:200],
        "security_header_presence": {
            name: bool(response.headers.get(name, "").strip())
            for name in (
                "content-security-policy",
                "strict-transport-security",
                "x-content-type-options",
                "x-frame-options",
                "referrer-policy",
                "permissions-policy",
            )
        },
        "set_cookie_count": len(response.headers.get_list("set-cookie")),
        "body_stored": False,
        "cookie_values_stored": False,
    }
    return {
        "checks": checks,
        "security_score": score,
        "score_explanation": explanation,
        "latency_ms": latency_ms,
        "evidence": evidence,
    }


def explain_with_model(
    db: Session,
    *,
    channel: ModelChannel,
    project_id: UUID,
    target_url: str,
    checks: list[dict[str, Any]],
    security_score: float,
    request_id: str | None,
    request_sender: RequestSender | None = None,
) -> dict[str, Any]:
    safe_context = {
        "target": target_url,
        "security_score": security_score,
        "checks": [
            {
                "id": item["id"],
                "name": item["name"],
                "status": item["status"],
                "severity": item["severity"],
                "explanation": item["explanation"],
                "remediation": item.get("remediation"),
            }
            for item in checks
        ],
        "data_policy": (
            "No response body, cookie value, credential, API key, or raw header value is included."
        ),
    }
    try:
        result = invoke_chat_completion(
            db,
            channel,
            project_id,
            (
                "请用简明中文解释这次自有网站的被动规则体检结果，并按优先级给出最多三步修复建议。"
                "不得把缺失安全响应头描述成已确认可利用漏洞，不得建议攻击、爆破、绕过或破坏性操作。"
                "说明这是基于单次只读请求的有限观察。"
                "只返回一个 JSON 对象，不要使用 Markdown 代码块或添加 JSON 前后说明。"
                "对象必须严格包含 summary（字符串）、priorities（1 至 3 个字符串的数组）和"
                "limitations（字符串）三个字段，不得添加其他字段。"
            ),
            context=safe_context,
            request_id=request_id,
            system_prompt=(
                "你是防御型网站安全顾问。你只能解释平台提供的脱敏、只读检查结果；"
                "不得更改规则评分，不得声称执行了漏洞利用，也不得输出攻击载荷。"
            ),
            request_sender=request_sender,
            timeout_seconds=WEBSITE_MODEL_TIMEOUT_SECONDS,
            max_redirects=0,
            json_mode=True,
        )
        output = parse_structured_output(
            result.output,
            WebsiteScanAIStructuredOutput,
            label="网站 AI 分析",
        )
        return {
            "status": "used",
            "model": channel.model,
            "summary": _render_ai_summary(output),
            "priorities": output.priorities,
            "limitations": output.limitations,
            "latency_ms": result.latency_ms,
            "prompt_tokens": int(result.usage.get("prompt_tokens", 0)),
            "completion_tokens": int(result.usage.get("completion_tokens", 0)),
        }
    except (ModelAdapterError, httpx.HTTPError, ValueError) as exc:
        return _degraded_ai_analysis(channel, exc)
