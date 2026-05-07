"""URL → cleaned-markdown extractor used by the ``read`` tool.

Wraps :mod:`httpx` for fetching and :mod:`trafilatura` for boilerplate
stripping. Output is structured so the model can cite ``title`` and
``url`` and quote ``content`` directly without further processing.

Hardening:

- :func:`~sekurvia_mcp.filters.check_url` blocks SSRF and applies the
  operator's domain allow/block lists *before* any HTTP request goes out.
- ``follow_redirects=False`` so we cannot be bounced off-domain into a
  link-local address after the initial check.
- Bounded read with a hard byte ceiling (``cfg.max_response_bytes``).
- Output truncated at ``max_chars`` and ``HARD_MAX_OUTPUT_CHARS``.
- Network-only timeout via :class:`httpx.Timeout`.
"""

from __future__ import annotations

from typing import Any

import httpx

# Importing trafilatura at module load is cheap and lets us fail fast if
# the optional dependency wasn't installed.
import trafilatura

from .config import HARD_MAX_OUTPUT_CHARS, Config
from .filters import UrlRejected, check_url


class ReadError(RuntimeError):
    """Raised on a failure that should surface as ``{"error": ..., "kind": ...}``.

    Same envelope shape as :class:`sekurvia_mcp.search.SearchError`.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


def _coerce_int(name: str, raw: Any, *, lo: int, hi: int) -> int:
    if isinstance(raw, bool):
        raise ReadError("ValidationError", f"{name} must be an integer, not a bool")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ReadError("ValidationError", f"{name} must be an integer (got: {raw!r})") from exc
    if value < lo or value > hi:
        raise ReadError("ValidationError", f"{name} out of range ({lo}..{hi})")
    return value


def _normalise_args(args: dict[str, Any]) -> dict[str, Any]:
    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ReadError("ValidationError", "url is required and must be a non-empty string")
    url = url.strip()

    max_chars = _coerce_int(
        "max_chars",
        args.get("max_chars", 8000),
        lo=500,
        hi=HARD_MAX_OUTPUT_CHARS,
    )

    include_links = args.get("include_links", False)
    if not isinstance(include_links, bool):
        raise ReadError("ValidationError", "include_links must be a boolean")

    return {
        "url": url,
        "max_chars": max_chars,
        "include_links": include_links,
    }


async def _fetch(url: str, cfg: Config) -> tuple[bytes, str | None]:
    """Fetch ``url`` and return the body bytes and the response Content-Type."""

    timeout = httpx.Timeout(cfg.timeout_s)
    headers = {
        "User-Agent": cfg.user_agent,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    }

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise ReadError("NetworkError", f"fetch timed out after {cfg.timeout_s}s") from exc
    except httpx.HTTPError as exc:
        raise ReadError("NetworkError", f"fetch failed: {exc}") from exc

    if 300 <= response.status_code < 400:
        loc = response.headers.get("location", "(none)")
        raise ReadError(
            "RemoteError",
            f"refusing to follow redirect to {loc!r} (status {response.status_code}); "
            "call sekurvia_read again on the redirect target if you trust it",
        )
    if response.status_code >= 400:
        raise ReadError(
            "RemoteError", f"upstream returned HTTP {response.status_code}"
        )

    body = response.content
    if len(body) > cfg.max_response_bytes:
        raise ReadError(
            "RemoteError",
            f"response exceeded {cfg.max_response_bytes} bytes (got {len(body)})",
        )
    return body, response.headers.get("content-type")


def _extract(
    html: str | bytes,
    *,
    url: str,
    include_links: bool,
) -> dict[str, Any]:
    """Run trafilatura. Returns ``{"content": ..., "metadata": {...}}`` or empties."""

    if isinstance(html, bytes):
        try:
            html_text = html.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            html_text = html.decode("latin-1", errors="replace")
    else:
        html_text = html

    content = trafilatura.extract(
        html_text,
        url=url,
        output_format="markdown",
        include_links=include_links,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    metadata: dict[str, Any] = {"title": None, "author": None, "publish_date": None}
    try:
        meta = trafilatura.extract_metadata(html_text)
    except Exception:
        meta = None

    if meta is not None:
        metadata["title"] = getattr(meta, "title", None)
        author = getattr(meta, "author", None)
        if isinstance(author, list):
            author = ", ".join(a for a in author if a)
        metadata["author"] = author or None
        publish_date = getattr(meta, "date", None)
        metadata["publish_date"] = publish_date or None

    return {"content": content or "", "metadata": metadata}


async def read_url(args: dict[str, Any], cfg: Config) -> dict[str, Any]:
    """Public entry point used by :mod:`sekurvia_mcp.server`."""

    norm = _normalise_args(args)

    try:
        check_url(norm["url"], cfg)
    except UrlRejected as exc:
        raise ReadError("ValidationError", str(exc)) from exc

    body, content_type = await _fetch(norm["url"], cfg)

    if content_type and not _is_html_like(content_type):
        return {
            "url": norm["url"],
            "title": None,
            "author": None,
            "publish_date": None,
            "content": "",
            "content_length": 0,
            "truncated": False,
            "content_type": content_type,
            "warning": (
                f"content-type {content_type!r} is not html-like; "
                "trafilatura was skipped — fetch with terminal+curl if you need the raw bytes"
            ),
        }

    extracted = _extract(body, url=norm["url"], include_links=norm["include_links"])
    content = extracted["content"]

    truncated = False
    if len(content) > norm["max_chars"]:
        content = content[: norm["max_chars"]].rstrip() + "\n\n…[truncated]"
        truncated = True

    return {
        "url": norm["url"],
        "title": extracted["metadata"]["title"],
        "author": extracted["metadata"]["author"],
        "publish_date": extracted["metadata"]["publish_date"],
        "content": content,
        "content_length": len(content),
        "truncated": truncated,
        "content_type": content_type,
    }


def _is_html_like(content_type: str) -> bool:
    primary = content_type.split(";", 1)[0].strip().lower()
    return primary in {
        "text/html",
        "application/xhtml+xml",
        "application/xml",
        "text/xml",
        "text/plain",
    }
