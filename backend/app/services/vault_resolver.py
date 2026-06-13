from __future__ import annotations
import json
import re
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.service_diag import ServiceCredential
from app.core.encryption import decrypt


class VaultCredentialNotFound(Exception):
    def __init__(self, cluster_id: str, service_type: str) -> None:
        super().__init__(f"No {service_type} credential configured for cluster '{cluster_id}'")


class VaultFieldNotFound(Exception):
    pass


class VaultResolver:
    PATTERN = re.compile(r'\$VAULT:([a-z]+):([a-zA-Z0-9_.]+)')

    async def resolve(self, command: str, cluster_id: str, db: AsyncSession) -> str:
        """Replace all $VAULT:<service>:<field> tokens with decrypted values.
        Never logs resolved values. Raises VaultCredentialNotFound or
        VaultFieldNotFound if a token cannot be resolved.

        Async because DB lookups must not block the event loop. We pre-fetch all
        distinct service credentials referenced in the command, then do the
        synchronous re.sub substitution against the in-memory cache.
        """
        if not self.PATTERN.search(command):
            return command

        # Pre-fetch all distinct service types referenced in the command.
        service_types = {m.group(1) for m in self.PATTERN.finditer(command)}
        cred_cache: dict[str, ServiceCredential] = {}
        for svc in service_types:
            cred = (await db.exec(
                select(ServiceCredential).where(
                    ServiceCredential.scope_type == "cluster",
                    ServiceCredential.scope_id == cluster_id,
                    ServiceCredential.service_type == svc,
                )
            )).first()
            if cred is None:
                raise VaultCredentialNotFound(cluster_id, svc)
            cred_cache[svc] = cred

        def replace(match: re.Match) -> str:
            service_type = match.group(1)
            field = match.group(2)
            return self._extract_field(cred_cache[service_type], field)

        return self.PATTERN.sub(replace, command)

    def _extract_field(self, cred: ServiceCredential, field: str) -> str:
        if field == "username":
            if not cred.username:
                raise VaultFieldNotFound(
                    f"Field 'username' is empty for {cred.service_type} credential. "
                    "Set it in the Vault settings."
                )
            return decrypt(cred.username)
        if field == "password":
            return decrypt(cred.password)
        if field == "host":
            if not cred.host:
                raise VaultFieldNotFound(
                    f"Field 'host' is empty for {cred.service_type} credential. "
                    "Set it in the Vault settings (format: svc.namespace.svc.cluster.local)."
                )
            return cred.host
        if field == "port":
            return str(cred.port) if cred.port is not None else ""
        if field.startswith("extra."):
            key = field[6:]
            try:
                data = json.loads(cred.extra or "{}")
            except json.JSONDecodeError as e:
                raise VaultFieldNotFound(f"Invalid JSON in extra for {cred.service_type}: {e}")
            val = data.get(key)
            if val is None:
                raise VaultFieldNotFound(
                    f"Key '{key}' not found in extra for {cred.service_type}. "
                    f"Available keys: {list(data.keys())}"
                )
            return str(val)
        raise VaultFieldNotFound(
            f"Unknown field '{field}'. Supported: username, password, host, port, extra.<key>"
        )


vault_resolver = VaultResolver()
