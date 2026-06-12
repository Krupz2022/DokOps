import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.core.encryption import decrypt, encrypt
from app.core.ssrf import validate_cluster_url
from app.models.cluster import CloudCredential, ClusterConnection
from app.services.k8s_service import k8s_service

logger = logging.getLogger(__name__)


@dataclass
class ConnectTokenRequest:
    name: str
    api_server: str
    token: str
    provider: str = "generic"
    ca_cert: Optional[str] = None
    namespace: str = "default"


async def _test_k8s_connectivity(
    api_server: str,
    token: str,
    ca_cert: Optional[str],
    client_cert_data: Optional[str] = None,
    client_key_data: Optional[str] = None,
) -> None:
    """Verify connectivity — supports both bearer-token and client-certificate auth."""
    import base64
    import os
    import tempfile

    from kubernetes_asyncio import client

    configuration = client.Configuration()
    configuration.host = api_server
    tmp_paths: list[str] = []

    def _write_tmp(data_b64: str, suffix: str) -> str:
        raw = base64.b64decode(data_b64)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(raw)
            tmp_paths.append(f.name)
            return f.name

    try:
        # Auth: client cert takes precedence over bearer token
        if client_cert_data and client_key_data:
            configuration.cert_file = _write_tmp(client_cert_data, ".crt")
            configuration.key_file  = _write_tmp(client_key_data,  ".key")
        elif token:
            configuration.api_key["authorization"] = f"Bearer {token}"
        else:
            raise ValueError("No authentication available (no token and no client certificate)")

        if ca_cert:
            configuration.ssl_ca_cert = _write_tmp(ca_cert, ".pem")
            configuration.verify_ssl = True
        else:
            configuration.verify_ssl = False

        api_client = client.ApiClient(configuration=configuration)
        try:
            core_api = client.CoreV1Api(api_client)
            await core_api.list_namespace(_request_timeout=5)
        except Exception as e:
            detail = str(e)
            lower  = detail.lower()
            logger.warning("Connectivity test failed for %s: %s", api_server, detail)
            if "401" in detail or "unauthorized" in lower:
                raise ValueError(
                    "Connectivity test failed: credentials rejected (HTTP 401). "
                    "For AAD-enabled AKS the user token may have expired — try re-importing."
                ) from e
            if "403" in detail or "forbidden" in lower:
                raise ValueError(
                    "Connectivity test failed: authenticated but lacks list:namespaces (HTTP 403). "
                    "Ensure the identity has at least Reader role on the cluster."
                ) from e
            if "connection refused" in lower or "connect call failed" in lower:
                raise ValueError(
                    f"Connectivity test failed: connection refused to {api_server}. "
                    "For a private AKS cluster run DokOps with --network host or inside the VNet."
                ) from e
            if "timed out" in lower or "timeout" in lower:
                raise ValueError(
                    f"Connectivity test failed: timed out connecting to {api_server}. "
                    "For a private AKS cluster run DokOps with --network host or inside the VNet."
                ) from e
            raise ValueError(f"Connectivity test failed: {detail}") from e
        finally:
            await api_client.close()
    finally:
        for p in tmp_paths:
            if os.path.exists(p):
                os.unlink(p)


async def _db_upsert_cluster(conn: ClusterConnection) -> tuple[ClusterConnection, bool]:
    """Insert or update a ClusterConnection by name. Returns (saved_conn, is_new)."""
    async with AsyncSessionLocal() as db:
        existing = (await db.exec(
            select(ClusterConnection).where(ClusterConnection.name == conn.name)
        )).first()
        if existing:
            existing.provider = conn.provider
            existing.api_server = conn.api_server
            existing.token = conn.token
            existing.ca_cert = conn.ca_cert
            existing.client_cert_data = conn.client_cert_data
            existing.client_key_data = conn.client_key_data
            existing.namespace = conn.namespace
            existing.added_by = conn.added_by
            existing.last_verified = conn.last_verified
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
            return existing, False
        db.add(conn)
        await db.commit()
        await db.refresh(conn)
        return conn, True


async def verify_token_connection(
    req: ConnectTokenRequest,
    allow_private: bool = False,
    added_by: Optional[str] = None,
) -> ClusterConnection:
    """Validate, test, encrypt, save, and register a token-based cluster connection."""
    validate_cluster_url(req.api_server, allow_private=allow_private)
    await _test_k8s_connectivity(req.api_server, req.token, req.ca_cert)

    conn = ClusterConnection(
        name=req.name,
        provider=req.provider,
        api_server=req.api_server,
        token=encrypt(req.token),
        ca_cert=req.ca_cert,
        namespace=req.namespace,
        added_by=added_by,
        last_verified=datetime.now(timezone.utc),
    )

    conn, is_new = await _db_upsert_cluster(conn)

    try:
        await k8s_service.add_connection(conn)
    except Exception:
        if is_new:
            async with AsyncSessionLocal() as db:
                row = await db.get(ClusterConnection, conn.id)
                if row:
                    await db.delete(row)
                    await db.commit()
        raise
    return conn


