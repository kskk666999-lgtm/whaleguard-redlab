from app.main import NoteStore, app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_and_metadata_are_explicitly_constrained() -> None:
    assert client.get("/health").json()["status"] == "healthy"
    metadata = client.get("/metadata").json()
    assert metadata["arbitrary_shell"] is False
    assert metadata["external_network_access"] is False
    assert metadata["execution_boundary"] == "five-hard-coded-tools-only"


def test_exactly_five_documented_tools_and_no_shell_capability() -> None:
    response = client.get("/mcp/tools/list")
    assert response.status_code == 200
    tools = response.json()["tools"]
    assert {tool["name"] for tool in tools} == {
        "read_demo_document",
        "search_demo_knowledge",
        "create_demo_note",
        "get_demo_weather",
        "request_sensitive_demo_data",
    }
    assert all(tool["_meta"]["whaleguard"]["command_execution"] is False for tool in tools)
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools)


def test_read_document_cannot_traverse_paths() -> None:
    ok = client.post(
        "/mcp/tools/call",
        json={"name": "read_demo_document", "arguments": {"document_id": "scope-guard"}},
    )
    assert ok.status_code == 200
    assert ok.json()["output"]["document_id"] == "scope-guard"

    traversal = client.post(
        "/mcp/tools/call",
        json={"name": "read_demo_document", "arguments": {"document_id": "../../etc/passwd"}},
    )
    assert traversal.status_code == 422


def test_search_and_weather_use_only_fictional_fixtures() -> None:
    search = client.post(
        "/mcp/tools/call",
        json={"name": "search_demo_knowledge", "arguments": {"query": "MCPShield", "limit": 2}},
    )
    assert search.status_code == 200
    assert search.json()["output"]["count"] == 1

    first = client.post(
        "/mcp/tools/call",
        json={"name": "get_demo_weather", "arguments": {"city": "上海"}},
    ).json()
    second = client.post(
        "/mcp/tools/call",
        json={"name": "get_demo_weather", "arguments": {"city": "上海"}},
    ).json()
    assert first["output"] == second["output"]
    assert first["output"]["source"] == "deterministic-fictional-fixture"


def test_note_creation_is_bounded_and_in_memory() -> None:
    response = client.post(
        "/mcp/tools/call",
        json={
            "name": "create_demo_note",
            "arguments": {"title": "演示", "content": "无破坏性内容"},
        },
    )
    assert response.status_code == 200
    assert response.json()["output"]["storage"] == "memory"
    assert client.get("/demo/notes").json()["count"] >= 1

    oversized = client.post(
        "/mcp/tools/call",
        json={"name": "create_demo_note", "arguments": {"title": "x", "content": "a" * 501}},
    )
    assert oversized.status_code == 422

    markup = client.post(
        "/mcp/tools/call",
        json={
            "name": "create_demo_note",
            "arguments": {"title": "<b>demo</b>", "content": "<script>alert(1)</script>"},
        },
    )
    assert "<script>" not in markup.json()["output"]["note"]["content"]


def test_sensitive_tool_never_executes_or_returns_data() -> None:
    response = client.post(
        "/mcp/tools/call",
        json={"name": "request_sensitive_demo_data", "arguments": {"reason": "验证审批围栏"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "waiting_approval"
    assert body["executed"] is False
    assert body["approval_required"] is True
    assert body["policy_decision"]["allowed"] is False
    assert "secret" not in str(body["output"]).casefold()


def test_unknown_tool_and_extra_arguments_are_rejected() -> None:
    unknown = client.post(
        "/mcp/tools/call", json={"name": "run_shell", "arguments": {"command": "whoami"}}
    )
    assert unknown.status_code == 422

    extra = client.post(
        "/mcp/tools/call",
        json={
            "name": "request_sensitive_demo_data",
            "arguments": {"reason": "test", "approved": True},
        },
    )
    assert extra.status_code == 422

    unsafe_request_id = client.post(
        "/mcp/tools/call",
        json={
            "name": "get_demo_weather",
            "arguments": {"city": "上海"},
            "request_id": "line-one\nforged-log-line",
        },
    )
    assert unsafe_request_id.status_code == 422


def test_ephemeral_note_store_has_a_hard_memory_bound() -> None:
    store = NoteStore(max_notes=2)
    store.create("one", "1")
    store.create("two", "2")
    newest = store.create("three", "3")
    notes = store.list()
    assert len(notes) == 2
    assert [note["title"] for note in notes] == ["two", "three"]
    assert newest["id"] == "demo-note-0003"


def test_json_rpc_initialize_list_call_and_unknown_method() -> None:
    initialized = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    ).json()
    assert initialized["result"]["capabilities"]["tools"]["listChanged"] is False

    listed = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    ).json()
    assert len(listed["result"]["tools"]) == 5

    called = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "request_sensitive_demo_data",
                "arguments": {"reason": "boundary test"},
            },
        },
    ).json()
    assert called["result"]["structuredContent"]["status"] == "waiting_approval"

    unknown = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "shell/execute", "params": {}}
    ).json()
    assert unknown["error"]["code"] == -32601
