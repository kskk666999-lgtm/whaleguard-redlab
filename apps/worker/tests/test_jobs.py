from uuid import uuid4

import httpx
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


def test_job_requires_delivery_id() -> None:
    with pytest.raises(ValueError, match="delivery_id"):
        jobs.evaluate_test_job(
            {
                "test_case": {"id": "safe-case", "evaluator": {"type": "rules"}},
                "output": "safe output",
            }
        )


def test_job_preserves_delivery_id_in_result() -> None:
    delivery_id = uuid4()
    result = jobs.evaluate_test_job(
        {
            "delivery_id": str(delivery_id),
            "test_case": {"id": "safe-case", "evaluator": {"type": "rules"}},
            "output": "safe output",
        }
    )
    assert result["delivery_id"] == str(delivery_id)


def test_callback_delivery_id_must_match_job() -> None:
    with pytest.raises(ValueError, match="does not match"):
        jobs.evaluate_test_job(
            {
                "delivery_id": str(uuid4()),
                "test_case": {"id": "safe-case", "evaluator": {"type": "rules"}},
                "output": "safe output",
                "callback": {
                    "api_base": "http://api:8000",
                    "run_id": str(uuid4()),
                    "delivery_id": str(uuid4()),
                },
            }
        )


class _SuccessfulClient:
    posted_delivery_ids: list[str] = []

    def __init__(self, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def post(self, _target, *, json, **_kwargs) -> httpx.Response:
        self.posted_delivery_ids.append(json["delivery_id"])
        return httpx.Response(200, request=httpx.Request("POST", "http://10.0.0.8/result"))


def test_callback_retries_transient_api_outage_with_stable_delivery_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery_id = uuid4()
    run_id = uuid4()
    resolution_attempts = 0
    observed_delays: list[float] = []
    _SuccessfulClient.posted_delivery_ids = []

    def resolve_after_outage(*_args, **_kwargs):
        nonlocal resolution_attempts
        resolution_attempts += 1
        if resolution_attempts < 3:
            raise jobs.CallbackResolutionError("callback API host could not be safely resolved")
        return httpx.URL("http://10.0.0.8:8000/result"), {"Host": "api:8000"}, {}

    monkeypatch.setenv("WG_WORKER_TOKEN", "test-worker-token")
    monkeypatch.setattr(jobs, "_callback_request_target", resolve_after_outage)
    monkeypatch.setattr(jobs.httpx, "Client", _SuccessfulClient)
    monkeypatch.setattr(jobs.time, "sleep", observed_delays.append)

    result = jobs.evaluate_test_job(
        {
            "delivery_id": str(delivery_id),
            "test_case": {"id": "safe-case", "evaluator": {"type": "rules"}},
            "output": "safe output",
            "callback": {
                "api_base": "http://api:8000",
                "run_id": str(run_id),
                "delivery_id": str(delivery_id),
            },
        }
    )

    assert result["delivery_id"] == str(delivery_id)
    assert resolution_attempts == 3
    assert observed_delays == [1.0, 2.0]
    assert _SuccessfulClient.posted_delivery_ids == [str(delivery_id)]


def test_callback_raises_after_bounded_transient_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery_id = uuid4()
    resolution_attempts = 0
    observed_delays: list[float] = []

    def unavailable(*_args, **_kwargs):
        nonlocal resolution_attempts
        resolution_attempts += 1
        raise jobs.CallbackResolutionError("callback API host could not be safely resolved")

    monkeypatch.setenv("WG_WORKER_TOKEN", "test-worker-token")
    monkeypatch.setattr(jobs, "_callback_request_target", unavailable)
    monkeypatch.setattr(jobs.time, "sleep", observed_delays.append)

    with pytest.raises(jobs.CallbackResolutionError, match="safely resolved"):
        jobs.evaluate_test_job(
            {
                "delivery_id": str(delivery_id),
                "test_case": {"id": "safe-case", "evaluator": {"type": "rules"}},
                "output": "safe output",
                "callback": {
                    "api_base": "http://api:8000",
                    "run_id": str(uuid4()),
                    "delivery_id": str(delivery_id),
                },
            }
        )

    assert resolution_attempts == len(jobs._CALLBACK_RETRY_DELAYS_SECONDS) + 1
    assert observed_delays == list(jobs._CALLBACK_RETRY_DELAYS_SECONDS)
