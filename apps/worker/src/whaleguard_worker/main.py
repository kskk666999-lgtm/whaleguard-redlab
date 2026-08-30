from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from redis import Redis
from redis.backoff import ConstantBackoff
from redis.exceptions import BusyLoadingError, ConnectionError, RedisError, TimeoutError
from redis.retry import Retry as RedisRetry
from rq import Queue, Worker
from rq.job import Job
from rq.serializers import JSONSerializer

_DEFAULT_WORKER_NAME_FILE = "/tmp/whaleguard-worker-name"  # noqa: S108
_SCHEDULER_CHECK_INTERVAL_SECONDS = 5
_REDIS_TRANSIENT_RETRIES = 20
_REDIS_TRANSIENT_BACKOFF_SECONDS = 0.25


class RestrictedWorker(Worker):
    """Execute only WhaleGuard's data-only evaluation job with no callbacks."""

    ALLOWED_JOB_FUNCTIONS = frozenset({"whaleguard_worker.jobs.evaluate_test_job"})

    @property
    def dequeue_timeout(self) -> int:
        """Wake the parent often enough to supervise the RQ scheduler child."""

        return min(super().dequeue_timeout, _SCHEDULER_CHECK_INTERVAL_SECONDS)

    def run_maintenance_tasks(self) -> None:
        """Keep PID 1 alive while Redis is briefly loading or reconnecting.

        RQ's maintenance implementation already restarts a dead scheduler with
        ``acquire_locks(auto_start=True)``. A short maintenance/dequeue interval
        makes that self-healing prompt, while the native Redis lock remains the
        sole leader-election mechanism.
        """

        try:
            super().run_maintenance_tasks()
        except RedisError as exc:
            self.log.warning(
                "Worker maintenance deferred during transient Redis state error_type=%s",
                type(exc).__name__,
            )

    @classmethod
    def is_allowed_job(cls, job: Job) -> bool:
        try:
            return (
                job.func_name in cls.ALLOWED_JOB_FUNCTIONS
                and job.instance is None
                and isinstance(job.args, (list, tuple))
                and len(job.args) == 1
                and isinstance(job.args[0], dict)
                and not job.kwargs
                and not any(
                    (
                        job._success_callback_name,
                        job._failure_callback_name,
                        job._stopped_callback_name,
                    )
                )
            )
        except Exception:
            return False

    def execute_job(self, job: Job, queue: Queue):
        if not self.is_allowed_job(job):
            # Do not include attacker-controlled function names or arguments in
            # logs. Remove the dequeued item and retain only canceled state.
            self.log.warning("Worker rejected a non-allowlisted queued job")
            try:
                queue.connection.lrem(queue.intermediate_queue_key, 1, job.id)
                job.cancel()
            except Exception:
                self.log.exception("Worker could not persist rejected-job state")
            return None
        return super().execute_job(job, queue)


def _worker_name_file() -> Path:
    # The Compose service mounts /tmp as a private, noexec tmpfs and runs one UID.
    return Path(os.getenv("WORKER_NAME_FILE", _DEFAULT_WORKER_NAME_FILE))


def _publish_worker_name(worker_name: str) -> None:
    """Atomically expose the current boot's unique worker name to its healthcheck."""
    destination = _worker_name_file()
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}")
    temporary.write_text(worker_name, encoding="utf-8")
    os.replace(temporary, destination)


def main() -> None:
    retryable_errors = (BusyLoadingError, ConnectionError, TimeoutError)
    connection = Redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"),
        retry=RedisRetry(
            ConstantBackoff(_REDIS_TRANSIENT_BACKOFF_SECONDS),
            retries=_REDIS_TRANSIENT_RETRIES,
            supported_errors=retryable_errors,
        ),
        retry_on_error=list(retryable_errors),
    )
    worker_base_name = os.getenv("WORKER_NAME", "whaleguard-worker")[:64]
    worker_name = f"{worker_base_name or 'whaleguard-worker'}-{uuid4().hex}"
    queues = [
        Queue(
            os.getenv("RQ_QUEUE", "whaleguard"),
            connection=connection,
            serializer=JSONSerializer,
        )
    ]
    worker = RestrictedWorker(
        queues,
        connection=connection,
        name=worker_name,
        serializer=JSONSerializer,
        log_job_description=False,
        maintenance_interval=_SCHEDULER_CHECK_INTERVAL_SECONDS,
    )
    _publish_worker_name(worker.name)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
