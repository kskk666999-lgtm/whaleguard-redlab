from __future__ import annotations

import json
import secrets
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_prefix="WHALEGUARD_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "WhaleGuard AI RedLab"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    database_url: str = Field(
        default="sqlite:///./whaleguard.db",
        validation_alias=AliasChoices("DATABASE_URL", "WHALEGUARD_DATABASE_URL"),
    )
    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        validation_alias=AliasChoices("REDIS_URL", "WHALEGUARD_REDIS_URL"),
    )
    jwt_secret: str = Field(
        default_factory=lambda: secrets.token_urlsafe(48),
        validation_alias=AliasChoices(
            "JWT_SECRET_KEY", "WHALEGUARD_JWT_SECRET", "WHALEGUARD_JWT_SECRET_KEY"
        ),
    )
    encryption_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "API_KEY_ENCRYPTION_KEY",
            "WHALEGUARD_ENCRYPTION_SECRET",
            "WHALEGUARD_API_KEY_ENCRYPTION_KEY",
        ),
    )
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    allowed_origins: Annotated[list[str], NoDecode] = [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]
    allowed_hosts: Annotated[list[str], NoDecode] = ["127.0.0.1", "localhost", "testserver"]
    max_request_bytes: int = 12 * 1024 * 1024
    max_upload_bytes: int = 10 * 1024 * 1024
    upload_dir: str = "./data/uploads"
    admin_username: str = "admin"
    admin_email: str = "admin@whaleguard.local"
    admin_password: str | None = None
    credentials_file: str = Field(
        default="./.local/first-run-credentials.txt",
        validation_alias=AliasChoices("WHALEGUARD_CREDENTIALS_FILE", "CREDENTIALS_FILE"),
    )
    seed_on_startup: bool = True
    auto_create_schema: bool = True
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    mock_agent_url: str = Field(
        default="http://mock-agent:8102",
        validation_alias=AliasChoices("MOCK_AGENT_URL", "WHALEGUARD_MOCK_AGENT_URL"),
    )
    task_queue_enabled: bool = True
    rq_queue: str = Field(
        default="whaleguard",
        validation_alias=AliasChoices("RQ_QUEUE", "WHALEGUARD_RQ_QUEUE"),
    )
    worker_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WG_WORKER_TOKEN", "WHALEGUARD_WORKER_TOKEN"),
    )
    worker_callback_base: str = "http://api:8000"

    @field_validator("allowed_origins", "allowed_hosts", mode="before")
    @classmethod
    def parse_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("allowed_origins")
    @classmethod
    def forbid_wildcard_origin(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("Wildcard CORS origins are not allowed")
        return value

    @property
    def effective_encryption_secret(self) -> str:
        return self.encryption_secret or self.jwt_secret


@lru_cache
def get_settings() -> Settings:
    return Settings()
