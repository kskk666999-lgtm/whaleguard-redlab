from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_and_login(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["database"] == "ok"

    invalid = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong-password"}
    )
    assert invalid.status_code == 401
    assert "password" not in invalid.text.lower()

    oversized = client.post(
        "/api/v1/auth/login",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": str(13 * 1024 * 1024)},
    )
    assert oversized.status_code == 413


def test_user_beginner_preferences_are_private_and_persisted(
    client: TestClient, auth: dict[str, str]
) -> None:
    initial = client.get("/api/v1/auth/preferences", headers=auth)
    assert initial.status_code == 200, initial.text
    assert initial.json() == {
        "experience_mode": "beginner",
        "onboarding_complete": False,
        "onboarding_goal": None,
    }

    updated = client.patch(
        "/api/v1/auth/preferences",
        headers=auth,
        json={
            "experience_mode": "advanced",
            "onboarding_complete": True,
            "onboarding_goal": "both",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json() == {
        "experience_mode": "advanced",
        "onboarding_complete": True,
        "onboarding_goal": "both",
    }

    me = client.get("/api/v1/auth/me", headers=auth)
    assert me.status_code == 200, me.text
    assert me.json()["preferences"] == updated.json()

    reloaded = client.get("/api/v1/auth/preferences", headers=auth)
    assert reloaded.status_code == 200
    assert reloaded.json() == updated.json()


def test_system_status_requires_login_and_uses_plain_language(
    client: TestClient, auth: dict[str, str]
) -> None:
    assert client.get("/api/v1/system/status").status_code == 401
    response = client.get("/api/v1/system/status", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["overall"] in {"ready", "degraded"}
    assert set(body["services"]) == {
        "api",
        "database",
        "redis",
        "worker",
        "labs",
        "model_provider",
    }
    assert body["services"]["api"]["status"] == "normal"
    assert body["services"]["database"]["status"] == "normal"
    assert body["services"]["model_provider"]["status"] in {"normal", "optional"}


def test_csrf_and_project_crud(client: TestClient, auth: dict[str, str]) -> None:
    no_csrf = {"Authorization": auth["Authorization"]}
    rejected = client.post("/api/v1/projects", headers=no_csrf, json={"name": "blocked"})
    assert rejected.status_code == 403

    created = client.post(
        "/api/v1/projects",
        headers=auth,
        json={"name": "API 集成测试项目", "description": "authorized local test"},
    )
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["status"] == "active"
    assert project["id"]

    updated = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers=auth,
        json={"tags": ["integration", "safe"]},
    )
    assert updated.status_code == 200
    assert updated.json()["tags"] == ["integration", "safe"]

    listed = client.get("/api/v1/projects?search=API&page_size=5", headers=auth)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    assert set(listed.json()) == {"items", "total", "page", "page_size", "pages"}


def test_rbac_viewer_cannot_write(client: TestClient, auth: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/users",
        headers=auth,
        json={
            "username": "viewer_test",
            "email": "viewer_test@whaleguard.local",
            "password": "Viewer-Password-2026!",
            "role_names": ["Viewer"],
        },
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer_test", "password": "Viewer-Password-2026!"},
    )
    assert login.status_code == 200
    viewer = login.json()
    viewer_headers = {
        "Authorization": f"Bearer {viewer['access_token']}",
        "X-CSRF-Token": viewer["csrf_token"],
    }
    assert client.get("/api/v1/projects", headers=viewer_headers).status_code == 200
    denied = client.post(
        "/api/v1/projects", headers=viewer_headers, json={"name": "must not create"}
    )
    assert denied.status_code == 403
