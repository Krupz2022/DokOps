import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

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
                ServiceCredential.service_type == "postgres",
            )
            if scope_type == "cluster":
                q = q.where(ServiceCredential.scope_id == cluster_id)
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()
            if cred:
                break

        if cred is None:
            q = select(ServiceCredential).where(ServiceCredential.service_type == "postgres")
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()

        if cred is None:
            label = f" (instance='{instance_name}')" if instance_name else ""
            raise RuntimeError(
                f"No postgres credential{label} found in Vault. "
                "Add one in Settings → Vault with service_type='postgres'."
            )
        host = cred.host or "localhost"
        port = cred.port or 5432
        username = decrypt(cred.username) if cred.username else "postgres"
        password = decrypt(cred.password) if cred.password else ""
        try:
            extra = json.loads(cred.extra or "{}")
        except json.JSONDecodeError:
            extra = {}
        dbname = extra.get("dbname", "postgres")
        return host, port, username, password, dbname


def _connect(host: str, port: int, username: str, password: str, dbname: str):
    import psycopg2
    return psycopg2.connect(
        host=host, port=port, user=username, password=password, dbname=dbname,
        connect_timeout=10, options="-c statement_timeout=30000",
    )


def _query(host: str, port: int, username: str, password: str, dbname: str,
           sql: str, params=None) -> List[Dict[str, Any]]:
    import psycopg2.extras
    conn = _connect(host, port, username, password, dbname)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
        conn.rollback()
        return rows
    finally:
        conn.close()


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
    return {"success": True, "data": None, "error": None, "source": "postgres",
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

async def postgres_active_connections(cluster_id: Optional[str] = None,
                                      instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Active connections grouped by state and database."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT datname, usename, state, wait_event_type, wait_event,
                   count(*) AS count,
                   max(EXTRACT(EPOCH FROM (now() - query_start)))::int AS max_age_s
            FROM pg_stat_activity
            WHERE pid <> pg_backend_pid()
            GROUP BY datname, usename, state, wait_event_type, wait_event
            ORDER BY count DESC
            LIMIT 50
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_long_running_queries(min_seconds: int = 30,
                                        cluster_id: Optional[str] = None,
                                        instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Queries running longer than min_seconds: PID, duration, state, query snippet."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT pid, usename, datname, state,
                   EXTRACT(EPOCH FROM (now() - query_start))::int AS duration_s,
                   left(query, 200) AS query_snippet
            FROM pg_stat_activity
            WHERE state NOT IN ('idle', 'idle in transaction (aborted)')
              AND query_start IS NOT NULL
              AND EXTRACT(EPOCH FROM (now() - query_start)) > %s
              AND pid <> pg_backend_pid()
            ORDER BY duration_s DESC
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql, (min_seconds,))
        if not rows:
            return {"success": True, "data": f"No queries running > {min_seconds}s.", "error": None, "source": "postgres"}
        return {"success": True, "data": _fmt(rows), "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_lock_waits(cluster_id: Optional[str] = None,
                              instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Queries blocked on locks: blocker PID, waiter PID, lock type, relation."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT bl.pid AS blocked_pid,
                   ba.usename AS blocked_user,
                   kl.pid AS blocking_pid,
                   ka.usename AS blocking_user,
                   bl.relation::regclass AS relation,
                   bl.locktype,
                   left(ba.query, 100) AS blocked_query
            FROM pg_catalog.pg_locks bl
            JOIN pg_catalog.pg_stat_activity ba ON ba.pid = bl.pid
            JOIN pg_catalog.pg_locks kl ON kl.transactionid = bl.transactionid AND kl.pid <> bl.pid
            JOIN pg_catalog.pg_stat_activity ka ON ka.pid = kl.pid
            WHERE NOT bl.granted
            LIMIT 20
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        if not rows:
            return {"success": True, "data": "No lock waits detected.", "error": None, "source": "postgres"}
        return {"success": True, "data": _fmt(rows), "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_table_sizes(cluster_id: Optional[str] = None,
                               instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Top 20 tables by total size (table + indexes + toast)."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT schemaname, tablename,
                   pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
                   pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
                   pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)
                                  - pg_relation_size(schemaname||'.'||tablename)) AS index_size,
                   n_live_tup AS live_rows,
                   n_dead_tup AS dead_rows
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
            LIMIT 20
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_index_usage(cluster_id: Optional[str] = None,
                               instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Index usage stats: scans, tuple reads, size. Low-scan indexes may be candidates for removal."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT schemaname, tablename, indexname,
                   pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
                   idx_scan, idx_tup_read, idx_tup_fetch
            FROM pg_stat_user_indexes
            ORDER BY idx_scan ASC, pg_relation_size(indexrelid) DESC
            LIMIT 30
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_bloat_estimate(cluster_id: Optional[str] = None,
                                  instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Dead tuple bloat estimate: tables with highest dead/live ratio (vacuum candidates)."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT schemaname, tablename, n_live_tup, n_dead_tup,
                   CASE WHEN n_live_tup > 0
                        THEN round(100.0 * n_dead_tup / (n_live_tup + n_dead_tup), 1)
                        ELSE 0 END AS dead_pct,
                   last_autovacuum, last_autoanalyze
            FROM pg_stat_user_tables
            WHERE n_dead_tup > 1000
            ORDER BY dead_pct DESC
            LIMIT 25
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        if not rows:
            return {"success": True, "data": "No significant bloat detected.", "error": None, "source": "postgres"}
        return {"success": True, "data": _fmt(rows), "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_replication_lag(cluster_id: Optional[str] = None,
                                   instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Streaming replication lag per replica: state, sent/write/flush/replay lag."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
                   pg_size_pretty(pg_wal_lsn_diff(sent_lsn, replay_lsn)) AS replay_lag,
                   sync_state
            FROM pg_stat_replication
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        if not rows:
            return {"success": True, "data": "No replicas connected (or this is a replica).", "error": None, "source": "postgres"}
        return {"success": True, "data": _fmt(rows), "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_cache_hit_ratio(cluster_id: Optional[str] = None,
                                   instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Buffer cache hit ratio per table. Low ratio (<95%) suggests too much disk I/O."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT schemaname, tablename,
                   heap_blks_read, heap_blks_hit,
                   CASE WHEN (heap_blks_read + heap_blks_hit) > 0
                        THEN round(100.0 * heap_blks_hit / (heap_blks_read + heap_blks_hit), 2)
                        ELSE NULL END AS cache_hit_pct
            FROM pg_statio_user_tables
            WHERE (heap_blks_read + heap_blks_hit) > 0
            ORDER BY cache_hit_pct ASC NULLS LAST
            LIMIT 30
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_query(database: str, query: str,
                         cluster_id: Optional[str] = None,
                         instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Run a custom read-only SQL query. SELECT only — write statements are rejected."""
    if query.strip().upper().split()[0] not in ("SELECT", "EXPLAIN", "WITH", "SHOW"):
        return {"success": False, "data": None, "error": "Only SELECT/EXPLAIN/WITH/SHOW queries are allowed.", "source": "postgres"}
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(_query, host, port, user, pwd, database, query)
        return {"success": True, "data": _fmt(rows[:100]), "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_database_stats(cluster_id: Optional[str] = None,
                                  instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Per-database stats: connections, transactions, cache hit, deadlocks, temp files."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT datname, numbackends, xact_commit, xact_rollback,
                   blks_read, blks_hit,
                   CASE WHEN (blks_read + blks_hit) > 0
                        THEN round(100.0 * blks_hit / (blks_read + blks_hit), 1)
                        ELSE NULL END AS cache_hit_pct,
                   deadlocks, temp_files, temp_bytes
            FROM pg_stat_database
            WHERE datname NOT IN ('template0', 'template1')
            ORDER BY numbackends DESC
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


# WRITE TOOLS

async def postgres_kill_query(pid: int,
                              cluster_id: Optional[str] = None,
                              instance_name: Optional[str] = None,
                              reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Cancel a query (pg_cancel_backend). The connection stays open; only the query is cancelled."""
    inputs = {"pid": pid, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("postgres_kill_query", inputs,
                        f"Cancel query for PID {pid} (pg_cancel_backend)?\n\nThe query is cancelled but the connection remains.", "medium")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname,
                                       "SELECT pg_cancel_backend(%s) AS result", (pid,))
        return {"success": True, "data": f"pg_cancel_backend({pid}) = {rows[0]['result'] if rows else 'false'}", "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_terminate_connection(pid: int,
                                        cluster_id: Optional[str] = None,
                                        instance_name: Optional[str] = None,
                                        reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Terminate a connection (pg_terminate_backend). Both query and connection are killed."""
    inputs = {"pid": pid, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("postgres_terminate_connection", inputs,
                        f"Terminate connection PID {pid} (pg_terminate_backend)?\n\nThe client connection will be forcibly closed.", "high")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname,
                                       "SELECT pg_terminate_backend(%s) AS result", (pid,))
        return {"success": True, "data": f"pg_terminate_backend({pid}) = {rows[0]['result'] if rows else 'false'}", "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}


async def postgres_run_vacuum(table: str, analyze: bool = True,
                              cluster_id: Optional[str] = None,
                              instance_name: Optional[str] = None,
                              reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Run VACUUM (ANALYZE) on a table to reclaim dead tuples."""
    inputs = {"table": table, "analyze": analyze, "cluster_id": cluster_id, "instance_name": instance_name}
    cmd = f"VACUUM {'ANALYZE ' if analyze else ''}{table}"
    if not confirmed:
        return _pending("postgres_run_vacuum", inputs,
                        f"Run `{cmd}`?\n\nVACUUM reclaims dead tuple space. ANALYZE updates query planner stats. Low risk but locks table briefly.", "medium")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        def _run():
            conn = _connect(host, port, user, pwd, dbname)
            old_iso = conn.isolation_level
            conn.set_isolation_level(0)  # VACUUM must run outside a transaction
            try:
                with conn.cursor() as cur:
                    cur.execute(cmd)
            finally:
                conn.set_isolation_level(old_iso)
                conn.close()
        await asyncio.to_thread(_run)
        return {"success": True, "data": f"`{cmd}` completed.", "error": None, "source": "postgres"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "postgres"}
