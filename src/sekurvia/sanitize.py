"""Pure sanitization helpers.

Three responsibilities, deliberately small so they're trivially testable:

* :func:`strip_html` — turn arbitrary HTML/text into plain whitespace-collapsed
  text and length-cap it.
* :func:`is_safe_url` — reject SSRF-prone result URLs (loopback, link-local,
  private-network, non-http schemes) unless the caller has explicitly
  allowlisted the host.
* :func:`clean_result` — convert one raw SearXNG result row into the minimal
  shape we ever return to the LLM.
"""

from __future__ import annotations

import ipaddress
import re
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import urlparse

from .config import Settings

_WHITESPACE_RE = re.compile(r"\s+")
_TRUNCATION_SUFFIX = "…"


class _TextExtractor(HTMLParser):
    """Strip tags; collect visible text. Skips script/style content."""

    _BLOCK_TAGS: ClassVar[frozenset[str]] = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._BLOCK_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def strip_html(value: str | None, *, max_chars: int) -> str:
    """Return *value* with HTML stripped, whitespace collapsed, length-capped.

    Robust to tag-soup, malformed entities, and ``None``/non-str inputs.
    Never raises.
    """
    if not value:
        return ""
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return ""

    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
        text = parser.text()
    except Exception:
        text = value

    text = _WHITESPACE_RE.sub(" ", text).strip()

    if max_chars > 0 and len(text) > max_chars:
        # Reserve one char for the ellipsis so we never overshoot.
        text = text[: max_chars - 1].rstrip() + _TRUNCATION_SUFFIX
    return text


def is_safe_url(url: str | None, settings: Settings) -> bool:
    """Decide whether *url* is safe to surface to the agent.

    Rules:
      * Must be a non-empty string with an http/https scheme and a host.
      * Host must not be a loopback/link-local/multicast/private/reserved
        IP literal — unless the host is explicitly in
        ``SEKURVIA_ALLOWED_DOMAINS``.
      * Must not match the blocklist.
      * If an allowlist is set, host must match it.

    Domain matches are case-insensitive and also match any subdomain
    (e.g. ``example.com`` matches ``a.b.example.com``).
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    host = (parsed.hostname or "").lower()
    if not host:
        return False

    in_allowlist = _matches_domain_set(host, settings.domain_allowlist)

    if _matches_domain_set(host, settings.domain_blocklist):
        return False

    if settings.domain_allowlist and not in_allowlist:
        return False

    return not (not in_allowlist and _is_dangerous_host(host))


def _matches_domain_set(host: str, domains: frozenset[str]) -> bool:
    if not domains:
        return False
    for d in domains:
        if not d:
            continue
        if host == d or host.endswith("." + d):
            return True
    return False


def _is_dangerous_host(host: str) -> bool:
    """Reject hostnames that resolve to non-public address space."""
    if host in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_private
        or ip.is_reserved
        or ip.is_unspecified
    )


def clean_result(raw: dict, settings: Settings) -> dict | None:
    """Reduce a SearXNG result row to the minimal safe payload.

    Returns ``None`` if the row's URL fails :func:`is_safe_url` so callers
    can drop unsafe entries silently.
    """
    if not isinstance(raw, dict):
        return None

    url = raw.get("url") or raw.get("pretty_url")
    if not is_safe_url(url, settings):
        return None

    title = strip_html(raw.get("title"), max_chars=300)
    snippet = strip_html(raw.get("content"), max_chars=settings.max_snippet_chars)
    engine = raw.get("engine") or raw.get("engines") or ""
    if isinstance(engine, list):
        engine = ", ".join(str(e) for e in engine if e)
    engine = strip_html(str(engine), max_chars=80)

    score: float | None = None
    raw_score = raw.get("score")
    if isinstance(raw_score, (int, float)):
        score = float(raw_score)

    cleaned: dict[str, Any] = {
        "title": title,
        "url": url,
        "snippet": snippet,
        "engine": engine,
    }
    if score is not None:
        cleaned["score"] = score

    published = raw.get("publishedDate") or raw.get("published_date")
    if isinstance(published, str) and published.strip():
        cleaned["published"] = strip_html(published, max_chars=64)

    return cleaned
