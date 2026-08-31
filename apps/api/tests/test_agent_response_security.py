import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from whaleguard_api import runner


def _objects():
    run = SimpleNamespace(id=uuid4(), project_id=uuid4(), timeout_seconds=30)
    case = SimpleNamespace(
        input_data={"prompt": "fictional local test"},
        context={},
        case_key="SEC-AGENT-RESPONSE",
        category="prompt_injection",
    )
    agent = SimpleNamespace(
        endpoint_url="http://mock-agent:8102",
        config={"mode": "remote"},
    )
    return run, case, agent


def test_agent_request_always_uses_the_response_byte_budget(monkeypatch) -> None:
    captured = {}

    def fake_guarded_request(_db, _method, url, _project_id, **kwargs):
        captured.update(kwargs)
        return httpx.Response(
            200,
            json={"status": "completed", "output": "safe"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(runner, "guarded_request", fake_guarded_request)
    run, case, agent = _objects()
    result = runner._call_agent(None, run, case, agent)
    assert result["output"] == "safe"
    assert captured["max_response_bytes"] == runner.AGENT_RESPONSE_MAX_BYTES


@pytest.mark.parametrize("payload", [[], "text", None, 7])
def test_agent_rejects_non_object_json(monkeypatch, payload) -> None:
    def fake_guarded_request(_db, _method, url, _project_id, **_kwargs):
        return httpx.Response(
            200,
            content=json.dumps(payload).encode(),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(runner, "guarded_request", fake_guarded_request)
    run, case, agent = _objects()
    with pytest.raises(ValueError, match="JSON 对象"):
        runner._call_agent(None, run, case, agent)


def test_agent_rejects_malformed_json_without_echoing_body(monkeypatch) -> None:
    canary = "WG-INVALID-JSON-CANARY"

    def fake_guarded_request(_db, _method, url, _project_id, **_kwargs):
        return httpx.Response(
            200,
            content=("{" + canary).encode(),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(runner, "guarded_request", fake_guarded_request)
    run, case, agent = _objects()
    with pytest.raises(ValueError, match="不是有效 JSON") as error:
        runner._call_agent(None, run, case, agent)
    assert canary not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("metrics", []),
        ("policy_decisions", {}),
        ("policy_decisions", ["not-an-object"]),
        ("trace", "not-an-array"),
        ("tool_calls", 7),
        ("tool_results", [None]),
    ],
)
def test_agent_rejects_invalid_nested_response_types(monkeypatch, field, value) -> None:
    payload = {"status": "completed", "output": "safe", field: value}

    def fake_guarded_request(_db, _method, url, _project_id, **_kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(runner, "guarded_request", fake_guarded_request)
    run, case, agent = _objects()
    with pytest.raises(ValueError, match=field):
        runner._call_agent(None, run, case, agent)
