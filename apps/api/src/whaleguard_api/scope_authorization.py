from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuthorizationScope, User
from .scope_guard import ALLOWED_SCHEMES, ScopeDenied


def normalize_exact_url(value: str) -> str:
    """Return a credential/query-free URL suitable for an exact path scope."""

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ScopeDenied("URL 格式无效") from exc
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ScopeDenied("仅允许 HTTP/HTTPS 协议")
    if parsed.username or parsed.password:
        raise ScopeDenied("URL 不允许包含用户凭据")
    if parsed.query or parsed.fragment:
        raise ScopeDenied("请填写不含查询参数或片段的页面 URL")
    decoded_path = parsed.path or "/"
    fully_decoded = False
    for _ in range(8):
        next_path = unquote(decoded_path)
        if next_path == decoded_path:
            fully_decoded = True
            break
        decoded_path = next_path
    if not fully_decoded:
        raise ScopeDenied("URL 路径编码层数过多")
    if "\\" in decoded_path or "\x00" in decoded_path:
        raise ScopeDenied("URL 路径包含不允许的转义或反斜杠")
    if any(segment in {".", ".."} for segment in decoded_path.split("/")):
        raise ScopeDenied("URL 路径不允许包含点号跳转片段")
    # Preserve the exact path spelling that the user authorized. Rewriting
    # duplicate/trailing slashes or harmless percent-encoding can change which
    # route a proxy/backend serves while making the stored Scope look broader.
    canonical_path = parsed.path or "/"
    if not canonical_path:
        raise ScopeDenied("URL 路径无效")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise ScopeDenied("URL 缺少主机名")
    if port is not None and not 1 <= port <= 65535:
        raise ScopeDenied("端口无效")
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    display_host = f"[{host}]" if ":" in host else host
    netloc = f"{display_host}:{port}" if port else display_host
    return urlunsplit((scheme, netloc, canonical_path, "", ""))


def ensure_temporary_exact_url_scope(
    db: Session,
    *,
    project_id: UUID,
    target_url: str,
    actor: User,
    name: str,
    notes: str,
    lifetime: timedelta,
) -> tuple[AuthorizationScope, bool]:
    """Create or explicitly renew only the exact URL path confirmed by the user."""

    normalized = normalize_exact_url(target_url)
    now = datetime.now(UTC)
    scope = db.scalar(
        select(AuthorizationScope).where(
            AuthorizationScope.project_id == project_id,
            AuthorizationScope.target_type == "url",
            AuthorizationScope.target_value == normalized,
        )
    )
    created = scope is None
    if scope is None:
        scope = AuthorizationScope(
            project_id=project_id,
            name=name[:200],
            target_type="url",
            target_value=normalized,
        )
        db.add(scope)
    scope.name = name[:200]
    scope.allowed_request_types = ["http", "https"]
    scope.is_authorized = True
    scope.confirmed_by_id = actor.id
    scope.authorized_at = now
    scope.expires_at = now + lifetime
    scope.notes = notes[:5000]
    db.flush()
    return scope, created
