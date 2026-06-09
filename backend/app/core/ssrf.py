import ipaddress
import socket
from urllib.parse import urlparse

_PRIVATE_NETWORKS = [
    # IPv4 private ranges
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    # IPv6 private ranges
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _resolve_all(hostname: str) -> list[str]:
    """Resolve hostname to all IP addresses (IPv4 + IPv6)."""
    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")
    return [r[4][0] for r in results]


def validate_url(url: str) -> None:
    """Raise ValueError if url targets a private/internal network.
    Use this before making any user-controlled outbound HTTP request.
    Blocks localhost and known cloud metadata IPs. Allows hostnames that
    can't be resolved (they may be valid in the deployment environment)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https URLs are allowed, got: {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")
    # Block well-known loopback addresses explicitly
    if hostname in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(f"Private IP addresses are not allowed: {hostname}")
    # Block cloud metadata service by hostname
    if hostname in ("169.254.169.254", "metadata.google.internal"):
        raise ValueError(f"Cloud metadata endpoint is not allowed: {hostname}")
    try:
        resolved_ips = _resolve_all(hostname)
    except ValueError:
        # Cannot resolve hostname → allow it (may be a valid service in deployment env)
        return
    for resolved_ip in resolved_ips:
        ip = ipaddress.ip_address(resolved_ip)
        for net in _PRIVATE_NETWORKS:
            if ip in net:
                raise ValueError(
                    f"Private/internal IP addresses are not allowed ({resolved_ip})"
                )


def validate_cluster_url(url: str, allow_private: bool = False) -> None:
    """Raise ValueError if url is unsafe for outbound k8s API requests."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("API server URL must use https://")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("API server URL has no hostname")
    resolved_ips = _resolve_all(hostname)
    if allow_private:
        return
    for resolved_ip in resolved_ips:
        ip = ipaddress.ip_address(resolved_ip)
        for net in _PRIVATE_NETWORKS:
            if ip in net:
                raise ValueError(
                    f"Private IP addresses are not allowed ({resolved_ip}). "
                    "Set ALLOW_PRIVATE_CLUSTER_IPS=true for on-prem clusters."
                )
