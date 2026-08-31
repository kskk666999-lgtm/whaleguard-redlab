from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from whaleguard_api.database import SessionLocal
from whaleguard_api.models import (
    AuditLog,
    AuthorizationScope,
    ModelChannel,
    Permission,
    Project,
    Role,
    User,
    WebsiteScan,
)
from whaleguard_api.routers import website_scans as website_scan_router
from whaleguard_api.scope_authorization import normalize_exact_url
from whaleguard_api.scope_guard import ScopeDenied
from whaleguard_api.security import encrypt_secret, hash_password
from whaleguard_api.website_scanner import explain_with_model, run_passive_website_scan


def _assessment() -> dict:
    return {
        "checks": [
            {
                "id": "content_security_policy",
                "name": "内容安全策略（CSP）",
                "status": "warning",
                "severity": "low",
                "explanation": "未观察到 CSP；这是加固机会，不是已确认可利用漏洞。",
                "remediation": "配置与业务匹配的 CSP。",
            },
            {
                "id": "mixed_content",
                "name": "HTTPS 页面混合内容",
                "status": "passed",
                "severity": "info",
                "explanation": "未观察到混合内容。",
            },
        ],
        "security_score": 95.0,
        "score_explanation": "规则体检得分 95/100；缺失头仅作为加固提示。",
        "latency_ms": 12,
        "evidence": {
            "target_url": "http://127.0.0.1:8102/demo-site",
            "method": "GET",
            "status_code": 200,
            "latency_ms": 12,
            "response_bytes": 128,
            "body_sha256": "a" * 64,
            "content_type": "text/html",
            "security_header_presence": {"content-security-policy": False},
            "set_cookie_count": 1,
            "body_stored": False,
            "cookie_values_stored": False,
        },
    }


def test_stale_website_scan_is_recovered_on_read(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
) -> None:
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        scan = WebsiteScan(
            project_id=UUID(project_id),
            target_url="http://127.0.0.1:8102/stale-demo-site",
            status="running",
            requested_by_id=admin.id,
            started_at=datetime.now(UTC) - timedelta(minutes=6),
        )
        db.add(scan)
        db.commit()
        scan_id = scan.id

    response = client.get(f"/api/v1/website-scans/{scan_id}", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert "自动结束遗留任务" in response.json()["score_explanation"]
    with SessionLocal() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "website_scan.stale_recovered",
                AuditLog.resource_id == str(scan_id),
            )
        )
        assert audit is not None


def test_passive_scanner_is_single_get_bounded_and_preserves_cross_origin_finding() -> None:
    calls: list[dict] = []
    html = b"""
    <html><body>
      <form action="https://collector.example/receive"><input type="password"></form>
      <form action="/same-origin"><input type="text"></form>
      <script src="http://assets.example/demo.js"></script>
    </body></html>
    """

    def sender(_db, method, url, _project_id, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            headers={
                "content-type": "text/html; charset=utf-8",
                "server": "DemoServer/1.2",
                "set-cookie": "session=fake-demo; Path=/",
            },
            content=html,
        )

    with SessionLocal() as db:
        result = run_passive_website_scan(
            db,
            target_url="https://127.0.0.1/demo-site",
            project_id=UUID(int=1),
            request_sender=sender,
        )

    assert len(calls) == 1
    assert calls[0]["method"] == "GET"
    assert calls[0]["max_response_bytes"] == 1024 * 1024
    assert calls[0]["max_redirects"] == 0
    by_id = {item["id"]: item for item in result["checks"]}
    assert by_id["cross_origin_form"]["status"] == "warning"
    assert by_id["mixed_content"]["status"] == "warning"
    assert by_id["cookie_attributes"]["status"] == "warning"
    serialized = json.dumps(result["evidence"])
    assert "session=fake-demo" not in serialized
    assert result["evidence"]["body_stored"] is False


