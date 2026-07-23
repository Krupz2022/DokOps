"""Per-user notification feed (Azure-Portal-style rollout notifications)."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.models.notification import Notification
from app.models.user import User

router = APIRouter()


@router.get("/", response_model=List[Notification])
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(deps.get_async_db),
    current_user: User = Depends(deps.get_current_user),
) -> List[Notification]:
    stmt = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        stmt = stmt.where(Notification.read == False)  # noqa: E712
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    return list((await db.exec(stmt)).all())


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    db: AsyncSession = Depends(deps.get_async_db),
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    row = await db.get(Notification, notification_id)
    if not row or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    row.read = True
    db.add(row)
    await db.commit()
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(deps.get_async_db),
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    rows = (await db.exec(
        select(Notification).where(
            Notification.user_id == current_user.id, Notification.read == False)  # noqa: E712
    )).all()
    for row in rows:
        row.read = True
        db.add(row)
    await db.commit()
    return {"ok": True, "count": len(rows)}
