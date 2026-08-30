from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from redis import Redis
from rq import Queue, Retry
from rq.serializers import JSONSerializer

from .config import get_settings

logger = logging.getLogger("whaleguard.queue")


def enqueue_rule_evaluation(
    run_id: UUID,
    delivery_id: UUID,
    test_case: dict[str, Any],
    output: str,
    trace: list[dict[str, Any]],
    latency_ms: int,
) -> str | None:
    settings = get_settings()
    if not settings.task_queue_enabled:
        return None
    if not settings.worker_token or not settings.worker_token.strip():
        # Settings validation rejects this configuration during normal startup.
        # Keep the enqueue boundary fail-closed as a second line of defence for
        # tests, alternate entry points, and configuration objects supplied by
        # embedding applications. Without a callback token, a successful RQ job
        # would have no durable path back to its DeliveryReceipt.
        logger.error("RQ enqueue refused: worker callback token is not configured")
        return None
    try:
        connection = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            health_check_interval=30,
        )
        queue = Queue(
            settings.rq_queue,
            connection=connection,
            serializer=JSONSerializer,
        )
        payload: dict[str, Any] = {
            "delivery_id": str(delivery_id),
            "test_case": test_case,
            "output": output,
            "trace": trace,
            "latency_ms": latency_ms,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "estimated_cost": 0.0},
        }
        payload["callback"] = {
            "api_base": settings.worker_callback_base,
            "run_id": str(run_id),
            "delivery_id": str(delivery_id),
        }
        job = queue.enqueue(
            "whaleguard_worker.jobs.evaluate_test_job",
            payload,
            job_timeout=120,
            retry=Retry(max=5, interval=[1, 2, 5, 10, 30]),
            result_ttl=3600,
            failure_ttl=86400,
        )
        return job.id
    except Exception as exc:
        logger.warning(
            "RQ unavailable; deterministic inline score retained: %s", type(exc).__name__
        )
        return None