def test_real_model_key_is_used_only_in_transport_for_sanitized_explanation(
    project_id: str,
) -> None:
    seen: dict = {}

    def sender(_db, method, url, _project_id, **kwargs):
        seen.update({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            headers={"x-request-id": "model-fixture"},
            json={
                "id": "chatcmpl-fixture",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "当前优先补齐传输和响应头保护。",
                                    "priorities": [
                                        "先启用 HTTPS。",
                                        "再逐项收紧安全响应头。",
                                    ],
                                    "limitations": "结论仅来自一次只读请求。",
                                },
                                ensure_ascii=False,
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            },
        )

    with SessionLocal() as db:
        channel = ModelChannel(
            project_id=UUID(project_id),
            name="Website AI fixture",
            provider="openai-compatible",
            base_url="https://model.example/v1",
            api_key_encrypted=encrypt_secret("wg-real-key-fixture"),
            model="fixture-model",
            timeout=300,
            enabled=True,
        )
        db.add(channel)
        db.flush()
        analysis = explain_with_model(
            db,
            channel=channel,
            project_id=UUID(project_id),
            target_url="https://owned.example/",
            checks=_assessment()["checks"],
            security_score=95,
            request_id="website-ai-fixture",
            request_sender=sender,
        )

    assert analysis == {
        "status": "used",
        "model": "fixture-model",
        "summary": (
            "当前优先补齐传输和响应头保护。\n\n优先修复：\n"
            "1. 先启用 HTTPS。\n2. 再逐项收紧安全响应头。\n\n"
            "观察局限：结论仅来自一次只读请求。"
        ),
        "priorities": ["先启用 HTTPS。", "再逐项收紧安全响应头。"],
        "limitations": "结论仅来自一次只读请求。",
        "latency_ms": analysis["latency_ms"],
        "prompt_tokens": 20,
        "completion_tokens": 10,
    }
    assert seen["method"] == "POST"
    assert seen["timeout"] == 45
    assert seen["max_redirects"] == 0
    assert seen["json_body"]["response_format"] == {"type": "json_object"}
    assert seen["headers"]["Authorization"] == "Bearer wg-real-key-fixture"
    encoded_body = json.dumps(seen["json_body"], ensure_ascii=False)
    assert "wg-real-key-fixture" not in encoded_body
    assert "session=fake-demo" not in encoded_body
    assert "No response body, cookie value" in encoded_body


def test_model_failure_degrades_without_exposing_transport_error(project_id: str) -> None:
    def sender(_db, _method, url, _project_id, **_kwargs):
        request = httpx.Request("POST", url)
        raise httpx.ConnectError("provider-secret-diagnostic", request=request)

    with SessionLocal() as db:
        channel = ModelChannel(
            project_id=UUID(project_id),
            name="Degraded AI fixture",
            provider="openai-compatible",
            base_url="https://model.example/v1",
            api_key_encrypted=encrypt_secret("wg-degraded-key-fixture"),
            model="fixture-model",
            enabled=True,
        )
        db.add(channel)
        db.flush()
        analysis = explain_with_model(
            db,
            channel=channel,
            project_id=UUID(project_id),
            target_url="https://owned.example/",
            checks=_assessment()["checks"],
            security_score=95,
            request_id="website-ai-degraded-fixture",
            request_sender=sender,
        )
    assert analysis["status"] == "degraded"
    assert analysis["failure_reason"] == "transport_error"
    assert "规则体检结果仍然有效" in analysis["error"]
    assert "provider-secret-diagnostic" not in json.dumps(analysis)


def test_model_timeout_degrades_with_sanitized_reason_and_preserves_checks(
    project_id: str,
) -> None:
    original_checks = _assessment()["checks"]
    snapshot = json.loads(json.dumps(original_checks, ensure_ascii=False))

    def sender(_db, _method, url, _project_id, **_kwargs):
        request = httpx.Request("POST", url)
        raise httpx.ReadTimeout("timeout-secret-diagnostic", request=request)

    with SessionLocal() as db:
        channel = ModelChannel(
            project_id=UUID(project_id),
            name="Timeout AI fixture",
            provider="deepseek-compatible",
            base_url="https://model.example/v1",
            api_key_encrypted=encrypt_secret("wg-timeout-key-fixture"),
            model="fixture-model",
            enabled=True,
        )
        db.add(channel)
        db.flush()
        analysis = explain_with_model(
            db,
            channel=channel,
            project_id=UUID(project_id),
            target_url="https://owned.example/",
            checks=original_checks,
            security_score=95,
            request_id="website-ai-timeout-fixture",
            request_sender=sender,
        )

    assert analysis["status"] == "degraded"
    assert analysis["failure_reason"] == "timeout"
    assert "timeout-secret-diagnostic" not in json.dumps(analysis)
    assert original_checks == snapshot


