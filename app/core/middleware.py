from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.face.diagnostics import bind_face_request_id, reset_face_request_id

logger = logging.getLogger("smartattend")


# Swagger UI and ReDoc load their assets from jsDelivr and use a small inline
# initialization script. Keep this more permissive policy limited to those
# documentation pages; all API responses retain the strict default policy.
DOCS_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "object-src 'none'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' data: https://cdn.jsdelivr.net; "
    "connect-src 'self'"
)
STRICT_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
)
FRONTEND_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; frame-ancestors 'none'; form-action 'self'; object-src 'none'; "
    "script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; font-src 'self' data:; "
    "connect-src 'self'; worker-src 'self' blob:"
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        supplied_id = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied_id
            if supplied_id
            and len(supplied_id) <= 64
            and all(ch.isalnum() or ch in "._-" for ch in supplied_id)
            else str(uuid.uuid4())
        )
        request.state.request_id = request_id
        token = bind_face_request_id(request_id)
        start = time.monotonic()
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "Unhandled request error request_id=%s path=%s",
                    request_id,
                    request.url.path,
                )
                response = JSONResponse(
                    status_code=500,
                    content={
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "An unexpected error occurred.",
                            "request_id": request_id,
                        }
                    },
                )
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Frame-Options"] = "DENY"
            docs_paths = {
                getattr(request.app, "docs_url", None),
                getattr(request.app, "redoc_url", None),
                getattr(
                    request.app, "swagger_ui_oauth2_redirect_url", "/docs/oauth2-redirect"
                ),
            }
            if request.url.path in docs_paths:
                response.headers["Content-Security-Policy"] = DOCS_CONTENT_SECURITY_POLICY
            elif (
                request.url.path == "/"
                or request.url.path.startswith(("/admin", "/teacher", "/assets/", "/favicon"))
            ) and not request.url.path.startswith(("/api/", "/health/")):
                response.headers["Content-Security-Policy"] = FRONTEND_CONTENT_SECURITY_POLICY
            else:
                response.headers["Content-Security-Policy"] = STRICT_CONTENT_SECURITY_POLICY
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)
            logger.info(
                "request_complete request_id=%s method=%s path=%s status=%s elapsed_ms=%s",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
            return response
        finally:
            reset_face_request_id(token)


class InProcessRateLimiter:
    """Per-worker sliding-window limiter; production deployments should also enforce edge limits."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            bucket = self.events[key]
            while bucket and bucket[0] <= now - self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


async def rate_limit_middleware(request: Request, call_next) -> Response:
    limiter: InProcessRateLimiter | None = getattr(
        request.app.state, "rate_limiter", None
    )
    path = request.url.path
    if (
        limiter
        and request.method in {"POST", "PATCH", "DELETE"}
        and any(
            part in path
            for part in (
                "teacher-requests",
                "auth",
                "passkeys",
                "activation",
                "face-enrollment",
                "/identify",
                "/admin/bootstrap",
            )
        )
    ):
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(f"{client}:{path}"):
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests. Try again later.",
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )
    return await call_next(request)
