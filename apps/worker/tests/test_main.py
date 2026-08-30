import importlib

from rq.serializers import JSONSerializer


def test_worker_uses_non_executable_queue_serialization_and_redacted_job_logs(
    monkeypatch, tmp_path
):
    worker_main = importlib.import_module("whaleguard_worker.main")
    captured = {}
    connection = object()

    class FakeRedis:
        @staticmethod
        def from_url(value):
            captured["redis_url"] = value
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
    worker_name = captured["worker"][1]["name"]
    assert worker_name.startswith("whaleguard-worker-")
    assert len(worker_name) == len("whaleguard-worker-") + 32
    assert worker_name_file.read_text(encoding="utf-8") == worker_name
    assert captured["work"] == {"with_scheduler": True}


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
