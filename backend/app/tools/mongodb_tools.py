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
                ServiceCredential.service_type == "mongodb",
            )
            if scope_type == "cluster":
                q = q.where(ServiceCredential.scope_id == cluster_id)
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()
            if cred:
                break

        if cred is None:
            q = select(ServiceCredential).where(ServiceCredential.service_type == "mongodb")
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()

        if cred is None:
            label = f" (instance='{instance_name}')" if instance_name else ""
            raise RuntimeError(
                f"No mongodb credential{label} found in Vault. "
                "Add one in Settings → Vault with service_type='mongodb'."
            )
        host = cred.host or "localhost"
        port = cred.port or 27017
        username = decrypt(cred.username) if cred.username else None
        password = decrypt(cred.password) if cred.password else None
        try:
            extra = json.loads(cred.extra or "{}")
        except json.JSONDecodeError:
            extra = {}
        auth_db = extra.get("auth_db", "admin")
        return host, port, username, password, auth_db


def _connect(host: str, port: int, username: Optional[str], password: Optional[str], auth_db: str):
    from pymongo import MongoClient
    if username and password:
        client = MongoClient(host=host, port=port, username=username, password=password,
                             authSource=auth_db, serverSelectionTimeoutMS=10000)
    else:
        client = MongoClient(host=host, port=port, serverSelectionTimeoutMS=10000)
    return client


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
    return {"success": True, "data": None, "error": None, "source": "mongodb",
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

async def mongo_server_status(cluster_id: Optional[str] = None,
                              instance_name: Optional[str] = None) -> Dict[str, Any]:
    """MongoDB server status: version, uptime, connections, opcounters."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, auth_db = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            client = _connect(host, port, username, password, auth_db)
            try:
                status = client.admin.command("serverStatus")
                conns = status.get("connections", {})
                ops = status.get("opcounters", {})
                mem = status.get("mem", {})
                return "\n".join([
                    f"Version:         {status.get('version')}",
                    f"Uptime:          {status.get('uptime', 0)}s",
                    f"Connections:     current={conns.get('current')}, available={conns.get('available')}",
                    f"Opcounters:      insert={ops.get('insert')}, query={ops.get('query')}, update={ops.get('update')}, delete={ops.get('delete')}",
                    f"Memory (MB):     resident={mem.get('resident')}, virtual={mem.get('virtual')}",
                    f"Repl set:        {status.get('repl', {}).get('setName', 'standalone')}",
                ])
            finally:
                client.close()
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "mongodb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mongodb"}


async def mongo_list_databases(cluster_id: Optional[str] = None,
                               instance_name: Optional[str] = None) -> Dict[str, Any]:
    """List all databases with size and empty status."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, auth_db = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            client = _connect(host, port, username, password, auth_db)
            try:
                result = client.admin.command("listDatabases")
                return [{"name": d["name"],
                         "size_mb": round(d.get("sizeOnDisk", 0) / 1024 / 1024, 2),
                         "empty": d.get("empty", False)} for d in result.get("databases", [])]
            finally:
                client.close()
        rows = await asyncio.to_thread(_run)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mongodb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mongodb"}


async def mongo_collection_stats(database: str,
                                 cluster_id: Optional[str] = None,
                                 instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Collection stats for a database: doc count, size, indexes."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, auth_db = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            client = _connect(host, port, username, password, auth_db)
            try:
                db_obj = client[database]
                rows = []
                for name in db_obj.list_collection_names():
                    try:
                        stats = db_obj.command("collStats", name)
                        rows.append({
                            "collection": name,
                            "docs": stats.get("count", 0),
                            "size_mb": round(stats.get("size", 0) / 1024 / 1024, 2),
                            "storage_mb": round(stats.get("storageSize", 0) / 1024 / 1024, 2),
                            "indexes": stats.get("nindexes", 0),
                        })
                    except Exception:
                        pass
                return sorted(rows, key=lambda x: x["storage_mb"], reverse=True)
            finally:
                client.close()
        rows = await asyncio.to_thread(_run)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mongodb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mongodb"}


async def mongo_slow_ops(min_seconds: int = 5,
                         cluster_id: Optional[str] = None,
                         instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Currently running operations slower than min_seconds."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, auth_db = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            client = _connect(host, port, username, password, auth_db)
            try:
                result = client.admin.command("currentOp",
                                              {"$ownOps": False, "active": True,
                                               "secs_running": {"$gte": min_seconds}})
                ops = result.get("inprog", [])
                rows = []
                for op in ops:
                    rows.append({
                        "opid": str(op.get("opid", "?")),
                        "op": op.get("op", "?"),
                        "ns": op.get("ns", "?"),
                        "secs": op.get("secs_running", 0),
                        "client": op.get("client", "?"),
                        "desc": str(op.get("desc", ""))[:40],
                    })
                return rows
            finally:
                client.close()
        rows = await asyncio.to_thread(_run)
        if not rows:
            return {"success": True, "data": f"No operations running > {min_seconds}s.", "error": None, "source": "mongodb"}
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mongodb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mongodb"}


async def mongo_index_stats(database: str, collection: str,
                            cluster_id: Optional[str] = None,
                            instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Index usage stats for a collection: accesses since last restart."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, auth_db = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            client = _connect(host, port, username, password, auth_db)
            try:
                pipeline = [{"$indexStats": {}}]
                stats = list(client[database][collection].aggregate(pipeline))
                rows = [{"name": s.get("name", "?"),
                         "key": str(s.get("key", {})),
                         "accesses": s.get("accesses", {}).get("ops", 0)} for s in stats]
                return sorted(rows, key=lambda x: x["accesses"])
            finally:
                client.close()
        rows = await asyncio.to_thread(_run)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mongodb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mongodb"}


async def mongo_replication_status(cluster_id: Optional[str] = None,
                                   instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Replica set status: member states, optime lag, health."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, auth_db = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            client = _connect(host, port, username, password, auth_db)
            try:
                rs = client.admin.command("replSetGetStatus")
                rows = []
                for m in rs.get("members", []):
                    rows.append({
                        "name": m.get("name", "?"),
                        "state": m.get("stateStr", "?"),
                        "health": m.get("health", 0),
                        "optime": str(m.get("optimeDate", "N/A")),
                    })
                return rows
            finally:
                client.close()
        rows = await asyncio.to_thread(_run)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mongodb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mongodb"}


async def mongo_query(database: str, collection: str, filter_json: str = "{}",
                      limit: int = 20,
                      cluster_id: Optional[str] = None,
                      instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Run a find() query. filter_json is a JSON string, e.g. '{\"status\": \"active\"}'."""
    try:
        filt = json.loads(filter_json)
    except json.JSONDecodeError as e:
        return {"success": False, "data": None, "error": f"Invalid JSON filter: {e}", "source": "mongodb"}
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, auth_db = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            client = _connect(host, port, username, password, auth_db)
            try:
                docs = list(client[database][collection].find(filt, {"_id": 0}).limit(limit))
                return [json.loads(json.dumps(d, default=str)) for d in docs]
            finally:
                client.close()
        docs = await asyncio.to_thread(_run)
        if not docs:
            return {"success": True, "data": "No documents matched.", "error": None, "source": "mongodb"}
        lines = [json.dumps(d, indent=2) for d in docs[:20]]
        return {"success": True, "data": "\n---\n".join(lines), "error": None, "source": "mongodb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mongodb"}


async def mongo_explain(database: str, collection: str, filter_json: str = "{}",
                        cluster_id: Optional[str] = None,
                        instance_name: Optional[str] = None) -> Dict[str, Any]:
    """EXPLAIN a query to check index usage and winning plan."""
    try:
        filt = json.loads(filter_json)
    except json.JSONDecodeError as e:
        return {"success": False, "data": None, "error": f"Invalid JSON filter: {e}", "source": "mongodb"}
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, auth_db = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            client = _connect(host, port, username, password, auth_db)
            try:
                plan = client[database][collection].find(filt).explain()
                wp = plan.get("queryPlanner", {}).get("winningPlan", {})
                return json.dumps(wp, indent=2, default=str)
            finally:
                client.close()
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "mongodb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mongodb"}


# WRITE TOOLS

async def mongo_kill_op(opid: str,
                        cluster_id: Optional[str] = None,
                        instance_name: Optional[str] = None,
                        reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Kill a running MongoDB operation by opid. Use mongo_slow_ops to find the opid."""
    inputs = {"opid": opid, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("mongo_kill_op", inputs,
                        f"Kill MongoDB operation opid={opid}?\n\nThe operation will be interrupted and may leave partial results.", "high")
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, auth_db = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            client = _connect(host, port, username, password, auth_db)
            try:
                try:
                    op_int = int(opid)
                except ValueError:
                    op_int = opid
                result = client.admin.command("killOp", op=op_int)
                return f"killOp({opid}) completed. info={result.get('info', 'ok')}"
            finally:
                client.close()
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "mongodb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mongodb"}


async def mongo_drop_collection(database: str, collection: str,
                                cluster_id: Optional[str] = None,
                                instance_name: Optional[str] = None,
                                reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Drop a collection and all its documents and indexes. Irreversible."""
    inputs = {"database": database, "collection": collection, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("mongo_drop_collection", inputs,
                        f"DROP collection '{collection}' from database '{database}'?\n\n⚠ All documents and indexes will be permanently deleted.", "critical")
    cid = cluster_id or _active_cluster()
    try:
        host, port, username, password, auth_db = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            client = _connect(host, port, username, password, auth_db)
            try:
                client[database].drop_collection(collection)
                return f"Collection '{database}.{collection}' dropped."
            finally:
                client.close()
        data = await asyncio.to_thread(_run)
        return {"success": True, "data": data, "error": None, "source": "mongodb"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mongodb"}
