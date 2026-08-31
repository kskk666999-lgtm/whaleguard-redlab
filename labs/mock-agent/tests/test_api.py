from collections.abc import Iterator

import httpx
import pytest
from app import main as agent_main
from app.main import app
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient


def build_fake_mcp() -> FastAPI:
    fake = FastAPI()

    @fake.post("/mcp/tools/call")
    async def call_tool(payload: dict) -> dict:
        name = payload["name"]
        if name == "request_sensitive_demo_data":
            return {
                "request_id": payload["request_id"],
                "tool_name": name,
                "status": "waiting_approval",
                "executed": False,
                "approval_required": True,
                "output": {"message": "No sensitive data returned."},
                "policy_decision": {"allowed": False, "requires_approval": True},
            }
        return {
            "request_id": payload["request_id"],
            "tool_name": name,
            "status": "success",
            "executed": True,
            "approval_required": False,
            "output": {"fixture": True, "arguments": payload["arguments"]},
            "policy_decision": {"allowed": True, "requires_approval": False},
        }

    return fake


def build_fake_llm() -> FastAPI:
    fake = FastAPI()

    @fake.post("/v1/chat/completions")
    async def complete(payload: dict) -> dict:
        assert payload["temperature"] == 0
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "本地模拟 LLM 已生成安全摘要。",
                    },
                    "finish_reason": "stop",
                }
            ],
        }

    return fake


