from __future__ import annotations

import os
import time
from uuid import uuid4

import httpx
from redis import Redis
from rq import Queue
from rq.job import Job
from rq.serializers import JSONSerializer


def main() -> None:
    api_base = os.getenv("CI_API_BASE", "http://127.0.0.1:8000")
    response = httpx.get(f"{api_base}/ready", timeout=5.0, trust_env=False)
    response.raise_for_status()
    if response.json().get("database") != "ok":
        raise SystemExit("API readiness did not confirm PostgreSQL")

    connection = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    connection.ping()
    queue = Queue(
        os.getenv("RQ_QUEUE", "whaleguard-ci"),
        connection=connection,
        serializer=JSONSerializer,
    )
    delivery_id = str(uuid4())
    queued = queue.enqueue(
        "whaleguard_worker.jobs.evaluate_test_job",
        {
            "delivery_id": delivery_id,
            "test_case": {
                "id": "ci-postgres-redis-rq",
                "evaluator": {"require_contains": ["safe"]},
            },
            "output": "safe",
            "trace": [],
            "latency_ms": 1,
            "usage": {},
        },
        job_timeout=60,
        result_ttl=60,
    )

    deadline = time.monotonic() + 60
    job = Job.fetch(queued.id, connection=connection, serializer=JSONSerializer)
    while time.monotonic() < deadline:
        status = job.get_status(refresh=True)
        if status == "finished":
            break
        if status in {"failed", "stopped", "canceled"}:
            raise SystemExit(f"RQ integration job entered terminal status: {status}")
        time.sleep(0.5)
    else:
        raise SystemExit("RQ integration job did not finish within 60 seconds")

    job.refresh()
    if not isinstance(job.result, dict) or job.result.get("delivery_id") != delivery_id:
        raise SystemExit("RQ worker result did not preserve the delivery_id")
    if job.result.get("passed") is not True:
        raise SystemExit("RQ worker returned an unexpected evaluation result")
    print("POSTGRES_REDIS_RQ_OK database=ok redis=ok worker_job=finished")


if __name__ == "__main__":
    main()
