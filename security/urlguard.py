"""Shared safe-URL / SSRF policy for outbound network opens.

This is the single authoritative place for deciding whether an http(s) URL
may be opened, navigated to, or fetched. Both desktop "open URL" computer
control and browser automation consult this module so the protections can
never drift apart.

It blocks (returns a reason string / True-for-forbidden):

  * non-http(s) schemes (file:, ftp:, javascript:, …),
  * hostnames with no host,
  * loopback, link-local, RFC-1918 private, CGNAT, multicast and reserved
    IPv4 ranges — including canonical numeric/hex/octal/dotted aliases and
    flat integer shorthand (e.g. ``127.0.0.1``, ``2130706433``, ``0x7f000001``,
    ``0177.0.0.1``),
  * IPv6 loopback, link-local, and unique-local addresses,
  * well-known metadata/internal hostnames (localhost, * .localhost,
    metadata.google.internal, kubernetes.default.svc, * .local).

Ordinary public hostnames are *not* resolved here — DNS resolution is left to
the network layer, and the caller may add its own DNS-level check (blocking
resolutions that don't land on global addresses) when it performs the fetch.
"""
from __future__ import annotations

from urllib.parse import urlsplit

_BLOCKED_HOST_NAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata",
        "kubernetes.default.svc",
    }
)

# Unsafe (non-http(s)) schemes are refused outright. Navigation/opener tools
# only ever issue http(s) requests.
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def parse_ip_int(host: str) -> int | None:
    """Best-effort integer form of an IPv4 literal (incl. hex/octal/int shorthand).

    Returns None when *host* is not a flat base-0 integer literal.
    """
    try:
        return int(host, 0)
    except (TypeError, ValueError):
        return None


def ipv4_to_int(host: str) -> int | None:
    """Parse dotted 'a.b.c.d' into a 32-bit int.

    Octets may be decimal, hex (0x..), or octal (leading 0), matching the loose
    numeric grammar browsers accept, so aliases like ``0177.0.0.1`` still map to
    loopback. Returns None when not exactly a 4-part dotted IPv4 literal.
    """
    try:
        parts = host.split(".")
        if len(parts) != 4:
            return None
        octets = []
        for p in parts:
            if not p:
                return None
            if p.lower().startswith("0x"):
                o = int(p, 16)
            elif len(p) > 1 and p.startswith("0"):
                o = int(p, 8)
            else:
                o = int(p, 10)
            if o < 0 or o > 255:
                return None
            octets.append(o)
        return (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
    except (TypeError, ValueError):
        return None


def in_rfc1918_or_special(n: int) -> bool:
    # 0.0.0.0/8 'this network', 10/8 private, 100.64.0.0/10 CGNAT,
    # 127/8 loopback, 169.254.0.0/16 link-local, 172.16.0.0/12 private,
    # 192.168.0.0/16 private, and 224/4 multicast + 240/4 reserved.
    return (
        ((n >> 24) in (0, 10, 127))
        or ((n >> 22) == 0x19101)              # 100.64.0.0/10
        or (0xAC100000 <= n <= 0xAC1FFFFF)     # 172.16.0.0/12
        or (0xC0A80000 <= n <= 0xC0A8FFFF)     # 192.168.0.0/16
        or ((n >> 16) == 0xA9FE)               # 169.254.0.0/16 link-local
        or (((n >> 28) & 0xF) in (0xE, 0xF))   # multicast 224/4 + reserved 240/4
    )


def forbidden_host(url: str) -> str | None:
    """Return a reason string if ``url`` targets a forbidden host, else None.

    No network call is made — only the literal host/form is inspected. Ordinary
    public hostnames are allowed here so callers can still decide; the DNS-level
    "must land on a global address" check lives in :func:`is_public_url`.
    """
    parts = urlsplit(url)
    if not parts.hostname:
        return "URL has no host."
    host = parts.hostname.strip().lower().strip("[]")
    if not host:
        return "URL has no host."
    if host in _BLOCKED_HOST_NAMES or host.endswith(".localhost") or host.endswith(".local"):
        return "Opening loopback/metadata/local URLs is not allowed."
    # IPv6 literal (contains ':').
    if ":" in host:
        if host in ("::1", "::", "0:0:0:0:0:0:0:1"):
            return "Opening loopback IPv6 addresses is not allowed."
        low = host.split("%")[0].lower()
        if low.startswith("fe80:") or low.startswith("fc") or low.startswith("fd"):
            return "Opening link-local/private IPv6 addresses is not allowed."
        return None
    # IPv4 & numeric shorthands.
    n = ipv4_to_int(host) if ("." in host) else parse_ip_int(host)
    if n is not None and in_rfc1918_or_special(n):
        return "Opening loopback/private/internal URLs is not allowed."
    return None


def forbidden_open_target(url: str) -> str | None:
    """Return a reason string if ``url`` may not be opened/navigated/fetched.

    Combines the scheme whitelist and the host-name/IP policy so every network
    open path uses exactly the same rule set.
    """
    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        return "Only http(s) URLs are allowed."
    if parts.username or parts.password:
        return "URLs with embedded credentials are not allowed."
    return forbidden_host(url)
