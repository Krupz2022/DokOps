# Pure ASGI middleware (not BaseHTTPMiddleware): BaseHTTPMiddleware wraps the
# response in an anyio cancel scope that tears down SSE streams mid-flight and
# leaks pooled asyncpg connections. See docs/middleware.md "Pure ASGI Middleware".
import time
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from app.core.db import AsyncSessionLocal
from app.models.audit import AuditLog
from app.core import security
from app.core.config import settings

# Maps (METHOD, path_suffix) → (action, resource) for Azure endpoints
_AZURE_ACTION_MAP = {
    ("POST", "/integrations/azure/connect"): ("AZURE_CONNECT", "azure/connection"),
    ("POST", "/integrations/azure/test"): ("AZURE_TEST_CONNECTION", "azure/connection"),
    ("DELETE", "/integrations/azure/disconnect"): ("AZURE_DISCONNECT", "azure/connection"),
    ("GET", "/integrations/azure/status"): ("AZURE_STATUS", "azure/connection"),
    ("GET", "/integrations/azure/cost"): ("AZURE_COST_FETCH", "azure/cost"),
    ("GET", "/integrations/azure/resources"): ("AZURE_RESOURCE_DISCOVERY", "azure/resources"),
    ("GET", "/integrations/azure/monitor"): ("AZURE_MONITOR_FETCH", "azure/monitor"),
    ("GET", "/integrations/azure/anomalies"): ("AZURE_ANOMALY_CHECK", "azure/anomalies"),
    ("GET", "/integrations/azure/recommendations"): ("AZURE_RECOMMENDATIONS_FETCH", "azure/recommendations"),
}


class AuditMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        method = scope["method"]
        if path in ["/health", "/"] or method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)
        process_time = time.time() - start_time

        actor = "anonymous"
        auth_header = Headers(scope=scope).get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                from jose import jwt
                payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[settings.ALGORITHM])
                actor = payload.get("sub", "unknown")
            except Exception:
                pass

        # Determine source + action + resource
        if "/integrations/azure/" in path or path.endswith("/integrations/azure"):
            source = "AZURE"
            # Check for feature toggle: PATCH /integrations/azure/features/{key}
            if method == "PATCH" and "/features/" in path:
                action = "AZURE_FEATURE_TOGGLE"
                key = path.split("/features/")[-1]
                resource = f"azure/feature/{key}"
            else:
                # Strip API prefix for lookup
                suffix = path.replace(f"{settings.API_V1_STR}", "")
                action, resource = _AZURE_ACTION_MAP.get(
                    (method, suffix),
                    (f"{method} {path}", "azure/unknown"),
                )
        elif "/k8s/" in path or path.endswith("/k8s"):
            source = "K8S"
            action = f"{method} {path}"
            resource = "k8s"
        else:
            source = "SYSTEM"
            action = f"{method} {path}"
            resource = "API"

        # Skip writing duplicate AZURE entries — the router's _audit() handles semantic Azure logs.
        # Only write for non-Azure paths here to avoid duplication.
        if source != "AZURE":
            audit_entry = AuditLog(
                actor=actor,
                action=action,
                resource=resource,
                result=str(status_code),
                mode="NORMAL",
                source=source,
                details=f"Duration: {process_time:.4f}s",
            )
            try:
                async with AsyncSessionLocal() as session:
                    session.add(audit_entry)
                    await session.commit()
            except Exception as e:
                print(f"Failed to write audit log: {e}")
