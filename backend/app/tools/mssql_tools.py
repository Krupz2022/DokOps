import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def _get_credential(cluster_id: Optional[str] = None, instance_name: Optional[str] = None):
    """
    Look up the mssql ServiceCredential from the DB.
    Resolution order: cluster scope → global scope.
    Returns (host, port, username, password, extra_dict).
    """
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
                ServiceCredential.service_type == "mssql",
            )
            if scope_type == "cluster":
                q = q.where(ServiceCredential.scope_id == cluster_id)
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()
            if cred:
                break

        if cred is None:
            q = select(ServiceCredential).where(ServiceCredential.service_type == "mssql")
            if instance_name:
                q = q.where(ServiceCredential.instance_name == instance_name)
            cred = db.exec(q).first()

        if cred is None:
            label = f" (instance='{instance_name}')" if instance_name else ""
            raise RuntimeError(
                f"No mssql credential{label} found in Vault. "
                "Add one in Settings → Vault with service_type='mssql'."
            )

        host = cred.host or ""
        port = cred.port or 1433
        username = decrypt(cred.username) if cred.username else ""
        password = decrypt(cred.password) if cred.password else ""
        try:
            extra = json.loads(cred.extra or "{}")
        except json.JSONDecodeError:
            extra = {}

        return host, port, username, password, extra


def _connect(host: str, port: int, username: str, password: str, database: str = "master"):
    """Open a synchronous pymssql connection."""
    import pymssql  # type: ignore
    return pymssql.connect(
        server=host,
        port=str(port),
        user=username,
        password=password,
        database=database,
        timeout=30,
        login_timeout=10,
        tds_version="7.4",
    )


def _run_query(host: str, port: int, username: str, password: str,
               query: str, database: str = "master",
               read_uncommitted: bool = False) -> List[Dict[str, Any]]:
    """Execute a query and return rows as list of dicts."""
    conn = _connect(host, port, username, password, database)
    try:
        with conn.cursor(as_dict=True) as cur:
            if read_uncommitted:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
            cur.execute(query)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


def _run_execute(host: str, port: int, username: str, password: str,
                 query: str, database: str = "master") -> int:
    """Execute a DML/DDL statement and return rowcount."""
    conn = _connect(host, port, username, password, database)
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


