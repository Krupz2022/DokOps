from __future__ import annotations

import base64
import logging
import os

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.datetimes import utcnow
from app.models.patch import MinionGroup, Organisation
from app.models.blueprint import BlueprintSource, BlueprintAssignment, Blueprint

log = logging.getLogger(__name__)


async def _resolve_scope(scope_kind: str, parts: list[str], db: AsyncSession) -> tuple[str, str] | None:
    """Map a path scope to (scope_type, scope_id). Returns None if the org/group is unknown."""
    if scope_kind == "orgs":
        org = (await db.exec(select(Organisation).where(Organisation.name == parts[0]))).first()
        return ("org", org.id) if org else None
    if scope_kind == "groups":
        org = (await db.exec(select(Organisation).where(Organisation.name == parts[0]))).first()
        if not org:
            return None
        grp = (await db.exec(
            select(MinionGroup).where(MinionGroup.org_id == org.id, MinionGroup.name == parts[1])
        )).first()
        return ("group", grp.id) if grp else None
    if scope_kind == "minions":
        return ("minion", parts[0])
    if scope_kind == "common":
        return ("global", "*")
    return None


async def _upsert_state_file(name: str, body: str, db: AsyncSession) -> Blueprint:
    sf = (await db.exec(select(Blueprint).where(Blueprint.name == name))).first()
    if sf:
        sf.yaml_body = body
        sf.updated_at = utcnow()
    else:
        sf = Blueprint(name=name, yaml_body=body)
    db.add(sf)
    await db.flush()
    return sf


async def seed_blueprints_from_dir(root: str, db: AsyncSession, prune: bool = False) -> tuple[int, int]:
    """Walk orgs/groups/minions dirs and upsert blueprints + sources + assignments.

    Returns (seeded, pruned). With prune=True (explicit re-seed / CD reconcile), any
    seeded blueprint whose backing YAML is gone is deleted with its sources + assignments.
    Only path-named blueprints (orgs/… groups/… minions/…) are pruned — UI-created ones
    are never touched. Startup uses prune=False so a not-yet-mounted folder can't wipe data.
    """
    seeded = 0
    seen: set[str] = set()
    for scope_kind in ("common", "orgs", "groups", "minions"):
        base = os.path.join(root, scope_kind)
        if not os.path.isdir(base):
            continue
        depth = {"common": 0, "orgs": 1, "groups": 2, "minions": 1}[scope_kind]
        for dirpath, _dirs, files in os.walk(base):
            rel = os.path.relpath(dirpath, base).replace("\\", "/")
            parts = [] if rel == "." else rel.split("/")
            yaml_files = [f for f in files if f.endswith((".yaml", ".yml"))]
            if len(parts) != depth or not yaml_files:
                continue
            scope = await _resolve_scope(scope_kind, parts, db)
            if not scope:
                log.warning("blueprint seed: unknown %s scope %s — skipped", scope_kind, parts)
                continue
            scope_type, scope_id = scope
            for fname in yaml_files:
                name = f"{scope_kind}/{fname}" if rel == "." else f"{scope_kind}/{rel}/{fname}"
                seen.add(name)
                with open(os.path.join(dirpath, fname), "r", encoding="utf-8") as fh:
                    sf = await _upsert_state_file(name, fh.read(), db)
                # sources from a sibling files/ dir
                files_dir = os.path.join(dirpath, "files")
                if os.path.isdir(files_dir):
                    for src_name in os.listdir(files_dir):
                        src_path = os.path.join(files_dir, src_name)
                        if not os.path.isfile(src_path):
                            continue
                        try:
                            with open(src_path, "r", encoding="utf-8") as sfh:
                                content = sfh.read()
                            enc = "utf-8"
                        except UnicodeDecodeError:
                            with open(src_path, "rb") as sfh:
                                content = base64.b64encode(sfh.read()).decode("ascii")
                            enc = "base64"
                        existing = (await db.exec(select(BlueprintSource).where(
                            BlueprintSource.blueprint_id == sf.id, BlueprintSource.name == src_name))).first()
                        if existing:
                            existing.content = content
                            existing.encoding = enc
                            db.add(existing)
                        else:
                            db.add(BlueprintSource(blueprint_id=sf.id, name=src_name, content=content, encoding=enc))
                # assignment (avoid duplicate)
                dup = (await db.exec(select(BlueprintAssignment).where(
                    BlueprintAssignment.blueprint_id == sf.id,
                    BlueprintAssignment.scope_type == scope_type,
                    BlueprintAssignment.scope_id == scope_id))).first()
                if not dup:
                    db.add(BlueprintAssignment(blueprint_id=sf.id, scope_type=scope_type, scope_id=scope_id))
                seeded += 1

    # Reconcile: drop seeded blueprints whose YAML no longer exists in the folder.
    pruned = 0
    if prune:
        for bp in (await db.exec(select(Blueprint))).all():
            is_seeded = bp.name.split("/", 1)[0] in ("common", "orgs", "groups", "minions")
            if is_seeded and bp.name not in seen:
                for src in (await db.exec(select(BlueprintSource).where(
                        BlueprintSource.blueprint_id == bp.id))).all():
                    await db.delete(src)
                for asn in (await db.exec(select(BlueprintAssignment).where(
                        BlueprintAssignment.blueprint_id == bp.id))).all():
                    await db.delete(asn)
                await db.delete(bp)
                pruned += 1

    await db.commit()
    return seeded, pruned
