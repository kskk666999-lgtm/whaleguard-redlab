from __future__ import annotations

import secrets
import time
from uuid import uuid4

import jwt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from .config import Settings, get_settings
from .security import decode_access_token


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))[:120]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(
            round((time.perf_counter() - started) * 1000, 2)
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response


class RequestTooLarge(Exception):
    pass


class RequestSizeLimitMiddleware:
    def __init__(self, app, settings: Settings | None = None) -> None:
        self.app = app
        self.settings = settings or get_settings()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length.decode("ascii")) > self.settings.max_request_bytes:
                    response = JSONResponse(
                        status_code=413, content={"detail": "请求体超过大小限制"}
                    )
                    await response(scope, receive, send)
                    return
            except (UnicodeDecodeError, ValueError):
                response = JSONResponse(status_code=400, content={"detail": "Content-Length 无效"})
                await response(scope, receive, send)
                return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.settings.max_request_bytes:
                    raise RequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLarge:
            response = JSONResponse(status_code=413, content={"detail": "请求体超过大小限制"})
            await response(scope, receive, send)


class CSRFMiddleware(BaseHTTPMiddleware):
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in self.SAFE_METHODS:
            return await call_next(request)
        if request.url.path.endswith("/auth/login"):
            return await call_next(request)
        authorization = request.headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            return await call_next(request)
        token = authorization.split(" ", 1)[1]
        csrf_header = request.headers.get("x-csrf-token", "")
        try:
            csrf_claim = str(decode_access_token(token).get("csrf", ""))
        except jwt.PyJWTError:
            return await call_next(request)
        if not csrf_header or not secrets.compare_digest(csrf_header, csrf_claim):
            return JSONResponse(status_code=403, content={"detail": "CSRF 校验失败"})
        return await call_next(request)
