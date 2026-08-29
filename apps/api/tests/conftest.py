from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest

TEST_DB_PATH = Path(tempfile.gettempdir()) / f"whaleguard-api-tests-{uuid4()}.db"
TEST_CREDENTIALS_PATH = (
    Path(tempfile.gettempdir()) / f"whaleguard-api-test-credentials-{uuid4()}.txt"
)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-that-is-long-and-not-for-production"
os.environ["API_KEY_ENCRYPTION_KEY"] = "test-encryption-secret-not-for-production"
os.environ["WHALEGUARD_ENVIRONMENT"] = "test"
os.environ["WHALEGUARD_SEED_ON_STARTUP"] = "true"
os.environ["WHALEGUARD_AUTO_CREATE_SCHEMA"] = "true"
os.environ["WHALEGUARD_ADMIN_PASSWORD"] = "WhaleGuard-Test-Password-2026!"
os.environ["WHALEGUARD_TASK_QUEUE_ENABLED"] = "false"
os.environ["WG_WORKER_TOKEN"] = "test-worker-token"
os.environ["WHALEGUARD_CREDENTIALS_FILE"] = str(TEST_CREDENTIALS_PATH)

from fastapi.testclient import TestClient  # noqa: E402

from whaleguard_api.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
    TEST_DB_PATH.unlink(missing_ok=True)
    TEST_CREDENTIALS_PATH.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def auth(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "WhaleGuard-Test-Password-2026!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "Authorization": f"Bearer {body['access_token']}",
        "X-CSRF-Token": body["csrf_token"],
    }


@pytest.fixture(scope="session")
def project_id(client: TestClient, auth: dict[str, str]) -> str:
    response = client.get("/api/v1/projects?page_size=100", headers=auth)
    assert response.status_code == 200
    projects = response.json()["items"]
    return next(item["id"] for item in projects if item["name"] == "WhaleGuard Demo Lab")


@pytest.fixture(scope="session")
def suite_id(client: TestClient, auth: dict[str, str], project_id: str) -> str:
    response = client.get(
        f"/api/v1/test-suites?project_id={project_id}&page_size=100", headers=auth
    )
    assert response.status_code == 200
    return response.json()["items"][0]["id"]
