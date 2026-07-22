from __future__ import annotations

import base64
import hashlib
import asyncio
import re

import yaml
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.blueprint_files import file_sha256, resolve_source_path

INLINE_MAX_BYTES = 1_000_000  # binary sources at/under this size ship inline; larger are fetched

from app.models.minion import Minion
from app.models.patch import MinionGroup, MinionGroupMember, Organisation
from app.models.blueprint import BlueprintSource, BlueprintAssignment, Blueprint
from app.models.activation_key import KeyBlueprint


_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _substitute(value, variables: dict, resource_id: str):
    """Replace ${name} in string values, recursively. Non-strings pass through."""
    if isinstance(value, str):
        def repl(m):
            name = m.group(1)
            if name not in variables:
                # Silently substituting empty here would turn /opt/${typo}/app.conf
                # into /opt//app.conf and write to the wrong place as root.
                raise ValueError(
                    f"undefined variable ${{{name}}} in resource {resource_id!r}"
                )
            return str(variables[name])
        return _VAR_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _substitute(v, variables, resource_id) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, variables, resource_id) for v in value]
    return value


def render_vars(states: list[dict], variables: dict) -> list[dict]:
    """Render a single file's resources against that file's own `vars:` block.

    Only files that declare `vars:` are rendered. A file without one is passed through
    untouched, so blueprints containing a literal ${...} — a shell snippet in a cmd
    state, say — keep working exactly as before.
    """
    if not variables:
        return states
    return [_substitute(s, variables, s.get("id", "?")) for s in states]


def merge_blueprints(ordered_yaml_bodies: list[str], names: list[str] | None = None) -> list[dict]:
    """Concatenate each body's `resources` list in order; later same-id states replace earlier.

    Variables are file-local, so each body is rendered against its own `vars:` before
    merging — by the time override-by-id runs, no placeholders remain.

    `names` (optional, parallel to the bodies) is used only to name the offending
    blueprint when one fails to parse — a raw ScannerError says "line 62" without
    saying line 62 of *what*.
    """
    order: list[str] = []
    by_id: dict[str, dict] = {}
    for i, body in enumerate(ordered_yaml_bodies):
        if not body or not body.strip():
            continue
        label = names[i] if names and i < len(names) else f"blueprint #{i + 1}"
        try:
            doc = yaml.safe_load(body) or {}
        except yaml.YAMLError as e:
            # Tabs are the usual culprit — YAML forbids them for indentation.
            raise ValueError(f"blueprint {label!r} has invalid YAML: {e}") from e
        states_list = render_vars(doc.get("resources", []) or [], doc.get("vars") or {})
        for state in states_list:
            sid = state.get("id")
            if not sid:
                raise ValueError("every state needs an `id`")
            if sid not in by_id:
                order.append(sid)
            by_id[sid] = state
    return [by_id[sid] for sid in order]


async def source_entry(src, db=None) -> dict:
    """Build the run-bundle entry for one BlueprintSource (inline, or fetch ref if large).

    Disk sources are measured from `src.size` — never by decoding them, which for a
    multi-GB artifact would allocate the whole file to read one integer.
    """
    if src.origin == "disk":
        if src.size > INLINE_MAX_BYTES:
            # The agent only verifies when a checksum is present, so a fetch ref must
            # never ship without one. Hash off the event loop; cached until the file
            # changes, so this is paid once per changed artifact.
            if not src.sha256:
                path = resolve_source_path(src.rel_path)
                src.sha256 = await asyncio.to_thread(file_sha256, path)
                if db is not None:
                    db.add(src)
                    await db.commit()
            return {"encoding": "base64", "fetch": True, "id": src.id,
                    "sha256": src.sha256, "size": src.size}
        # Small enough to inline: read it (bounded by INLINE_MAX_BYTES).
        raw = await asyncio.to_thread(resolve_source_path(src.rel_path).read_bytes)
        try:
            return {"encoding": "utf-8", "content": raw.decode("utf-8")}
        except UnicodeDecodeError:
            return {"encoding": "base64", "content": base64.b64encode(raw).decode("ascii")}

    if src.encoding == "base64":
        raw = base64.b64decode(src.content or "")
        if len(raw) > INLINE_MAX_BYTES:
            return {"encoding": "base64", "fetch": True, "id": src.id,
                    "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
        return {"encoding": "base64", "content": src.content}
    return {"encoding": "utf-8", "content": src.content}


async def collect_referenced_sources(states: list[dict], sources_by_name: dict, db=None) -> dict[str, dict]:
    """Return entry objects for the sources referenced by a file-resource's `source`.

    `file` / `file.managed` reference one source by exact name; `file.recurse`
    references every source under its `source` prefix (names carry the tree)."""
    exact = {s.get("source") for s in states
             if s.get("type") in ("file", "file.managed") and s.get("source")}
    prefixes = {str(s.get("source")).strip("/") for s in states
                if s.get("type") == "file.recurse" and s.get("source")}
    return {name: await source_entry(src, db) for name, src in sources_by_name.items()
            if name in exact or any(name.startswith(p + "/") for p in prefixes)}


async def compile_blueprint(minion_id: str, db: AsyncSession) -> tuple[list[dict], dict[str, str]]:
    """Gather org→group→minion assignments, merge, and bundle referenced sources."""
    minion = await db.get(Minion, minion_id)
    if not minion:
        return [], {}

    # Resolve the minion's scopes, in apply order. "global" is the base layer
    # every minion gets; org/group/minion override it by resource id.
    scope_ids: list[tuple[str, str]] = [("global", "*")]  # (scope_type, scope_id)

    group_ids = [
        m.group_id
        for m in (await db.exec(
            select(MinionGroupMember).where(MinionGroupMember.minion_id == minion_id)
        )).all()
    ]
    org_ids: list[str] = []
    for gid in group_ids:
        grp = await db.get(MinionGroup, gid)
        if grp and grp.org_id not in org_ids:
            org_ids.append(grp.org_id)

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

    merged = merge_blueprints([sf.yaml_body for sf in ordered_files],
                              [sf.name for sf in ordered_files])

    # Build the source pool from the surviving files, later files overriding by source name.
    pool: dict = {}
    for sf in ordered_files:
        for src in (await db.exec(
            select(BlueprintSource).where(BlueprintSource.blueprint_id == sf.id)
        )).all():
            pool[src.name] = src

    return merged, await collect_referenced_sources(merged, pool, db)


async def compile_key_blueprints(key_id: str, db: AsyncSession) -> tuple[list[dict], dict[str, str]]:
    """Merge an activation key's attached blueprints (in position order) + bundle their sources."""
    rows = (await db.exec(
        select(KeyBlueprint).where(KeyBlueprint.key_id == key_id).order_by(KeyBlueprint.position)
    )).all()
    blueprints: list[Blueprint] = []
    for kb in rows:
        bp = await db.get(Blueprint, kb.blueprint_id)
        if bp:
            blueprints.append(bp)
    merged = merge_blueprints([bp.yaml_body for bp in blueprints],
                              [bp.name for bp in blueprints])
    pool: dict = {}
    for bp in blueprints:
        for src in (await db.exec(
            select(BlueprintSource).where(BlueprintSource.blueprint_id == bp.id)
        )).all():
            pool[src.name] = src
    return merged, await collect_referenced_sources(merged, pool, db)
