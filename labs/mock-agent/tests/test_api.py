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
