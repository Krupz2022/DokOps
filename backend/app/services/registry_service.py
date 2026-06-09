import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from app.core.db import engine
from app.core.encryption import decrypt
from app.models.registry import RegistryConnection
from app.models.setting import SystemSetting

BUILT_IN_REGISTRIES = [
    {"name": "Docker Hub", "url": "hub.docker.com", "built_in": True},
    {"name": "GHCR",       "url": "ghcr.io",        "built_in": True},
    {"name": "Quay.io",    "url": "quay.io",         "built_in": True},
    {"name": "Kubernetes Registry", "url": "registry.k8s.io", "built_in": True},
]

FETCH_ALLOWLIST: set[str] = {
    "hub.docker.com",
    "ghcr.io",
    "quay.io",
    "registry.k8s.io",
    "raw.githubusercontent.com",
    "api.github.com",
}

_DIGEST_RE = re.compile(r"@sha256:[a-f0-9]+")


def _strip_digest(image: str) -> str:
    return _DIGEST_RE.sub("", image)


def _parse_image(image: str) -> tuple[str, str, str]:
    """Return (registry_host, image_path, tag).

    Handles:
      nginx                        -> hub.docker.com, library/nginx, latest
      myrepo/myapp:v2              -> hub.docker.com, myrepo/myapp, v2
      ghcr.io/owner/repo:latest    -> ghcr.io, owner/repo, latest
      myacr.azurecr.io/img:prod    -> myacr.azurecr.io, img, prod
    """
    image = _strip_digest(image)
    parts = image.split("/")
    last = parts[-1]

    if ":" in last:
        name_part, tag = last.rsplit(":", 1)
        parts[-1] = name_part
    else:
        tag = "latest"

    # A part has a "." or port colon -> it's a registry hostname
    if len(parts) >= 2 and ("." in parts[0] or ":" in parts[0]):
        registry = parts[0]
        path = "/".join(parts[1:])
    else:
        registry = "hub.docker.com"
        if len(parts) == 1:
            path = f"library/{parts[0]}"
        else:
            path = "/".join(parts)

    return registry, path, tag


def _rank_tag(tag: str) -> int:
    """Lower score = better (simpler, more stable tag)."""
    import re as _re
    t = tag.lower()
    if t in ("latest", "stable", "lts"): return 0
    if _re.match(r"^\d+\.\d+\.\d+$", t): return 1   # 1.27.0
    if _re.match(r"^\d+\.\d+$", t): return 2         # 1.27
    if _re.match(r"^\d+$", t): return 3              # 7
    if t == "alpine": return 4
    if t.startswith("stable-") and "-perl" not in t: return 10
    if t.startswith("mainline-") and "-perl" not in t: return 11
    if _re.match(r"^[\d.]+(-alpine)?$", t): return 12
    return 99  # everything else (platform-specific, perl, slim, etc.)


