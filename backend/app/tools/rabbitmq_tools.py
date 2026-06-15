import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

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
                ServiceCredential.service_type == "rabbitmq",
            )
            if scope_type == "cluster":
                q = q.where(ServiceCredential.scope_id == cluster_id)
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()
            if cred:
                break

        if cred is None:
            q = select(ServiceCredential).where(ServiceCredential.service_type == "rabbitmq")
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()

        if cred is None:
            label = f" (instance='{instance_name}')" if instance_name else ""
            raise RuntimeError(
                f"No rabbitmq credential{label} found in Vault. "
                "Add one in Settings → Vault with service_type='rabbitmq'."
            )
        host = cred.host or ""
        username = decrypt(cred.username) if cred.username else "guest"
        password = decrypt(cred.password) if cred.password else "guest"
        try:
            extra = json.loads(cred.extra or "{}")
        except json.JSONDecodeError:
            extra = {}
        management_port = int(extra.get("management_port", 15672))
        vhost = extra.get("vhost", "/")
        return host, management_port, username, password, vhost


def _base_url(host: str, port: int) -> str:
    """Build base URL, honouring embedded scheme or inferring https for port 443/15671."""
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    scheme = "https" if port in (443, 15671) else "http"
    return f"{scheme}://{host}:{port}"


def _api_get(host: str, port: int, username: str, password: str, path: str) -> Any:
    import httpx
    r = httpx.get(f"{_base_url(host, port)}/api{path}", auth=(username, password), timeout=15)
    r.raise_for_status()
    return r.json()


