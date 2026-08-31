from __future__ import annotations

import socket
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from whaleguard_api.database import SessionLocal
from whaleguard_api.models import (
    AuditLog,
    AuthorizationScope,
    MCPServer,
    ModelChannel,
    Permission,
    Role,
    User,
)
from whaleguard_api.routers import targets
from whaleguard_api.scope_guard import (
    ScopeDecision,
    _path_scope_matches,
    _strip_cross_origin_sensitive_headers,
    _url_scope_matches,
    evaluate_url,
    guarded_request,
    log_policy_decision,
)
from whaleguard_api.security import hash_password, redact


def test_scope_guard_private_public_and_protocol(monkeypatch, project_id: str) -> None:
    def private_dns(_host: str, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", private_dns)
    with SessionLocal() as db:
        blocked_private = evaluate_url(db, "http://private.example/test", UUID(project_id))
        assert not blocked_private.allowed
        db.add(
            AuthorizationScope(
                project_id=UUID(project_id),
                name="explicit private test scope",
                target_type="domain",
                target_value="private.example",
                allowed_request_types=["http", "https"],
                is_authorized=True,
            )
        )
        db.commit()
        assert evaluate_url(db, "http://private.example/test", UUID(project_id)).allowed

    def public_dns(_host: str, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)
    with SessionLocal() as db:
        blocked = evaluate_url(db, "https://public.example/test", UUID(project_id))
        assert not blocked.allowed
        assert "Scope" in blocked.reason
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


def test_bundled_health_probe_exception_is_exact_and_internal(monkeypatch) -> None:
    def private_dns(_host: str, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.18.0.5", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", private_dns)
    with SessionLocal() as db:
        allowed = evaluate_url(
            db,
            "http://mock-agent:8102/health",
            None,
            allow_bundled_health_probe=True,
        )
        assert allowed.allowed
        wrong_path = evaluate_url(
            db,
            "http://mock-agent:8102/tasks",
            None,
            allow_bundled_health_probe=True,
        )
        assert not wrong_path.allowed
        with pytest.raises(ValueError, match="固定安全边界"):
            guarded_request(
                db,
                "POST",
                "http://mock-agent:8102/health",
                None,
                max_redirects=0,
                max_response_bytes=8192,
                allow_bundled_health_probe=True,
            )


def test_compound_mcp_credentials_are_redacted_on_write_and_read(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
) -> None:
    canary = "WG-MCP-CANARY-MUST-NEVER-RETURN"
    config = {
        "command": "safe-demo",
        "clientSecret": canary,
        "apiＫey": canary,
        "headers": [{"name": "Authorization", "value": canary}],
        "env": [f"API_KEY={canary}"],
        "nested": [
            {"access-token-value": canary},
            {"credentialBlob": canary},
            {"privateKeyPem": canary},
            {"x-api-key": canary},
        ],
    }
    redacted = redact(config)
    assert canary not in str(redacted)
    assert redacted["command"] == "safe-demo"

    created = client.post(
        "/api/v1/mcp/servers",
        headers=auth,
        json={
            "project_id": project_id,
            "name": f"Compound redaction {uuid4().hex}",
            "transport": "stdio",
            "config": config,
        },
    )
    assert created.status_code == 201, created.text
    assert canary not in created.text
    server_id = created.json()["id"]
    with SessionLocal() as db:
        stored = db.get(MCPServer, UUID(server_id))
    assert stored is not None
    assert canary not in str(stored.config)
    with SessionLocal() as db:
        legacy = MCPServer(
            project_id=UUID(project_id),
            name=f"Legacy response redaction {uuid4().hex}",
            transport="stdio",
            config={"clientSecret": canary, "command": "legacy-safe-demo"},
        )
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id

    fetched = client.get(f"/api/v1/mcp/servers/{legacy_id}", headers=auth)
    assert fetched.status_code == 200, fetched.text
    assert canary not in fetched.text
    assert fetched.json()["config"]["clientSecret"] == "[REDACTED]"
    listed = client.get("/api/v1/mcp/servers?page_size=100", headers=auth)
    assert listed.status_code == 200, listed.text
    assert canary not in listed.text

    updated = client.patch(
        f"/api/v1/mcp/servers/{server_id}",
        headers=auth,
        json={
            "config": {
                "headers": [{"name": "Authorization", "value": canary}],
                "env": [f"ACCESS_TOKEN={canary}"],
            }
        },
    )
    assert updated.status_code == 200, updated.text
    assert canary not in updated.text

    imported = client.post(
        "/api/v1/mcp/servers/import",
        headers=auth,
        json={
            "project_id": project_id,
            "config": {
                "mcpServers": {
                    f"unicode-{uuid4().hex}": {
                        "command": "safe-import",
                        "env": [f"ＡＰＩ_KEY={canary}"],
                    }
                }
            },
        },
    )
    assert imported.status_code == 201, imported.text
    assert canary not in imported.text


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


def test_confirmed_model_channel_requires_models_write_and_scopes_write(
    client: TestClient,
    project_id: str,
) -> None:
    suffix = uuid4().hex
    username = f"models_only_{suffix}"
    password = "Models-Only-Channel-2026!"
    base_url = f"https://models-only-{suffix}.example/v1"
    with SessionLocal() as db:
        models_write = db.scalar(select(Permission).where(Permission.code == "models.write"))
        assert models_write is not None
        role = Role(
            name=f"Models Only {suffix}",
            description="Regression fixture without scope management permission",
            permissions=[models_write],
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
    response = client.post(
        "/api/v1/model-channels",
        headers=limited_auth,
        json={
            "project_id": project_id,
            "name": "Must Not Create Confirmed Scope",
            "provider": "openai-compatible",
            "base_url": base_url,
            "api_key": "wg-models-only-fixture",
            "model": "fixture-model",
            "authorization_confirmed": True,
        },
    )
    assert response.status_code == 403
    with SessionLocal() as db:
        scopes = list(
            db.scalars(
                select(AuthorizationScope).where(
                    AuthorizationScope.project_id == UUID(project_id),
                    AuthorizationScope.target_value.in_(
                        {
                            f"{base_url}/models",
                            f"{base_url}/chat/completions",
                        }
                    ),
                )
            )
        )
        assert scopes == []

    unconfirmed = client.post(
        "/api/v1/model-channels",
        headers=limited_auth,
        json={
            "project_id": project_id,
            "name": "Models Only Without Scope",
            "provider": "openai-compatible",
            "base_url": f"https://unconfirmed-{suffix}.example/v1",
            "api_key": "wg-unconfirmed-fixture",
            "model": "fixture-model",
            "authorization_confirmed": False,
        },
    )
    assert unconfirmed.status_code == 201, unconfirmed.text


def test_exact_url_scope_origin_path_and_sensitive_redirect_headers() -> None:
    assert _path_scope_matches("/api", "/api")
    assert not _path_scope_matches("/api", "/api/v1/chat")
    assert not _path_scope_matches("/api", "/api-evil")
    assert not _path_scope_matches("/api", "/api/%2e%2e/private")
    assert not _path_scope_matches("/api", "/%61pi")
    assert not _path_scope_matches("/api", "/api/")
    assert not _path_scope_matches("/api", "//api")
    assert not _path_scope_matches("/api", "\\api")
    assert _url_scope_matches("https://owned.example/api", "https://owned.example:443/api")
    assert not _url_scope_matches(
        "https://owned.example/api", "https://owned.example/api?mode=admin"
    )
    assert not _url_scope_matches(
        "https://owned.example:8443/api", "https://owned.example:9443/api"
    )
    assert not _url_scope_matches(
        "https://owned.example:8443/api", "https://owned.example:8443/api/private"
    )

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


def test_manual_exact_url_scope_rejects_query_and_canonicalizes_default_port(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
) -> None:
    rejected = client.post(
        f"/api/v1/projects/{project_id}/scopes",
        headers=auth,
        json={
            "name": "Query must not persist",
            "target_type": "url",
            "target_value": "https://owned.example/api?token=never-store",
            "is_authorized": True,
        },
    )
    assert rejected.status_code == 422
    assert "never-store" not in rejected.text

    created = client.post(
        f"/api/v1/projects/{project_id}/scopes",
        headers=auth,
        json={
            "name": "Canonical exact URL",
            "target_type": "url",
            "target_value": "https://owned.example:443/api",
            "is_authorized": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["target_value"] == "https://owned.example/api"


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


def test_scope_guard_permanently_blocks_metadata_even_with_exact_scope(
    monkeypatch, project_id: str
) -> None:
    def metadata_dns(_host: str, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", metadata_dns)
    with SessionLocal() as db:
        db.add(
            AuthorizationScope(
                project_id=UUID(project_id),
                name="must not override permanent deny",
                target_type="url",
                target_value="http://owned.example/",
                allowed_request_types=["http", "https"],
                is_authorized=True,
            )
        )
        db.commit()
        decision = evaluate_url(db, "http://owned.example/", UUID(project_id))
        assert not decision.allowed
        assert "永久禁止" in decision.reason or "元数据" in decision.reason
        mapped = evaluate_url(db, "http://[::ffff:169.254.169.254]/", UUID(project_id))
        assert not mapped.allowed
        direct = evaluate_url(db, "http://metadata.google.internal/", UUID(project_id))
        assert not direct.allowed


def test_confirmed_model_channel_creates_temporary_exact_scope_and_401_is_failure(
    monkeypatch,
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
) -> None:
    response = client.post(
        "/api/v1/model-channels",
        headers=auth,
        json={
            "project_id": project_id,
            "name": "Confirmed Public Model Fixture",
            "provider": "openai-compatible",
            "base_url": "https://model-api.example/v1",
            "api_key": "wg-model-fixture-secret",
            "model": "fixture-model",
            "timeout": 300,
            "authorization_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    channel_id = response.json()["id"]
    with SessionLocal() as db:
        scopes = list(
            db.scalars(
                select(AuthorizationScope).where(
                    AuthorizationScope.project_id == UUID(project_id),
                    AuthorizationScope.target_type == "url",
                    AuthorizationScope.target_value.in_(
                        {
                            "https://model-api.example/v1/models",
                            "https://model-api.example/v1/chat/completions",
                        }
                    ),
                )
            )
        )
        assert {scope.target_value for scope in scopes} == {
            "https://model-api.example/v1/models",
            "https://model-api.example/v1/chat/completions",
        }
        for scope in scopes:
            assert scope.is_authorized
            assert scope.confirmed_by_id is not None
            expires_at = scope.expires_at
            assert expires_at is not None
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            assert 0 < (expires_at - datetime.now(UTC)).days <= 30

    seen_request: dict = {}

    def unauthorized(_db, _method, _url, _project_id, **kwargs):
        seen_request.update(kwargs)
        return httpx.Response(401, json={"error": "invalid key"})

    monkeypatch.setattr(targets, "guarded_request", unauthorized)
    connection = client.post(f"/api/v1/model-channels/{channel_id}/test-connection", headers=auth)
    assert connection.status_code == 200
    assert connection.json()["success"] is False
    assert connection.json()["status_code"] == 401
    assert "API Key" in connection.json()["message"]
    assert "wg-model-fixture-secret" not in connection.text
    assert seen_request["timeout"] == 60
    assert seen_request["max_redirects"] == 0


def test_model_channel_rejects_query_or_fragment(
    client: TestClient, auth: dict[str, str], project_id: str
) -> None:
    response = client.post(
        "/api/v1/model-channels",
        headers=auth,
        json={
            "project_id": project_id,
            "name": "Invalid query model",
            "provider": "openai-compatible",
            "base_url": "https://model-api.example/v1?token=must-not-persist",
            "api_key": "fixture",
            "model": "fixture-model",
            "authorization_confirmed": True,
        },
    )
    assert response.status_code == 422
    assert "must-not-persist" not in response.text