def _fmt(rows: List[Dict[str, Any]]) -> str:
    """Format rows as a readable text table."""
    if not rows:
        return "No rows returned."
    keys = list(rows[0].keys())
    col_widths = {k: max(len(str(k)), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    sep = "  ".join("-" * col_widths[k] for k in keys)
    header = "  ".join(str(k).ljust(col_widths[k]) for k in keys)
    lines = [header, sep]
    for row in rows:
        lines.append("  ".join(str(row.get(k, "")).ljust(col_widths[k]) for k in keys))
    lines.append(f"\n({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return "\n".join(lines)


def _pending_confirmation(tool_name: str, inputs: dict, message: str, risk_level: str) -> Dict[str, Any]:
    return {
        "success": True,
        "data": None,
        "error": None,
        "source": "mssql",
        "requires_confirmation": True,
        "pending_operation": {
            "tool_name": tool_name,
            "tool_inputs": inputs,
            "confirmation_message": message,
            "risk_level": risk_level,
        },
    }


def _active_cluster() -> Optional[str]:
    try:
        from app.services.k8s_service import active_cluster_ctx
        return active_cluster_ctx.get()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# READ TOOLS
# ---------------------------------------------------------------------------

async def mssql_list_databases(cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """List all user databases with state, recovery model, and size."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(
            _run_query, host, port, user, pwd,
            "SELECT name, state_desc, recovery_model_desc, compatibility_level, create_date "
            "FROM sys.databases WHERE database_id > 4 ORDER BY name;",
        )
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_connections(cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Active sessions grouped by status, host, and login — CPU and memory per session."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(
            _run_query, host, port, user, pwd,
            "SELECT s.session_id, s.login_name, s.host_name, s.program_name, s.status, "
            "DB_NAME(s.database_id) AS db_name, s.cpu_time, s.memory_usage*8 AS memory_kb, "
            "s.logical_reads, s.last_request_start_time "
            "FROM sys.dm_exec_sessions s WHERE s.is_user_process = 1 ORDER BY s.cpu_time DESC;",
        )
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_slow_queries(cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Queries running longer than 5 seconds — session, wait type, elapsed time, query text."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(
            _run_query, host, port, user, pwd,
            "SELECT r.session_id, DB_NAME(r.database_id) AS db_name, r.status, r.wait_type, "
            "ROUND(r.wait_time/1000.0,1) AS wait_sec, ROUND(r.total_elapsed_time/1000.0,1) AS elapsed_sec, "
            "ROUND(r.cpu_time/1000.0,1) AS cpu_sec, r.logical_reads, LEFT(t.text,200) AS query_text "
            "FROM sys.dm_exec_requests r CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t "
            "WHERE r.total_elapsed_time > 5000 AND r.session_id != @@SPID ORDER BY r.total_elapsed_time DESC;",
        )
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_blocking_chains(cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Full blocking tree — which session blocks which, with both queries shown."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(
            _run_query, host, port, user, pwd,
            "SELECT blocked.session_id AS blocked_spid, blocked.login_name AS blocked_login, "
            "blocked.host_name AS blocked_host, blocker.session_id AS blocking_spid, "
            "blocker.login_name AS blocking_login, ROUND(r.wait_time/1000.0,1) AS wait_sec, "
            "LEFT(bt.text,120) AS blocking_query, LEFT(wt.text,120) AS blocked_query "
            "FROM sys.dm_exec_sessions blocked "
            "JOIN sys.dm_exec_requests r ON blocked.session_id = r.session_id "
            "JOIN sys.dm_exec_sessions blocker ON r.blocking_session_id = blocker.session_id "
            "CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) wt "
            "OUTER APPLY sys.dm_exec_sql_text(blocker.most_recent_sql_handle) bt "
            "WHERE r.blocking_session_id > 0 ORDER BY r.wait_time DESC;",
        )
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_wait_stats(cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Top 20 server wait types by total wait time — idle waits excluded."""
    cid = cluster_id or _active_cluster()
    _benign = (
        "'SLEEP_TASK','BROKER_TO_FLUSH','BROKER_TASK_STOP','CLR_AUTO_EVENT',"
        "'DISPATCHER_QUEUE_SEMAPHORE','FT_IFTS_SCHEDULER_IDLE_WAIT','HADR_WORK_QUEUE',"
        "'LAZYWRITER_SLEEP','LOGMGR_QUEUE','ONDEMAND_TASK_QUEUE','REQUEST_FOR_DEADLOCK_SEARCH',"
        "'RESOURCE_QUEUE','SERVER_IDLE_CHECK','SLEEP_DBSTARTUP','SLEEP_DCOMSTARTUP',"
        "'SLEEP_MASTERDBREADY','SLEEP_MASTERMDREADY','SLEEP_MASTERUPGRADED','SLEEP_MSDBSTARTUP',"
        "'SLEEP_SYSTEMTASK','SLEEP_TEMPDBSTARTUP','SNI_HTTP_ACCEPT','SP_SERVER_DIAGNOSTICS_SLEEP',"
        "'SQLTRACE_BUFFER_FLUSH','WAITFOR','XE_DISPATCHER_WAIT','XE_TIMER_EVENT'"
    )
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(
            _run_query, host, port, user, pwd,
            f"SELECT TOP 20 wait_type, waiting_tasks_count, "
            f"ROUND(wait_time_ms/1000.0,1) AS total_wait_sec, "
            f"ROUND(max_wait_time_ms/1000.0,1) AS max_wait_sec, "
            f"ROUND((wait_time_ms-signal_wait_time_ms)/1000.0,1) AS resource_wait_sec "
            f"FROM sys.dm_os_wait_stats "
            f"WHERE wait_type NOT IN ({_benign}) AND waiting_tasks_count > 0 "
            f"ORDER BY wait_time_ms DESC;",
        )
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_database_sizes(cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """All databases with data file size, log file size, and recovery model."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(
            _run_query, host, port, user, pwd,
            "SELECT d.name, d.recovery_model_desc, d.state_desc, "
            "ROUND(SUM(CASE WHEN mf.type=0 THEN mf.size*8/1024.0 ELSE 0 END),1) AS data_mb, "
            "ROUND(SUM(CASE WHEN mf.type=1 THEN mf.size*8/1024.0 ELSE 0 END),1) AS log_mb "
            "FROM sys.databases d JOIN sys.master_files mf ON d.database_id=mf.database_id "
            "GROUP BY d.name, d.recovery_model_desc, d.state_desc ORDER BY data_mb DESC;",
        )
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_index_fragmentation(cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Indexes with fragmentation above 10% — shows rebuild vs reorganize recommendation."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(
            _run_query, host, port, user, pwd,
            "SELECT DB_NAME(ips.database_id) AS db_name, "
            "OBJECT_NAME(ips.object_id, ips.database_id) AS table_name, "
            "i.name AS index_name, "
            "ROUND(ips.avg_fragmentation_in_percent,1) AS frag_pct, "
            "ips.page_count, "
            "CASE WHEN ips.avg_fragmentation_in_percent > 30 THEN 'REBUILD' "
            "     WHEN ips.avg_fragmentation_in_percent > 10 THEN 'REORGANIZE' END AS action "
            "FROM sys.dm_db_index_physical_stats(NULL,NULL,NULL,NULL,'LIMITED') ips "
            "JOIN sys.indexes i ON ips.object_id=i.object_id AND ips.index_id=i.index_id "
            "WHERE ips.avg_fragmentation_in_percent > 10 AND ips.page_count > 500 "
            "ORDER BY ips.avg_fragmentation_in_percent DESC;",
        )
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_missing_indexes(cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Top 20 missing indexes by optimizer impact score with suggested CREATE INDEX statement."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(
            _run_query, host, port, user, pwd,
            "SELECT TOP 20 "
            "ROUND(migs.avg_total_user_cost*migs.avg_user_impact*(migs.user_seeks+migs.user_scans),0) AS impact, "
            "migs.user_seeks, migs.user_scans, mid.statement AS table_name, "
            "mid.equality_columns, mid.inequality_columns, mid.included_columns "
            "FROM sys.dm_db_missing_index_groups mig "
            "JOIN sys.dm_db_missing_index_group_stats migs ON mig.index_group_handle=migs.group_handle "
            "JOIN sys.dm_db_missing_index_details mid ON mig.index_handle=mid.index_handle "
            "ORDER BY impact DESC;",
        )
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_top_queries_by_cpu(cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Top 20 cached query plans by total CPU — execution count, avg CPU, avg duration."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(
            _run_query, host, port, user, pwd,
            "SELECT TOP 20 qs.total_worker_time/1000 AS total_cpu_ms, qs.execution_count, "
            "qs.total_worker_time/qs.execution_count/1000 AS avg_cpu_ms, "
            "qs.total_elapsed_time/qs.execution_count/1000 AS avg_elapsed_ms, "
            "qs.total_logical_reads/qs.execution_count AS avg_logical_reads, "
            "LEFT(qt.text,200) AS query_text "
            "FROM sys.dm_exec_query_stats qs "
            "CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) qt "
            "ORDER BY qs.total_worker_time DESC;",
        )
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_ag_status(cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Always On AG replica health — sync state, redo queue, log send queue per replica."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(
            _run_query, host, port, user, pwd,
            "SELECT ag.name AS ag_name, ar.replica_server_name, drs.database_name, "
            "drs.synchronization_state_desc, drs.synchronization_health_desc, "
            "drs.redo_queue_size, drs.log_send_queue_size, drs.last_redone_time "
            "FROM sys.dm_hadr_database_replica_states drs "
            "JOIN sys.availability_replicas ar ON drs.replica_id=ar.replica_id "
            "JOIN sys.availability_groups ag ON ar.group_id=ag.group_id "
            "ORDER BY ag.name, ar.replica_server_name;",
        )
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_query(database_name: str, query: str,
                      cluster_id: Optional[str] = None, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Run a read-only SELECT query against a specific database. Returns results as formatted table."""
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rows = await asyncio.to_thread(_run_query, host, port, user, pwd, query, database_name, True)
        return {"success": True, "data": _fmt(rows), "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


# ---------------------------------------------------------------------------
# WRITE TOOLS (require God Mode confirmation)
# ---------------------------------------------------------------------------

async def mssql_execute(database_name: str, query: str,
                        cluster_id: Optional[str] = None,
                        instance_name: Optional[str] = None,
                        reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Execute any T-SQL statement (INSERT/UPDATE/DELETE/DDL) against a specific database."""
    inputs = {"database_name": database_name, "query": query, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending_confirmation(
            "mssql_execute", inputs,
            f"The AI wants to execute the following T-SQL on database '{database_name}':\n\n"
            f"{query}\n\n"
            "This may modify or delete data. Approve to proceed.",
            "high",
        )
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        rowcount = await asyncio.to_thread(_run_execute, host, port, user, pwd, query, database_name)
        return {"success": True, "data": f"Query executed. Rows affected: {rowcount}", "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_kill_spid(spid: int, cluster_id: Optional[str] = None,
                          instance_name: Optional[str] = None,
                          reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Terminate a SQL Server session by SPID. The client receives a connection error."""
    inputs = {"spid": spid, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending_confirmation(
            "mssql_kill_spid", inputs,
            f"The AI wants to terminate SQL Server session SPID {spid}.\n\n"
            "The client will receive a connection error immediately. Any open transaction will be rolled back.",
            "high",
        )
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        await asyncio.to_thread(_run_execute, host, port, user, pwd, f"KILL {int(spid)};")
        return {"success": True, "data": f"Session {spid} terminated.", "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_rebuild_index(database_name: str, schema_name: str, table_name: str,
                              index_name: str, cluster_id: Optional[str] = None,
                              instance_name: Optional[str] = None,
                              reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Rebuild a specific index on a table (ONLINE where supported)."""
    inputs = {"database_name": database_name, "schema_name": schema_name,
              "table_name": table_name, "index_name": index_name, "cluster_id": cluster_id,
              "instance_name": instance_name}
    if not confirmed:
        return _pending_confirmation(
            "mssql_rebuild_index", inputs,
            f"The AI wants to rebuild index '{index_name}' on '{schema_name}.{table_name}' "
            f"in database '{database_name}'.\n\nThis acquires locks for the duration of the rebuild.",
            "medium",
        )
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = (
            f"ALTER INDEX [{index_name}] ON [{schema_name}].[{table_name}] "
            f"REBUILD WITH (ONLINE = ON);"
        )
        await asyncio.to_thread(_run_execute, host, port, user, pwd, sql, database_name)
        return {"success": True, "data": f"Index '{index_name}' rebuilt.", "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}


async def mssql_update_statistics(database_name: str, schema_name: str, table_name: str,
                                  cluster_id: Optional[str] = None,
                                  instance_name: Optional[str] = None,
                                  reason: str = "", confirmed: bool = False) -> Dict[str, Any]:
    """Update statistics with FULLSCAN on a table — forces query plan recompilation."""
    inputs = {"database_name": database_name, "schema_name": schema_name,
              "table_name": table_name, "cluster_id": cluster_id, "instance_name": instance_name}
    if not confirmed:
        return _pending_confirmation(
            "mssql_update_statistics", inputs,
            f"The AI wants to run UPDATE STATISTICS WITH FULLSCAN on "
            f"'{schema_name}.{table_name}' in database '{database_name}'.\n\n"
            "This reads the entire table and may impact performance briefly.",
            "low",
        )
    cid = cluster_id or _active_cluster()
    try:
        host, port, user, pwd, _ = await asyncio.to_thread(_get_credential, cid, instance_name)
        sql = f"UPDATE STATISTICS [{schema_name}].[{table_name}] WITH FULLSCAN;"
        await asyncio.to_thread(_run_execute, host, port, user, pwd, sql, database_name)
        return {"success": True, "data": f"Statistics updated for '{schema_name}.{table_name}'.", "error": None, "source": "mssql"}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e), "source": "mssql"}
