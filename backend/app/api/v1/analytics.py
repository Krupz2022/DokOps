from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select, func

from app.api.deps import get_db, get_current_active_superuser
from app.models.analytics import AITokenUsage
from app.models.user import User

router = APIRouter()


def _cutoff(range_str: str) -> datetime:
    days = {"7d": 7, "30d": 30, "90d": 90}
    return datetime.utcnow() - timedelta(days=days[range_str])


@router.get("/tokens")
async def get_token_analytics(
    range: str = Query("7d", pattern="^(7d|30d|90d)$"),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_active_superuser),
) -> Dict[str, Any]:
    since = _cutoff(range)

    # ── Summary ──────────────────────────────────────────────────────────────
    summary_row = session.exec(
        select(
            func.coalesce(func.sum(AITokenUsage.input_tokens), 0),
            func.coalesce(func.sum(AITokenUsage.output_tokens), 0),
            func.count(AITokenUsage.id),
            func.count(func.distinct(AITokenUsage.user_id)),
        ).where(AITokenUsage.created_at >= since)
    ).one()

    total_input = int(summary_row[0])
    total_output = int(summary_row[1])
    total_tokens = total_input + total_output
    total_calls = int(summary_row[2])
    unique_users = int(summary_row[3])

    summary = {
        "total_tokens": total_tokens,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_calls": total_calls,
        "unique_users": unique_users,
    }

    # ── Daily breakdown ───────────────────────────────────────────────────────
    daily_rows = session.exec(
        select(
            func.date(AITokenUsage.created_at).label("date"),
            func.sum(AITokenUsage.input_tokens + AITokenUsage.output_tokens).label("tokens"),
            func.count(AITokenUsage.id).label("calls"),
        )
        .where(AITokenUsage.created_at >= since)
        .group_by(func.date(AITokenUsage.created_at))
        .order_by(func.date(AITokenUsage.created_at))
    ).all()

    daily: List[Dict[str, Any]] = [
        {"date": str(row[0]), "tokens": int(row[1]), "calls": int(row[2])}
        for row in daily_rows
    ]

    # ── By source ─────────────────────────────────────────────────────────────
    source_rows = session.exec(
        select(
            AITokenUsage.source,
            func.sum(AITokenUsage.input_tokens + AITokenUsage.output_tokens).label("tokens"),
            func.count(AITokenUsage.id).label("calls"),
        )
        .where(AITokenUsage.created_at >= since)
        .group_by(AITokenUsage.source)
    ).all()

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
    model_rows = session.exec(
        select(
            AITokenUsage.model,
            func.sum(AITokenUsage.input_tokens + AITokenUsage.output_tokens).label("tokens"),
            func.count(AITokenUsage.id).label("calls"),
        )
        .where(AITokenUsage.created_at >= since)
        .group_by(AITokenUsage.model)
    ).all()

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
    user_rows = session.exec(
        select(
            AITokenUsage.user_id,
            func.sum(AITokenUsage.input_tokens + AITokenUsage.output_tokens).label("tokens"),
            func.count(AITokenUsage.id).label("calls"),
        )
        .where(AITokenUsage.created_at >= since)
        .group_by(AITokenUsage.user_id)
    ).all()

    # Build user_id → username map for non-null user_ids
    user_ids = [row[0] for row in user_rows if row[0] is not None]
    username_map: Dict[int, str] = {}
    if user_ids:
        users = session.exec(select(User).where(User.id.in_(user_ids))).all()  # type: ignore[attr-defined]
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
        "summary": summary,
        "daily": daily,
        "by_source": by_source,
        "by_model": by_model,
        "by_user": by_user,
    }
