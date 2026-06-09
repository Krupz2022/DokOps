import asyncio
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _get_credential(cluster_id: Optional[str] = None, instance_name: Optional[str] = None):
    from sqlmodel import Session, select
    from app.core.db import engine
    from app.core.encryption import decrypt
    from app.models.service_diag import ServiceCredential

    with Session(engine) as db:
        cred = None
        for scope_type, scope_id in [("cluster", cluster_id), ("global", None)]:
            if scope_type == "cluster" and not cluster_id:
                continue
            q = select(ServiceCredential).where(
                ServiceCredential.scope_type == scope_type,
                ServiceCredential.service_type == "redis",
            )
            if scope_type == "cluster":
                q = q.where(ServiceCredential.scope_id == cluster_id)
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()
            if cred:
                break

        if cred is None:
            q = select(ServiceCredential).where(ServiceCredential.service_type == "redis")
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()

        if cred is None:
            label = f" (instance='{instance_name}')" if instance_name else ""
            raise RuntimeError(
                f"No redis credential{label} found in Vault. "
                "Add one in Settings → Vault with service_type='redis'."
            )
        host = cred.host or "localhost"
        port = cred.port or 6379
        username = decrypt(cred.username) if cred.username else None
        password = decrypt(cred.password) if cred.password else None
        try:
            extra = json.loads(cred.extra or "{}")
        except json.JSONDecodeError:
            extra = {}
        db_index = int(extra.get("db_index", 0))
        return host, port, username, password, db_index


def _connect(host: str, port: int, username: Optional[str], password: Optional[str], db_index: int):
    import redis
    return redis.Redis(host=host, port=port, username=username or None,
                       password=password or None, db=db_index,
                       decode_responses=True, socket_connect_timeout=10)