def test_model_provider_error_and_malformed_output_are_safely_classified(
    project_id: str,
) -> None:
    responses = iter(
        [
            httpx.Response(
                429,
                json={"error": "provider-secret-diagnostic-must-not-leak"},
            ),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"summary":"missing required fields",'
                                    '"private":"provider-secret-output"}'
                                )
                            }
                        }
                    ]
                },
            ),
        ]
    )

    def sender(*_args, **_kwargs):
        return next(responses)

    with SessionLocal() as db:
        channel = ModelChannel(
            project_id=UUID(project_id),
            name="Provider error AI fixture",
            provider="deepseek-compatible",
            base_url="https://model.example/v1",
            api_key_encrypted=encrypt_secret("wg-provider-key-fixture"),
            model="fixture-model",
            enabled=True,
        )
        db.add(channel)
        db.flush()
        provider_error = explain_with_model(
            db,
            channel=channel,
            project_id=UUID(project_id),
            target_url="https://owned.example/",
            checks=_assessment()["checks"],
            security_score=95,
            request_id="website-ai-provider-error-fixture",
            request_sender=sender,
        )
        malformed = explain_with_model(
            db,
            channel=channel,
            project_id=UUID(project_id),
            target_url="https://owned.example/",
            checks=_assessment()["checks"],
            security_score=95,
            request_id="website-ai-malformed-fixture",
            request_sender=sender,
        )

    assert provider_error["failure_reason"] == "provider_error"
    assert malformed["failure_reason"] == "structured_output"
    serialized = json.dumps([provider_error, malformed], ensure_ascii=False)
    assert "provider-secret" not in serialized


