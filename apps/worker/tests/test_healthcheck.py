from datetime import UTC, datetime

from rq.serializers import JSONSerializer
from whaleguard_worker import healthcheck


class FakeWorker:
    key = "rq:worker:whaleguard-worker"
    last_heartbeat = datetime.now(UTC)

    def __init__(self, state: str = "idle", queues: tuple[str, ...] = ("whaleguard",)):
        self._state = state
        self._queues = queues

    def get_state(self) -> str:
        return self._state

    def queue_names(self) -> list[str]:
        return list(self._queues)


class FakeConnection:
    def __init__(self, ttl: int = 480, *, scheduler: bool = True):
        self.worker_ttl = ttl
        self.scheduler = scheduler

    def ttl(self, key: str) -> int:
        if key.startswith("rq:scheduler"):
            return 60 if self.scheduler else -1
        return self.worker_ttl

    def get(self, key: str):
        if key == "rq:scheduler-lock:whaleguard" and self.scheduler:
            return b"scheduler-leader"
        return None

    def hget(self, key: str, field: str):
        if key == "rq:scheduler:scheduler-leader" and field == "last_heartbeat" and self.scheduler:
            return b"2026-08-31T00:00:00.000000Z"
        return None


def test_healthcheck_requires_registered_worker_on_expected_queue(monkeypatch):
    captured = {}
    worker = FakeWorker()

    def find_by_key(key, **kwargs):
        captured["key"] = key
        captured.update(kwargs)
        return worker

    monkeypatch.setattr(healthcheck.Worker, "find_by_key", find_by_key)
    connection = FakeConnection()

    assert healthcheck.worker_is_healthy(connection, "whaleguard-worker", "whaleguard")
    assert captured["key"] == "rq:worker:whaleguard-worker"
    assert captured["connection"] is connection
    assert captured["serializer"] is JSONSerializer


def test_healthcheck_rejects_missing_stale_suspended_or_wrong_queue_worker(monkeypatch):
    connection = FakeConnection()

    monkeypatch.setattr(healthcheck.Worker, "find_by_key", lambda *_args, **_kwargs: None)
    assert not healthcheck.worker_is_healthy(connection, "whaleguard-worker", "whaleguard")

    for worker in (
        FakeWorker(state="suspended"),
        FakeWorker(queues=("other",)),
    ):
        monkeypatch.setattr(
            healthcheck.Worker,
            "find_by_key",
            lambda *_args, _worker=worker, **_kwargs: _worker,
        )
        assert not healthcheck.worker_is_healthy(connection, "whaleguard-worker", "whaleguard")

    stale_connection = FakeConnection(ttl=-1)
    monkeypatch.setattr(
        healthcheck.Worker,
        "find_by_key",
        lambda *_args, **_kwargs: FakeWorker(),
    )
    assert not healthcheck.worker_is_healthy(stale_connection, "whaleguard-worker", "whaleguard")


def test_healthcheck_rejects_worker_when_queue_has_no_live_scheduler(monkeypatch):
    monkeypatch.setattr(
        healthcheck.Worker,
        "find_by_key",
        lambda *_args, **_kwargs: FakeWorker(),
    )

    assert not healthcheck.worker_is_healthy(
        FakeConnection(scheduler=False), "whaleguard-worker", "whaleguard"
    )


def test_healthcheck_reads_only_the_current_boot_worker_name(monkeypatch, tmp_path):
    worker_name_file = tmp_path / "worker-name"
    monkeypatch.setenv("WORKER_NAME_FILE", str(worker_name_file))
    assert healthcheck.current_worker_name() is None

    worker_name_file.write_text("whaleguard-worker-current\n", encoding="utf-8")
    assert healthcheck.current_worker_name() == "whaleguard-worker-current"

    worker_name_file.write_text("x" * 129, encoding="utf-8")
    assert healthcheck.current_worker_name() is None
