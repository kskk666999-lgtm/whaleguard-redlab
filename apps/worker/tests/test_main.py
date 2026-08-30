import importlib
from datetime import UTC, datetime

from redis.exceptions import BusyLoadingError
from rq.group import Group
from rq.serializers import JSONSerializer


def test_worker_uses_non_executable_queue_serialization_and_redacted_job_logs(
    monkeypatch, tmp_path
):
    worker_main = importlib.import_module("whaleguard_worker.main")
    captured = {}
    connection = object()

    class FakeRedis:
        @staticmethod
        def from_url(value, **kwargs):
            captured["redis_url"] = value
            captured["redis_kwargs"] = kwargs
            return connection

    class FakeQueue:
        def __init__(self, name, **kwargs):
            captured["queue"] = (name, kwargs)

    class FakeWorker:
        def __init__(self, queues, **kwargs):
            captured["worker"] = (queues, kwargs)
            self.name = kwargs["name"]

        def work(self, **kwargs):
            captured["work"] = kwargs

    monkeypatch.setattr(worker_main, "Redis", FakeRedis)
    monkeypatch.setattr(worker_main, "Queue", FakeQueue)
    monkeypatch.setattr(worker_main, "RestrictedWorker", FakeWorker)
    worker_name_file = tmp_path / "worker-name"
    monkeypatch.setenv("WORKER_NAME_FILE", str(worker_name_file))
    worker_main.main()

    assert captured["queue"][1]["serializer"] is JSONSerializer
    assert captured["worker"][1]["serializer"] is JSONSerializer
    assert captured["worker"][1]["log_job_description"] is False
    assert captured["worker"][1]["maintenance_interval"] == 5
    worker_name = captured["worker"][1]["name"]
    assert worker_name.startswith("whaleguard-worker-")
    assert len(worker_name) == len("whaleguard-worker-") + 32
    assert worker_name_file.read_text(encoding="utf-8") == worker_name
    assert captured["work"] == {"with_scheduler": True}
    assert captured["redis_kwargs"]["retry_on_error"]


class _FakeProcess:
    def __init__(self, alive: bool):
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _FakeScheduler:
    def __init__(self, process, *, error: Exception | None = None, outcomes=None):
        self._process = process
        self.error = error
        self.outcomes = list(outcomes or [{"whaleguard"}])
        self.acquire_calls: list[bool] = []

    def acquire_locks(self, auto_start: bool = False):
        self.acquire_calls.append(auto_start)
        if self.error:
            raise self.error
        outcome = self.outcomes.pop(0) if self.outcomes else {"whaleguard"}
        if outcome and auto_start:
            self._process = _FakeProcess(True)
        return outcome


def _maintenance_worker(scheduler) -> object:
    worker_main = importlib.import_module("whaleguard_worker.main")
    worker = worker_main.RestrictedWorker.__new__(worker_main.RestrictedWorker)
    worker.scheduler = scheduler
    worker.last_cleaned_at = datetime.now(UTC)
    worker.connection = object()
    worker.worker_ttl = 420
    worker.log = type("Log", (), {"warning": lambda *_args, **_kwargs: None})()
    worker.clean_registries = lambda: None
    return worker


def test_dead_scheduler_is_restarted_during_bounded_maintenance(monkeypatch):
    scheduler = _FakeScheduler(_FakeProcess(False))
    worker = _maintenance_worker(scheduler)
    monkeypatch.setattr(Group, "clean_registries", lambda **_kwargs: None)

    worker.run_maintenance_tasks()

    assert scheduler.acquire_calls == [True]
    assert worker.dequeue_timeout == 5


def test_initial_scheduler_lock_miss_is_retried_for_takeover(monkeypatch):
    scheduler = _FakeScheduler(None, outcomes=[set(), {"whaleguard"}])
    worker = _maintenance_worker(scheduler)
    monkeypatch.setattr(Group, "clean_registries", lambda **_kwargs: None)

    worker.run_maintenance_tasks()
    worker.run_maintenance_tasks()

    assert scheduler.acquire_calls == [True, True]
    assert scheduler._process.is_alive()


def test_busy_loading_during_scheduler_recovery_does_not_escape(monkeypatch):
    scheduler = _FakeScheduler(None, error=BusyLoadingError("Redis is loading"))
    worker = _maintenance_worker(scheduler)
    monkeypatch.setattr(Group, "clean_registries", lambda **_kwargs: None)

    worker.run_maintenance_tasks()

    assert scheduler.acquire_calls == [True]


def test_worker_rejects_unknown_functions_and_all_rq_callbacks():
    worker_main = importlib.import_module("whaleguard_worker.main")

    class FakeJob:
        def __init__(self, func_name, callbacks=(None, None, None), *, instance=None):
            self.func_name = func_name
            self.instance = instance
            self.args = [{"test_case": {}, "output": "safe"}]
            self.kwargs = {}
            (
                self._success_callback_name,
                self._failure_callback_name,
                self._stopped_callback_name,
            ) = callbacks

    allowed = FakeJob("whaleguard_worker.jobs.evaluate_test_job")
    unknown = FakeJob("os.system")
    callback = FakeJob(
        "whaleguard_worker.jobs.evaluate_test_job",
        callbacks=("unexpected.callback", None, None),
    )

    assert worker_main.RestrictedWorker.is_allowed_job(allowed) is True
    assert worker_main.RestrictedWorker.is_allowed_job(unknown) is False
    assert worker_main.RestrictedWorker.is_allowed_job(callback) is False
    assert (
        worker_main.RestrictedWorker.is_allowed_job(
            FakeJob("whaleguard_worker.jobs.evaluate_test_job", instance={})
        )
        is False
    )