async def discover_aks_clusters(credential_id: str) -> List[Dict[str, Any]]:
    """Return list of AKS clusters for the given CloudCredential."""
    async with AsyncSessionLocal() as db:
        cred = (await db.exec(select(CloudCredential).where(CloudCredential.id == credential_id))).first()
    if not cred:
        raise ValueError("Credential not found")

    blob = json.loads(decrypt(cred.credential_blob))
    try:
        from azure.identity import ClientSecretCredential
        from azure.mgmt.containerservice import ContainerServiceClient

        azure_cred = ClientSecretCredential(
            tenant_id=blob["tenant_id"],
            client_id=blob["client_id"],
            client_secret=blob["client_secret"],
        )
        aks_client = ContainerServiceClient(azure_cred, blob["subscription_id"])
        clusters = list(aks_client.managed_clusters.list())
        return [
            {
                "name": c.name,
                "resource_group": c.id.split("/")[4] if c.id else "",
                "location": c.location,
                "kubernetes_version": c.kubernetes_version,
                "provisioning_state": c.provisioning_state,
                "node_count": sum(p.count or 0 for p in (c.agent_pool_profiles or [])),
            }
            for c in clusters
        ]
    except ImportError:
        raise ValueError("azure-mgmt-containerservice is not installed")


async def discover_eks_clusters(credential_id: str) -> List[Dict[str, Any]]:
    """Return list of EKS clusters for the given CloudCredential."""
    async with AsyncSessionLocal() as db:
        cred = (await db.exec(select(CloudCredential).where(CloudCredential.id == credential_id))).first()
    if not cred:
        raise ValueError("Credential not found")

    blob = json.loads(decrypt(cred.credential_blob))
    try:
        import boto3

        eks = boto3.client(
            "eks",
            aws_access_key_id=blob["access_key_id"],
            aws_secret_access_key=blob["secret_access_key"],
            region_name=blob.get("region", "us-east-1"),
        )
        names = eks.list_clusters()["clusters"]
        result = []
        for name in names:
            info = eks.describe_cluster(name=name)["cluster"]
            result.append({
                "name": name,
                "region": blob.get("region", "us-east-1"),
                "kubernetes_version": info.get("version", ""),
                "status": info.get("status", ""),
                "endpoint": info.get("endpoint", ""),
            })
        return result
    except ImportError:
        raise ValueError("boto3 is not installed")


async def import_aks_cluster(
    credential_id: str,
    cluster_name: str,
    resource_group: str,
    added_by: Optional[str] = None,
) -> ClusterConnection:
    """Fetch AKS user credentials and store as a ClusterConnection."""
    async with AsyncSessionLocal() as db:
        cred = (await db.exec(select(CloudCredential).where(CloudCredential.id == credential_id))).first()
    if not cred:
        raise ValueError("Credential not found")

    blob = json.loads(decrypt(cred.credential_blob))
    import base64

    import yaml
    from azure.identity import ClientSecretCredential
    from azure.mgmt.containerservice import ContainerServiceClient

    azure_cred = ClientSecretCredential(
        tenant_id=blob["tenant_id"],
        client_id=blob["client_id"],
        client_secret=blob["client_secret"],
    )
    aks_client = ContainerServiceClient(azure_cred, blob["subscription_id"])
    result = aks_client.managed_clusters.list_cluster_user_credentials(
        resource_group_name=resource_group,
        resource_name=cluster_name,
    )
    kubeconfig_bytes = result.kubeconfigs[0].value
    kubeconfig = yaml.safe_load(kubeconfig_bytes)

    cluster_info = kubeconfig["clusters"][0]["cluster"]
    user_info = kubeconfig["users"][0]["user"]

    api_server = cluster_info["server"]
    ca_cert = cluster_info.get("certificate-authority-data")
    token = user_info.get("token") or ""
    client_cert_data: Optional[str] = None
    client_key_data: Optional[str] = None

    # Always attempt admin credentials — they use stable client-certificate auth
    # that doesn't expire like AAD user tokens.
    logger.info("Fetching admin credentials for %s (cert-based auth, no expiry)", cluster_name)
    try:
        admin_result = aks_client.managed_clusters.list_cluster_admin_credentials(
            resource_group_name=resource_group,
            resource_name=cluster_name,
        )
        admin_kubeconfig = yaml.safe_load(admin_result.kubeconfigs[0].value)
        adm_cluster = admin_kubeconfig["clusters"][0]["cluster"]
        adm_user    = admin_kubeconfig["users"][0].get("user") or {}
        api_server          = adm_cluster["server"]
        ca_cert             = adm_cluster.get("certificate-authority-data")
        client_cert_data    = adm_user.get("client-certificate-data")
        client_key_data     = adm_user.get("client-key-data")
        token               = adm_user.get("token") or ""
    except Exception as e:
        logger.warning("Could not fetch admin credentials for %s (%s) — falling back to user token", cluster_name, e)

    if not token and not (client_cert_data and client_key_data):
        raise ValueError(
            "AKS cluster returned no usable credentials (no bearer token, no client certificate). "
            "Ensure the Service Principal has 'Azure Kubernetes Service Cluster Admin Role'."
        )

    # Validate URL (private IPs allowed for AKS)
    validate_cluster_url(api_server, allow_private=True)
    await _test_k8s_connectivity(api_server, token, ca_cert, client_cert_data, client_key_data)

    from app.core.encryption import encrypt
    conn = ClusterConnection(
        name=cluster_name,
        provider="aks",
        api_server=api_server,
        token=encrypt(token) if token else encrypt(""),
        ca_cert=ca_cert,
        client_cert_data=client_cert_data,
        client_key_data=encrypt(client_key_data) if client_key_data else None,
        added_by=added_by,
        last_verified=datetime.now(timezone.utc),
    )

    conn, is_new = await _db_upsert_cluster(conn)

    try:
        await k8s_service.add_connection(conn)
    except Exception:
        if is_new:
            async with AsyncSessionLocal() as db:
                row = await db.get(ClusterConnection, conn.id)
                if row:
                    await db.delete(row)
                    await db.commit()
        raise
    return conn


