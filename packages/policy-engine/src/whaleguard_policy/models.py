from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)\b(api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|password|secret|"
    r"credential|authorization|cookie|private[-_ ]?key)\b(\s*[:=]\s*|/)([^\s,;&#]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\b(bearer\s+)([^\s,;]+)")
_TOKEN_SHAPES = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"|sk-[A-Za-z0-9_-]{16,}"
    r"|github_pat_[A-Za-z0-9_]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|xox[baprs]-[A-Za-z0-9-]{16,}"
    r"|[rs]k_(?:live|test)_[A-Za-z0-9]{16,}"
    r")(?![A-Za-z0-9_-])"
)


def _redact_text(value: str) -> str:
    value = _BEARER_TOKEN.sub(lambda match: f"{match.group(1)}[REDACTED]", value)
    value = _SENSITIVE_TEXT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)
    return _TOKEN_SHAPES.sub("[REDACTED]", value)


def _redact_target(value: str) -> str:
    """Keep useful routing evidence without logging credentials or query values."""

    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc or not parsed.hostname:
            return _redact_text(value)[:4_096]
        hostname = parsed.hostname
        safe_host = f"[{hostname}]" if ":" in hostname else hostname
        try:
            if parsed.port is not None:
                safe_host = f"{safe_host}:{parsed.port}"
        except ValueError:
            pass
        return urlunsplit(
            (
                parsed.scheme,
                safe_host,
                _redact_text(parsed.path)[:2_048],
                "[REDACTED]" if parsed.query else "",
                "[REDACTED]" if parsed.fragment else "",
            )
        )
    except (TypeError, ValueError):
        return "[INVALID_TARGET]"


def _redact_log_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 6:
        return "[MAX_DEPTH]"
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).casefold().replace("-", "_")
            if any(marker in normalized_key for marker in _SENSITIVE_KEY_MARKERS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_log_value(item, depth=depth + 1)
        return redacted
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redact_log_value(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        return _redact_text(value)[:4_096]
    return value


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AuthorizationScope:
    """A normalized, explicitly authorized target definition."""

    value: str
    kind: str = "host"  # host, domain, ip, cidr
    enabled: bool = True
    expires_at: datetime | None = None
    allowed_request_types: frozenset[str] = frozenset({"http", "model", "agent", "metadata"})
    allow_public: bool = False

    def is_active(self, now: datetime | None = None) -> bool:
        check_time = now or datetime.now(UTC)
        expiry = self.expires_at
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return self.enabled and (expiry is None or expiry > check_time)


@dataclass(frozen=True, slots=True)
class RequestContext:
    project_id: str
    request_type: str = "http"
    tool_name: str | None = None
    tool_risk: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    approval_state: ApprovalState = ApprovalState.NOT_REQUIRED
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    code: str
    reason: str
    target: str
    project_id: str
    resolved_ips: tuple[str, ...] = ()
    matched_scope: str | None = None
    requires_approval: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)

    def to_log_record(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            "target": _redact_target(self.target),
            "project_id": self.project_id,
            "resolved_ips": list(self.resolved_ips),
            "matched_scope": self.matched_scope,
            "requires_approval": self.requires_approval,
            "timestamp": self.timestamp.isoformat(),
            "details": _redact_log_value(self.details),
        }
