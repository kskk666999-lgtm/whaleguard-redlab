from uuid import uuid4

import pytest
from whaleguard_worker import jobs


def fake_answers(*addresses: str):
    return [(2, 1, 6, "", (address, 8000)) for address in addresses]


@pytest.mark.parametrize(
    "value",
    [
        "http://user:pass@api:8000",
        "http://api:8000/prefix",
        "http://api:8000?next=/admin",
        "http://api:9000",
        "https://api:8000",
        "file://api",
    ],
)
def test_callback_base_must_be_a_clean_allowlisted_origin(value: str):
    with pytest.raises(ValueError):
        jobs._safe_callback_base(value)


def test_callback_run_id_cannot_change_the_internal_route(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        jobs.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: fake_answers("10.0.0.8"),
    )
    with pytest.raises(ValueError, match="UUID"):
        jobs._callback_request_target("http://api:8000", "../settings?enabled=true")


def test_callback_dns_must_resolve_only_to_private_addresses(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        jobs.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: fake_answers("10.0.0.8", "169.254.169.254"),
    )
    with pytest.raises(ValueError, match="exclusively to private"):
        jobs._callback_request_target("http://api:8000", uuid4())


def test_callback_uses_checked_ip_without_second_dns_lookup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WG_WORKER_ALLOWED_API_ORIGINS", "https://api:8000")
    monkeypatch.setattr(
        jobs.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: fake_answers("10.0.0.8"),
    )
    run_id = uuid4()
    target, headers, extensions = jobs._callback_request_target("https://api:8000", run_id)
    assert target.host == "10.0.0.8"
    assert target.path.endswith(f"/{run_id}/result")
    assert headers["Host"] == "api:8000"
    assert extensions["sni_hostname"] == "api"
