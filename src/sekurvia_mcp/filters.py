"""URL hardening shared by the search and read tools.

Two layers of defense:

1. Scheme/host validation – reject anything that's not http(s) with a parseable
   host. This blocks ``file://``, ``gopher://``, javascript: URIs etc. that an
   upstream SearXNG result or a model-supplied URL could otherwise smuggle past.
2. Network-aware filtering – resolve the host (best-effort) and reject any
   address that lands inside a loopback / link-local / private / multicast /
   reserved range, *unless* the host matches an explicit
   ``SEKURVIA_ALLOWED_DOMAINS`` entry. This is the SSRF guard.

Domain allow/block lists support exact match and ``.suffix`` matching so that
``example.com`` covers ``a.b.example.com``.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from .config import Config


class UrlRejected(ValueError):
    """Raised when a URL is rejected by the SSRF / domain filters."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"rejected URL {url!r}: {reason}")
        self.url = url
        self.reason = reason


@dataclass(frozen=True)
class CheckedUrl:
    """A URL that has passed scheme + host validation."""

    raw: str
    scheme: str
    host: str
    port: int | None


def _split(url: str) -> CheckedUrl:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UrlRejected(url, f"scheme not allowed: {parsed.scheme or '(none)'}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UrlRejected(url, "missing host")
    return CheckedUrl(raw=url, scheme=parsed.scheme, host=host, port=parsed.port)


def _domain_matches(host: str, patterns: tuple[str, ...]) -> bool:
    """``patterns`` is a list of bare hostnames; suffix-match with a leading dot."""

    for p in patterns:
        if not p:
            continue
        if host == p or host.endswith("." + p):
            return True
    return False


def _looks_private(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve(host: str) -> list[str]:
    """Resolve ``host`` to a list of IPs. Returns ``[]`` if resolution fails.

    A failed resolution is treated as "let httpx surface the error" rather
    than rejecting outright — the SSRF guard only kicks in for *successful*
    resolutions that happen to point at private space.
    """

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return [info[4][0] for info in infos]


def check_url(url: str, cfg: Config, *, allow_private: bool = False) -> CheckedUrl:
    """Validate a URL, raising :class:`UrlRejected` on any policy violation.

    ``allow_private`` is set only by the *internal* SearXNG client (which
    points at ``127.0.0.1:8888`` or similar) — never by the public
    ``read``/``search`` tools.
    """

    checked = _split(url)

    # Literal-IP shortcut: skip DNS, evaluate the address directly.
    try:
        literal_ip = ipaddress.ip_address(checked.host)
    except ValueError:
        literal_ip = None

    # Block list always wins.
    if _domain_matches(checked.host, cfg.blocked_domains):
        raise UrlRejected(url, "host is on SEKURVIA_BLOCKED_DOMAINS")

    on_allowlist = _domain_matches(checked.host, cfg.allowed_domains)

    if cfg.allowed_domains and not on_allowlist:
        raise UrlRejected(url, "host is not on SEKURVIA_ALLOWED_DOMAINS")

    if allow_private or on_allowlist:
        return checked

    if literal_ip is not None:
        if _looks_private(str(literal_ip)):
            raise UrlRejected(url, f"address {literal_ip} is in a non-routable range")
        return checked

    for addr in _resolve(checked.host):
        if _looks_private(addr):
            raise UrlRejected(url, f"resolves to non-routable address {addr}")
    return checked


def filter_search_results(
    results: list[dict],
    cfg: Config,
) -> list[dict]:
    """Drop result entries whose URL is rejected by :func:`check_url`."""

    keep: list[dict] = []
    for entry in results:
        url = entry.get("url")
        if not isinstance(url, str):
            continue
        try:
            check_url(url, cfg)
        except UrlRejected:
            continue
        keep.append(entry)
    return keep
