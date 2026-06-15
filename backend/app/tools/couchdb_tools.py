import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_credential(cluster_id: Optional[str] = None, instance_name: Optional[str] = None):
    from sqlmodel import Session, select
    from app.core.db import sync_engine
    from app.core.encryption import decrypt
    from app.models.service_diag import ServiceCredential

    # R8: sync session by design — _get_credential is only ever invoked via
    # asyncio.to_thread(), so it runs on a worker thread, not the event loop.
    with Session(sync_engine) as db:
        cred = None
        for scope_type, scope_id in [("cluster", cluster_id), ("global", None)]:
            if scope_type == "cluster" and not cluster_id:
                continue
            q = select(ServiceCredential).where(
                ServiceCredential.scope_type == scope_type,
                ServiceCredential.service_type == "couchdb",
            )
            if scope_type == "cluster":
                q = q.where(ServiceCredential.scope_id == cluster_id)
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()
            if cred:
                break

        if cred is None:
            q = select(ServiceCredential).where(ServiceCredential.service_type == "couchdb")
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()

        if cred is None:
            label = f" (instance='{instance_name}')" if instance_name else ""
            raise RuntimeError(
                f"No couchdb credential{label} found in Vault. "
                "Add one in Settings → Vault with service_type='couchdb'."
            )
        host = cred.host or "localhost"
        port = cred.port or 5984
        username = decrypt(cred.username) if cred.username else "admin"
        password = decrypt(cred.password) if cred.password else ""
        return host, port, username, password


def _get(host: str, port: int, username: str, password: str, path: str) -> Any:
    import httpx
    r = httpx.get(f"http://{host}:{port}{path}", auth=(username, password), timeout=15)
    r.raise_for_status()
    return r.json()


