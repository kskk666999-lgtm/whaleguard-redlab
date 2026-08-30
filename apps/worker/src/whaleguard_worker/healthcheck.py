from __future__ import annotations

import os
from pathlib import Path

from redis import Redis
from rq import Worker
from rq.scheduler import RQScheduler
from rq.serializers import JSONSerializer

_RUNNING_STATES = frozenset({"started", "idle", "busy"})
_DEFAULT_WORKER_NAME_FILE = "/tmp/whaleguard-worker-name"  # noqa: S108


def current_worker_name() -> str | None:
    try:
        value = Path(os.getenv("WORKER_NAME_FILE", _DEFAULT_WORKER_NAME_FILE)).read_text(
            encoding="utf-8"
        )
    except OSError:
        return None
    value = value.strip()
    return value if 1 <= len(value) <= 128 else None


def worker_is_healthy(connection: Redis, worker_name: str, queue_name: str) -> bool:
    """Return true only for a live RQ registration on the configured queue.

    Redis connectivity alone is insufficient: the worker must have registered
    its birth, published a heartbeat with a positive TTL, and be listening on
    the same queue used by the API.
    """

    worker_key = f"{Worker.redis_worker_namespace_prefix}{worker_name}"
    worker = Worker.find_by_key(
        worker_key,
        connection=connection,
        serializer=JSONSerializer,
    )
    if worker is None:
        return False
    if worker.get_state() not in _RUNNING_STATES:
        return False
    if worker.last_heartbeat is None or connection.ttl(worker.key) <= 0:
        return False
    return queue_name in worker.queue_names() and scheduler_is_healthy(connection, queue_name)


def scheduler_is_healthy(connection: Redis, queue_name: str) -> bool:
    """Require a live scheduler heartbeat for the configured queue leader."""

    lock_key = RQScheduler.get_locking_key(queue_name)
    owner = connection.get(lock_key)
    if isinstance(owner, bytes):
        try:
            owner = owner.decode("utf-8")
        except UnicodeDecodeError:
            return False
    if not isinstance(owner, str) or not 1 <= len(owner) <= 128:
        return False
    scheduler_key = f"rq:scheduler:{owner}"
    return bool(
        connection.ttl(lock_key) > 0
        and connection.ttl(scheduler_key) > 0
        and connection.hget(scheduler_key, "last_heartbeat")
    )


def main() -> int:
    try:
        connection = Redis.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379/0"),
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        worker_name = current_worker_name()
        healthy = bool(worker_name) and worker_is_healthy(
            connection, worker_name, os.getenv("RQ_QUEUE", "whaleguard")
        )
    except Exception:
        healthy = False
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
