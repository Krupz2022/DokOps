import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
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


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        if request.url.path in ["/health", "/"] or request.method == "OPTIONS":
            return response

        actor = "anonymous"
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                from jose import jwt
                payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[settings.ALGORITHM])
                actor = payload.get("sub", "unknown")
            except:
                pass

        path = request.url.path
        method = request.method

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
                result=str(response.status_code),
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

        return response
