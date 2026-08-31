import socket
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from whaleguard_policy import (
    ApprovalState,
    AuthorizationScope,
    PolicyDecision,
    RequestContext,
    RiskLevel,
    ScopedAsyncClient,
    ScopeGuard,
)


def resolver(mapping):
    def resolve(host, port):
        return [(2, 1, 6, "", (ip, port)) for ip in mapping[host]]

    return resolve


def context(**kwargs):
    values = {"project_id": "demo"}
    values.update(kwargs)
    return RequestContext(**values)


def test_private_targets_require_an_explicit_scope():
    guard = ScopeGuard(resolver=resolver({"agent.local": ["172.18.0.5"]}))
    decision = guard.check_url("http://agent.local:8102/run", context())
    assert not decision.allowed
    assert decision.code == "target_out_of_scope"

    scoped = ScopeGuard(
        [AuthorizationScope("agent.local", kind="domain")],
        resolver=resolver({"agent.local": ["172.18.0.5"]}),
    )
    assert scoped.check_url("http://agent.local:8102/run", context()).allowed


def test_default_resolver_is_bound_when_guard_is_created(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        resolver({"agent.local": ["10.10.10.10"]}),
    )
    assert not ScopeGuard().check_url("http://agent.local", context()).allowed


def test_public_target_blocked_by_default():
    guard = ScopeGuard(resolver=resolver({"public.example": ["8.8.8.8"]}))
    decision = guard.check_url("https://public.example/api", context())
    assert not decision.allowed
    assert decision.code == "target_out_of_scope"


def test_explicit_public_domain_requires_allow_public():
    scope = AuthorizationScope("authorized.example", kind="domain", allow_public=True)
    guard = ScopeGuard([scope], resolver=resolver({"authorized.example": ["8.8.8.8"]}))
    assert guard.check_url("https://authorized.example/api", context()).allowed


def test_public_domain_scope_cannot_rebind_to_link_local_metadata():
    scope = AuthorizationScope("authorized.example", kind="domain", allow_public=True)
    guard = ScopeGuard([scope], resolver=resolver({"authorized.example": ["169.254.169.254"]}))
    decision = guard.check_url("https://authorized.example/latest/meta-data", context())
    assert not decision.allowed
    assert decision.code == "unsafe_resolution_blocked"


@pytest.mark.parametrize(
    "address",
    [
        "::ffff:169.254.169.254",
        "64:ff9b::a9fe:a9fe",
        "64:ff9b:1::a9fe:a9fe",
        "100.100.100.200",
    ],
)
def test_public_domain_scope_blocks_embedded_or_special_metadata_routes(address):
    scope = AuthorizationScope("authorized.example", kind="domain", allow_public=True)
    guard = ScopeGuard([scope], resolver=resolver({"authorized.example": [address]}))
    decision = guard.check_url("https://authorized.example/metadata", context())
    assert not decision.allowed
    assert decision.code == "unsafe_resolution_blocked"


def test_mixed_dns_answers_fail_closed_against_rebinding():
    scope = AuthorizationScope("mixed.example", kind="domain", allow_public=False)
    guard = ScopeGuard([scope], resolver=resolver({"mixed.example": ["127.0.0.1", "8.8.8.8"]}))
    decision = guard.check_url("http://mixed.example", context())
    assert not decision.allowed
    assert decision.code == "public_resolution_blocked"


def test_ipv4_mapped_ipv6_cannot_bypass_public_block():
    guard = ScopeGuard(resolver=resolver({"mapped.example": ["::ffff:8.8.8.8"]}))
    decision = guard.check_url("http://mapped.example", context())
    assert not decision.allowed
    assert decision.resolved_ips == ("8.8.8.8",)


def test_link_local_is_not_part_of_default_scope():
    guard = ScopeGuard(resolver=resolver({"link-local.example": ["169.254.169.254"]}))
    decision = guard.check_url("http://link-local.example/latest/meta-data", context())
    assert not decision.allowed
    assert decision.code == "target_out_of_scope"


def test_non_http_schemes_and_userinfo_blocked():
    guard = ScopeGuard()
    assert guard.check_url("file:///etc/passwd", context()).code == "scheme_blocked"
    assert guard.check_url("gopher://127.0.0.1", context()).code == "scheme_blocked"
    assert guard.check_url("http://user:pass@127.0.0.1", context()).code == "invalid_authority"


