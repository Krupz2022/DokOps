from __future__ import annotations

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


async def backfill_disk_sources(root: str, db: AsyncSession) -> int:
    """One-time: flip legacy inline rows whose bytes are already a file on disk.

    Before disk-backing, folder-seeded artifacts were copied into the DB as base64.
    This reclaims that space. Only rows that (a) belong to a path-named blueprint and
    (b) have a backing file present are touched — so running with the blueprints
    folder unmounted is a no-op rather than data loss. Idempotent: converted rows are
    no longer "inline" and won't match again.
    """
    converted = 0
    names = {bp.id: bp.name for bp in (await db.exec(select(Blueprint))).all()}
    rows = (await db.exec(
        select(BlueprintSource).where(BlueprintSource.origin == "inline")
    )).all()
    for src in rows:
        bp_name = names.get(src.blueprint_id, "")
        if bp_name.split("/", 1)[0] not in ("common", "orgs", "groups", "minions"):
            continue  # UI-created blueprint — its sources have no folder file
        rel_dir = os.path.dirname(bp_name)
        rel_path = f"{rel_dir}/files/{src.name}" if rel_dir else f"files/{src.name}"
        abs_path = os.path.join(root, rel_path)
        if not os.path.isfile(abs_path):
            continue  # no backing file — leave the bytes where they are
        st = os.stat(abs_path)
        src.origin = "disk"
        src.rel_path = rel_path
        src.size = st.st_size
        src.mtime_ns = st.st_mtime_ns
        src.sha256 = None
        src.content = ""
        src.encoding = "utf-8"
        db.add(src)
        converted += 1
    if converted:
        await db.commit()
    return converted


async def seed_blueprints_from_dir(root: str, db: AsyncSession, prune: bool = False) -> tuple[int, int]:
    """Walk orgs/groups/minions dirs and upsert blueprints + sources + assignments.

    Returns (seeded, pruned). With prune=True (explicit re-seed / CD reconcile), any
    seeded blueprint whose backing YAML is gone is deleted with its sources + assignments,
    and any disk source whose file is gone (deleted or moved) is dropped. `pruned` counts
    both. Only path-named blueprints (orgs/… groups/… minions/…) and origin="disk" sources
    are pruned — UI-created ones are never touched. Startup uses prune=False so a
    not-yet-mounted folder can't wipe data.
    """
    seeded = 0
    seen: set[str] = set()
    seen_sources: set[tuple[str, str]] = set()  # (blueprint_id, source name)
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
                    # walk subdirs too: files/prereq/x.zip → source "prereq/x.zip" (file.recurse trees)
                    src_names = [
                        os.path.relpath(os.path.join(d, f), files_dir).replace("\\", "/")
                        for d, _sd, fs in os.walk(files_dir) for f in fs
                    ]
                    for src_name in src_names:
                        src_path = os.path.join(files_dir, src_name)
                        # stat() only — artifacts can be gigabytes and must never be
                        # read into the DB just to register that they exist.
                        try:
                            st = os.stat(src_path)
                        except OSError as e:
                            log.warning("blueprint seed: cannot stat %s — skipped (%s)", src_path, e)
                            continue
                        rel_path = os.path.relpath(src_path, root).replace("\\", "/")
                        existing = (await db.exec(select(BlueprintSource).where(
                            BlueprintSource.blueprint_id == sf.id, BlueprintSource.name == src_name))).first()
                        if existing is None:
                            existing = BlueprintSource(blueprint_id=sf.id, name=src_name)
                        if (existing.size, existing.mtime_ns) != (st.st_size, st.st_mtime_ns):
                            existing.sha256 = None  # content changed; cached hash is stale
                        existing.origin = "disk"
                        existing.rel_path = rel_path
                        existing.size = st.st_size
                        existing.mtime_ns = st.st_mtime_ns
                        existing.content = ""  # bytes stay on disk
                        existing.encoding = "utf-8"
                        db.add(existing)
                        seen_sources.add((sf.id, src_name))
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

        # Drop disk sources whose file is gone from the folder (deleted or moved).
        # Without this a moved artifact leaves its old row behind pointing at a path
        # that no longer exists — it lingers in the UI and 404s on fetch. Only
        # origin="disk" rows are considered: UI-created sources have no folder file
        # and must never be pruned by a folder walk.
        for src in (await db.exec(
            select(BlueprintSource).where(BlueprintSource.origin == "disk")
        )).all():
            if (src.blueprint_id, src.name) not in seen_sources:
                await db.delete(src)
                pruned += 1

    await db.commit()
    return seeded, pruned
