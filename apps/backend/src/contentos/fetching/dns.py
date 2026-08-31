"""Network-address safety: resolve-then-validate SSRF prevention.

A hostname is fetchable only when EVERY resolved address is safe; one unsafe
answer fails the whole host closed. Resolution is injectable so tests never
need the public internet.
"""

import ipaddress
import socket
from collections.abc import Callable

Resolver = Callable[[str, int], list[str]]


class DnsResolutionError(Exception):
    """The hostname could not be resolved to any address."""


class UnsafeAddressError(Exception):
    """A resolved address is not safe for outbound research fetching."""


def default_resolver(host: str, port: int) -> list[str]:
    """Resolve via the OS, returning unique IP literals for TCP connections."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise DnsResolutionError(f"cannot resolve host '{host}'") from exc
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        if isinstance(address, str) and address not in addresses:
            addresses.append(address)
    return addresses


def is_safe_address(ip_literal: str) -> bool:
    """True only for globally routable unicast addresses.

    Rejects loopback, RFC 1918 private, link-local (including cloud metadata
    169.254.169.254), multicast, unspecified, reserved/documentation ranges,
    IPv6 unique-local, and IPv4-mapped IPv6 forms of any of those.
    """
    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip_literal)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        return False
    return address.is_global


def resolve_safe_addresses(host: str, port: int, resolver: Resolver) -> list[str]:
    """Resolve ``host`` and validate every answer; fail closed on any unsafe IP."""
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        addresses = resolver(host, port)
    if not addresses:
        raise DnsResolutionError(f"host '{host}' resolved to no addresses")
    for address in addresses:
        if not is_safe_address(address):
            raise UnsafeAddressError(f"host '{host}' resolves to an unsafe address")
    return addresses