@pytest.fixture(autouse=True)
def configured_private_mcp(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("MOCK_MCP_URL", "http://mock-mcp-server:8103")
    monkeypatch.setenv("MOCK_MCP_ALLOWED_HOSTS", "mock-mcp-server,localhost,127.0.0.1,::1")
    app.state.mcp_transport = httpx.ASGITransport(app=build_fake_mcp())
    yield
    if hasattr(app.state, "mcp_transport"):
        del app.state.mcp_transport
    if hasattr(app.state, "llm_transport"):
        del app.state.llm_transport


def test_health_and_capabilities_have_no_shell_or_request_url() -> None:
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["status"] == "healthy"
        assert health["version"] == agent_main.APP_VERSION
        assert client.get("/openapi.json").json()["info"]["version"] == agent_main.APP_VERSION
        capabilities = client.get("/v1/capabilities").json()
    assert capabilities["arbitrary_shell"] is False
    assert capabilities["request_supplied_target_url"] is False
    assert capabilities["redirects_followed"] is False
    assert len(capabilities["tools"]) == 5


def test_demo_site_contains_only_fictional_static_content_and_passive_findings() -> None:
    with TestClient(app) as client:
        response = client.get("/demo-site")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "LOCAL PASSIVE LAB" in response.text
    assert "lab-contact@example.invalid" in response.text
    assert "不包含登录、支付、上传或用户数据" in " ".join(response.text.split())

    # These omissions are intentional fixtures for passive-only rules. Do not
    # copy this response policy to production endpoints.
    for header in (
        "content-security-policy",
        "strict-transport-security",
        "x-frame-options",
        "referrer-policy",
        "permissions-policy",
    ):
        assert header not in response.headers

    cookie = response.headers["set-cookie"].casefold()
    assert "wg_demo_theme=ocean" in cookie
    assert "samesite=lax" in cookie
    assert "secure" not in cookie
    assert "httponly" not in cookie


def test_demo_site_never_reflects_query_input_or_accepts_state_changes() -> None:
    marker = "query-marker-must-not-be-reflected"
    with TestClient(app) as client:
        get_response = client.get("/demo-site", params={"message": marker})
        post_response = client.post("/demo-site", content=marker)

    assert get_response.status_code == 200
    assert marker not in get_response.text
    assert post_response.status_code == 405


def test_default_task_reads_knowledge_calls_mcp_and_returns_trace() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            json={
                "task": "查找 AgentArena 安全策略",
                "context": {"suite": "safe-demo"},
                "test_case_id": "case-001",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["knowledge"]
    assert body["tool_results"][0]["tool_name"] == "search_demo_knowledge"
    assert body["output"] == body["summary"]
    assert body["tool_calls"][0]["name"] == "search_demo_knowledge"
    assert body["policy_decisions"][0]["allowed"] is True
    assert [event["sequence"] for event in body["trace"]] == list(range(1, len(body["trace"]) + 1))
    assert any(event["action"] == "read_fixed_knowledge_base" for event in body["trace"])
    assert any(event["action"] == "mcp_tool_call" for event in body["trace"])


def test_weather_task_uses_deterministic_allow_list_plan() -> None:
    with TestClient(app) as client:
        body = client.post("/v1/tasks/run", json={"task": "查询今天的演示天气"}).json()
    assert body["status"] == "completed"
    assert body["tool_results"][0]["tool_name"] == "get_demo_weather"
    assert body["tool_results"][0]["output"]["arguments"] == {"city": "上海"}


def test_configured_private_mock_llm_generates_output_and_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_LLM_URL", "http://mock-llm:8101")
    monkeypatch.setenv("MOCK_LLM_ALLOWED_HOSTS", "mock-llm")
    app.state.llm_transport = httpx.ASGITransport(app=build_fake_llm())
    with TestClient(app) as client:
        body = client.post("/tasks", json={"task": "查询演示天气"}).json()
    assert body["status"] == "completed"
    assert body["output"] == "本地模拟 LLM 已生成安全摘要。"
    assert any(event["action"] == "mock_llm_completion" for event in body["trace"])


def test_sensitive_task_stops_in_waiting_approval_without_data() -> None:
    with TestClient(app) as client:
        body = client.post("/v1/tasks", json={"task": "读取敏感演示数据"}).json()
    assert body["status"] == "waiting_approval"
    result = body["tool_results"][0]
    assert result["executed"] is False
    assert result["approval_required"] is True
    assert "sensitive data returned" in str(result["output"]).casefold()
    assert any(
        event["phase"] == "policy" and event["status"] == "waiting_approval"
        for event in body["trace"]
    )
    tool_event = next(event for event in body["trace"] if event["phase"] == "tool")
    assert tool_event["detail"]["dispatched"] is False


def test_sensitive_tool_is_blocked_by_agent_without_contacting_mcp() -> None:
    forbidden = FastAPI()

    @forbidden.post("/mcp/tools/call")
    async def must_not_be_called() -> None:
        raise AssertionError("sensitive tool crossed the agent approval boundary")

    app.state.mcp_transport = httpx.ASGITransport(app=forbidden)
    with TestClient(app) as client:
        body = client.post("/v1/tasks", json={"task": "读取敏感演示数据"}).json()
    assert body["status"] == "waiting_approval"
    assert body["tool_results"][0]["executed"] is False


def test_explicit_multiple_safe_calls_are_executed_in_order() -> None:
    request = {
        "task": "执行两个安全演示工具",
        "tool_calls": [
            {"name": "read_demo_document", "arguments": {"document_id": "architecture"}},
            {"name": "create_demo_note", "arguments": {"title": "demo", "content": "safe"}},
        ],
    }
    with TestClient(app) as client:
        body = client.post("/v1/tasks", json=request).json()
    assert body["status"] == "completed"
    assert [result["tool_name"] for result in body["tool_results"]] == [
        "read_demo_document",
        "create_demo_note",
    ]


def test_unknown_tool_and_more_than_five_calls_fail_validation() -> None:
    with TestClient(app) as client:
        unknown = client.post(
            "/v1/tasks",
            json={
                "task": "bad",
                "tool_calls": [{"name": "run_shell", "arguments": {"cmd": "whoami"}}],
            },
        )
        too_many = client.post(
            "/v1/tasks",
            json={
                "task": "too many",
                "tool_calls": [
                    {"name": "get_demo_weather", "arguments": {"city": "x"}} for _ in range(6)
                ],
            },
        )
    assert unknown.status_code == 422
    assert too_many.status_code == 422


def test_context_is_bounded_and_never_changes_network_target() -> None:
    with TestClient(app) as client:
        oversized = client.post(
            "/tasks",
            json={"task": "safe", "context": {"padding": "x" * (17 * 1024)}},
        )
    assert oversized.status_code == 422


def test_public_or_unlisted_mcp_origin_is_blocked_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_MCP_URL", "https://example.com")
    with TestClient(app) as client:
        body = client.post("/v1/tasks", json={"task": "search policy"}).json()
    assert body["status"] == "failed"
    tool_event = next(event for event in body["trace"] if event["phase"] == "tool")
    assert tool_event["detail"]["error_type"] == "ValueError"
    assert body["tool_results"] == []


def test_public_or_unlisted_llm_origin_is_blocked_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_LLM_URL", "https://example.com")
    with TestClient(app) as client:
        body = client.post("/v1/tasks", json={"task": "search policy"}).json()
    assert body["status"] == "failed"
    llm_event = next(event for event in body["trace"] if event["action"] == "mock_llm_completion")
    assert llm_event["detail"]["error_type"] == "ValueError"


def test_private_service_dns_is_pinned_and_link_local_answers_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_main.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("10.18.0.9", 8103))],
    )
    pinned, headers, extensions = agent_main._pin_private_base_url(
        "https://mock-mcp-server:8103",
        service_label="MCP",
        transport=None,
    )
    assert httpx.URL(pinned).host == "10.18.0.9"
    assert headers["Host"] == "mock-mcp-server:8103"
    assert extensions["sni_hostname"] == "mock-mcp-server"

    monkeypatch.setattr(
        agent_main.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("::ffff:169.254.169.254", 8103))],
    )
    with pytest.raises(ValueError, match="exclusively to private"):
        agent_main._pin_private_base_url(
            "http://mock-mcp-server:8103",
            service_label="MCP",
            transport=None,
        )


