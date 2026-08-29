from __future__ import annotations

from urllib.parse import urljoin

import httpx

from .models import RequestContext
from .scope_guard import ScopeGuard


class ScopeViolation(RuntimeError):
    pass


class ScopedAsyncClient:
    """HTTP client that validates and DNS-pins every request/redirect hop.

    Validation without pinning is insufficient: a hostname can resolve to an
    allowed address during the policy check and a different address when the
    HTTP stack connects. The transport therefore receives the already checked
    IP while the original Host header and TLS SNI name are retained.
    """

    def __init__(
        self,
        guard: ScopeGuard,
        *,
        max_redirects: int = 3,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.guard = guard
        self.max_redirects = max_redirects
        # The pinned IP is the pool origin, while SNI is request-specific. Avoid
        # reusing a TLS connection for two authorized hostnames sharing an IP.
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
            transport=transport,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    @staticmethod
    def _pinned_request(
        current: str,
        resolved_ip: str,
        kwargs: dict,
    ) -> tuple[httpx.URL, dict]:
        original_url = httpx.URL(current)
        pinned_url = original_url.copy_with(host=resolved_ip)

        request_kwargs = dict(kwargs)
        headers = httpx.Headers(request_kwargs.pop("headers", None))
        headers["Host"] = original_url.netloc.decode("ascii")
        request_kwargs["headers"] = headers

        extensions = dict(request_kwargs.pop("extensions", {}) or {})
        extensions["sni_hostname"] = original_url.raw_host.decode("ascii")
        request_kwargs["extensions"] = extensions
        return pinned_url, request_kwargs

    @staticmethod
    def _is_sensitive_redirect_header(name: str) -> bool:
        normalized = name.casefold().replace("_", "-")
        return (
            normalized.endswith("-auth")
            or normalized.startswith("auth-")
            or any(
                marker in normalized
                for marker in (
                    "authorization",
                    "cookie",
                    "api-key",
                    "token",
                    "secret",
                    "credential",
                )
            )
        )

    @staticmethod
    def _redirect_kwargs(
        kwargs: dict,
        *,
        source: str,
        destination: str,
        status_code: int,
    ) -> dict:
        redirected = dict(kwargs)
        headers = httpx.Headers(redirected.pop("headers", None))
        source_url = httpx.URL(source)
        destination_url = httpx.URL(destination)
        if (
            source_url.scheme,
            source_url.raw_host,
            source_url.port,
        ) != (
            destination_url.scheme,
            destination_url.raw_host,
            destination_url.port,
        ):
            for name in tuple(headers.keys()):
                if ScopedAsyncClient._is_sensitive_redirect_header(name):
                    headers.pop(name, None)
            redirected.pop("auth", None)
            redirected.pop("cookies", None)

        if status_code in {301, 302, 303}:
            for name in ("content", "data", "files", "json"):
                redirected.pop(name, None)
            for name in ("Content-Length", "Content-Type", "Transfer-Encoding"):
                headers.pop(name, None)
        redirected["headers"] = headers
        return redirected

    async def request(
        self, method: str, url: str, context: RequestContext, **kwargs
    ) -> httpx.Response:
        kwargs = dict(kwargs)
        params = kwargs.pop("params", None)
        current_url = httpx.URL(url)
        if params is not None:
            current_url = current_url.copy_merge_params(params)
        current = str(current_url)
        for redirect_count in range(self.max_redirects + 1):
            decision = self.guard.check_url(current, context)
            if not decision.allowed:
                raise ScopeViolation(f"{decision.code}: {decision.reason}")
            if not decision.resolved_ips:
                raise ScopeViolation("dns_empty: 策略未提供可固定的目标地址")
            pinned_url, request_kwargs = self._pinned_request(
                current, decision.resolved_ips[0], kwargs
            )
            response = await self._client.request(method, pinned_url, **request_kwargs)
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            if redirect_count == self.max_redirects:
                raise ScopeViolation("redirect_limit: 重定向次数超过策略上限")
            next_url = urljoin(current, location)
            kwargs = self._redirect_kwargs(
                kwargs,
                source=current,
                destination=next_url,
                status_code=response.status_code,
            )
            current = next_url
            method = "GET" if response.status_code in {301, 302, 303} else method
        raise ScopeViolation("unreachable")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()
