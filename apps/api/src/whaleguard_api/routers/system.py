from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Request
from redis import Redis
from rq import Queue, Worker
from sqlalchemy import select, text

from ..config import get_settings
from ..dependencies import DB, CurrentUser
from ..models import AuditLog, ModelChannel
from ..schemas import SystemServiceStatus, SystemStatusResponse
from ..scope_guard import ScopeDenied, guarded_request

router = APIRouter(prefix="/system", tags=["系统"])


def _service(
    status: Literal["normal", "not_started", "optional", "abnormal"],
    label: str,
    detail: str,
    *,
    optional: bool = False,
) -> SystemServiceStatus:
    return SystemServiceStatus(
        status=status,
        label=label,
        detail=detail,
        optional=optional,
    )


def _database_status(db: DB) -> SystemServiceStatus:
    try:
        db.execute(text("SELECT 1"))
        return _service("normal", "数据库", "业务数据可正常读取")
    except Exception:
        db.rollback()
        return _service("abnormal", "数据库", "数据库暂时不可用")


def _queue_status() -> tuple[SystemServiceStatus, SystemServiceStatus]:
    settings = get_settings()
    if not settings.task_queue_enabled:
        return (
            _service("optional", "Redis", "当前开发模式未启用任务队列", optional=True),
            _service("optional", "后台任务", "当前开发模式使用本地执行", optional=True),
        )
    try:
        redis = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1.5,
            socket_timeout=1.5,
        )
        redis.ping()
    except Exception:
        return (
            _service("abnormal", "Redis", "任务缓存服务没有响应"),
            _service("not_started", "后台任务", "等待 Redis 恢复后才能接收任务"),
        )

    queue = Queue(settings.rq_queue, connection=redis)
    now = datetime.now(UTC)
    active_workers = []
    try:
        for worker in Worker.all(connection=redis, queue=queue):
            heartbeat = worker.last_heartbeat
            if heartbeat is None:
                continue
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=UTC)
            if now - heartbeat.astimezone(UTC) <= timedelta(seconds=90):
                active_workers.append(worker)
    except Exception:
        active_workers = []
    worker = (
        _service("normal", "后台任务", f"{len(active_workers)} 个任务处理器在线")
        if active_workers
        else _service("not_started", "后台任务", "后台任务服务没有启动")
    )
    return _service("normal", "Redis", "任务缓存服务正常"), worker


def _labs_status(db: DB, request_id: str | None) -> SystemServiceStatus:
    settings = get_settings()
    endpoints = (
        ("Mock Agent", f"{settings.mock_agent_url.rstrip('/')}/health"),
        ("Mock LLM", "http://mock-llm:8101/health"),
        ("Mock MCP", "http://mock-mcp-server:8103/health"),
    )
    failures: list[str] = []
    for label, url in endpoints:
        try:
            response = guarded_request(
                db,
                "GET",
                url,
                None,
                timeout=2,
                max_redirects=0,
                request_id=request_id,
                max_response_bytes=8192,
                allow_bundled_health_probe=True,
            )
            if response.status_code != 200:
                failures.append(label)
        except (ScopeDenied, httpx.HTTPError, ValueError):
            failures.append(label)
    if failures:
        return _service("abnormal", "本地靶场", f"{', '.join(failures)} 暂时不可用")
    return _service("normal", "本地靶场", "三个本地模拟服务均已准备好")


def _model_status(db: DB) -> tuple[SystemServiceStatus, str | None]:
    channels = list(
        db.scalars(
            select(ModelChannel)
            .where(ModelChannel.enabled.is_(True))
            .order_by(ModelChannel.updated_at.desc())
        )
    )
    if not channels:
        return _service("optional", "AI 模型", "未配置也可以完整学习 Academy", optional=True), None
    for channel in channels:
        audit = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.action == "model_channel.test_connection",
                AuditLog.resource_id == str(channel.id),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        if audit is not None and audit.outcome == "success":
            return _service(
                "normal", "AI 模型", f"{channel.name} 已连接", optional=True
            ), channel.name
    return (
        _service("optional", "AI 模型", "模型已配置，但尚未通过最近一次连接测试", optional=True),
        channels[0].name,
    )


@router.get("/status", response_model=SystemStatusResponse)
def system_status(
    request: Request,
    db: DB,
    _user: CurrentUser,
) -> SystemStatusResponse:
    database = _database_status(db)
    redis, worker = _queue_status()
    labs = _labs_status(db, getattr(request.state, "request_id", None))
    model, model_name = _model_status(db)
    services = {
        "api": _service("normal", "API", "本地服务正常"),
        "database": database,
        "redis": redis,
        "worker": worker,
        "labs": labs,
        "model_provider": model,
    }
    required = [database, redis, worker, labs]
    overall = "ready" if all(item.status == "normal" for item in required) else "degraded"
    return SystemStatusResponse(
        overall=overall,
        checked_at=datetime.now(UTC),
        services=services,
        model_provider_name=model_name,
    )
