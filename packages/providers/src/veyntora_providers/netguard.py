"""Endpoints typed by users (own models, BYOK) must be public HTTPS services.

Veyntora calls these endpoints from inside the network, so an address on it (OpenBao,
PostgreSQL, the cloud metadata service) would let a user reach what they cannot. The
check runs when the endpoint is saved and again before each use, since DNS can change.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class EndpointNotAllowedError(ValueError):
    """The endpoint is not a public HTTPS service."""


def _public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def check_public_https(url: str) -> None:
    """Raise EndpointNotAllowedError unless every address of the host is public."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise EndpointNotAllowedError("the endpoint must be an https:// URL")
    if parts.username or parts.password:
        raise EndpointNotAllowedError("the endpoint must not contain credentials")
    host = parts.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, parts.port or 443, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise EndpointNotAllowedError(f"the host {host} cannot be resolved") from exc
        # Strip an IPv6 zone ("fe80::1%eth0"); link-local is refused either way.
        addresses = [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos]
    if not addresses or not all(_public(a) for a in addresses):
        raise EndpointNotAllowedError(
            "the endpoint points into a private network; only public services are allowed"
        )