def _post(host: str, port: int, username: str, password: str, path: str, body: dict) -> Any:
    import httpx
    r = httpx.post(f"http://{host}:{port}{path}", auth=(username, password), json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def _delete(host: str, port: int, username: str, password: str, path: str) -> Any:
    import httpx
    r = httpx.delete(f"http://{host}:{port}{path}", auth=(username, password), timeout=15)
    r.raise_for_status()
    return r.json()


def _fmt(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "No rows returned."
    keys = list(rows[0].keys())
    col_widths = {k: max(len(str(k)), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    sep = "  ".join("-" * col_widths[k] for k in keys)
    header = "  ".join(str(k).ljust(col_widths[k]) for k in keys)
    lines = [header, sep] + ["  ".join(str(r.get(k, "")).ljust(col_widths[k]) for k in keys) for r in rows]
    lines.append(f"\n({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return "\n".join(lines)


def _pending(tool_name: str, inputs: dict, message: str, risk_level: str) -> Dict[str, Any]:
    return {"success": True, "data": None, "error": None, "source": "couchdb",
            "requires_confirmation": True,
            "pending_operation": {"tool_name": tool_name, "tool_inputs": inputs,
                                  "confirmation_message": message, "risk_level": risk_level}}


def _active_cluster() -> Optional[str]:
    try:
        from app.services.k8s_service import active_cluster_ctx
        return active_cluster_ctx.get()
    except Exception:
        return None


# READ TOOLS

async def couchdb_server_info(cluster_id: Optional[str] = None,
                              instance_name: Optional[str] = None) -> Dict[str, Any]:
    """CouchDB server version, UUID, features enabled."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd = await asyncio.to_thread(_get_credential, cid, instance_name)
        info = await asyncio.to_thread(_get, host, port, user, pwd, "/")
        lines = [f"Version:   {info.get('version', '?')}",
                 f"UUID:      {info.get('uuid', '?')}",
                 f"Git SHA:   {info.get('git_sha', '?')}",
                 f"Features:  {', '.join(info.get('features', []))}",
                 f"Vendor:    {info.get('vendor', {}).get('name', '?')}"]
        return {"success": True, "data": "\n".join(lines), "error": None, "source": "couchdb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "couchdb"}


async def couchdb_list_databases(cluster_id: Optional[str] = None,
                                 instance_name: Optional[str] = None) -> Dict[str, Any]:
    """List all databases."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd = await asyncio.to_thread(_get_credential, cid, instance_name)
        dbs = await asyncio.to_thread(_get, host, port, user, pwd, "/_all_dbs")
        system_dbs = {"_users", "_replicator", "_global_changes"}
        user_dbs = [d for d in dbs if d not in system_dbs]
        system = [d for d in dbs if d in system_dbs]
        lines = [f"User databases ({len(user_dbs)}):"] + [f"  {d}" for d in sorted(user_dbs)]
        lines += [f"\nSystem databases ({len(system)}):"] + [f"  {d}" for d in sorted(system)]
        return {"success": True, "data": "\n".join(lines), "error": None, "source": "couchdb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "couchdb"}


async def couchdb_database_info(database: str,
                                cluster_id: Optional[str] = None,
                                instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Stats for a specific database: doc count, disk size, compaction status."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd = await asyncio.to_thread(_get_credential, cid, instance_name)
        info = await asyncio.to_thread(_get, host, port, user, pwd, f"/{database}")
        sizes = info.get("sizes", {})
        lines = [f"Database:      {info.get('db_name')}",
                 f"Doc count:     {info.get('doc_count', 0):,}",
                 f"Deleted docs:  {info.get('doc_del_count', 0):,}",
                 f"Data size:     {sizes.get('active', 0) // 1024:,} KB",
                 f"Disk size:     {sizes.get('file', 0) // 1024:,} KB",
                 f"External size: {sizes.get('external', 0) // 1024:,} KB",
                 f"Compaction:    {'running' if info.get('compact_running') else 'idle'}",
                 f"Update seq:    {info.get('update_seq', '?')}"]
        return {"success": True, "data": "\n".join(lines), "error": None, "source": "couchdb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "couchdb"}


async def couchdb_active_tasks(cluster_id: Optional[str] = None,
                               instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Active background tasks: compactions, indexing, replications."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd = await asyncio.to_thread(_get_credential, cid, instance_name)
        tasks = await asyncio.to_thread(_get, host, port, user, pwd, "/_active_tasks")
        if not tasks:
            return {"success": True, "data": "No active tasks.", "error": None, "source": "couchdb"}
        rows = [{"type": t.get("type", "?"), "node": t.get("node", "?"),
                 "database": t.get("database", "?"), "progress": f"{t.get('progress', 0)}%",
                 "started_on": t.get("started_on", "?")} for t in tasks]
        return {"success": True, "data": _fmt(rows), "error": None, "source": "couchdb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "couchdb"}


async def couchdb_node_stats(cluster_id: Optional[str] = None,
                             instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Node statistics: request rates, DB reads/writes, open OS files."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd = await asyncio.to_thread(_get_credential, cid, instance_name)
        stats = await asyncio.to_thread(_get, host, port, user, pwd, "/_node/_local/_stats")
        lines = [
            f"DB reads (total):    {stats.get('couch_db_reads', {}).get('value', 'N/A')}",
            f"DB writes (total):   {stats.get('couch_db_writes', {}).get('value', 'N/A')}",
            f"Open DBs:            {stats.get('couch_open_databases', {}).get('value', 'N/A')}",
            f"Open OS files:       {stats.get('couch_open_os_files', {}).get('value', 'N/A')}",
            f"HTTP 200 responses:  {stats.get('httpd_status_codes', {}).get('200', {}).get('value', 'N/A')}",
            f"HTTP 500 responses:  {stats.get('httpd_status_codes', {}).get('500', {}).get('value', 'N/A')}",
        ]
        return {"success": True, "data": "\n".join(lines), "error": None, "source": "couchdb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "couchdb"}


async def couchdb_replication_status(cluster_id: Optional[str] = None,
                                     instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Replication documents in _replicator: source, target, state."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd = await asyncio.to_thread(_get_credential, cid, instance_name)
        data = await asyncio.to_thread(_get, host, port, user, pwd, "/_replicator/_all_docs?include_docs=true")
        docs = [row.get("doc", {}) for row in data.get("rows", []) if not row["id"].startswith("_")]
        if not docs:
            return {"success": True, "data": "No replication documents.", "error": None, "source": "couchdb"}
        rows = [{"id": d.get("_id", "?")[:30], "source": str(d.get("source", "?"))[:40],
                 "target": str(d.get("target", "?"))[:40], "state": d.get("_replication_state", "?")}
                for d in docs]
        return {"success": True, "data": _fmt(rows), "error": None, "source": "couchdb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "couchdb"}


# WRITE TOOLS

async def couchdb_compact_db(database: str,
                             cluster_id: Optional[str] = None,
                             instance_name: Optional[str] = None,
                             reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Trigger database compaction to reclaim disk space from deleted documents."""
    inputs = {"database": database, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("couchdb_compact_db", inputs,
                        f"Compact database '{database}'?\n\nCompaction runs in the background and reclaims disk from deleted docs. Low risk.", "medium")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd = await asyncio.to_thread(_get_credential, cid, instance_name)
        result = await asyncio.to_thread(_post, host, port, user, pwd, f"/{database}/_compact", {})
        return {"success": True, "data": f"Compaction started for '{database}'. ok={result.get('ok')}", "error": None, "source": "couchdb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "couchdb"}


async def couchdb_delete_db(database: str,
                            cluster_id: Optional[str] = None,
                            instance_name: Optional[str] = None,
                            reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Delete a database and all its documents. This is irreversible."""
    inputs = {"database": database, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("couchdb_delete_db", inputs,
                        f"DELETE database '{database}' and ALL its documents?\n\n⚠ This is permanent and cannot be undone.", "critical")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd = await asyncio.to_thread(_get_credential, cid, instance_name)
        result = await asyncio.to_thread(_delete, host, port, user, pwd, f"/{database}")
        return {"success": True, "data": f"Database '{database}' deleted. ok={result.get('ok')}", "error": None, "source": "couchdb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "couchdb"}
