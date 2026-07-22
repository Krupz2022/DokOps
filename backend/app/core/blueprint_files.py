"""Disk-backed blueprint source helpers.

Folder-seeded sources are already files on disk, so the DB stores a reference
(rel_path + size + mtime) instead of their bytes. These helpers resolve those
references safely and hash them without loading a whole artifact into memory.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# backend/app/blueprints — the root every rel_path is relative to.
BLUEPRINTS_ROOT = Path(__file__).resolve().parent.parent / "blueprints"

_HASH_CHUNK = 1024 * 1024


def resolve_source_path(rel_path: str, root: Path | str | None = None) -> Path:
    """Resolve a stored rel_path under the blueprints root.

    rel_path comes out of the database and reaches the filesystem, so it is
    confined to the root: anything resolving outside raises ValueError. Callers
    turn that into a 403 rather than letting it touch the disk.
    """
    base = Path(root or BLUEPRINTS_ROOT).resolve()
    target = (base / rel_path).resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"source path escapes blueprints root: {rel_path!r}")
    return target


def file_sha256(path: Path | str) -> str:
    """Stream-hash a file. Constant memory regardless of size."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_HASH_CHUNK), b""):
            h.update(block)
    return h.hexdigest()
