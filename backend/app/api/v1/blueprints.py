# backend/app/api/v1/blueprints.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_async_db, get_current_user, get_current_active_superuser
from app.core.datetimes import utcnow
from app.models.blueprint import BlueprintSource, BlueprintAssignment, Blueprint
from app.models.user import User

router = APIRouter()


class BlueprintIn(BaseModel):
    name: str
    yaml_body: str = "resources: []"


class SourceIn(BaseModel):
    content: str


class AssignmentIn(BaseModel):
    scope_type: str  # org | group | minion
    scope_id: str


@router.get("/")
async def list_blueprints(db: AsyncSession = Depends(get_async_db), _: User = Depends(get_current_user)):
    return (await db.exec(select(Blueprint))).all()


@router.post("/")
async def create_blueprint(body: BlueprintIn, db: AsyncSession = Depends(get_async_db),
                       _: User = Depends(get_current_active_superuser)):
    if (await db.exec(select(Blueprint).where(Blueprint.name == body.name))).first():
        raise HTTPException(status_code=409, detail="Blueprint name already exists")
    sf = Blueprint(name=body.name, yaml_body=body.yaml_body)
    db.add(sf)
    await db.commit()
    await db.refresh(sf)
    return sf


@router.get("/{blueprint_id}")
async def get_blueprint(blueprint_id: str, db: AsyncSession = Depends(get_async_db), _: User = Depends(get_current_user)):
    sf = await db.get(Blueprint, blueprint_id)
    if not sf:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return sf


@router.put("/{blueprint_id}")
async def update_blueprint(blueprint_id: str, body: BlueprintIn, db: AsyncSession = Depends(get_async_db),
                       _: User = Depends(get_current_active_superuser)):
    sf = await db.get(Blueprint, blueprint_id)
    if not sf:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    sf.name = body.name
    sf.yaml_body = body.yaml_body
    sf.updated_at = utcnow()
    db.add(sf)
    await db.commit()
    await db.refresh(sf)
    return sf


@router.delete("/{blueprint_id}")
async def delete_blueprint(blueprint_id: str, db: AsyncSession = Depends(get_async_db),
                       _: User = Depends(get_current_active_superuser)):
    sf = await db.get(Blueprint, blueprint_id)
    if not sf:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    for src in (await db.exec(select(BlueprintSource).where(BlueprintSource.blueprint_id == blueprint_id))).all():
        await db.delete(src)
    for asn in (await db.exec(select(BlueprintAssignment).where(BlueprintAssignment.blueprint_id == blueprint_id))).all():
        await db.delete(asn)
    await db.delete(sf)
    await db.commit()
    return {"deleted": True}


@router.put("/{blueprint_id}/sources/{name}")
async def upsert_source(blueprint_id: str, name: str, body: SourceIn,
                        db: AsyncSession = Depends(get_async_db),
                        _: User = Depends(get_current_active_superuser)):
    if not await db.get(Blueprint, blueprint_id):
        raise HTTPException(status_code=404, detail="Blueprint not found")
    existing = (await db.exec(
        select(BlueprintSource).where(BlueprintSource.blueprint_id == blueprint_id, BlueprintSource.name == name)
    )).first()
    if existing:
        existing.content = body.content
        db.add(existing)
    else:
        existing = BlueprintSource(blueprint_id=blueprint_id, name=name, content=body.content)
        db.add(existing)
    await db.commit()
    await db.refresh(existing)
    return existing


@router.post("/{blueprint_id}/assignments")
async def add_assignment(blueprint_id: str, body: AssignmentIn,
                         db: AsyncSession = Depends(get_async_db),
                         _: User = Depends(get_current_active_superuser)):
    if not await db.get(Blueprint, blueprint_id):
        raise HTTPException(status_code=404, detail="Blueprint not found")
    if body.scope_type not in ("org", "group", "minion"):
        raise HTTPException(status_code=400, detail="scope_type must be org|group|minion")
    asn = BlueprintAssignment(blueprint_id=blueprint_id, scope_type=body.scope_type, scope_id=body.scope_id)
    db.add(asn)
    await db.commit()
    await db.refresh(asn)
    return asn


@router.delete("/assignments/{assignment_id}")
async def delete_assignment(assignment_id: str, db: AsyncSession = Depends(get_async_db),
                            _: User = Depends(get_current_active_superuser)):
    asn = await db.get(BlueprintAssignment, assignment_id)
    if not asn:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.delete(asn)
    await db.commit()
    return {"deleted": True}


@router.get("/{blueprint_id}/sources")
async def list_sources(blueprint_id: str, db: AsyncSession = Depends(get_async_db),
                       _: User = Depends(get_current_user)):
    if not await db.get(Blueprint, blueprint_id):
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return (await db.exec(select(BlueprintSource).where(BlueprintSource.blueprint_id == blueprint_id))).all()


@router.get("/{blueprint_id}/assignments")
async def list_assignments(blueprint_id: str, db: AsyncSession = Depends(get_async_db),
                           _: User = Depends(get_current_user)):
    if not await db.get(Blueprint, blueprint_id):
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return (await db.exec(select(BlueprintAssignment).where(BlueprintAssignment.blueprint_id == blueprint_id))).all()
