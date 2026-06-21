from __future__ import annotations

import yaml


def merge_blueprints(ordered_yaml_bodies: list[str]) -> list[dict]:
    """Concatenate each body's `resources` list in order; later same-id states replace earlier."""
    order: list[str] = []
    by_id: dict[str, dict] = {}
    for body in ordered_yaml_bodies:
        if not body or not body.strip():
            continue
        doc = yaml.safe_load(body) or {}
        states_list = doc.get("states") or doc.get("resources") or []
        for state in states_list:
            sid = state.get("id")
            if not sid:
                raise ValueError("every state needs an `id`")
            if sid not in by_id:
                order.append(sid)
            by_id[sid] = state
    return [by_id[sid] for sid in order]


def collect_referenced_sources(
    states: list[dict], sources_by_name: dict[str, str]
) -> dict[str, str]:
    """Return only the sources referenced by a file-state's `source`."""
    wanted = {s.get("source") for s in states if s.get("type") == "file" and s.get("source")}
    return {name: content for name, content in sources_by_name.items() if name in wanted}


from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.minion import Minion
from app.models.patch import MinionGroup, MinionGroupMember, Organisation
from app.models.blueprint import BlueprintSource, BlueprintAssignment, Blueprint


async def compile_blueprint(minion_id: str, db: AsyncSession) -> tuple[list[dict], dict[str, str]]:
    """Gather org→group→minion assignments, merge, and bundle referenced sources."""
    minion = await db.get(Minion, minion_id)
    if not minion:
        return [], {}

    # Resolve the minion's scopes, in apply order.
    scope_ids: list[tuple[str, str]] = []  # (scope_type, scope_id)

    group_ids = [
        m.group_id
        for m in (await db.exec(
            select(MinionGroupMember).where(MinionGroupMember.minion_id == minion_id)
        )).all()
    ]
    org_ids: set[str] = set()
    for gid in group_ids:
        grp = await db.get(MinionGroup, gid)
        if grp:
            org_ids.add(grp.org_id)

    for oid in org_ids:
        scope_ids.append(("org", oid))
    for gid in group_ids:
        scope_ids.append(("group", gid))
    scope_ids.append(("minion", minion_id))

    # Gather assignments → ordered Blueprint rows (preserve scope order).
    ordered_files: list[Blueprint] = []
    seen_file_ids: set[str] = set()
    for scope_type, scope_id in scope_ids:
        rows = (await db.exec(
            select(BlueprintAssignment).where(
                BlueprintAssignment.scope_type == scope_type,
                BlueprintAssignment.scope_id == scope_id,
            )
        )).all()
        for asn in rows:
            sf = await db.get(Blueprint, asn.blueprint_id)
            if sf and sf.id not in seen_file_ids:
                ordered_files.append(sf)
                seen_file_ids.add(sf.id)

    merged = merge_blueprints([sf.yaml_body for sf in ordered_files])

    # Build the source pool from the surviving files, later files overriding by source name.
    pool: dict[str, str] = {}
    for sf in ordered_files:
        for src in (await db.exec(
            select(BlueprintSource).where(BlueprintSource.blueprint_id == sf.id)
        )).all():
            pool[src.name] = src.content

    return merged, collect_referenced_sources(merged, pool)