def test_expired_scope_is_ignored():
    scope = AuthorizationScope(
        "public.example",
        kind="domain",
        allow_public=True,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    guard = ScopeGuard([scope], resolver=resolver({"public.example": ["8.8.8.8"]}))
    assert guard.check_url("https://public.example", context()).code == "target_out_of_scope"


def test_high_risk_tool_waits_for_approval():
    guard = ScopeGuard()
    pending = context(tool_name="request_sensitive_demo_data", tool_risk=RiskLevel.HIGH)
    decision = guard.check_tool("mock-mcp", pending)
    assert not decision.allowed and decision.code == "approval_required"
    approved = context(
        tool_name="create_demo_note",
        tool_risk=RiskLevel.HIGH,
        approval_state=ApprovalState.APPROVED,
    )
    assert guard.check_tool("mock-mcp", approved).allowed


def test_every_decision_is_sent_to_audit_sink():
    records = []
    guard = ScopeGuard(
        [AuthorizationScope("127.0.0.1", kind="host")],
        decision_sink=records.append,
    )
    guard.check_url("http://127.0.0.1:8000/health", context())
    assert len(records) == 1
    assert records[0].to_log_record()["allowed"] is True


def test_policy_log_record_redacts_query_credentials_and_sensitive_details():
    token_shaped_value = "sk-" + "A" * 24
    jwt_shaped_value = ".".join(("eyJ" + "A" * 12, "B" * 12, "C" * 12))
    provider_shaped_value = "AIza" + "D" * 35
    decision = PolicyDecision(
        allowed=False,
        code="blocked",
        reason="blocked",
        target="https://user:pass@example.test/v1/token/secret-value?api_key=top-secret#token",
        project_id="demo",
        details={
            "authorization": "Bearer header-secret",
            "nested": {
                "message": (
                    "password=do-not-log raw="
                    f"{token_shaped_value} {jwt_shaped_value} {provider_shaped_value}"
                ),
                "safe": "kept",
            },
        },
    )
    record = decision.to_log_record()
    serialized = str(record)
    assert "pass" not in record["target"]
    assert "top-secret" not in serialized
    assert "header-secret" not in serialized
    assert "do-not-log" not in serialized
    assert token_shaped_value not in serialized
    assert jwt_shaped_value not in serialized
    assert provider_shaped_value not in serialized
    assert record["details"]["nested"]["safe"] == "kept"


@pytest.mark.asyncio
async def test_scoped_client_pins_checked_ip_and_preserves_host_and_sni():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    guard = ScopeGuard(
        [AuthorizationScope("agent.internal", kind="domain")],
        resolver=resolver({"agent.internal": ["10.20.30.40"]}),
    )
    async with ScopedAsyncClient(guard, transport=httpx.MockTransport(handler)) as client:
        response = await client.request(
            "GET",
            "https://agent.internal:8443/health",
            context(),
            extensions={"sni_hostname": "attacker.invalid"},
        )

    assert response.status_code == 200
    assert requests[0].url.host == "10.20.30.40"
    assert requests[0].headers["host"] == "agent.internal:8443"
    assert requests[0].extensions["sni_hostname"] == "agent.internal"


@pytest.mark.asyncio
async def test_redirect_drops_body_and_cross_origin_credentials():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"Location": "http://second.internal/result"})
        return httpx.Response(200)

    guard = ScopeGuard(
        [
            AuthorizationScope("first.internal", kind="domain"),
            AuthorizationScope("second.internal", kind="domain"),
        ],
        resolver=resolver(
            {
                "first.internal": ["10.0.0.10"],
                "second.internal": ["10.0.0.11"],
            }
        ),
    )
    async with ScopedAsyncClient(guard, transport=httpx.MockTransport(handler)) as client:
        response = await client.request(
            "POST",
            "http://first.internal/start",
            context(),
            json={"sensitive": "fixture"},
            auth=("fixture-user", "fixture-password"),
            headers={
                "Cookie": "session=fixture",
                "X-API-Key": "provider-key-fixture",
                "X-Custom-Token": "custom-token-fixture",
                "X-Custom-Auth": "custom-auth-fixture",
            },
            params={"api_key": "query-fixture"},
        )

    assert response.status_code == 200
    assert len(requests) == 2
    assert requests[1].method == "GET"
    assert requests[1].content == b""
    assert requests[0].url.query == b"api_key=query-fixture"
    assert requests[1].url.query == b""
    assert "authorization" not in requests[1].headers
    assert "cookie" not in requests[1].headers
    assert "x-api-key" not in requests[1].headers
    assert "x-custom-token" not in requests[1].headers
    assert "x-custom-auth" not in requests[1].headers