def _api_delete(host: str, port: int, username: str, password: str, path: str,
                headers: Optional[Dict[str, str]] = None) -> Any:
    import httpx
    r = httpx.delete(f"{_base_url(host, port)}/api{path}", auth=(username, password),
                     headers=headers or {}, timeout=15)
    r.raise_for_status()
    return r.text


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
    return {"success": True, "data": None, "error": None, "source": "rabbitmq",
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

async def rabbitmq_list_queues(cluster_id: Optional[str] = None,
                               instance_name: Optional[str] = None) -> Dict[str, Any]:
    """List all queues — depth, ready/unacked, consumer count, state, publish rate."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        queues = await asyncio.to_thread(_api_get, host, port, user, pwd, "/queues")
        rows = [{"name": q.get("name", ""), "vhost": q.get("vhost", "/"),
                 "messages": q.get("messages", 0), "ready": q.get("messages_ready", 0),
                 "unacked": q.get("messages_unacknowledged", 0), "consumers": q.get("consumers", 0),
                 "state": q.get("state", "?"),
                 "publish/s": f"{q.get('message_stats', {}).get('publish_details', {}).get('rate', 0):.1f}"}
                for q in queues]
        return {"success": True, "data": _fmt(rows), "error": None, "source": "rabbitmq"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "rabbitmq"}


async def rabbitmq_queue_detail(queue_name: str, vhost: str = "/",
                                cluster_id: Optional[str] = None,
                                instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Full stats for a specific queue: rates, memory, consumer count."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, default_vhost = await asyncio.to_thread(_get_credential, cid, instance_name)
        vh = vhost or default_vhost
        q = await asyncio.to_thread(_api_get, host, port, user, pwd,
                                    f"/queues/{quote(vh, safe='')}/{quote(queue_name, safe='')}")
        ms = q.get("message_stats", {})
        lines = [f"Queue:      {q['name']} (vhost={q.get('vhost', '/')})",
                 f"State:      {q.get('state', '?')}",
                 f"Messages:   {q.get('messages', 0)}  (ready={q.get('messages_ready', 0)}, unacked={q.get('messages_unacknowledged', 0)})",
                 f"Consumers:  {q.get('consumers', 0)}",
                 f"Memory:     {q.get('memory', 0) // 1024} KB",
                 f"Publish/s:  {ms.get('publish_details', {}).get('rate', 0):.1f}",
                 f"Deliver/s:  {ms.get('deliver_get_details', {}).get('rate', 0):.1f}",
                 f"Ack/s:      {ms.get('ack_details', {}).get('rate', 0):.1f}"]
        return {"success": True, "data": "\n".join(lines), "error": None, "source": "rabbitmq"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "rabbitmq"}


async def rabbitmq_dead_letter_queues(cluster_id: Optional[str] = None,
                                      instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Queues with dead-letter exchange configured — DLX name, routing key, depth."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        queues = await asyncio.to_thread(_api_get, host, port, user, pwd, "/queues")
        dlqs = [q for q in queues if q.get("arguments", {}).get("x-dead-letter-exchange") is not None]
        if not dlqs:
            return {"success": True, "data": "No dead-letter queues configured.", "error": None, "source": "rabbitmq"}
        rows = [{"name": q.get("name", ""), "vhost": q.get("vhost", "/"),
                 "messages": q.get("messages", 0),
                 "dlx": q["arguments"]["x-dead-letter-exchange"],
                 "dlrk": q["arguments"].get("x-dead-letter-routing-key", "")} for q in dlqs]
        return {"success": True, "data": _fmt(rows), "error": None, "source": "rabbitmq"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "rabbitmq"}


async def rabbitmq_list_consumers(cluster_id: Optional[str] = None,
                                  instance_name: Optional[str] = None) -> Dict[str, Any]:
    """All active consumers — queue, tag, prefetch count, ack mode."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        consumers = await asyncio.to_thread(_api_get, host, port, user, pwd, "/consumers")
        if not consumers:
            return {"success": True, "data": "No active consumers.", "error": None, "source": "rabbitmq"}
        rows = [{"queue": c.get("queue", {}).get("name", "?"),
                 "vhost": c.get("queue", {}).get("vhost", "/"),
                 "consumer_tag": c.get("consumer_tag", "?")[:40],
                 "prefetch": c.get("prefetch_count", 0),
                 "ack_mode": "auto" if not c.get("ack_required") else "manual",
                 "exclusive": c.get("exclusive", False)} for c in consumers]
        return {"success": True, "data": _fmt(rows), "error": None, "source": "rabbitmq"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "rabbitmq"}


async def rabbitmq_list_connections(cluster_id: Optional[str] = None,
                                    instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Open client connections — peer IP, channels, state, user."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        conns = await asyncio.to_thread(_api_get, host, port, user, pwd, "/connections")
        if not conns:
            return {"success": True, "data": "No active connections.", "error": None, "source": "rabbitmq"}
        rows = [{"name": c.get("name", "?")[:50], "peer_host": c.get("peer_host", "?"),
                 "peer_port": c.get("peer_port", "?"), "state": c.get("state", "?"),
                 "channels": c.get("channels", 0), "user": c.get("user", "?")} for c in conns]
        return {"success": True, "data": _fmt(rows), "error": None, "source": "rabbitmq"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "rabbitmq"}


async def rabbitmq_node_health(cluster_id: Optional[str] = None,
                               instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Node health: memory alarm, disk alarm, FD usage, process count, uptime."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        nodes = await asyncio.to_thread(_api_get, host, port, user, pwd, "/nodes")
        lines = []
        for n in nodes:
            mem_used_mb = n.get("mem_used", 0) // 1024 // 1024
            mem_limit_mb = n.get("mem_limit", 0) // 1024 // 1024
            lines += [f"Node:         {n['name']}",
                      f"  Running:    {n.get('running')}",
                      f"  Mem alarm:  {n.get('mem_alarm')}  ({mem_used_mb}MB / {mem_limit_mb}MB limit)",
                      f"  Disk alarm: {n.get('disk_free_alarm')}",
                      f"  FD used:    {n.get('fd_used', 0)} / {n.get('fd_total', 0)}",
                      f"  Procs:      {n.get('proc_used', 0)} / {n.get('proc_total', 0)}",
                      f"  Uptime:     {n.get('uptime', 0) // 1000}s"]
        return {"success": True, "data": "\n".join(lines), "error": None, "source": "rabbitmq"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "rabbitmq"}


async def rabbitmq_list_exchanges(cluster_id: Optional[str] = None,
                                  instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Named exchanges with type, durability, and publish rate."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        exchanges = await asyncio.to_thread(_api_get, host, port, user, pwd, "/exchanges")
        rows = [{"name": e.get("name", ""), "vhost": e.get("vhost", "/"),
                 "type": e.get("type", "?"), "durable": e.get("durable", False),
                 "publish/s": f"{e.get('message_stats', {}).get('publish_in_details', {}).get('rate', 0):.1f}"}
                for e in exchanges if e.get("name")]
        return {"success": True, "data": _fmt(rows), "error": None, "source": "rabbitmq"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "rabbitmq"}


# WRITE TOOLS

async def rabbitmq_purge_queue(queue_name: str, vhost: str = "/",
                               cluster_id: Optional[str] = None,
                               instance_name: Optional[str] = None,
                               reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Purge all messages from a queue. Queue definition stays; all messages are dropped."""
    inputs = {"queue_name": queue_name, "vhost": vhost, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("rabbitmq_purge_queue", inputs,
                        f"Purge ALL messages from queue '{queue_name}' (vhost='{vhost}')?\n\nMessages are permanently deleted.", "high")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, default_vhost = await asyncio.to_thread(_get_credential, cid, instance_name)
        vh = vhost or default_vhost
        await asyncio.to_thread(_api_delete, host, port, user, pwd,
                                f"/queues/{quote(vh, safe='')}/{quote(queue_name, safe='')}/contents")
        return {"success": True, "data": f"Queue '{queue_name}' purged.", "error": None, "source": "rabbitmq"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "rabbitmq"}


async def rabbitmq_delete_queue(queue_name: str, vhost: str = "/",
                                cluster_id: Optional[str] = None,
                                instance_name: Optional[str] = None,
                                reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Delete a queue entirely including all its messages."""
    inputs = {"queue_name": queue_name, "vhost": vhost, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("rabbitmq_delete_queue", inputs,
                        f"DELETE queue '{queue_name}' (vhost='{vhost}')?\n\nAll messages and the queue definition will be permanently removed.", "high")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, default_vhost = await asyncio.to_thread(_get_credential, cid, instance_name)
        vh = vhost or default_vhost
        await asyncio.to_thread(_api_delete, host, port, user, pwd,
                                f"/queues/{quote(vh, safe='')}/{quote(queue_name, safe='')}")
        return {"success": True, "data": f"Queue '{queue_name}' deleted.", "error": None, "source": "rabbitmq"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "rabbitmq"}


async def rabbitmq_close_connection(connection_name: str,
                                    cluster_id: Optional[str] = None,
                                    instance_name: Optional[str] = None,
                                    reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Force-close a client connection by name. Use rabbitmq_list_connections to get the name."""
    inputs = {"connection_name": connection_name, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("rabbitmq_close_connection", inputs,
                        f"Force-close connection '{connection_name}'?\n\nClient receives a connection error. In-flight messages may be lost.", "high")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        await asyncio.to_thread(_api_delete, host, port, user, pwd,
                                f"/connections/{quote(connection_name, safe='')}",
                                headers={"X-Reason": "Closed by DokOps admin"})
        return {"success": True, "data": f"Connection '{connection_name}' closed.", "error": None, "source": "rabbitmq"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "rabbitmq"}
