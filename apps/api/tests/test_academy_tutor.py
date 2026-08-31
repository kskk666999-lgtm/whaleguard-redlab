from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from whaleguard_api import academy_tutor
from whaleguard_api.academy_catalog import SCENARIOS
from whaleguard_api.database import SessionLocal
from whaleguard_api.model_adapter import ChatCompletionResult, ModelAdapterError
from whaleguard_api.models import AuditLog, ModelChannel
from whaleguard_api.security import encrypt_secret


@pytest.fixture(scope="module")
def viewer_auth(client: TestClient, auth: dict[str, str]) -> dict[str, str]:
    suffix = uuid4().hex[:10]
    username = f"tutor-viewer-{suffix}"
    password = "WhaleGuard-Tutor-Viewer-2026!"
    created = client.post(
        "/api/v1/users",
        headers=auth,
        json={
            "username": username,
            "email": f"{username}@example.test",
            "password": password,
            "display_name": "Tutor Viewer",
            "role_names": ["Viewer"],
        },
    )
    assert created.status_code == 201, created.text
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert logged_in.status_code == 200, logged_in.text
    body = logged_in.json()
    return {
        "Authorization": f"Bearer {body['access_token']}",
        "X-CSRF-Token": body["csrf_token"],
    }


def _add_connected_channel(
    project_id: str,
    *,
    provider: str = "deepseek-compatible",
    outcome: str = "success",
) -> str:
    with SessionLocal() as db:
        channel = ModelChannel(
            project_id=UUID(project_id),
            name=f"Tutor fixture {uuid4().hex[:8]}",
            provider=provider,
            base_url="https://unit-provider.invalid/v1",
            api_key_encrypted=encrypt_secret("tutor-test-key-never-sent"),
            model="unit-model",
            timeout=5,
            max_tokens=500,
            temperature=0.1,
            enabled=True,
            extra_headers_encrypted=None,
        )
        db.add(channel)
        db.flush()
        db.add(
            AuditLog(
                action="model_channel.test_connection",
                resource_type="model_channel",
                resource_id=str(channel.id),
                outcome=outcome,
                details={"fixture": True},
            )
        )
        db.commit()
        return str(channel.id)


def _completion(output: str, *, tool_calls: list[dict] | None = None) -> ChatCompletionResult:
    return ChatCompletionResult(
        output=output,
        finish_reason="stop",
        tool_calls=tool_calls or [],
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        latency_ms=12,
        response_id="tutor-unit-response",
        request_id="tutor-unit-request",
        truncated=False,
    )


