from __future__ import annotations

import ipaddress
import os
import socket
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from .evaluator import evaluate_rules

_PRIVATE_CALLBACK_NETWORKS = tuple(
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
_CALLBACK_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0, 8.0, 10.0)
_RETRYABLE_CALLBACK_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class CallbackResolutionError(ValueError):
    """A potentially transient failure while resolving an approved callback host."""


def _canonical_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("callback API base must be an allow-listed HTTP(S) origin")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise ValueError("callback API port is invalid") from exc
    hostname = parsed.hostname.rstrip(".").lower()
    authority = f"[{hostname}]" if ":" in hostname else hostname
    return f"{parsed.scheme.lower()}://{authority}:{port}"


def _safe_callback_base(value: str) -> str:
    candidate = _canonical_origin(value)
    configured = os.getenv(
        "WG_WORKER_ALLOWED_API_ORIGINS",
        "http://api:8000,http://127.0.0.1:8000,http://localhost:8000",
    )
    allowed_origins: set[str] = set()
    for item in configured.split(","):
        if not item.strip():
            continue
        try:
            allowed_origins.add(_canonical_origin(item.strip()))
        except ValueError:
            continue
    if candidate not in allowed_origins:
        raise ValueError("callback API base must be an allow-listed HTTP(S) origin")
    return candidate


def _normalize_ip(value: ipaddress.IPv4Address | ipaddress.IPv6Address):
    if isinstance(value, ipaddress.IPv6Address) and value.ipv4_mapped:
        return value.ipv4_mapped
    return value


def _resolve_private_callback(host: str, port: int) -> tuple[str, ...]:
    try:
        direct = _normalize_ip(ipaddress.ip_address(host))
        addresses = {str(direct): direct}
    except ValueError:
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = {}
            for answer in answers:
                raw = answer[4][0].split("%", 1)[0]
                parsed = _normalize_ip(ipaddress.ip_address(raw))
                addresses[str(parsed)] = parsed
        except (OSError, ValueError) as exc:
            raise CallbackResolutionError("callback API host could not be safely resolved") from exc

    if not addresses:
        raise ValueError("callback API host returned no addresses")
    if any(
        not any(address in network for network in _PRIVATE_CALLBACK_NETWORKS)
        for address in addresses.values()
    ):
        raise ValueError("callback API host must resolve exclusively to private addresses")
    return tuple(sorted(addresses))


def _callback_request_target(value: str, run_id: Any) -> tuple[httpx.URL, dict[str, str], dict]:
    base = _safe_callback_base(value)
    try:
        canonical_run_id = str(UUID(str(run_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("callback run_id must be a UUID") from exc

    original_url = httpx.URL(f"{base}/api/v1/internal/runs/{canonical_run_id}/result")
    port = original_url.port or (443 if original_url.scheme == "https" else 80)
    resolved_ips = _resolve_private_callback(original_url.host, port)
    pinned_url = original_url.copy_with(host=resolved_ips[0])
    headers = {"Host": original_url.netloc.decode("ascii")}
    extensions = {"sni_hostname": original_url.raw_host.decode("ascii")}
    return pinned_url, headers, extensions


def _deliver_callback_with_retry(callback: dict[str, Any], result: dict[str, Any]) -> None:
    """Deliver one stable idempotency key across a bounded API outage window."""

    worker_token = os.environ.get("WG_WORKER_TOKEN", "")
    if not worker_token:
        raise ValueError("WG_WORKER_TOKEN is required for callback delivery")

    last_transient_error: Exception | None = None
    attempts = len(_CALLBACK_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            target, headers, extensions = _callback_request_target(
                str(callback["api_base"]), callback["run_id"]
            )
            headers["X-Worker-Token"] = worker_token
            with httpx.Client(
                timeout=10.0,
                trust_env=False,
                follow_redirects=False,
                limits=httpx.Limits(max_keepalive_connections=0),
            ) as client:
                response = client.post(
                    target,
                    json=result,
                    headers=headers,
                    extensions=extensions,
                )
            if response.status_code in _RETRYABLE_CALLBACK_STATUS_CODES:
                response.raise_for_status()
            if response.is_error:
                response.raise_for_status()
            return
        except (CallbackResolutionError, httpx.TransportError) as exc:
            last_transient_error = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRYABLE_CALLBACK_STATUS_CODES:
                raise
            last_transient_error = exc

        if attempt >= len(_CALLBACK_RETRY_DELAYS_SECONDS):
            break
        time.sleep(_CALLBACK_RETRY_DELAYS_SECONDS[attempt])

    if last_transient_error is None:  # pragma: no cover - defensive invariant
        raise RuntimeError("callback delivery failed without a transient error")
    raise last_transient_error


def evaluate_test_job(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        delivery_id = str(UUID(str(payload["delivery_id"])))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("delivery_id must be a UUID") from exc

    started = time.perf_counter()
    result = evaluate_rules(
        payload["test_case"],
        str(payload.get("output", "")),
        trace=payload.get("trace") or [],
        usage=payload.get("usage") or {},
        latency_ms=int(payload.get("latency_ms") or 0),
    ).as_dict()
    result["delivery_id"] = delivery_id
    result["worker_elapsed_ms"] = round((time.perf_counter() - started) * 1000)

    callback = payload.get("callback")
    if callback:
        callback_delivery_id = str(UUID(str(callback.get("delivery_id"))))
        if callback_delivery_id != delivery_id:
            raise ValueError("callback delivery_id does not match job delivery_id")
        _deliver_callback_with_retry(callback, result)
    return result
