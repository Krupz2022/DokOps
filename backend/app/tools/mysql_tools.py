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
                ServiceCredential.service_type == "mysql",
            )
            if scope_type == "cluster":
                q = q.where(ServiceCredential.scope_id == cluster_id)
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()
            if cred:
                break

        if cred is None:
            q = select(ServiceCredential).where(ServiceCredential.service_type == "mysql")
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()

        if cred is None:
            label = f" (instance='{instance_name}')" if instance_name else ""
            raise RuntimeError(
                f"No mysql credential{label} found in Vault. "
                "Add one in Settings → Vault with service_type='mysql'."
            )
        host = cred.host or "localhost"
        port = cred.port or 3306
        username = decrypt(cred.username) if cred.username else "root"
        password = decrypt(cred.password) if cred.password else ""
        try:
            extra = json.loads(cred.extra or "{}")
        except json.JSONDecodeError:
            extra = {}
        dbname = extra.get("dbname", "mysql")
        return host, port, username, password, dbname


def _connect(host: str, port: int, username: str, password: str, dbname: str):
    import pymysql
    import pymysql.cursors
    return pymysql.connect(
        host=host, port=port, user=username, password=password, db=dbname,
        connect_timeout=10, read_timeout=30, write_timeout=30,
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
    )


def _query(host: str, port: int, username: str, password: str, dbname: str,
           sql: str, params=None) -> List[Dict[str, Any]]:
    conn = _connect(host, port, username, password, dbname)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return list(cur.fetchall())
    finally:
        conn.close()


def _execute(host: str, port: int, username: str, password: str, dbname: str,
             sql: str, params=None) -> int:
    conn = _connect(host, port, username, password, dbname)
    try:
        with conn.cursor() as cur:
            affected = cur.execute(sql, params or ())
        conn.commit()
        return affected or 0
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
    return {"success": True, "data": None, "error": None, "source": "mysql",
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

async def mysql_processlist(cluster_id: Optional[str] = None,
                            instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Active queries and connections: ID, user, db, command, time, state, query snippet."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname,
                                       "SELECT ID, USER, HOST, DB, COMMAND, TIME, STATE, LEFT(INFO, 150) AS Query "
                                       "FROM information_schema.PROCESSLIST ORDER BY TIME DESC LIMIT 50")
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}


async def mysql_global_status(cluster_id: Optional[str] = None,
                              instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Key global status variables: connections, queries, uptime, QPS, InnoDB buffer usage."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        interesting = {
            "Uptime", "Questions", "Queries", "Connections", "Threads_connected",
            "Threads_running", "Slow_queries", "Aborted_connects", "Aborted_clients",
            "Innodb_buffer_pool_read_requests", "Innodb_buffer_pool_reads",
            "Innodb_row_lock_current_waits", "Innodb_row_lock_time_avg",
        }
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, "SHOW GLOBAL STATUS")
        filtered = [r for r in rows if r.get("Variable_name") in interesting]
        lines = [f"{r['Variable_name']}: {r['Value']}" for r in filtered]
        return {"success": True, "data": "\n".join(lines), "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}


async def mysql_innodb_status(cluster_id: Optional[str] = None,
                              instance_name: Optional[str] = None) -> Dict[str, Any]:
    """InnoDB engine status — transactions, lock waits, deadlocks, buffer pool usage."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname,
                                       "SHOW ENGINE INNODB STATUS")
        status = rows[0].get("Status", "") if rows else ""
        sections = []
        for section in ["TRANSACTIONS", "BUFFER POOL AND MEMORY", "ROW OPERATIONS", "DEADLOCKS"]:
            start = status.find(section)
            if start >= 0:
                end = min(start + 800, len(status))
                sections.append(status[start:end])
        return {"success": True, "data": "\n\n---\n\n".join(sections) or status[:2000], "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}


async def mysql_table_sizes(cluster_id: Optional[str] = None,
                            instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Top 20 tables by total size (data + index)."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT TABLE_SCHEMA, TABLE_NAME,
                   ROUND(DATA_LENGTH / 1024 / 1024, 2) AS data_mb,
                   ROUND(INDEX_LENGTH / 1024 / 1024, 2) AS index_mb,
                   ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) AS total_mb,
                   TABLE_ROWS
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA NOT IN ('information_schema', 'performance_schema', 'mysql', 'sys')
            ORDER BY (DATA_LENGTH + INDEX_LENGTH) DESC
            LIMIT 20
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}


async def mysql_lock_waits(cluster_id: Optional[str] = None,
                           instance_name: Optional[str] = None) -> Dict[str, Any]:
    """InnoDB lock waits: blocking thread, waiting thread, table, lock type."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        try:
            sql = """
                SELECT r.trx_id AS waiting_trx,
                       r.trx_mysql_thread_id AS waiting_thread,
                       r.trx_query AS waiting_query,
                       b.trx_id AS blocking_trx,
                       b.trx_mysql_thread_id AS blocking_thread,
                       b.trx_query AS blocking_query
                FROM information_schema.innodb_lock_waits w
                JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
                JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id
                LIMIT 20
            """
            rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        except Exception:
            sql = """
                SELECT r.trx_id AS waiting_trx,
                       r.trx_mysql_thread_id AS waiting_thread,
                       r.trx_query AS waiting_query,
                       b.trx_id AS blocking_trx,
                       b.trx_mysql_thread_id AS blocking_thread,
                       b.trx_query AS blocking_query
                FROM performance_schema.data_lock_waits w
                JOIN information_schema.innodb_trx b ON b.trx_id = CAST(w.blocking_engine_transaction_id AS CHAR)
                JOIN information_schema.innodb_trx r ON r.trx_id = CAST(w.requesting_engine_transaction_id AS CHAR)
                LIMIT 20
            """
            rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        if not rows:
            return {"success": True, "data": "No lock waits detected.", "error": None, "source": "mysql"}
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}