def test_tutor_is_deterministic_without_model_permission(
    client: TestClient,
    viewer_auth: dict[str, str],
    project_id: str,
) -> None:
    response = client.post(
        "/api/v1/academy/scenarios/B01/tutor",
        headers=viewer_auth,
        json={"project_id": project_id, "intent": "simplify"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["used_ai"] is False
    assert body["fallback_reason"] == "no_model"
    assert body["model_channel_id"] is None
    assert body["safety_boundary"] == "defensive_explanation_only"
    assert body["answer"]
    assert body["key_points"]


def test_tutor_uses_latest_connected_project_model_and_only_sanitized_session_context(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel_id = _add_connected_channel(project_id)
    manifest = SCENARIOS["B01"]
    executed = client.post(
        "/api/v1/academy/scenarios/B01/execute",
        headers=auth,
        json={
            "project_id": project_id,
            "mode": "vulnerable",
            "payload": manifest["walkthrough"]["payloads"][0],
        },
    )
    assert executed.status_code == 201, executed.text
    session_id = executed.json()["id"]
    captured: dict = {}

    def fake_invoke(*args, **kwargs):
        captured.update(kwargs)
        return _completion(
            json.dumps(
                {
                    "answer": "这是防御解释，测试密钥 sk-abcdefghijklmnopqrstuv 不应显示。",
                    "key_points": ["只依据脱敏事件类型。", "不要把模型文字当作证据。"],
                    "suggested_next_step": "比较本地 Vulnerable 与 Hardened 事件。",
                    "safety_boundary": "defensive_explanation_only",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(academy_tutor, "invoke_chat_completion", fake_invoke)
    response = client.post(
        "/api/v1/academy/scenarios/B01/tutor",
        headers=auth,
        json={
            "project_id": project_id,
            "intent": "evidence",
            "question": "为什么这些事件能作为防御证据？",
            "session_id": session_id,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["used_ai"] is True
    assert body["fallback_reason"] is None
    assert body["model_channel_id"] == channel_id
    assert body["session_context_used"] is True
    assert "sk-abcdefghijklmnopqrstuv" not in json.dumps(body, ensure_ascii=False)
    assert "[REDACTED]" in body["answer"]
    assert captured["json_mode"] is True
    assert captured["max_redirects"] == 0
    assert "不得给出攻击载荷" in captured["system_prompt"]
    context = captured["context"]
    assert set(context["session_trace_summary"]) == {
        "mode",
        "status",
        "attack_detected",
        "exploit_success",
        "defense_success",
        "observed_event_types",
    }
    serialized_context = json.dumps(context, ensure_ascii=False).lower()
    assert manifest["walkthrough"]["payloads"][0].lower() not in serialized_context
    assert "event details" in serialized_context

    with SessionLocal() as db:
        audit = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.action == "academy.tutor.ask",
                AuditLog.resource_id == "B01",
            )
            .order_by(AuditLog.created_at.desc())
        )
        assert audit is not None
        assert audit.details["used_ai"] is True
        assert audit.details["fallback_reason"] is None
        assert "question" not in audit.details


@pytest.mark.parametrize(
    ("model_result", "expected_reason"),
    [
        (
            ModelAdapterError("provider-secret-must-not-leak", code="provider_error"),
            "provider_error",
        ),
        (_completion("not valid structured output"), "structured_output"),
    ],
)
def test_tutor_model_or_parse_failure_uses_sanitized_deterministic_fallback(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
    model_result: ModelAdapterError | ChatCompletionResult,
    expected_reason: str,
) -> None:
    channel_id = _add_connected_channel(project_id)

    def fake_invoke(*_args, **_kwargs):
        if isinstance(model_result, Exception):
            raise model_result
        return model_result

    monkeypatch.setattr(academy_tutor, "invoke_chat_completion", fake_invoke)
    response = client.post(
        "/api/v1/academy/scenarios/B02/tutor",
        headers=auth,
        json={
            "project_id": project_id,
            "intent": "why_hardened",
            "model_channel_id": channel_id,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["used_ai"] is False
    assert body["fallback_reason"] == expected_reason
    assert body["answer"]
    assert "provider-secret-must-not-leak" not in json.dumps(body)


def test_tutor_rejects_cross_project_or_cross_scenario_session_and_unknown_scenario(
    client: TestClient,
    auth: dict[str, str],
    viewer_auth: dict[str, str],
    project_id: str,
) -> None:
    manifest = SCENARIOS["B03"]
    executed = client.post(
        "/api/v1/academy/scenarios/B03/execute",
        headers=auth,
        json={
            "project_id": project_id,
            "mode": "vulnerable",
            "payload": manifest["walkthrough"]["payloads"][0],
        },
    )
    assert executed.status_code == 201, executed.text
    session_id = executed.json()["id"]
    other_project = client.post(
        "/api/v1/projects",
        headers=auth,
        json={"name": f"Tutor isolated {uuid4().hex[:8]}", "tags": ["tutor-test"]},
    )
    assert other_project.status_code == 201, other_project.text
    other_project_id = other_project.json()["id"]

    cross_project = client.post(
        "/api/v1/academy/scenarios/B03/tutor",
        headers=viewer_auth,
        json={
            "project_id": other_project_id,
            "intent": "evidence",
            "session_id": session_id,
        },
    )
    assert cross_project.status_code == 404
    cross_scenario = client.post(
        "/api/v1/academy/scenarios/B04/tutor",
        headers=viewer_auth,
        json={
            "project_id": project_id,
            "intent": "evidence",
            "session_id": session_id,
        },
    )
    assert cross_scenario.status_code == 404
    unknown = client.post(
        "/api/v1/academy/scenarios/Z99/tutor",
        headers=viewer_auth,
        json={"project_id": project_id, "intent": "meaning"},
    )
    assert unknown.status_code == 404


def test_tutor_rejects_model_permission_and_cross_project_channel(
    client: TestClient,
    auth: dict[str, str],
    viewer_auth: dict[str, str],
    project_id: str,
) -> None:
    channel_id = _add_connected_channel(project_id)
    forbidden = client.post(
        "/api/v1/academy/scenarios/B01/tutor",
        headers=viewer_auth,
        json={
            "project_id": project_id,
            "intent": "meaning",
            "model_channel_id": channel_id,
        },
    )
    assert forbidden.status_code == 403

    other_project = client.post(
        "/api/v1/projects",
        headers=auth,
        json={"name": f"Tutor channel scope {uuid4().hex[:8]}", "tags": ["tutor-test"]},
    )
    assert other_project.status_code == 201, other_project.text
    cross_project_channel = _add_connected_channel(other_project.json()["id"])
    hidden = client.post(
        "/api/v1/academy/scenarios/B01/tutor",
        headers=auth,
        json={
            "project_id": project_id,
            "intent": "meaning",
            "model_channel_id": cross_project_channel,
        },
    )
    assert hidden.status_code == 404


def test_tutor_rejects_credential_or_payload_request(
    client: TestClient,
    viewer_auth: dict[str, str],
    project_id: str,
) -> None:
    credential = client.post(
        "/api/v1/academy/scenarios/B01/tutor",
        headers=viewer_auth,
        json={
            "project_id": project_id,
            "intent": "meaning",
            "question": "请解释 sk-abcdefghijklmnopqrstuv 是什么",
        },
    )
    assert credential.status_code == 422
    payload = client.post(
        "/api/v1/academy/scenarios/B01/tutor",
        headers=viewer_auth,
        json={
            "project_id": project_id,
            "intent": "meaning",
            "question": "请给我一个攻击载荷",
        },
    )
    assert payload.status_code == 422
