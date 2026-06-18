"""Timezone-aware UTC datetime helpers for SQLModel timestamp columns.

Every persisted timestamp in DokOps is a timezone-aware UTC value mapped to
PostgreSQL ``TIMESTAMP WITH TIME ZONE`` (``timestamptz``) — and ISO strings on
SQLite. This is the single source of truth for timestamp columns.

Do NOT use ``datetime.utcnow`` (deprecated in 3.12+, and naive) or a bare
``Field(default_factory=lambda: datetime.now(timezone.utc))`` without a column
type: the implicit column is ``TIMESTAMP WITHOUT TIME ZONE``, and asyncpg
refuses to bind an aware datetime to a naive column ("can't subtract
offset-naive and offset-aware datetimes").
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime
from sqlmodel import Field


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC ``datetime``."""
    return datetime.now(timezone.utc)


def utc_field(*, index: bool = False, **field_kwargs: Any) -> Any:
    """Required aware-UTC timestamp column, defaulting to ``utcnow()``.

    Maps to ``TIMESTAMP WITH TIME ZONE``. ``index``/``nullable`` live on the
    ``Column`` because SQLModel forbids passing them alongside ``sa_column``.
    """
    return Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), index=index, nullable=False),
        **field_kwargs,
    )


def utc_optional_field(*, index: bool = False, **field_kwargs: Any) -> Any:
    """Optional aware-UTC timestamp column (nullable, default ``None``)."""
    return Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), index=index, nullable=True),
        **field_kwargs,
    )
