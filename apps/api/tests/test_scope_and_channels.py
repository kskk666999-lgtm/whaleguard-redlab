from __future__ import annotations

import socket
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from whaleguard_api.database import SessionLocal
from whaleguard_api.models import AuditLog, AuthorizationScope, ModelChannel
from whaleguard_api.scope_guard import (
    ScopeDecision,
    _path_scope_matches,
    _strip_cross_origin_sensitive_headers,
    evaluate_url,
    log_policy_decision,
)


def test_scope_guard_private_public_and_protocol(monkeypatch, project_id: str) -> None:
    def private_dns(_host: str, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", private_dns)
    with SessionLocal() as db:
        assert evaluate_url(db, "http://private.example/test", UUID(project_id)).allowed

    def public_dns(_host: str, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)
    with SessionLocal() as db:
        blocked = evaluate_url(db, "https://public.example/test", UUID(project_id))
        assert not blocked.allowed
        assert "授权" in blocked.reason or "公网" in blocked.reason
        assert not evaluate_url(db, "file:///etc/passwd", UUID(project_id)).allowed

        db.add(
            AuthorizationScope(
                project_id=UUID(project_id),
                name="explicit public test scope",
                target_type="domain",
                target_value="public.example",
                allowed_request_types=["http", "https"],
                is_authorized=True,
            )
        )
        db.commit()
        allowed = evaluate_url(db, "https://public.example/test", UUID(project_id))
        assert allowed.allowed


def test_model_api_key_encrypted_and_masked(
    client: TestClient, auth: dict[str, str], project_id: str
) -> None:
    plaintext = "WHALEGUARD_TEST_SECRET_MUST_NEVER_BE_RETURNED_7F3A"
    response = client.post(
        "/api/v1/model-channels",
        headers=auth,
        json={
            "project_id": project_id,
            "name": "Encrypted Channel",
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:65530/v1",
            "api_key": plaintext,
            "model": "demo-model",
            "extra_headers": {"X-Demo": "safe"},
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert plaintext not in response.text
    assert body["api_key_masked"].startswith("sk-")
    assert body["extra_header_names"] == ["X-Demo"]

    with SessionLocal() as db:
        channel = db.get(ModelChannel, UUID(body["id"]))
        assert channel is not None
        assert plaintext.encode() not in (channel.api_key_encrypted or b"")

    connection = client.post(f"/api/v1/model-channels/{body['id']}/test-connection", headers=auth)
    assert connection.status_code == 200
    assert connection.json()["success"] is False
    assert plaintext not in connection.text


def test_url_scope_path_boundary_and_sensitive_redirect_headers() -> None:
    assert _path_scope_matches("/api", "/api")
    assert _path_scope_matches("/api", "/api/v1/chat")
    assert not _path_scope_matches("/api", "/api-evil")
    assert not _path_scope_matches("/api", "/api/%2e%2e/private")

    stripped = _strip_cross_origin_sensitive_headers(
        {
            "Authorization": "Bearer should-not-cross",
            "Cookie": "session=should-not-cross",
            "X-API-Key": "should-not-cross",
            "X-Auth-Token": "should-not-cross",
            "X-Credential": "should-not-cross",
            "Content-Type": "application/json",
            "X-Safe-Trace": "safe",
        }
    )
    assert stripped == {"Content-Type": "application/json", "X-Safe-Trace": "safe"}


def test_policy_audit_strips_query_fragment_and_userinfo(project_id: str) -> None:
    decision = ScopeDecision(
        allowed=False,
        reason="fixture",
        url="https://user:password@example.test/api?api_key=never-log#token-fragment",
        normalized_host="example.test",
    )
    with SessionLocal() as db:
        log_policy_decision(db, decision, UUID(project_id), "sanitization-fixture")
        db.commit()
        record = db.scalar(
            select(AuditLog)
            .where(AuditLog.request_id == "sanitization-fixture")
            .order_by(AuditLog.created_at.desc())
        )
        assert record is not None
        assert record.details["url"] == "https://example.test/api"
        serialized = str(record.details)
        assert "never-log" not in serialized
        assert "password" not in serialized
        assert "token-fragment" not in serialized
