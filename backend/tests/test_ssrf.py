import socket
import pytest
from unittest.mock import patch
from app.core.ssrf import validate_cluster_url


def _getaddrinfo_ipv4(ip: str):
    """Helper: return a getaddrinfo-style result for a single IPv4 address."""
    return [(socket.AF_INET, None, None, None, (ip, 0))]


def test_rejects_http():
    with pytest.raises(ValueError, match="https"):
        validate_cluster_url("http://cluster.example.com")

def test_accepts_https():
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=_getaddrinfo_ipv4("203.0.113.5")):
        validate_cluster_url("https://cluster.example.com")  # no exception

def test_rejects_private_ip_10():
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=_getaddrinfo_ipv4("10.0.0.1")):
        with pytest.raises(ValueError, match="Private IP"):
            validate_cluster_url("https://internal-cluster.local")

def test_rejects_private_ip_169():
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=_getaddrinfo_ipv4("169.254.169.254")):
        with pytest.raises(ValueError, match="Private IP"):
            validate_cluster_url("https://metadata.internal")

def test_allows_private_ip_when_flag_set():
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=_getaddrinfo_ipv4("10.0.0.1")):
        validate_cluster_url("https://internal-cluster.local", allow_private=True)  # no exception


def test_rejects_ipv6_loopback():
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=[(socket.AF_INET6, None, None, None, ("::1", 0, 0, 0))]):
        with pytest.raises(ValueError, match="Private IP"):
            validate_cluster_url("https://localhost-v6.example.com")
