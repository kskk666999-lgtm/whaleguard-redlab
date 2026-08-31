from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import get_settings
from .database import Base, SessionLocal, engine
from .middleware import (
    CSRFMiddleware,
    RequestContextMiddleware,
    RequestSizeLimitMiddleware,
    RequestTooLarge,
)
from .outbox import dispatch_pending_outbox
from .routers import (
    academy,
    admin,
    auth,
    findings,
    projects,
    system,
    targets,
    testing,
    website_scans,
)
from .schemas import HealthResponse
from .seed import seed_database

settings = get_settings()
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("whaleguard.api")


async def _outbox_pump(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(dispatch_pending_outbox)
        except Exception as exc:
            logger.warning("Outbox pump deferred error_type=%s", type(exc).__name__)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2.0)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    if settings.seed_on_startup:
        with SessionLocal() as db:
            seed_database(db, settings)
    outbox_stop = asyncio.Event()
    outbox_task = None
    if settings.task_queue_enabled:
        outbox_task = asyncio.create_task(_outbox_pump(outbox_stop), name="outbox-pump")
    logger.info("WhaleGuard API startup completed environment=%s", settings.environment)
    try:
        yield
    finally:
        outbox_stop.set()
        if outbox_task is not None:
            with suppress(asyncio.CancelledError):
                await outbox_task
        engine.dispose()


app = FastAPI(
    title="WhaleGuard AI RedLab API",
    description="鲸盾 AI 安全红队实验平台后端，仅用于本地、自有或明确授权目标。",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
    max_age=600,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(RequestSizeLimitMiddleware, settings=settings)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [
        {
            "loc": [str(item) for item in error.get("loc", [])],
            "msg": error.get("msg", "输入无效"),
            "type": error.get("type", "validation_error"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": "请求参数校验失败",
            "errors": errors,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(RequestTooLarge)
async def request_too_large_handler(_request: Request, _exc: RequestTooLarge):
    return JSONResponse(status_code=413, content={"detail": "请求体超过大小限制"})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "request_id": getattr(request.state, "request_id", None),
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled request failure request_id=%s error_type=%s", request_id, type(exc).__name__
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "服务内部错误", "request_id": request_id},
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "ok", "api": settings.api_prefix}


@app.get("/health", response_model=HealthResponse, tags=["系统"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)


@app.get("/ready", response_model=HealthResponse, tags=["系统"])
def ready() -> HealthResponse:
    database_status = "ok"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        database_status = "unavailable"
    return HealthResponse(
        status="ok" if database_status == "ok" else "degraded",
        service=settings.app_name,
        version=__version__,
        database=database_status,
    )


for api_router in (
    auth.router,
    academy.router,
    projects.router,
    targets.router,
    testing.router,
    findings.router,
    website_scans.router,
    system.router,
    admin.router,
):
    app.include_router(api_router, prefix=settings.api_prefix)