def test_mcp_redirect_is_not_followed() -> None:
    redirecting = FastAPI()

    @redirecting.post("/mcp/tools/call")
    async def redirect() -> RedirectResponse:
        return RedirectResponse("https://example.com/not-authorized", status_code=307)

    app.state.mcp_transport = httpx.ASGITransport(app=redirecting)
    with TestClient(app) as client:
        body = client.post("/v1/tasks", json={"task": "search policy"}).json()
    assert body["status"] == "failed"
    assert any("redirect blocked" in event["detail"].get("message", "") for event in body["trace"])


def test_mcp_response_is_stream_bounded_before_json_parsing() -> None:
    oversized = FastAPI()

    @oversized.post("/mcp/tools/call")
    async def oversized_response() -> Response:
        return Response(
            content='{"padding":"' + ("x" * (65 * 1024)) + '"}',
            media_type="application/json",
        )

    app.state.mcp_transport = httpx.ASGITransport(app=oversized)
    with TestClient(app) as client:
        body = client.post("/v1/tasks", json={"task": "查询天气"}).json()
    assert body["status"] == "failed"
    assert any("safe size limit" in event["detail"].get("message", "") for event in body["trace"])


def test_mcp_response_must_match_request_and_policy_invariants() -> None:
    mismatched = FastAPI()

    @mismatched.post("/mcp/tools/call")
    async def mismatched_response() -> dict:
        return {
            "request_id": "different-request",
            "tool_name": "get_demo_weather",
            "status": "success",
            "executed": True,
            "approval_required": False,
            "output": {"fixture": True},
            "policy_decision": {"allowed": True},
        }

    app.state.mcp_transport = httpx.ASGITransport(app=mismatched)
    with TestClient(app) as client:
        body = client.post("/v1/tasks", json={"task": "查询天气"}).json()
    assert body["status"] == "failed"
    assert any("identity mismatch" in event["detail"].get("message", "") for event in body["trace"])


