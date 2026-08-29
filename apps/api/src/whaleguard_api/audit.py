from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog, User
from .security import redact


def write_audit(
    db: Session,
    request: Request | None,
    action: str,
    resource_type: str,
    resource_id: UUID | str | None = None,
    actor: User | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> AuditLog:
    client_ip = request.client.host if request and request.client else None
    record = AuditLog(
        actor_id=actor.id if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        outcome=outcome,
        ip_address=client_ip,
        user_agent=(request.headers.get("user-agent", "")[:512] if request else None),
        request_id=(getattr(request.state, "request_id", None) if request else None),
        details=redact(details or {}),
    )
    db.add(record)
    return record
