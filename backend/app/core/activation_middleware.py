from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
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


class ActivationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not ACTIVATION_ENABLED:
            return await call_next(request)

        if request.url.path in _BYPASS_PATHS or request.url.path.startswith("/minion/"):
            return await call_next(request)

        from app.core.db import AsyncSessionLocal
        from app.models.activation import Activation

        async with AsyncSessionLocal() as db:
            row = (await db.exec(select(Activation))).first()
            if not row or not row.is_active:
                return JSONResponse(status_code=423, content={"detail": "activation_required"})

        return await call_next(request)