async def mysql_slow_queries(cluster_id: Optional[str] = None,
                             instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Top queries from performance_schema by total execution time."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = """
            SELECT LEFT(DIGEST_TEXT, 150) AS query,
                   COUNT_STAR AS exec_count,
                   ROUND(SUM_TIMER_WAIT / 1e12, 3) AS total_s,
                   ROUND(AVG_TIMER_WAIT / 1e12, 3) AS avg_s,
                   ROUND(MAX_TIMER_WAIT / 1e12, 3) AS max_s
            FROM performance_schema.events_statements_summary_by_digest
            WHERE SCHEMA_NAME NOT IN ('information_schema', 'performance_schema', 'mysql', 'sys')
            ORDER BY SUM_TIMER_WAIT DESC
            LIMIT 20
        """
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, sql)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}


async def mysql_replication_status(cluster_id: Optional[str] = None,
                                   instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Replication status: IO/SQL thread state, lag, errors."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        try:
            rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, "SHOW REPLICA STATUS")
        except Exception:
            rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname, "SHOW SLAVE STATUS")
        if not rows:
            return {"success": True, "data": "Not a replica (or replication not configured).", "error": None, "source": "mysql"}
        r = rows[0]
        lines = [f"IO_Running:          {r.get('Slave_IO_Running') or r.get('Replica_IO_Running')}",
                 f"SQL_Running:         {r.get('Slave_SQL_Running') or r.get('Replica_SQL_Running')}",
                 f"Seconds_Behind:      {r.get('Seconds_Behind_Master') or r.get('Seconds_Behind_Source')}",
                 f"Last_IO_Error:       {r.get('Last_IO_Error', '')}",
                 f"Last_SQL_Error:      {r.get('Last_SQL_Error', '')}",
                 f"Master_Host:         {r.get('Master_Host') or r.get('Source_Host')}",
                 f"Relay_Log_Pos:       {r.get('Relay_Log_Pos')}"]
        return {"success": True, "data": "\n".join(lines), "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}


async def mysql_user_grants(cluster_id: Optional[str] = None,
                            instance_name: Optional[str] = None) -> Dict[str, Any]:
    """All database users and their host/authentication info."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(_query, host, port, user, pwd, dbname,
                                       "SELECT User, Host, account_locked, password_expired "
                                       "FROM mysql.user ORDER BY User")
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}


# WRITE TOOLS

async def mysql_execute(query: str, database: str = "mysql",
                        cluster_id: Optional[str] = None,
                        instance_name: Optional[str] = None,
                        reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Run a write SQL statement (INSERT/UPDATE/DELETE/ALTER/etc.)."""
    inputs = {"query": query, "database": database, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("mysql_execute", inputs,
                        f"Execute SQL on database '{database}'?\n\n```sql\n{query[:400]}\n```\n\nReason: {reason or 'none provided'}", "high")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        affected = await asyncio.to_thread(_execute, host, port, user, pwd, database, query)
        return {"success": True, "data": f"Query executed. Rows affected: {affected}.", "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}


async def mysql_kill_connection(connection_id: int,
                                cluster_id: Optional[str] = None,
                                instance_name: Optional[str] = None,
                                reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Kill a MySQL connection by ID. Use mysql_processlist to find the ID."""
    inputs = {"connection_id": connection_id, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("mysql_kill_connection", inputs,
                        f"Kill MySQL connection ID {connection_id}?\n\nThe client will receive an error and its transaction will roll back.", "high")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, dbname = await asyncio.to_thread(_get_credential, cid, instance_name)
        await asyncio.to_thread(_execute, host, port, user, pwd, dbname, f"KILL {connection_id}")
        return {"success": True, "data": f"Connection {connection_id} killed.", "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}


async def mysql_optimize_table(table: str, database: str = "mysql",
                               cluster_id: Optional[str] = None,
                               instance_name: Optional[str] = None,
                               reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Run OPTIMIZE TABLE to defragment and reclaim space for InnoDB/MyISAM tables."""
    inputs = {"table": table, "database": database, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending("mysql_optimize_table", inputs,
                        f"OPTIMIZE TABLE `{database}`.`{table}`?\n\nFor InnoDB this rebuilds the table in-place and may take time on large tables.", "medium")
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(_query, host, port, user, pwd, database,
                                       f"OPTIMIZE TABLE `{table}`")
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mysql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mysql"}
