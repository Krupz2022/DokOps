from __future__ import annotations
import json
import re
from sqlmodel import Session, select
from app.models.service_diag import ServiceCredential
from app.core.encryption import decrypt


class VaultCredentialNotFound(Exception):
    def __init__(self, cluster_id: str, service_type: str) -> None:
        super().__init__(f"No {service_type} credential configured for cluster '{cluster_id}'")


class VaultFieldNotFound(Exception):
    pass


class VaultResolver:
    PATTERN = re.compile(r'\$VAULT:([a-z]+):([a-zA-Z0-9_.]+)')

    def resolve(self, command: str, cluster_id: str, db: Session) -> str:
        """Replace all $VAULT:<service>:<field> tokens with decrypted values.
        Never logs resolved values. Raises VaultCredentialNotFound or
        VaultFieldNotFound if a token cannot be resolved."""
        if not self.PATTERN.search(command):
            return command

        def replace(match: re.Match) -> str:
            service_type = match.group(1)
            field = match.group(2)
            cred = db.exec(
                select(ServiceCredential).where(
                    ServiceCredential.scope_type == "cluster",
                    ServiceCredential.scope_id == cluster_id,
                    ServiceCredential.service_type == service_type,
                )
            ).first()
            if cred is None:
                raise VaultCredentialNotFound(cluster_id, service_type)
            return self._extract_field(cred, field)

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
