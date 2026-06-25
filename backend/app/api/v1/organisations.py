from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_async_db, get_current_user, require_god_mode
from app.models.patch import MinionGroup, MinionGroupMember, Organisation
from app.models.user import User

router = APIRouter()


class OrgCreate(BaseModel):
    name: str
    slug: str


class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None


class MemberAdd(BaseModel):
    minion_id: str


class MemberAssign(BaseModel):
    minion_id: str
    group_id: str


# All /groups/... routes MUST come before /{org_id} routes to prevent FastAPI
# from matching "groups" as an org_id parameter.


@router.get("/groups")
async def list_all_groups(
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    """List all groups across all organisations (for credential scope dropdowns)."""
    return (await db.exec(select(MinionGroup))).all()


@router.delete("/groups/{group_id}/members/{minion_id}")
async def remove_member(
    group_id: str,
    minion_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    row = await db.get(MinionGroupMember, (group_id, minion_id))
    if not row:
        raise HTTPException(status_code=404)
    await db.delete(row)
    await db.commit()
    return {"removed": True}


@router.post("/groups/{group_id}/members")
async def add_member(
    group_id: str,
    body: MemberAdd,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    if not await db.get(MinionGroup, group_id):
        raise HTTPException(status_code=404, detail="Group not found")
    existing = await db.get(MinionGroupMember, (group_id, body.minion_id))
    if existing:
        return {"added": False, "reason": "already member"}
    # Single-group invariant: a minion belongs to at most one group. Refuse to add a
    # minion that's already in another group (use POST /{org}/assign to *move* it).
    other = (await db.exec(
        select(MinionGroupMember).where(MinionGroupMember.minion_id == body.minion_id)
    )).first()
    if other:
        raise HTTPException(
            status_code=409,
            detail=f"Minion already in group {other.group_id}; remove it first or use /assign to move it",
        )
    db.add(MinionGroupMember(group_id=group_id, minion_id=body.minion_id))
    await db.commit()
    return {"added": True}


@router.get("/groups/{group_id}")
async def get_group(
    group_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    grp = await db.get(MinionGroup, group_id)
    if not grp:
        raise HTTPException(status_code=404)
    members = (await db.exec(
        select(MinionGroupMember).where(MinionGroupMember.group_id == group_id)
    )).all()
    return {**grp.model_dump(), "member_ids": [m.minion_id for m in members]}


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    grp = await db.get(MinionGroup, group_id)
    if not grp:
        raise HTTPException(status_code=404)
    await db.delete(grp)
    await db.commit()
    return {"deleted": True}


# Now the /{org_id} routes come after all /groups/... routes


@router.get("/")
async def list_orgs(db: AsyncSession = Depends(get_async_db), _: User = Depends(get_current_user)):
    return (await db.exec(select(Organisation))).all()


@router.post("/")
async def create_org(
    body: OrgCreate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    if (await db.exec(select(Organisation).where(Organisation.slug == body.slug))).first():
        raise HTTPException(status_code=409, detail="Slug already in use")
    org = Organisation(name=body.name, slug=body.slug)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.post("/{org_id}/assign")
async def assign_minion(
    org_id: str,
    body: MemberAssign,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    """Move a minion to a different group within this org (one group per org enforced)."""
    if not await db.get(Organisation, org_id):
        raise HTTPException(status_code=404, detail="Organisation not found")
    grp = await db.get(MinionGroup, body.group_id)
    if not grp or grp.org_id != org_id:
        raise HTTPException(status_code=400, detail="Group does not belong to this org")
    from app.services.patch_service import assign_minion_to_group
    assign_minion_to_group(body.minion_id, org_id, body.group_id)
    return {"assigned": True, "minion_id": body.minion_id, "group_id": body.group_id}


@router.get("/{org_id}/groups")
async def list_groups(
    org_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    return (await db.exec(select(MinionGroup).where(MinionGroup.org_id == org_id))).all()


@router.post("/{org_id}/groups")
async def create_group(
    org_id: str,
    body: GroupCreate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    if not await db.get(Organisation, org_id):
        raise HTTPException(status_code=404, detail="Organisation not found")
    grp = MinionGroup(org_id=org_id, name=body.name, description=body.description)
    db.add(grp)
    await db.commit()
    await db.refresh(grp)
    return grp


@router.get("/{org_id}")
async def get_org(
    org_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    org = await db.get(Organisation, org_id)
    if not org:
        raise HTTPException(status_code=404)
    groups = (await db.exec(select(MinionGroup).where(MinionGroup.org_id == org_id))).all()
    members = (await db.exec(
        select(MinionGroupMember).where(
            MinionGroupMember.group_id.in_([g.id for g in groups])  # type: ignore[attr-defined]
        )
    )).all()
    members_by_group: dict[str, list[str]] = {}
    for m in members:
        members_by_group.setdefault(m.group_id, []).append(m.minion_id)
    return {
        **org.model_dump(),
        "groups": [{**g.model_dump(), "member_ids": members_by_group.get(g.id, [])} for g in groups],
    }


@router.delete("/{org_id}")
async def delete_org(
    org_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(require_god_mode),
):
    org = await db.get(Organisation, org_id)
    if not org:
        raise HTTPException(status_code=404)
    await db.delete(org)
    await db.commit()
    return {"deleted": True}
