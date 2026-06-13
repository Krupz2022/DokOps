# backend/app/services/webhook_security.py
import hashlib
import hmac
import json
import time
from collections import defaultdict
from typing import Dict, Optional

from fastapi import HTTPException, Request
from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models.setting import SystemSetting

VALID_SOURCES = frozenset(
    ["alertmanager", "grafana", "datadog", "pagerduty", "opsgenie", "elasticsearch", "generic"]
)

# In-memory rate limiter: {source: {minute_bucket_int: count}}
_rate_counters: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
RATE_LIMIT_PER_MINUTE = 60


def _current_minute() -> int:
    return int(time.time() // 60)


def check_rate_limit(source: str) -> None:
    bucket = _current_minute()
    _rate_counters[source][bucket] += 1
    # Prune old buckets (keep only current and previous minute)
    for old in [k for k in _rate_counters[source] if k < bucket - 1]:
        del _rate_counters[source][old]
    if _rate_counters[source][bucket] > RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded for source '{source}'")


async def _get_secrets() -> Dict[str, str]:
    async with AsyncSessionLocal() as session:
        row = await session.get(SystemSetting, "alert_webhook_secrets")
        if not row or not row.value:
            return {}
        try:
            return json.loads(row.value)
        except json.JSONDecodeError:
            return {}


def _constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _verify_hmac_sha256(secret: str, raw_body: bytes, signature_header: str) -> bool:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    # PagerDuty sends "v1=<hex>", Datadog sends raw hex
    incoming = signature_header.split("=")[-1] if "=" in signature_header else signature_header
    return hmac.compare_digest(expected, incoming)


async def validate_webhook_source(source: str, request: Request) -> bytes:
    """
    Validate source name, rate limit, and signature.
    Returns the raw request body (needed by callers for payload parsing).
    Raises HTTPException on any validation failure.
    """
    if source not in VALID_SOURCES:
        raise HTTPException(status_code=404, detail=f"Unknown alert source: {source}")

    check_rate_limit(source)

    secrets = await _get_secrets()
    secret = secrets.get(source)
    if not secret:
        raise HTTPException(status_code=503, detail=f"Webhook source '{source}' is not configured in Alert settings")

    raw_body = await request.body()

    if source == "datadog":
        sig = request.headers.get("X-Datadog-Signature", "")
        if not _verify_hmac_sha256(secret, raw_body, sig):
            raise HTTPException(status_code=401, detail="Datadog signature verification failed")

    elif source == "pagerduty":
        sig = request.headers.get("X-PagerDuty-Signature", "")
        if not _verify_hmac_sha256(secret, raw_body, sig):
            raise HTTPException(status_code=401, detail="PagerDuty signature verification failed")

    elif source == "grafana":
        token = request.headers.get("X-Grafana-Webhook-Secret", "")
        if not _constant_time_compare(secret, token):
            raise HTTPException(status_code=401, detail="Grafana webhook secret mismatch")

    elif source == "opsgenie":
        token = request.headers.get("X-OpsGenie-Webhook-Token", "")
        if not _constant_time_compare(secret, token):
            raise HTTPException(status_code=401, detail="OpsGenie token mismatch")

    elif source in ("alertmanager", "elasticsearch"):
        auth = request.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip()
        if not _constant_time_compare(secret, token):
            raise HTTPException(status_code=401, detail="Authorization token mismatch")

    elif source == "generic":
        token = request.headers.get("X-DokOps-Webhook-Secret", "")
        if not _constant_time_compare(secret, token):
            raise HTTPException(status_code=401, detail="DokOps webhook secret mismatch")

    return raw_body
