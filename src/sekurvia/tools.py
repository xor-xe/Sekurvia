"""Tool handlers.

Hermes contract (from the plugin guide):

* Signature is ``async def handler(args: dict, **kwargs) -> str``.
* Always return a JSON string — success and error alike.
* Never raise; catch every exception and surface it as JSON.
* Accept ``**kwargs`` so future Hermes context additions don't break us.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import sanitize
from .client import SearxngClient
from .config import Settings, get_settings
from .errors import ConfigError, NetworkError, RemoteError, ValidationError

log = logging.getLogger(__name__)


def _err(message: str, kind: str, **extra: Any) -> str:
    payload: dict[str, Any] = {"error": message, "kind": kind}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _normalize_query(raw: Any, max_chars: int) -> str:
    if not isinstance(raw, str):
        return ""
    cleaned = raw.strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


def _coerce_categories(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    return []


async def web_search(args: dict | None, **_: Any) -> str:
    """Run a single SearXNG web search; return JSON results."""
    args = args or {}

    try:
        settings: Settings = get_settings()
    except ConfigError as exc:
        return _err(str(exc), "ConfigError")

    query = _normalize_query(args.get("query"), settings.max_query_chars)
    if not query:
        return _err("query is required and must be a non-empty string", "ValidationError")

    requested_max = args.get("max_results")
    try:
        max_results = (
            int(requested_max) if requested_max is not None else settings.max_results
        )
    except (TypeError, ValueError):
        return _err("max_results must be an integer", "ValidationError")
    max_results = max(1, min(max_results, settings.max_results))

    language = args.get("language") or settings.default_language

    safesearch = args.get("safesearch")
    if safesearch is None:
        safesearch = settings.default_safesearch
    try:
        safesearch = int(safesearch)
    except (TypeError, ValueError):
        return _err("safesearch must be 0, 1, or 2", "ValidationError")
    if safesearch not in (0, 1, 2):
        return _err("safesearch must be 0, 1, or 2", "ValidationError")

    time_range = args.get("time_range") or ""
    if time_range not in {"", "day", "week", "month", "year"}:
        return _err(
            "time_range must be one of '', 'day', 'week', 'month', 'year'",
            "ValidationError",
        )

    categories = _coerce_categories(args.get("categories"))

    log.debug("sekurvia.web_search len=%d safesearch=%s lang=%s", len(query), safesearch, language)

    try:
        async with SearxngClient(settings) as client:
            raw_results = await client.search(
                query,
                categories=categories or None,
                language=language,
                safesearch=safesearch,
                time_range=time_range,
            )
    except ConfigError as exc:
        return _err(str(exc), "ConfigError")
    except ValidationError as exc:
        return _err(str(exc), "ValidationError")
    except NetworkError as exc:
        return _err(str(exc), "NetworkError")
    except RemoteError as exc:
        payload = {"status_code": exc.status_code} if exc.status_code is not None else {}
        return _err(str(exc), "RemoteError", **payload)
    except Exception:
        log.exception("sekurvia.web_search: unexpected failure")
        return _err("internal error while running search", "InternalError")

    cleaned: list[dict[str, Any]] = []
    for raw in raw_results:
        item = sanitize.clean_result(raw, settings)
        if item is not None:
            cleaned.append(item)
        if len(cleaned) >= max_results:
            break

    payload = {
        "query": query,
        "count": len(cleaned),
        "results": cleaned,
    }
    return json.dumps(payload, ensure_ascii=False)
