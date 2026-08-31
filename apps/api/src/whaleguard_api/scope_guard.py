from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog, AuthorizationScope

try:
    from whaleguard_policy import (
        ApprovalState as SharedApprovalState,
    )
    from whaleguard_policy import (
        AuthorizationScope as SharedAuthorizationScope,
    )
    from whaleguard_policy import (
        RequestContext as SharedRequestContext,
    )
    from whaleguard_policy import (
        RiskLevel as SharedRiskLevel,
    )
    from whaleguard_policy import (
        ScopeGuard as SharedScopeGuard,
    )
except ImportError:  # Standalone API installs retain the same fail-closed fallback.
    SharedScopeGuard = None


ALLOWED_SCHEMES = {"http", "https"}
RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
IPV6_PRIVATE = ipaddress.ip_network("fc00::/7")
BUNDLED_HEALTH_PROBE_URLS = frozenset(
    {
        "http://mock-agent:8102/health",
        "http://mock-llm:8101/health",
        "http://mock-mcp-server:8103/health",
    }
)
KNOWN_METADATA_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "instance-data.ec2.internal",
}
KNOWN_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("fd00:ec2::254"),
}


class ScopeDenied(ValueError):
    pass


@dataclass(slots=True)
class ScopeDecision:
    allowed: bool
    reason: str
    url: str
    normalized_host: str | None = None
    resolved_ips: list[str] = field(default_factory=list)
    matched_scope_ids: list[str] = field(default_factory=list)
    requires_approval: bool = False
    risk_level: str = "low"


