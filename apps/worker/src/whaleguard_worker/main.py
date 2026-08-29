from __future__ import annotations

import os

from redis import Redis
from rq import Queue, Worker
from rq.job import Job
from rq.serializers import JSONSerializer


class RestrictedWorker(Worker):
    """Execute only WhaleGuard's data-only evaluation job with no callbacks."""

    ALLOWED_JOB_FUNCTIONS = frozenset({"whaleguard_worker.jobs.evaluate_test_job"})

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


def main() -> None:
    connection = Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    queues = [
        Queue(
            os.getenv("RQ_QUEUE", "whaleguard"),
            connection=connection,
            serializer=JSONSerializer,
        )
    ]
    RestrictedWorker(
        queues,
        connection=connection,
        name=os.getenv("WORKER_NAME", "whaleguard-worker"),
        serializer=JSONSerializer,
        log_job_description=False,
    ).work(with_scheduler=True)


if __name__ == "__main__":
    main()
