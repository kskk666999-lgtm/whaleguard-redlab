from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .config import Settings, get_settings

_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(
    user_id: UUID,
    roles: list[str],
    permissions: list[str],
    settings: Settings | None = None,
) -> tuple[str, str, int]:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    expires_in = settings.access_token_minutes * 60
    csrf_token = secrets.token_urlsafe(32)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=expires_in),
        "jti": secrets.token_urlsafe(18),
        "csrf": csrf_token,
        "roles": roles,
        "permissions": permissions,
        "iss": "whaleguard-redlab",
        "aud": "whaleguard-redlab-api",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, csrf_token, expires_in


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        issuer="whaleguard-redlab",
        audience="whaleguard-redlab-api",
        options={"require": ["sub", "exp", "iat", "jti", "csrf"]},
    )


def _fernet(settings: Settings | None = None) -> Fernet:
    settings = settings or get_settings()
    digest = hashlib.sha256(settings.effective_encryption_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None, settings: Settings | None = None) -> bytes | None:
    if not value:
        return None
    return _fernet(settings).encrypt(value.encode("utf-8"))


def decrypt_secret(value: bytes | None, settings: Settings | None = None) -> str | None:
    if not value:
        return None
    try:
        return _fernet(settings).decrypt(value).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Encrypted value could not be decrypted") from exc


def encrypt_json(value: dict[str, Any], settings: Settings | None = None) -> bytes | None:
    if not value:
        return None
    return encrypt_secret(json.dumps(value, ensure_ascii=False, sort_keys=True), settings)


def decrypt_json(value: bytes | None, settings: Settings | None = None) -> dict[str, Any]:
    plaintext = decrypt_secret(value, settings)
    return json.loads(plaintext) if plaintext else {}


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    suffix = value[-4:] if len(value) > 4 else "****"
    return f"sk-********{suffix}"


SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "private_key",
    "access_key",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value