def normalize_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    address = ipaddress.ip_address(value.split("%", 1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def is_default_allowed_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.is_loopback:
        return True
    if isinstance(address, ipaddress.IPv4Address):
        return any(address in network for network in RFC1918)
    return address in IPV6_PRIVATE


def is_permanently_blocked_ip(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Block address classes that must never become reachable through a user scope."""

    return bool(
        address in KNOWN_METADATA_IPS
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or (address.is_reserved and not address.is_loopback)
    )


def resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal = normalize_ip(host)
        return [literal]
    except ValueError:
        pass
    try:
        records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ScopeDenied("域名解析失败") from exc
    addresses = sorted({normalize_ip(record[4][0]) for record in records}, key=str)
    if not addresses:
        raise ScopeDenied("域名未解析到任何地址")
    return addresses


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _active(scope: AuthorizationScope, scheme: str, now: datetime) -> bool:
    return bool(
        scope.is_authorized
        and scheme in scope.allowed_request_types
        and (_aware(scope.expires_at) is None or _aware(scope.expires_at) > now)
    )


def _domain_matches(pattern: str, host: str) -> bool:
    pattern = pattern.rstrip(".").lower()
    host = host.rstrip(".").lower()
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return host.endswith(f".{suffix}") and host != suffix
    return host == pattern


def _path_scope_matches(authorized_path: str, candidate_path: str) -> bool:
    # Exact URL scopes intentionally compare the transmitted path spelling.
    # Decoding or normalizing here can collapse distinct proxy/backend routes
    # (for example /a//b, /a/%62, or /a\\b) into the same authorization.
    return (candidate_path or "/") == (authorized_path or "/")


def _effective_url_port(value) -> int | None:
    if value.port is not None:
        return value.port
    return {"http": 80, "https": 443}.get(value.scheme.lower())


def _url_scope_matches(authorized_url: str, candidate_url: str) -> bool:
    authorized = urlsplit(authorized_url)
    candidate = urlsplit(candidate_url)
    return (
        authorized.scheme.lower() == candidate.scheme.lower()
        and (authorized.hostname or "").rstrip(".").lower()
        == (candidate.hostname or "").rstrip(".").lower()
        and _effective_url_port(authorized) == _effective_url_port(candidate)
        and _path_scope_matches(authorized.path, candidate.path)
        and authorized.query == candidate.query
        and authorized.fragment == candidate.fragment
    )


def _scope_matches(
    scope: AuthorizationScope,
    host: str,
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    url: str,
) -> bool:
    try:
        if scope.target_type == "ip":
            return address == normalize_ip(scope.target_value)
        if scope.target_type == "cidr":
            network = ipaddress.ip_network(scope.target_value, strict=False)
            return address in network
        if scope.target_type == "domain":
            return _domain_matches(scope.target_value, host)
        if scope.target_type == "url":
            return _url_scope_matches(scope.target_value, url)
    except ValueError:
        return False
    return False


def evaluate_url(
    db: Session,
    url: str,
    project_id: UUID | None,
    request_type: str | None = None,
    tool_risk_level: str = "low",
    has_approval: bool = False,
    allow_bundled_health_probe: bool = False,
) -> ScopeDecision:
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in ALLOWED_SCHEMES:
            raise ScopeDenied("仅允许 HTTP/HTTPS 协议")
        if parsed.username or parsed.password:
            raise ScopeDenied("URL 不允许包含用户凭据")
        if not parsed.hostname:
            raise ScopeDenied("URL 缺少主机名")
        host = parsed.hostname.rstrip(".").lower()
        if host in KNOWN_METADATA_HOSTS:
            raise ScopeDenied("永久阻止云元数据服务目标")
        if host in {"0", "0.0.0.0", "::", "[::]"}:
            raise ScopeDenied("不允许未指定地址")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ScopeDenied("端口无效") from exc
        if port is not None and not 1 <= port <= 65535:
            raise ScopeDenied("端口无效")
        addresses = resolve_host(host)
        if any(is_permanently_blocked_ip(address) for address in addresses):
            raise ScopeDenied("目标解析到永久禁止的链路本地、元数据或保留地址")
        effective_type = request_type or scheme
        if allow_bundled_health_probe:
            if (
                project_id is not None
                or url not in BUNDLED_HEALTH_PROBE_URLS
                or not all(is_default_allowed_ip(address) for address in addresses)
            ):
                raise ScopeDenied("内部健康探针仅允许固定的 Docker 私网本地靶场端点")
            return ScopeDecision(
                allowed=True,
                reason="固定本地靶场健康探针通过校验",
                url=url,
                normalized_host=host,
                resolved_ips=[str(address) for address in addresses],
                risk_level=tool_risk_level,
            )
        now = datetime.now(UTC)
        scopes = []
        if project_id is not None:
            scopes = list(
                db.scalars(
                    select(AuthorizationScope).where(AuthorizationScope.project_id == project_id)
                )
            )
        active_scopes = [scope for scope in scopes if _active(scope, effective_type, now)]
        if SharedScopeGuard is not None:
            shared_scopes = []
            scope_by_value: dict[str, AuthorizationScope] = {}
            for scope in active_scopes:
                value = scope.target_value
                kind = scope.target_type
                if kind == "url":
                    target_parts = urlsplit(value)
                    if not _url_scope_matches(value, url):
                        continue
                    value = target_parts.hostname or ""
                    kind = "domain"
                shared = SharedAuthorizationScope(
                    value=value,
                    kind=kind,
                    enabled=True,
                    expires_at=_aware(scope.expires_at),
                    allowed_request_types=frozenset(scope.allowed_request_types),
                    allow_public=True,
                )
                shared_scopes.append(shared)
                scope_by_value[value] = scope
            shared_decision = SharedScopeGuard(shared_scopes).check_url(
                url,
                SharedRequestContext(
                    project_id=str(project_id or "no-project-scope"),
                    request_type=effective_type,
                    tool_risk=SharedRiskLevel(tool_risk_level),
                    requires_approval=tool_risk_level in {"high", "critical"},
                    approval_state=(
                        SharedApprovalState.APPROVED
                        if has_approval
                        else SharedApprovalState.NOT_REQUIRED
                    ),
                ),
            )
            matched_scope = scope_by_value.get(shared_decision.matched_scope or "")
            return ScopeDecision(
                allowed=shared_decision.allowed,
                reason=shared_decision.reason,
                url=url,
                normalized_host=host,
                resolved_ips=list(shared_decision.resolved_ips),
                matched_scope_ids=[str(matched_scope.id)] if matched_scope else [],
                requires_approval=shared_decision.requires_approval,
                risk_level=tool_risk_level,
            )
        matched_ids: set[str] = set()
        for address in addresses:
            matches = [
                scope for scope in active_scopes if _scope_matches(scope, host, address, url)
            ]
            if not matches:
                raise ScopeDenied(f"解析地址 {address} 不在已确认授权范围内")
            matched_ids.update(str(scope.id) for scope in matches)

        requires_approval = tool_risk_level in {"high", "critical"}
        if requires_approval and not has_approval:
            return ScopeDecision(
                allowed=False,
                reason="高风险工具调用需要人工审批",
                url=url,
                normalized_host=host,
                resolved_ips=[str(address) for address in addresses],
                matched_scope_ids=sorted(matched_ids),
                requires_approval=True,
                risk_level=tool_risk_level,
            )
        return ScopeDecision(
            allowed=True,
            reason="目标通过 Scope Guard 校验",
            url=url,
            normalized_host=host,
            resolved_ips=[str(address) for address in addresses],
            matched_scope_ids=sorted(matched_ids),
            risk_level=tool_risk_level,
        )
    except ScopeDenied as exc:
        return ScopeDecision(allowed=False, reason=str(exc), url=url, risk_level=tool_risk_level)


def log_policy_decision(
    db: Session, decision: ScopeDecision, project_id: UUID | None, request_id: str | None = None
) -> None:
    db.add(
        AuditLog(
            action="scope_guard.evaluate",
            resource_type="authorization_scope",
            resource_id=str(project_id) if project_id else None,
            outcome="allowed" if decision.allowed else "blocked",
            request_id=request_id,
            details={
                "url": _sanitize_url_for_log(decision.url),
                "host": decision.normalized_host,
                "resolved_ips": decision.resolved_ips,
                "matched_scope_ids": decision.matched_scope_ids,
                "reason": decision.reason,
                "requires_approval": decision.requires_approval,
                "risk_level": decision.risk_level,
            },
        )
    )


def _sanitize_url_for_log(url: str) -> str:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if not host:
            return "[invalid-url]"
        display_host = f"[{host}]" if ":" in host else host
        netloc = f"{display_host}:{parsed.port}" if parsed.port else display_host
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", "", ""))[:2048]
    except (TypeError, ValueError):
        return "[invalid-url]"


def _strip_cross_origin_sensitive_headers(headers: dict[str, str]) -> dict[str, str]:
    sensitive_fragments = (
        "authorization",
        "cookie",
        "api-key",
        "api_key",
        "token",
        "secret",
        "credential",
        "private-key",
        "private_key",
    )
    return {
        key: value
        for key, value in headers.items()
        if not any(fragment in key.casefold() for fragment in sensitive_fragments)
    }


def guarded_request(
    db: Session,
    method: str,
    url: str,
    project_id: UUID | None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
    max_redirects: int = 3,
    request_id: str | None = None,
    json_body: dict | None = None,
    max_response_bytes: int | None = None,
    allow_bundled_health_probe: bool = False,
) -> httpx.Response:
    if allow_bundled_health_probe and (
        method.upper() != "GET"
        or project_id is not None
        or url not in BUNDLED_HEALTH_PROBE_URLS
        or headers
        or json_body is not None
        or max_redirects != 0
        or max_response_bytes is None
        or max_response_bytes > 8192
    ):
        raise ValueError("内部健康探针参数超出固定安全边界")
    current_url = url
    original_origin = None
    for redirect_count in range(max_redirects + 1):
        decision = evaluate_url(
            db,
            current_url,
            project_id,
            allow_bundled_health_probe=allow_bundled_health_probe,
        )
        log_policy_decision(db, decision, project_id, request_id)
        db.commit()
        if not decision.allowed:
            raise ScopeDenied(decision.reason)
        parsed = urlsplit(current_url)
        origin = (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)
        if original_origin is None:
            original_origin = origin
        request_headers = dict(headers or {})
        if origin != original_origin:
            request_headers = _strip_cross_origin_sensitive_headers(request_headers)
        checked_ip = decision.resolved_ips[0]
        original_url = httpx.URL(current_url)
        pinned_url = original_url.copy_with(host=checked_ip)
        request_headers["Host"] = original_url.netloc.decode("ascii")
        extensions = {"sni_hostname": original_url.raw_host.decode("ascii")}
        with httpx.Client(follow_redirects=False, timeout=timeout, trust_env=False) as client:
            if max_response_bytes is None:
                response = client.request(
                    method,
                    pinned_url,
                    headers=request_headers,
                    json=json_body,
                    extensions=extensions,
                )
            else:
                if max_response_bytes < 1:
                    raise ValueError("max_response_bytes 必须大于零")
                with client.stream(
                    method,
                    pinned_url,
                    headers=request_headers,
                    json=json_body,
                    extensions=extensions,
                ) as streamed:
                    body = bytearray()
                    for chunk in streamed.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_response_bytes:
                            raise ScopeDenied("响应正文超过允许大小")
                    response = httpx.Response(
                        status_code=streamed.status_code,
                        headers=streamed.headers,
                        content=bytes(body),
                        request=streamed.request,
                        extensions=streamed.extensions,
                    )
        post_decision = evaluate_url(
            db,
            current_url,
            project_id,
            allow_bundled_health_probe=allow_bundled_health_probe,
        )
        log_policy_decision(db, post_decision, project_id, request_id)
        db.commit()
        if not post_decision.allowed or post_decision.resolved_ips != decision.resolved_ips:
            raise ScopeDenied("请求期间 DNS 解析结果发生变化，已阻止潜在 DNS Rebinding")
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        if redirect_count >= max_redirects:
            raise ScopeDenied("重定向次数超过限制")
        location = response.headers.get("location")
        if not location:
            raise ScopeDenied("重定向响应缺少 Location")
        current_url = urljoin(current_url, location)
        if response.status_code in {301, 302, 303}:
            method = "GET"
            json_body = None
    raise ScopeDenied("请求未完成")