def _pending(tool_name: str, inputs: dict, message: str, risk_level: str) -> Dict[str, Any]:
    return {"success": True, "data": None, "error": None, "source": "redis",
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

async def redis_info(cluster_id: Optional[str] = None,
                     instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Redis server summary: version, memory, clients, persistence, replication."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            info = r.info()
            sections = {
                "server": ["redis_version", "uptime_in_seconds", "config_file"],
                "memory": ["used_memory_human", "used_memory_peak_human", "maxmemory_human", "mem_fragmentation_ratio"],
                "clients": ["connected_clients", "blocked_clients", "maxclients"],
                "persistence": ["rdb_last_save_time", "rdb_changes_since_last_save", "aof_enabled"],
                "replication": ["role", "connected_slaves", "master_replid"],
                "stats": ["total_commands_processed", "instantaneous_ops_per_sec", "keyspace_hits", "keyspace_misses"],
            }
            lines = []
            for section, keys in sections.items():
                lines.append(f"[{section}]")
                for k in keys:
                    if k in info:
                        lines.append(f"  {k}: {info[k]}")
            return "\n".join(lines)
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}


async def redis_keyspace_stats(cluster_id: Optional[str] = None,
                               instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Keyspace stats per database: key count, expiry count, average TTL."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            ks = r.info("keyspace")
            if not ks:
                return "No databases with keys."
            lines = []
            for db_key, stats in ks.items():
                lines.append(f"{db_key}: keys={stats.get('keys', 0)}, expires={stats.get('expires', 0)}, avg_ttl={stats.get('avg_ttl', 0)}ms")
            return "\n".join(lines)
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}


async def redis_slow_log(count: int = 25,
                         cluster_id: Optional[str] = None,
                         instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Most recent slow log entries: command, duration, client."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            entries = r.slowlog_get(count)
            if not entries:
                return "Slow log is empty."
            lines = []
            for e in entries:
                cmd = " ".join(str(x) for x in (e.get("command") or []))[:120]
                dur_ms = e.get("duration", 0) / 1000
                client = e.get("client_addr", "?")
                lines.append(f"[{e.get('id')}] {dur_ms:.1f}ms  {cmd}  (client={client})")
            return "\n".join(lines)
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}


async def redis_client_list(cluster_id: Optional[str] = None,
                            instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Active client connections with ID, addr, cmd, memory."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            return r.client_list()
        clients = await asyncio.to_thread(_run)
        if not clients:
            return {"success": True, "data": "No clients connected.", "error": None, "source": "redis"}
        col_keys = ["id", "addr", "cmd", "age", "idle", "mem"]
        rows = [{k: str(c.get(k, "")) for k in col_keys} for c in clients[:50]]
        widths = {k: max(len(k), max(len(r[k]) for r in rows)) for k in col_keys}
        sep = "  ".join("-" * widths[k] for k in col_keys)
        header = "  ".join(k.ljust(widths[k]) for k in col_keys)
        lines = [header, sep] + ["  ".join(r[k].ljust(widths[k]) for k in col_keys) for r in rows]
        return {"success": True, "data": "\n".join(lines), "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}


async def redis_memory_usage(cluster_id: Optional[str] = None,
                             instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Memory report: used, peak, fragmentation, eviction policy, maxmemory."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            m = r.info("memory")
            return "\n".join([
                f"Used memory:        {m.get('used_memory_human')}",
                f"Peak memory:        {m.get('used_memory_peak_human')}",
                f"RSS memory:         {m.get('used_memory_rss_human')}",
                f"Fragmentation ratio:{m.get('mem_fragmentation_ratio')}",
                f"Max memory:         {m.get('maxmemory_human')} (policy: {m.get('maxmemory_policy')})",
                f"Active defrag:      {m.get('active_defrag_running')}",
            ])
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}


async def redis_big_keys(cluster_id: Optional[str] = None,
                         instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Top 20 keys by memory usage (scans up to 1000 keys)."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            keys = []
            cursor = 0
            while True:
                cursor, batch = r.scan(cursor, count=100)
                keys.extend(batch)
                if cursor == 0 or len(keys) >= 1000:
                    break
            sizes = []
            for k in keys[:1000]:
                try:
                    sz = r.memory_usage(k) or 0
                    sizes.append((k, sz, r.type(k)))
                except Exception:
                    pass
            top = sorted(sizes, key=lambda x: x[1], reverse=True)[:20]
            if not top:
                return "No keys found."
            lines = [f"{'key':<50}  {'type':<10}  {'bytes':>10}"]
            lines.append("-" * 74)
            for k, sz, t in top:
                lines.append(f"{k[:50]:<50}  {t:<10}  {sz:>10,}")
            return "\n".join(lines)
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}


async def redis_replication_status(cluster_id: Optional[str] = None,
                                   instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Replication info: role, connected replicas, replication lag."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            rep = r.info("replication")
            lines = [f"role:                {rep.get('role')}",
                     f"connected_slaves:    {rep.get('connected_slaves', 0)}",
                     f"master_replid:       {rep.get('master_replid', 'N/A')}",
                     f"master_repl_offset:  {rep.get('master_repl_offset', 'N/A')}",
                     f"repl_backlog_active: {rep.get('repl_backlog_active', 0)}"]
            for i in range(int(rep.get("connected_slaves", 0))):
                slave_info = rep.get(f"slave{i}", "")
                lines.append(f"slave{i}: {slave_info}")
            return "\n".join(lines)
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}


async def redis_config_get(pattern: str = "*",
                           cluster_id: Optional[str] = None,
                           instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Read server configuration parameters matching a glob pattern."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            cfg = r.config_get(pattern)
            return "\n".join(f"{k}: {v}" for k, v in sorted(cfg.items()))
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data or "No matching config keys.", "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}


# WRITE TOOLS

async def redis_delete_key(key: str,
                           cluster_id: Optional[str] = None,
                           instance_name: Optional[str] = None,
                           reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Delete a specific key from Redis."""
    inputs = {"key": key, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("redis_delete_key", inputs,
                        f"Delete Redis key '{key}'?\n\nThis is permanent and cannot be undone.", "high")
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            deleted = r.delete(key)
            return f"Key '{key}' {'deleted' if deleted else 'not found (already absent)'}."
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}


async def redis_kill_client(client_id: str,
                            cluster_id: Optional[str] = None,
                            instance_name: Optional[str] = None,
                            reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Kill an active client connection by ID. Use redis_client_list to get the ID."""
    inputs = {"client_id": client_id, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("redis_kill_client", inputs,
                        f"Kill Redis client id={client_id}?\n\nThe client will receive a connection error.", "medium")
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            result = r.client_kill_filter(id=client_id)
            return f"Killed {result} client(s) with id={client_id}."
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}


async def redis_flushdb(cluster_id: Optional[str] = None,
                        instance_name: Optional[str] = None,
                        reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Flush all keys from the current database. ALL DATA WILL BE LOST."""
    inputs = {"cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("redis_flushdb", inputs,
                        "FLUSH the entire Redis database?\n\n⚠ ALL KEYS will be permanently deleted. This cannot be undone.", "critical")
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, db_index = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            r = _connect(host, port, username, password, db_index)
            r.flushdb()
            return f"Database {db_index} flushed successfully."
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "redis"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "redis"}
