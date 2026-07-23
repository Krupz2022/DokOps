# Pure ASGI middleware (not BaseHTTPMiddleware): BaseHTTPMiddleware wraps the
# response in an anyio cancel scope that tears down SSE streams mid-flight and
# leaks pooled asyncpg connections. See docs/middleware.md "Pure ASGI Middleware".
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from sqlmodel import select

from app.core.license_constants import ACTIVATION_ENABLED

_BYPASS_PATHS = {
    "/health",
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/login/access-token",
    "/api/v1/activation/activate",
    "/api/v1/activation/status",
}


class ActivationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not ACTIVATION_ENABLED:
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path in _BYPASS_PATHS or path.startswith("/minion/"):
            await self.app(scope, receive, send)
            return

        from app.core.db import AsyncSessionLocal
        from app.models.activation import Activation

        async with AsyncSessionLocal() as db:
            row = (await db.exec(select(Activation))).first()
        if not row or not row.is_active:
            response = JSONResponse(status_code=423, content={"detail": "activation_required"})
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
