from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .models import ApprovalState, AuthorizationScope, PolicyDecision, RequestContext, RiskLevel

Resolver = Callable[[str, int], Iterable[tuple]]
DecisionSink = Callable[[PolicyDecision], None]


class ScopeGuard:
    """Fail-closed URL and tool authorization policy.

    The guard validates the original target and every redirect. A caller must use
    :class:`ScopedAsyncClient` (or equivalent enforcement) so a redirect cannot
    bypass these checks. Every DNS answer is normalized and checked; mixed
    authorized/unauthorized answers are rejected to prevent DNS rebinding tricks.
    """

    ALLOWED_SCHEMES = frozenset({"http", "https"})
    DEFAULT_NETWORKS = tuple(
        ipaddress.ip_network(cidr)
        for cidr in (
            "127.0.0.0/8",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "::1/128",
            "fc00::/7",
        )
    )
    # A domain authorization must not silently grant access to non-routable or
    # metadata-adjacent address classes. An operator can still authorize an
    # exact IP/CIDR explicitly when a lab genuinely needs one of these ranges.
    BLOCKED_DOMAIN_RESOLUTION_NETWORKS = tuple(
        ipaddress.ip_network(cidr)
        for cidr in (
            "0.0.0.0/8",
            "100.64.0.0/10",
            "169.254.0.0/16",
            "192.0.0.0/24",
            "198.18.0.0/15",
            "224.0.0.0/4",
            "240.0.0.0/4",
            "::/96",
            "64:ff9b::/96",
            "64:ff9b:1::/48",
            "100::/64",
            "fe80::/10",
            "fec0::/10",
            "ff00::/8",
            "2001::/32",
            "2001:db8::/32",
            "2002::/16",
        )
    )

    def __init__(
        self,
        scopes: Iterable[AuthorizationScope] = (),
        *,
        resolver: Resolver | None = None,
        decision_sink: DecisionSink | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.scopes = tuple(scopes)
        # Resolve the default at instance creation time so tests and embedding
        # applications can replace ``socket.getaddrinfo`` deterministically.
        self._resolver = resolver or socket.getaddrinfo
        self._decision_sink = decision_sink
        self._now = now or (lambda: datetime.now(UTC))

    def check_url(self, target: str, context: RequestContext) -> PolicyDecision:
        parsed = urlsplit(target)
        if parsed.scheme.lower() not in self.ALLOWED_SCHEMES:
            return self._deny("scheme_blocked", "仅允许 HTTP/HTTPS 协议", target, context)
        if not parsed.hostname or parsed.username or parsed.password:
            return self._deny(
                "invalid_authority", "目标主机无效或包含禁止的用户信息", target, context
            )
        try:
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        except ValueError:
            return self._deny("invalid_port", "目标端口无效", target, context)

        approval_denial = self._check_approval(target, context)
        if approval_denial:
            return approval_denial

        hostname = parsed.hostname.rstrip(".").lower()
        try:
            addresses = self._resolve(hostname, port)
        except (OSError, ValueError) as exc:
            return self._deny(
                "dns_resolution_failed",
                "域名解析失败，已按失败关闭策略阻止",
                target,
                context,
                details={"error_type": type(exc).__name__},
            )
        if not addresses:
            return self._deny("dns_empty", "域名未返回可验证地址", target, context)

        active = [scope for scope in self.scopes if scope.is_active(self._now())]
        matched = self._matching_scope(hostname, addresses, context.request_type, active)
        if matched:
            unsafe_answers = [
                str(ip)
                for ip in addresses
                if matched.kind in {"host", "domain"} and self._is_blocked_domain_resolution(ip)
            ]
            if unsafe_answers:
                return self._deny(
                    "unsafe_resolution_blocked",
                    "域名解析到禁止的链路本地、未指定、组播或保留地址",
                    target,
                    context,
                    resolved=addresses,
                    matched_scope=matched.value,
                    details={"blocked_ips": unsafe_answers},
                )
            public_answers = [str(ip) for ip in addresses if not self._is_default_allowed(ip)]
            if public_answers and not matched.allow_public:
                return self._deny(
                    "public_resolution_blocked",
                    "授权条目未允许公网解析结果",
                    target,
                    context,
                    resolved=addresses,
                    matched_scope=matched.value,
                )
            return self._allow(target, context, addresses, matched.value)

        return self._deny(
            "target_out_of_scope",
            "目标不在项目已确认的 Scope 内",
            target,
            context,
            resolved=addresses,
        )

    def check_redirect(self, location: str, context: RequestContext) -> PolicyDecision:
        return self.check_url(location, context)

    def check_tool(self, target: str, context: RequestContext) -> PolicyDecision:
        approval_denial = self._check_approval(target, context)
        if approval_denial:
            return approval_denial
        if context.tool_risk is RiskLevel.CRITICAL:
            return self._deny(
                "critical_tool_blocked", "关键风险 Tool 默认禁止执行", target, context
            )
        return self._emit(
            PolicyDecision(
                allowed=True,
                code="tool_allowed",
                reason="Tool 风险和审批策略已满足",
                target=target,
                project_id=context.project_id,
                requires_approval=context.requires_approval,
            )
        )

    def _check_approval(self, target: str, context: RequestContext) -> PolicyDecision | None:
        approval_needed = context.requires_approval or context.tool_risk in {
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }
        if approval_needed and context.approval_state is not ApprovalState.APPROVED:
            code = (
                "approval_rejected"
                if context.approval_state is ApprovalState.REJECTED
                else "approval_required"
            )
            reason = "高风险操作需要已批准的人工审批"
            return self._deny(code, reason, target, context, requires_approval=True)
        return None

    def _resolve(
        self, hostname: str, port: int
    ) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        try:
            direct = self._normalize_ip(ipaddress.ip_address(hostname))
            return (direct,)
        except ValueError:
            pass
        answers = self._resolver(hostname, port)
        unique: dict[str, ipaddress.IPv4Address | ipaddress.IPv6Address] = {}
        for answer in answers:
            raw = answer[4][0]
            parsed = self._normalize_ip(ipaddress.ip_address(raw.split("%", 1)[0]))
            unique[str(parsed)] = parsed
        return tuple(unique[key] for key in sorted(unique))

    @staticmethod
    def _normalize_ip(value: ipaddress.IPv4Address | ipaddress.IPv6Address):
        if isinstance(value, ipaddress.IPv6Address) and value.ipv4_mapped:
            return value.ipv4_mapped
        return value

    def _is_default_allowed(self, address) -> bool:
        return any(address in network for network in self.DEFAULT_NETWORKS)

    def _is_blocked_domain_resolution(self, address) -> bool:
        special_non_global = not self._is_default_allowed(address) and not address.is_global
        return special_non_global or any(
            address in network for network in self.BLOCKED_DOMAIN_RESOLUTION_NETWORKS
        )

    def _matching_scope(
        self,
        hostname: str,
        addresses: tuple,
        request_type: str,
        scopes: list[AuthorizationScope],
    ) -> AuthorizationScope | None:
        for scope in scopes:
            if request_type not in scope.allowed_request_types:
                continue
            value = scope.value.strip().rstrip(".").lower()
            if scope.kind in {"host", "domain"}:
                wildcard = value.startswith("*.")
                base = value[2:] if wildcard else value
                host_match = hostname == base or (wildcard and hostname.endswith("." + base))
                if host_match:
                    return scope
            elif scope.kind == "ip":
                try:
                    scoped_ip = self._normalize_ip(ipaddress.ip_address(value))
                except ValueError:
                    continue
                if all(address == scoped_ip for address in addresses):
                    return scope
            elif scope.kind == "cidr":
                try:
                    network = ipaddress.ip_network(value, strict=False)
                except ValueError:
                    continue
                if all(address in network for address in addresses):
                    return scope
        return None

    def _allow(self, target, context, resolved, matched_scope) -> PolicyDecision:
        return self._emit(
            PolicyDecision(
                allowed=True,
                code="allowed",
                reason="目标通过项目 Scope 与网络策略检查",
                target=target,
                project_id=context.project_id,
                resolved_ips=tuple(str(ip) for ip in resolved),
                matched_scope=matched_scope,
                requires_approval=context.requires_approval,
            )
        )

    def _deny(
        self,
        code,
        reason,
        target,
        context,
        *,
        resolved=(),
        matched_scope=None,
        requires_approval=False,
        details=None,
    ) -> PolicyDecision:
        return self._emit(
            PolicyDecision(
                allowed=False,
                code=code,
                reason=reason,
                target=target,
                project_id=context.project_id,
                resolved_ips=tuple(str(ip) for ip in resolved),
                matched_scope=matched_scope,
                requires_approval=requires_approval,
                details=details or {},
            )
        )

    def _emit(self, decision: PolicyDecision) -> PolicyDecision:
        if self._decision_sink:
            self._decision_sink(decision)
        return decision
