"""Prefer IPv4 for outbound HTTPS (e.g. full CSV download) when IPv6 paths are broken."""

from __future__ import annotations

import socket
from typing import Any

_real_getaddrinfo = socket.getaddrinfo


def _prefer_ipv4_getaddrinfo(
    host: str,
    port: Any,
    family: int = 0,
    type: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> Any:
    res = _real_getaddrinfo(host, port, family, type, proto, flags)
    v4 = [r for r in res if r[0] == socket.AF_INET]
    return v4 if v4 else res


def enable_ipv4_preference() -> None:
    """Prefer IPv4 for TLS (avoids broken IPv6 paths to some hosts)."""
    socket.getaddrinfo = _prefer_ipv4_getaddrinfo  # type: ignore[assignment]