def test_website_scan_api_creates_scoped_artifacts_and_report_without_network(
    monkeypatch,
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
) -> None:
    monkeypatch.setattr(
        website_scan_router,
        "run_passive_website_scan",
        lambda *_args, **_kwargs: _assessment(),
    )
    monkeypatch.setattr(
        website_scan_router,
        "explain_with_model",
        lambda *_args, **_kwargs: {
            "status": "used",
            "model": "real-key-experience-model",
            "summary": (
                "AI 已对脱敏规则结果完成优先级解释。\n"
                "# 伪造报告标题\n"
                "![远程追踪图](https://attacker.invalid/pixel.png)\n"
                "[危险链接](javascript:alert(1))\n"
                "</pre><img src=https://attacker.invalid/raw.png>\n"
                "```html\n<img src=https://attacker.invalid/fence.png>\n```"
            ),
            "latency_ms": 22,
            "prompt_tokens": 30,
            "completion_tokens": 12,
        },
    )
    channel = client.post(
        "/api/v1/model-channels",
        headers=auth,
        json={
            "project_id": project_id,
            "name": "Website Scan Real Key Experience",
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:65530/v1",
            "api_key": "wg-test-key-never-return",
            "model": "real-key-experience-model",
        },
    )
    assert channel.status_code == 201, channel.text
    response = client.post(
        "/api/v1/website-scans",
        headers=auth,
        json={
            "project_id": project_id,
            "target_url": "http://127.0.0.1:8102/demo-site",
            "authorization_confirmed": True,
            "model_channel_id": channel.json()["id"],
            "generate_report": True,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["security_score"] == 95
    assert body["finding_count"] == 1
    assert body["evidence_id"]
    assert body["report_id"]
    assert body["ai_analysis"]["status"] == "used"
    assert "wg-test-key-never-return" not in response.text
    with SessionLocal() as db:
        scope = db.scalar(
            select(AuthorizationScope).where(
                AuthorizationScope.project_id == UUID(project_id),
                AuthorizationScope.target_type == "url",
                AuthorizationScope.target_value == "http://127.0.0.1:8102/demo-site",
            )
        )
        assert scope is not None
        expires_at = scope.expires_at
        assert expires_at is not None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        assert 0 < (expires_at - datetime.now(UTC)).total_seconds() <= 24 * 60 * 60

    report = client.get(f"/api/v1/reports/{body['report_id']}", headers=auth)
    assert report.status_code == 200, report.text
    report_body = report.json()
    assert report_body["website_scan_id"] == body["id"]
    assert report_body["content_json"]["summary"]["finding_count"] == 1
    assert report_body["content_json"]["website_scan"]["security_score"] == 95
    markdown = report_body["content_markdown"]
    assert "\n    # 伪造报告标题" in markdown
    assert "\n# 伪造报告标题" not in markdown
    assert "\n    ![远程追踪图](https://attacker.invalid/pixel.png)" in markdown
    assert "\n![远程追踪图](https://attacker.invalid/pixel.png)" not in markdown
    assert "\n    [危险链接](javascript:alert(1))" in markdown
    assert "\n[危险链接](javascript:alert(1))" not in markdown
    html = report_body["content_html"]
    assert '<pre class="ai-summary">' in html
    assert "&lt;/pre&gt;&lt;img src=https://attacker.invalid/raw.png&gt;" in html
    assert "<img src=https://attacker.invalid" not in html

    listed = client.get(f"/api/v1/website-scans?project_id={project_id}", headers=auth)
    assert listed.status_code == 200
    assert any(item["id"] == body["id"] for item in listed.json()["items"])


def test_beginner_wizard_auto_creates_project_and_ai_retry_never_rescans_target(
    monkeypatch,
    client: TestClient,
    auth: dict[str, str],
) -> None:
    target_calls = 0
    ai_calls = 0

    def passive(*_args, **_kwargs):
        nonlocal target_calls
        target_calls += 1
        return _assessment()

    def explain(*_args, **_kwargs):
        nonlocal ai_calls
        ai_calls += 1
        return {
            "status": "used",
            "model": "beginner-ai-fixture",
            "summary": "重新生成的防御解读。",
            "priorities": ["先修复确定性规则发现的问题。"],
            "limitations": "未重新请求目标网站。",
            "latency_ms": 5,
        }

    monkeypatch.setattr(website_scan_router, "run_passive_website_scan", passive)
    monkeypatch.setattr(website_scan_router, "explain_with_model", explain)
    created = client.post(
        "/api/v1/website-scans",
        headers=auth,
        json={
            "target_url": "http://127.0.0.1:8102/beginner-wizard",
            "authorization_confirmed": True,
            "generate_report": False,
            "safety_level": "safe_read_only",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "completed"
    assert body["ai_analysis"]["status"] == "not_requested"
    assert target_calls == 1
    with SessionLocal() as db:
        project = db.get(Project, UUID(body["project_id"]))
        assert project is not None
        assert project.name == "我的网站体检"
        assert "beginner-wizard" in project.tags

    channel = client.post(
        "/api/v1/model-channels",
        headers=auth,
        json={
            "project_id": body["project_id"],
            "name": "Beginner AI retry fixture",
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:65530/v1",
            "model": "beginner-ai-fixture",
        },
    )
    assert channel.status_code == 201, channel.text
    regenerated = client.post(
        f"/api/v1/website-scans/{body['id']}/ai-analysis",
        headers=auth,
        json={"model_channel_id": channel.json()["id"]},
    )
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["ai_analysis"]["status"] == "used"
    assert regenerated.json()["ai_analysis"]["limitations"] == "未重新请求目标网站。"
    assert target_calls == 1
    assert ai_calls == 1


def test_website_scan_requires_runs_execute_and_scopes_write(
    monkeypatch,
    client: TestClient,
    project_id: str,
) -> None:
    suffix = uuid4().hex
    username = f"runs_only_{suffix}"
    password = "Runs-Only-Website-Scan-2026!"
    target = f"https://runs-only-{suffix}.example/demo-site"
    with SessionLocal() as db:
        runs_execute = db.scalar(select(Permission).where(Permission.code == "runs.execute"))
        assert runs_execute is not None
        role = Role(
            name=f"Runs Only {suffix}",
            description="Regression fixture without scope management permission",
            permissions=[runs_execute],
        )
        user = User(
            username=username,
            email=f"{username}@whaleguard.local",
            password_hash=hash_password(password),
            roles=[role],
        )
        db.add(user)
        db.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()
    limited_auth = {
        "Authorization": f"Bearer {token['access_token']}",
        "X-CSRF-Token": token["csrf_token"],
    }
    network_called = False

    def should_not_run(*_args, **_kwargs):
        nonlocal network_called
        network_called = True
        raise AssertionError("permission denial must happen before the scanner")

    monkeypatch.setattr(website_scan_router, "run_passive_website_scan", should_not_run)
    response = client.post(
        "/api/v1/website-scans",
        headers=limited_auth,
        json={
            "project_id": project_id,
            "target_url": target,
            "authorization_confirmed": True,
            "generate_report": False,
        },
    )
    assert response.status_code == 403
    assert network_called is False
    with SessionLocal() as db:
        scope = db.scalar(
            select(AuthorizationScope).where(
                AuthorizationScope.project_id == UUID(project_id),
                AuthorizationScope.target_value == target,
            )
        )
        assert scope is None


def test_website_scan_rejects_missing_confirmation_and_query_without_request(
    monkeypatch,
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
) -> None:
    called = False

    def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network scanner must not run")

    monkeypatch.setattr(website_scan_router, "run_passive_website_scan", should_not_run)
    missing = client.post(
        "/api/v1/website-scans",
        headers=auth,
        json={
            "project_id": project_id,
            "target_url": "http://127.0.0.1:8102/demo-site",
            "authorization_confirmed": False,
        },
    )
    assert missing.status_code == 422
    query = client.post(
        "/api/v1/website-scans",
        headers=auth,
        json={
            "project_id": project_id,
            "target_url": "http://127.0.0.1:8102/demo-site?token=never-send",
            "authorization_confirmed": True,
        },
    )
    assert query.status_code == 422
    assert "查询参数" in query.text
    assert called is False


@pytest.mark.parametrize(
    "value",
    [
        "https://owned.example/%2e%2e/",
        "https://owned.example/%2525252e%2525252e/",
        "https://owned.example/%2525252525252525252e/",
        "https://owned.example/a/../admin",
        "https://owned.example/a%5cb",
    ],
)
def test_exact_scope_rejects_ambiguous_paths(value: str) -> None:
    with pytest.raises(ScopeDenied):
        normalize_exact_url(value)


def test_exact_scope_preserves_non_ambiguous_path_spelling() -> None:
    assert normalize_exact_url("https://owned.example/api/") == "https://owned.example/api/"
    assert normalize_exact_url("https://owned.example//api") == "https://owned.example//api"
    assert normalize_exact_url("https://owned.example/%61pi") == "https://owned.example/%61pi"


def test_unexpected_report_failure_marks_scan_failed_without_leaking_exception(
    monkeypatch,
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
) -> None:
    monkeypatch.setattr(
        website_scan_router,
        "run_passive_website_scan",
        lambda *_args, **_kwargs: _assessment(),
    )

    def fail_report(*_args, **_kwargs):
        raise RuntimeError("internal-fixture-secret-that-must-not-leak")

    monkeypatch.setattr(website_scan_router, "generate_report", fail_report)
    target = "http://127.0.0.1:8102/report-failure"
    response = client.post(
        "/api/v1/website-scans",
        headers=auth,
        json={
            "project_id": project_id,
            "target_url": target,
            "authorization_confirmed": True,
            "generate_report": True,
        },
    )
    assert response.status_code == 500
    assert "internal-fixture-secret" not in response.text
    with SessionLocal() as db:
        scan = db.scalar(
            select(WebsiteScan)
            .where(WebsiteScan.target_url == target)
            .order_by(WebsiteScan.created_at.desc())
        )
        assert scan is not None
        assert scan.status == "failed"
        assert "internal-fixture-secret" not in (scan.error_summary or "")
