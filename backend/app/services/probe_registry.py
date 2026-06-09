from __future__ import annotations
from typing import Optional

# PROBES[service_type][probe_name][install_type] = command template
# Placeholders: {user}, {password}, {port}, {container}
# Use render_command() to substitute — never use str.format() (keyword collision with 'pass')
PROBES: dict = {
    "rabbitmq": {
        "status": {
            "native": "rabbitmqctl status",
            "docker": "docker exec {container} rabbitmqctl status",
        },
        "queues": {
            "native": "rabbitmqctl list_vhosts name | tail -n +4 | grep -v '^$' | while IFS= read -r vh; do echo \"=== vhost: $vh ===\"; rabbitmqctl list_queues -p \"$vh\" name messages consumers memory 2>/dev/null; done",
            "docker": "docker exec {container} bash -c 'rabbitmqctl list_vhosts name | tail -n +4 | grep -v \"^$\" | while IFS= read -r vh; do echo \"=== vhost: $vh ===\"; rabbitmqctl list_queues -p \"$vh\" name messages consumers memory 2>/dev/null; done'",
        },
        "cluster": {
            "native": "rabbitmqctl cluster_status",
            "docker": "docker exec {container} rabbitmqctl cluster_status",
        },
        "overview": {
            "native": "curl -sf -u {user}:{password} http://localhost:{port}/api/overview | python3 -m json.tool",
            "docker": "curl -sf -u {user}:{password} http://localhost:{port}/api/overview | python3 -m json.tool",
        },
        "connections": {
            "native": "curl -sf -u {user}:{password} http://localhost:{port}/api/connections | python3 -m json.tool",
            "docker": "curl -sf -u {user}:{password} http://localhost:{port}/api/connections | python3 -m json.tool",
        },
        "logs": {
            "native": "journalctl -u rabbitmq-server --no-pager -n 150",
            "docker": "docker logs {container} --tail 150",
        },
    },
    "redis": {
        "info": {
            "native": "REDISCLI_AUTH={password} redis-cli --no-auth-warning info",
            "docker": "docker exec -e REDISCLI_AUTH={password} {container} redis-cli --no-auth-warning info",
        },
        "slowlog": {
            "native": "REDISCLI_AUTH={password} redis-cli --no-auth-warning slowlog get 20",
            "docker": "docker exec -e REDISCLI_AUTH={password} {container} redis-cli --no-auth-warning slowlog get 20",
        },
        "memory": {
            "native": "REDISCLI_AUTH={password} redis-cli --no-auth-warning memory doctor",
            "docker": "docker exec -e REDISCLI_AUTH={password} {container} redis-cli --no-auth-warning memory doctor",
        },
        "clients": {
            "native": "REDISCLI_AUTH={password} redis-cli --no-auth-warning client list",
            "docker": "docker exec -e REDISCLI_AUTH={password} {container} redis-cli --no-auth-warning client list",
        },
        "logs": {
            "native": "journalctl -u redis -u redis-server --no-pager -n 150 2>/dev/null | tail -150",
            "docker": "docker logs {container} --tail 150",
        },
    },
    "couchdb": {
        "server_info": {
            "native": "curl -sf -u {user}:{password} http://localhost:{port}/ | python3 -m json.tool",
            "docker": "curl -sf -u {user}:{password} http://localhost:{port}/ | python3 -m json.tool",
        },
        "active_tasks": {
            "native": "curl -sf -u {user}:{password} http://localhost:{port}/_active_tasks | python3 -m json.tool",
            "docker": "curl -sf -u {user}:{password} http://localhost:{port}/_active_tasks | python3 -m json.tool",
        },
        "stats": {
            "native": "curl -sf -u {user}:{password} http://localhost:{port}/_node/_local/_stats | python3 -m json.tool",
            "docker": "curl -sf -u {user}:{password} http://localhost:{port}/_node/_local/_stats | python3 -m json.tool",
        },
        "db_list": {
            "native": "curl -sf -u {user}:{password} http://localhost:{port}/_all_dbs | python3 -m json.tool",
            "docker": "curl -sf -u {user}:{password} http://localhost:{port}/_all_dbs | python3 -m json.tool",
        },
        "logs": {
            "native": "journalctl -u couchdb --no-pager -n 150",
            "docker": "docker logs {container} --tail 150",
        },
    },
    "mongodb": {
        "status": {
            "native": "bash -c 'mongosh --quiet $([ -n \"{user}\" ] && echo \"--username {user} --password {password} --authenticationDatabase admin\") --eval \"db.adminCommand({serverStatus:1})\" 2>&1 | head -60'",
            "docker": "docker exec {container} bash -c 'mongosh --quiet $([ -n \"{user}\" ] && echo \"--username {user} --password {password} --authenticationDatabase admin\") --eval \"db.adminCommand({serverStatus:1})\" 2>&1 | head -60'",
        },
        "logs": {
            "native": "journalctl -u mongod -u mongodb --no-pager -n 150 2>/dev/null | tail -150",
            "docker": "docker logs {container} --tail 150",
        },
    },
    "mysql": {
        "status": {
            "native": "mysqladmin -u {user} --password={password} status",
            "docker": "docker exec {container} mysqladmin -u {user} --password={password} status",
        },
        "processlist": {
            "native": "mysql -u {user} --password={password} -e 'SHOW PROCESSLIST'",
            "docker": "docker exec {container} mysql -u {user} --password={password} -e 'SHOW PROCESSLIST'",
        },
        "logs": {
            "native": "journalctl -u mysql -u mysqld -u mariadb --no-pager -n 150 2>/dev/null | tail -150",
            "docker": "docker logs {container} --tail 150",
        },
    },
    "postgres": {
        "status": {
            "native": "PGPASSWORD={password} pg_isready -U {user}",
            "docker": "docker exec -e PGPASSWORD={password} {container} pg_isready -U {user}",
        },
        "activity": {
            "native": "PGPASSWORD={password} psql -U {user} -c 'SELECT pid, state, left(query,80) FROM pg_stat_activity LIMIT 20'",
            "docker": "docker exec -e PGPASSWORD={password} {container} psql -U {user} -c 'SELECT pid, state, left(query,80) FROM pg_stat_activity LIMIT 20'",
        },
        "logs": {
            "native": "journalctl -u postgresql -u postgres --no-pager -n 150 2>/dev/null | tail -150",
            "docker": "docker logs {container} --tail 150",
        },
    },
    "mssql": {
        "status": {
            "native": "sqlcmd -S localhost,{port} -U {user} -P {password} -Q 'SELECT @@VERSION' -l 10",
            "docker": "docker exec {container} bash -c 'SQLCMD=$(ls /opt/mssql-tools*/bin/sqlcmd 2>/dev/null | head -1); $SQLCMD -S localhost -U {user} -P {password} -Q \"SELECT @@VERSION\" -l 10'",
        },
        "processlist": {
            "native": "sqlcmd -S localhost,{port} -U {user} -P {password} -Q 'SELECT session_id, status, LEFT(text,80) AS query FROM sys.dm_exec_requests CROSS APPLY sys.dm_exec_sql_text(sql_handle)' -l 10",
            "docker": "docker exec {container} bash -c 'SQLCMD=$(ls /opt/mssql-tools*/bin/sqlcmd 2>/dev/null | head -1); $SQLCMD -S localhost -U {user} -P {password} -Q \"SELECT session_id, status, LEFT(text,80) AS query FROM sys.dm_exec_requests CROSS APPLY sys.dm_exec_sql_text(sql_handle)\" -l 10'",
        },
        "databases": {
            "native": "sqlcmd -S localhost,{port} -U {user} -P {password} -Q 'SELECT name, state_desc, recovery_model_desc FROM sys.databases ORDER BY name' -l 10",
            "docker": "docker exec {container} bash -c 'SQLCMD=$(ls /opt/mssql-tools*/bin/sqlcmd 2>/dev/null | head -1); $SQLCMD -S localhost -U {user} -P {password} -Q \"SELECT name, state_desc, recovery_model_desc FROM sys.databases ORDER BY name\" -l 10'",
        },
        "logs": {
            "native": "journalctl -u mssql-server --no-pager -n 150",
            "docker": "docker logs {container} --tail 150",
        },
    },
}