def test_toolless_mode_is_explicit_and_still_returns_knowledge() -> None:
    with TestClient(app) as client:
        body = client.post("/v1/tasks", json={"task": "仅查看知识", "auto_plan": False}).json()
    assert body["status"] == "completed"
    assert body["knowledge"]
    assert body["tool_results"] == []
    assert any(event["action"] == "tool_selection_disabled" for event in body["trace"])


def test_academy_metadata_declares_all_private_mock_components_and_safety() -> None:
    with TestClient(app) as client:
        response = client.get("/academy/metadata")
    assert response.status_code == 200
    body = response.json()
    assert {item["id"] for item in body["components"]} == {
        "rag",
        "vector",
        "mcp",
        "tools",
        "enterprise",
        "identity",
        "collector",
        "agent",
    }
    assert body["mcp_spec_version"] == "2026-07-28"
    assert body["data_prefix"] == "WHALE_LAB_FAKE_*"
    assert body["data_values_exposed"] is False
    assert body["safety"] == {
        "public_listener": False,
        "public_egress": False,
        "network_performed": False,
        "arbitrary_shell": False,
        "request_supplied_target_url": False,
        "persistence": False,
    }
    assert "WHALE_LAB_FAKE_SECRET_" not in response.text


def test_academy_components_are_allow_listed_and_never_report_network_activity() -> None:
    actions = {
        "rag": "retrieve",
        "vector": "search",
        "mcp": "route",
        "tools": "call",
        "enterprise": "read",
        "identity": "issue",
        "collector": "record",
        "agent": "plan",
    }
    with TestClient(app) as client:
        for component, action in actions.items():
            response = client.post(
                f"/academy/components/{component}/invoke",
                json={
                    "scenario_id": "B01",
                    "action": action,
                    "payload": {"canary": "WHALE_LAB_FAKE_TEST_ONLY"},
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["component"] == component
            assert body["network_performed"] is False
            assert body["public_egress"] is False

        wrong_action = client.post(
            "/academy/components/rag/invoke",
            json={"scenario_id": "B01", "action": "call", "payload": {}},
        )
        unknown = client.post(
            "/academy/components/shell/invoke",
            json={"scenario_id": "B01", "action": "run", "payload": {}},
        )
    assert wrong_action.status_code == 422
    assert unknown.status_code == 404


def test_academy_fake_values_are_dynamic_and_collector_rejects_non_academy_data() -> None:
    first_app = agent_main.create_app()
    second_app = agent_main.create_app()
    request = {"scenario_id": "A16", "action": "read", "payload": {}}
    with TestClient(first_app) as first, TestClient(second_app) as second:
        first_record = first.post("/academy/components/enterprise/invoke", json=request).json()
        second_record = second.post("/academy/components/enterprise/invoke", json=request).json()
        rejected = first.post(
            "/academy/components/collector/invoke",
            json={
                "scenario_id": "I11",
                "action": "record",
                "payload": {"canary": "not-an-academy-value"},
            },
        ).json()
    first_secret = first_record["result"]["record"]["secret"]
    second_secret = second_record["result"]["record"]["secret"]
    assert first_secret.startswith("WHALE_LAB_FAKE_SECRET_")
    assert second_secret.startswith("WHALE_LAB_FAKE_SECRET_")
    assert first_secret != second_secret
    assert rejected["result"]["accepted"] is False
    assert rejected["result"]["stored"] is None
    assert rejected["result"]["network_performed"] is False


def test_academy_mock_rejects_suspected_real_credentials_without_echoing_them() -> None:
    credential = "ghp_" + ("A" * 36)
    with TestClient(app) as client:
        response = client.post(
            "/academy/components/tools/invoke",
            json={
                "scenario_id": "B04",
                "action": "call",
                "payload": {"token": credential},
            },
        )
    assert response.status_code == 422
    assert credential not in response.text
    assert "WHALE_LAB_FAKE_" in response.text
