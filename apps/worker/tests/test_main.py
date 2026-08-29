import importlib

from rq.serializers import JSONSerializer


def test_worker_uses_non_executable_queue_serialization_and_redacted_job_logs(monkeypatch):
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

        def work(self, **kwargs):
            captured["work"] = kwargs

    monkeypatch.setattr(worker_main, "Redis", FakeRedis)
    monkeypatch.setattr(worker_main, "Queue", FakeQueue)
    monkeypatch.setattr(worker_main, "RestrictedWorker", FakeWorker)
    worker_main.main()

    assert captured["queue"][1]["serializer"] is JSONSerializer
    assert captured["worker"][1]["serializer"] is JSONSerializer
    assert captured["worker"][1]["log_job_description"] is False
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