async def import_eks_cluster(
    credential_id: str,
    cluster_name: str,
    added_by: Optional[str] = None,
) -> ClusterConnection:
    """Generate an EKS bearer token and store as a ClusterConnection."""
    async with AsyncSessionLocal() as db:
        cred = (await db.exec(select(CloudCredential).where(CloudCredential.id == credential_id))).first()
    if not cred:
        raise ValueError("Credential not found")

    blob = json.loads(decrypt(cred.credential_blob))
    import base64

    import boto3
    from botocore.signers import RequestSigner

    boto_session = boto3.Session(
        aws_access_key_id=blob["access_key_id"],
        aws_secret_access_key=blob["secret_access_key"],
        region_name=blob.get("region", "us-east-1"),
    )
    eks = boto_session.client("eks")
    cluster_info = eks.describe_cluster(name=cluster_name)["cluster"]

    region = blob.get("region", "us-east-1")
    signer = RequestSigner(
        "sts",
        region,
        "sts",
        "v4",
        boto_session.get_credentials(),
        boto_session.events,
    )
    params = {
        "method": "GET",
        "url": f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15",
        "body": {},
        "headers": {"x-k8s-aws-id": cluster_name},
        "context": {},
    }
    presigned_url = signer.generate_presigned_url(
        params, region_name=region, expires_in=60, operation_name=""
    )
    token = "k8s-aws-v1." + base64.urlsafe_b64encode(presigned_url.encode()).decode().rstrip("=")

    api_server = cluster_info["endpoint"]
    ca_cert = cluster_info.get("certificateAuthority", {}).get("data")

    req = ConnectTokenRequest(
        name=cluster_name,
        api_server=api_server,
        token=token,
        provider="eks",
        ca_cert=ca_cert,
    )
    return await verify_token_connection(req, allow_private=False, added_by=added_by)


async def connect_from_kubeconfig(
    content: bytes,
    added_by: Optional[str] = None,
) -> ClusterConnection:
    import yaml as _yaml

    try:
        kc = _yaml.safe_load(content)
    except Exception as e:
        raise ValueError(f"Invalid YAML: {e}") from e

    try:
        ctx_name = kc.get("current-context") or kc["contexts"][0]["name"]
        ctx = next(c["context"] for c in kc["contexts"] if c["name"] == ctx_name)
        cluster_raw = next(c for c in kc["clusters"] if c["name"] == ctx["cluster"])
        user_raw = next(u for u in kc["users"] if u["name"] == ctx["user"])
    except (KeyError, StopIteration, TypeError) as e:
        raise ValueError(f"Could not parse kubeconfig structure: {e}") from e

    cluster_info = cluster_raw["cluster"]
    user_info = user_raw.get("user") or {}

    api_server: str = cluster_info.get("server", "")
    ca_cert: Optional[str] = cluster_info.get("certificate-authority-data")
    token: str = user_info.get("token", "")

    if not token:
        raise ValueError(
            "Kubeconfig must contain a bearer token. "
            "Exec-based auth (aws-iam-authenticator, gke-gcloud-auth-plugin) is not supported for file upload — "
            "use Cloud Auto-Discovery instead."
        )

    req = ConnectTokenRequest(
        name=ctx["cluster"],
        api_server=api_server,
        token=token,
        provider="generic",
        ca_cert=ca_cert,
    )
    return await verify_token_connection(req, allow_private=True, added_by=added_by)


async def save_cloud_credential(
    provider: str, blob: Dict[str, Any], added_by: Optional[str] = None
) -> CloudCredential:
    cred = CloudCredential(
        provider=provider,
        credential_blob=encrypt(json.dumps(blob)),
        added_by=added_by,
    )
    async with AsyncSessionLocal() as db:
        db.add(cred)
        await db.commit()
        await db.refresh(cred)
    return cred