DEFAULT_PORTS: dict[str, int] = {
    "rabbitmq": 15672,
    "redis": 6379,
    "couchdb": 5984,
    "mongodb": 27017,
    "mysql": 3306,
    "postgres": 5432,
    "mssql": 1433,
}

PORT_SERVICE_MAP: dict[int, str] = {
    5672: "rabbitmq",
    15672: "rabbitmq",
    6379: "redis",
    5984: "couchdb",
    27017: "mongodb",
    3306: "mysql",
    5432: "postgres",
    1433: "mssql",
}

UNIT_SERVICE_MAP: dict[str, str] = {
    # Linux systemd unit names
    "rabbitmq-server": "rabbitmq",
    "redis-server": "redis",
    "redis": "redis",
    "couchdb": "couchdb",
    "mongod": "mongodb",
    "mysql": "mysql",
    "mariadb": "mysql",
    "postgresql": "postgres",
    "mssql-server": "mssql",
    # Windows service names
    "rabbitmq": "rabbitmq",
    "mongodb": "mongodb",
    "mysql80": "mysql",
    "mysql57": "mysql",
    "mssqlserver": "mssql",
}

IMAGE_SERVICE_MAP: dict[str, str] = {
    "rabbitmq": "rabbitmq",
    "redis": "redis",
    "couchdb": "couchdb",
    "mongo": "mongodb",
    "mysql": "mysql",
    "mariadb": "mysql",
    "postgres": "postgres",
    "mssql-server": "mssql",
    "mssql": "mssql",
}


def render_command(
    service_type: str,
    probe_name: str,
    install_type: str,
    cred: Optional[dict],
    port: int,
    container: str = "",
) -> str:
    """Substitute placeholders in a probe command template using str.replace (avoids 'pass' keyword)."""
    service_probes = PROBES.get(service_type)
    if not service_probes:
        raise ValueError(f"Unknown service_type: {service_type!r}")
    probe = service_probes.get(probe_name)
    if not probe:
        raise ValueError(f"Unknown probe {probe_name!r} for service {service_type!r}")
    template = probe.get(install_type)
    if not template:
        raise ValueError(f"Unknown install_type: {install_type!r}")

    import shlex
    # Credentials are shell-quoted to prevent injection; port/container are not user-supplied
    replacements = {
        "{user}":      shlex.quote((cred["username"] or "") if cred else ""),
        "{password}":  shlex.quote((cred["password"] or "") if cred else ""),
        "{port}":      str(port),
        "{container}": shlex.quote(container or ""),
    }
    result = template
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    return result
