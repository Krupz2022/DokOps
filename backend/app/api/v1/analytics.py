from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func as sa_func
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_async_db, get_current_active_superuser
from app.core.datetimes import utcnow
from app.models.analytics import AITokenUsage
from app.models.user import User

router = APIRouter()


def _bucket_for_span(start: datetime, end: datetime) -> str:
    """Choose chart granularity from the range length.

    <= 31 days -> day, 32-180 -> week, > 180 -> month.
    """
    span_days = (end - start).days
    if span_days <= 31:
        return "day"
    if span_days <= 180:
        return "week"
    return "month"


_MAX_SPAN = timedelta(days=366)


def _resolve_range(start: datetime, end: datetime) -> tuple[datetime, datetime, str]:
    """Validate, clamp, and classify a requested range."""
    if start >= end:
        raise HTTPException(status_code=422, detail="start must be before end")
    if end - start > _MAX_SPAN:
        start = end - _MAX_SPAN
    return start, end, _bucket_for_span(start, end)


def _bucket_expr(granularity: str, dialect: str):
    """A dialect-aware expression that buckets created_at into a string label.

    Returns a column expression labeled "date". SQLite uses strftime; everything
    else (PostgreSQL) uses date_trunc + to_char so the output is always a string.
    """
    col = AITokenUsage.created_at
    if dialect == "sqlite":
        fmt = {"day": "%Y-%m-%d", "week": "%Y-%W", "month": "%Y-%m"}[granularity]
        return sa_func.strftime(fmt, col).label("date")
    # PostgreSQL (and other date_trunc-capable engines)
    if granularity == "day":
        return sa_func.to_char(sa_func.date_trunc("day", col), "YYYY-MM-DD").label("date")
    if granularity == "week":
        # ISO year-week, Monday-anchored, e.g. "2026-24"
        return sa_func.to_char(col, "IYYY-IW").label("date")
    return sa_func.to_char(sa_func.date_trunc("month", col), "YYYY-MM").label("date")


@router.get("/tokens")
async def get_token_analytics(
    start: datetime = Query(..., description="ISO start (inclusive)"),
    end: datetime = Query(..., description="ISO end (exclusive)"),
    session: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_active_superuser),
) -> Dict[str, Any]:
    start, end, granularity = _resolve_range(start, end)
    dialect = session.bind.dialect.name
    bucket = _bucket_expr(granularity, dialect)

    # ── Summary ──────────────────────────────────────────────────────────────
    summary_row = (await session.exec(
        select(
            func.coalesce(func.sum(AITokenUsage.input_tokens), 0),
            func.coalesce(func.sum(AITokenUsage.output_tokens), 0),
            func.count(AITokenUsage.id),
            func.count(func.distinct(AITokenUsage.user_id)),
            func.coalesce(func.sum(AITokenUsage.cached_tokens), 0),
        ).where(AITokenUsage.created_at >= start, AITokenUsage.created_at < end)
    )).one()

    total_input = int(summary_row[0])
    total_output = int(summary_row[1])
    total_tokens = total_input + total_output
    total_calls = int(summary_row[2])
    unique_users = int(summary_row[3])
    total_cached = int(summary_row[4])

    summary = {
        "total_tokens": total_tokens,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_calls": total_calls,
        "unique_users": unique_users,
        "cached_tokens": total_cached,
    }

    # ── Daily breakdown ───────────────────────────────────────────────────────
    daily_rows = (await session.exec(
        select(
            bucket,
            func.sum(AITokenUsage.input_tokens + AITokenUsage.output_tokens).label("tokens"),
            func.count(AITokenUsage.id).label("calls"),
        )
        .where(AITokenUsage.created_at >= start, AITokenUsage.created_at < end)
        .group_by(bucket)
        .order_by(bucket)
    )).all()

    daily: List[Dict[str, Any]] = [
        {"date": str(row[0]), "tokens": int(row[1]), "calls": int(row[2])}
        for row in daily_rows
    ]

    # ── By source ─────────────────────────────────────────────────────────────
    source_rows = (await session.exec(
        select(
            AITokenUsage.source,
            func.sum(AITokenUsage.input_tokens + AITokenUsage.output_tokens).label("tokens"),
            func.count(AITokenUsage.id).label("calls"),
        )
        .where(AITokenUsage.created_at >= start, AITokenUsage.created_at < end)
        .group_by(AITokenUsage.source)
    )).all()

    by_source: List[Dict[str, Any]] = [
        {
            "source": row[0],
            "tokens": int(row[1]),
            "calls": int(row[2]),
            "pct": round(int(row[1]) / total_tokens * 100, 1) if total_tokens else 0.0,
        }
        for row in source_rows
    ]

    # ── By model ──────────────────────────────────────────────────────────────
    model_rows = (await session.exec(
        select(
            AITokenUsage.model,
            func.sum(AITokenUsage.input_tokens + AITokenUsage.output_tokens).label("tokens"),
            func.count(AITokenUsage.id).label("calls"),
        )
        .where(AITokenUsage.created_at >= start, AITokenUsage.created_at < end)
        .group_by(AITokenUsage.model)
    )).all()

    by_model: List[Dict[str, Any]] = [
        {
            "model": row[0],
            "tokens": int(row[1]),
            "calls": int(row[2]),
            "pct": round(int(row[1]) / total_tokens * 100, 1) if total_tokens else 0.0,
        }
        for row in model_rows
    ]

    # ── By user ───────────────────────────────────────────────────────────────
    user_rows = (await session.exec(
        select(
            AITokenUsage.user_id,
            func.sum(AITokenUsage.input_tokens + AITokenUsage.output_tokens).label("tokens"),
            func.count(AITokenUsage.id).label("calls"),
        )
        .where(AITokenUsage.created_at >= start, AITokenUsage.created_at < end)
        .group_by(AITokenUsage.user_id)
    )).all()

    # Build user_id → username map for non-null user_ids
    user_ids = [row[0] for row in user_rows if row[0] is not None]
    username_map: Dict[int, str] = {}
    if user_ids:
        users = (await session.exec(select(User).where(User.id.in_(user_ids)))).all()  # type: ignore[attr-defined]
        username_map = {u.id: u.username for u in users}

    by_user: List[Dict[str, Any]] = [
        {
            "user_id": row[0],
            "username": username_map.get(row[0], "system") if row[0] is not None else "system",
            "tokens": int(row[1]),
            "calls": int(row[2]),
        }
        for row in user_rows
    ]

    return {
        "granularity": granularity,
        "summary": summary,
        "daily": daily,
        "by_source": by_source,
        "by_model": by_model,
        "by_user": by_user,
    }