async def _search_docker_hub(org_repo: str, timeout: float = 8.0) -> list[str]:
    url = (
        f"https://hub.docker.com/v2/repositories/{org_repo}"
        f"/tags?page_size=50&ordering=last_updated"
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            all_tags = [r["name"] for r in resp.json().get("results", [])]
            # Return sorted by preference: simple stable tags first
            return sorted(all_tags, key=_rank_tag)
        except Exception:
            return []


async def _oci_get_auth_token(
    client: httpx.AsyncClient,
    registry: str,
    image_path: str,
    username: Optional[str],
    password: Optional[str],
) -> Optional[str]:
    """Probe the registry to get a Bearer token if needed."""
    probe_url = f"https://{registry}/v2/{image_path}/tags/list"
    basic_auth = (username, password) if username and password else None
    try:
        resp = await client.get(probe_url, auth=basic_auth)
        if resp.status_code == 401 and username and password:
            www_auth = resp.headers.get("www-authenticate", "")
            return await _exchange_oci_token(client, www_auth, username, password)
    except Exception:
        pass
    return None


async def _oci_get_tags(
    registry: str,
    image_path: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 8.0,
) -> list[str]:
    """Query OCI Distribution Spec /v2/{path}/tags/list. Handles Bearer token exchange."""
    url = f"https://{registry}/v2/{image_path}/tags/list"
    basic_auth = (username, password) if username and password else None

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(url, auth=basic_auth)

            if resp.status_code == 401 and username and password:
                www_auth = resp.headers.get("www-authenticate", "")
                token = await _exchange_oci_token(client, www_auth, username, password)
                if token:
                    resp = await client.get(
                        url, headers={"Authorization": f"Bearer {token}"}
                    )

            if resp.status_code == 200:
                return (resp.json().get("tags") or [])[:10]
            return []
        except Exception:
            return []


async def _oci_list_catalog(
    registry: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 10.0,
) -> tuple[list[str], Optional[str]]:
    """List all repositories in a registry via /v2/_catalog.
    Returns (repos, error_message). error_message is None on success.

    Uses the same Bearer token flow as _oci_check_image_tag: probe without
    credentials first, exchange for a token on 401, then retry.
    """
    url = f"https://{registry}/v2/_catalog?n=200"

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            # Probe without auth — many registries return 401 + WWW-Authenticate
            resp = await client.get(url)

            if resp.status_code == 401 and username and password:
                www_auth = resp.headers.get("www-authenticate", "")
                token = await _exchange_oci_catalog_token(client, www_auth, username, password)
                if token:
                    resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                else:
                    # Token exchange failed — try basic auth as last resort
                    resp = await client.get(url, auth=(username, password))

            if resp.status_code == 200:
                repos = resp.json().get("repositories") or []
                if not repos:
                    return [], (
                        "Registry returned an empty catalog. "
                        "For ACR this usually means the service principal needs AcrPush or Contributor role "
                        "(AcrPull alone cannot enumerate repositories). "
                        "Use 'Verify Image' above to check a specific image directly."
                    )
                return repos, None
            if resp.status_code in (401, 403):
                return [], (
                    f"HTTP {resp.status_code} — insufficient permissions to list the catalog. "
                    "For ACR: assign the AcrPush or Contributor role to the service principal. "
                    "Use 'Verify Image' above to confirm a specific image directly."
                )
            return [], f"Registry returned HTTP {resp.status_code}: {resp.text[:200]}"
        except httpx.TimeoutException:
            return [], f"Connection timed out reaching https://{registry}/v2/_catalog — check network connectivity."
        except httpx.ConnectError as exc:
            return [], f"Could not connect to {registry}: {exc}"
        except Exception as exc:
            return [], f"Unexpected error ({type(exc).__name__}): {exc}"


async def _exchange_oci_catalog_token(
    client: httpx.AsyncClient,
    www_auth: str,
    username: str,
    password: str,
) -> Optional[str]:
    """Exchange credentials for a catalog-scoped token."""
    realm_m = re.search(r'realm="([^"]+)"', www_auth)
    service_m = re.search(r'service="([^"]+)"', www_auth)
    if not realm_m:
        return None

    params: dict[str, str] = {"scope": "registry:catalog:*"}
    if service_m:
        params["service"] = service_m.group(1)

    try:
        resp = await client.get(realm_m.group(1), params=params, auth=(username, password))
        if resp.status_code == 200:
            data = resp.json()
            return data.get("token") or data.get("access_token")
    except Exception:
        pass
    return None


async def _oci_check_image_tag(
    registry: str,
    image_path: str,
    tag: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 8.0,
) -> dict:
    """Check if a specific image:tag exists. Returns {exists, digest, media_type}."""
    url = f"https://{registry}/v2/{image_path}/manifests/{tag}"
    headers = {"Accept": "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, */*"}
    basic_auth = (username, password) if username and password else None

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.head(url, auth=basic_auth, headers=headers)

            if resp.status_code == 401 and username and password:
                www_auth = resp.headers.get("www-authenticate", "")
                token = await _exchange_oci_token(client, www_auth, username, password)
                if token:
                    resp = await client.head(
                        url,
                        headers={**headers, "Authorization": f"Bearer {token}"},
                    )

            if resp.status_code == 200:
                return {
                    "exists": True,
                    "digest": resp.headers.get("docker-content-digest", ""),
                    "media_type": resp.headers.get("content-type", ""),
                }
            return {"exists": False, "digest": None, "media_type": None}
        except Exception as exc:
            return {"exists": False, "error": str(exc), "digest": None, "media_type": None}


async def _exchange_oci_token(
    client: httpx.AsyncClient,
    www_auth: str,
    username: str,
    password: str,
) -> Optional[str]:
    """Parse WWW-Authenticate Bearer header and exchange credentials for a short-lived token."""
    realm_m = re.search(r'realm="([^"]+)"', www_auth)
    service_m = re.search(r'service="([^"]+)"', www_auth)
    scope_m = re.search(r'scope="([^"]+)"', www_auth)
    if not realm_m:
        return None

    params: dict[str, str] = {}
    if service_m:
        params["service"] = service_m.group(1)
    if scope_m:
        params["scope"] = scope_m.group(1)

    try:
        resp = await client.get(
            realm_m.group(1), params=params, auth=(username, password)
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("token") or data.get("access_token")
    except Exception:
        pass
    return None


class RegistryService:
    def is_enabled(self) -> bool:
        with Session(engine) as db:
            row = db.get(SystemSetting, "registry_lookup_enabled")
        return row is not None and row.value.lower() == "true"

    def list_built_in(self) -> list[dict]:
        return BUILT_IN_REGISTRIES.copy()

    def _get_user_registries(self) -> list[RegistryConnection]:
        with Session(engine) as db:
            return list(db.exec(select(RegistryConnection)).all())

    def find_registry_by_name_or_url(self, identifier: str) -> Optional[RegistryConnection]:
        """Find a registry by display name (case-insensitive) or hostname."""
        identifier_lower = identifier.lower().strip()
        with Session(engine) as db:
            rows = list(db.exec(select(RegistryConnection)).all())
        for r in rows:
            if r.name.lower() == identifier_lower or r.url.lower() == identifier_lower:
                return r
        # Partial match fallback
        for r in rows:
            if identifier_lower in r.name.lower() or identifier_lower in r.url.lower():
                return r
        return None

    def _get_fetch_allowlist(self) -> set[str]:
        user_urls = {r.url for r in self._get_user_registries()}
        return FETCH_ALLOWLIST | user_urls

    async def list_catalog(self, registry_id: str) -> tuple[list[str], Optional[str]]:
        with Session(engine) as db:
            reg = db.get(RegistryConnection, registry_id)
        if not reg:
            return [], "Registry not found."
        pw_plain: Optional[str] = None
        if reg.password:
            try:
                pw_plain = decrypt(reg.password)
            except Exception:
                pass
        return await _oci_list_catalog(reg.url, reg.username, pw_plain)

    async def check_image(self, registry_id: str, image: str) -> dict:
        """Check if image (e.g. 'myapp:v1.2.3' or 'myapp') exists in the registry."""
        with Session(engine) as db:
            reg = db.get(RegistryConnection, registry_id)
        if not reg:
            return {"exists": False, "error": "Registry not found"}

        pw_plain: Optional[str] = None
        if reg.password:
            try:
                pw_plain = decrypt(reg.password)
            except Exception:
                pass

        if ":" in image:
            image_path, tag = image.rsplit(":", 1)
        else:
            image_path, tag = image, "latest"

        # Strip leading registry host if user pasted full image ref
        if image_path.startswith(reg.url + "/"):
            image_path = image_path[len(reg.url) + 1:]

        result = await _oci_check_image_tag(reg.url, image_path, tag, reg.username, pw_plain)
        result["image"] = f"{reg.url}/{image_path}:{tag}"
        return result

    async def search_image(self, image_name: str) -> list[dict]:
        registry, path, _tag = _parse_image(image_name)
        results: list[dict] = []
        user_regs = self._get_user_registries()

        if registry == "hub.docker.com":
            # Image has no explicit registry hostname — try all connected private
            # registries first so "myapp:v1.2.3" finds it in ACR/ECR before Docker Hub.
            for reg in user_regs:
                pw_plain: Optional[str] = None
                if reg.password:
                    try:
                        pw_plain = decrypt(reg.password)
                    except Exception:
                        pass
                tags = await _oci_get_tags(reg.url, path, reg.username, pw_plain)
                if tags:
                    results.append({
                        "registry": reg.url,
                        "registry_name": reg.name,
                        "full_image": f"{reg.url}/{path}",
                        "tags": tags,
                    })

            # Fall through to Docker Hub only if no private registry matched
            if not results:
                tags = await _search_docker_hub(path)
                if tags:
                    results.append(
                        {"registry": "hub.docker.com", "full_image": path, "tags": tags}
                    )
            return results

        built_in_urls = {r["url"] for r in BUILT_IN_REGISTRIES if r["url"] != "hub.docker.com"}
        if registry in built_in_urls:
            tags = await _oci_get_tags(registry, path)
            if tags:
                results.append(
                    {"registry": registry, "full_image": f"{registry}/{path}", "tags": tags}
                )
            return results

        # Explicit private registry hostname in the image name
        for reg in user_regs:
            if reg.url == registry or registry.endswith(f".{reg.url}"):
                pw_plain = None
                if reg.password:
                    try:
                        pw_plain = decrypt(reg.password)
                    except Exception:
                        pass
                tags = await _oci_get_tags(registry, path, reg.username, pw_plain)
                if tags:
                    results.append({
                        "registry": registry,
                        "registry_name": reg.name,
                        "full_image": f"{registry}/{path}",
                        "tags": tags,
                    })
        return results

    async def fetch_url(self, url: str) -> str:
        hostname = urlparse(url).hostname or ""
        # Fast-path: check static allowlist before hitting the DB
        if hostname not in FETCH_ALLOWLIST and hostname not in self._get_fetch_allowlist():
            raise ValueError(
                f"Domain '{hostname}' is not in the registry fetch allowlist. "
                "Only configured registry domains are accessible."
            )

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            text = resp.text
            if len(text) > 4000:
                text = text[:4000] + "\n... (truncated)"
            return text


registry_service = RegistryService()
