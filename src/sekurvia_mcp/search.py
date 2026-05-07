"""SearXNG JSON-API client used by the ``search`` tool.

This is the Python port of `searxng-search/scripts/searxng-query.sh`. Same
defaults, same response envelope, same hardening posture (bounded timeout,
bounded body size, HTML stripped from titles/snippets, result URLs filtered
through :mod:`sekurvia_mcp.filters`).

The function returns a plain dict so :mod:`sekurvia_mcp.server` can
``json.dumps`` it as the MCP tool response.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from .config import (
    HARD_MAX_RESULTS,
    HARD_MIN_RESULTS,
    Config,
)
from .filters import filter_search_results

_TAG_RE = re.compile(r"<[^>]+>")
_VALID_TIME_RANGES = {"", "day", "week", "month", "year"}


class SearchError(RuntimeError):
    """Raised on a failure that should surface as ``{"error": ..., "kind": ...}``.

    ``kind`` is one of: ``ConfigError``, ``ValidationError``, ``NetworkError``,
    ``RemoteError``. Mirrors the bash helper's contract.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "")


def _coerce_int(name: str, raw: Any, *, lo: int, hi: int) -> int:
    if isinstance(raw, bool):
        raise SearchError("ValidationError", f"{name} must be an integer, not a bool")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise SearchError("ValidationError", f"{name} must be an integer (got: {raw!r})") from exc
    if value < lo or value > hi:
        raise SearchError("ValidationError", f"{name} out of range ({lo}..{hi})")
    return value


def _normalise_args(args: dict[str, Any], cfg: Config) -> dict[str, Any]:
    """Validate caller args, fall back to per-server defaults on omission."""

    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise SearchError("ValidationError", "query is required and must be a non-empty string")
    query = query.strip()
    if len(query) > 1024:
        query = query[:1024]

    max_results = _coerce_int(
        "max_results",
        args.get("max_results", cfg.default_max_results),
        lo=HARD_MIN_RESULTS,
        hi=HARD_MAX_RESULTS,
    )
    safesearch = _coerce_int(
        "safesearch",
        args.get("safesearch", cfg.default_safesearch),
        lo=0,
        hi=2,
    )
    page = _coerce_int("page", args.get("page", 1), lo=1, hi=20)

    time_range = args.get("time_range", "") or ""
    if not isinstance(time_range, str) or time_range not in _VALID_TIME_RANGES:
        raise SearchError(
            "ValidationError",
            f"time_range must be one of {sorted(_VALID_TIME_RANGES)} (got: {time_range!r})",
        )

    language = args.get("language", cfg.default_language) or cfg.default_language
    if not isinstance(language, str):
        raise SearchError("ValidationError", "language must be a string")
    language = language.strip() or cfg.default_language

    categories = args.get("categories", "") or ""
    if not isinstance(categories, str):
        raise SearchError("ValidationError", "categories must be a comma-separated string")

    return {
        "query": query,
        "max_results": max_results,
        "safesearch": safesearch,
        "page": page,
        "time_range": time_range,
        "language": language,
        "categories": categories.strip(),
    }


def _build_form(args: dict[str, Any]) -> dict[str, str]:
    """Build the SearXNG POST form.

    httpx's AsyncClient rejects ``data=[(k, v), ...]`` (it builds a sync
    request stream), so we keep this as a flat dict — there are no
    duplicate keys in the SearXNG form anyway.
    """

    form: dict[str, str] = {
        "q": args["query"],
        "format": "json",
        "safesearch": str(args["safesearch"]),
        "language": args["language"],
        "pageno": str(args["page"]),
    }
    if args["time_range"]:
        form["time_range"] = args["time_range"]
    if args["categories"]:
        form["categories"] = args["categories"]
    return form


def _shape_results(
    raw_results: list[dict[str, Any]],
    *,
    max_snippet: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        url = r.get("url")
        if not isinstance(url, str):
            continue
        title = _strip_html(str(r.get("title") or "")).strip()
        snippet = _strip_html(str(r.get("content") or "")).strip()
        if max_snippet > 0 and len(snippet) > max_snippet:
            snippet = snippet[:max_snippet].rstrip() + "…"
        engine = r.get("engine")
        if not engine:
            engines = r.get("engines")
            if isinstance(engines, list):
                engine = ", ".join(str(e) for e in engines if e)
        score = r.get("score")
        out.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "engine": engine or None,
                "score": float(score) if isinstance(score, (int, float)) else None,
            }
        )
    return out


async def searxng_search(args: dict[str, Any], cfg: Config) -> dict[str, Any]:
    """Run a single SearXNG query, return ``{query, count, results, ...}``."""

    norm = _normalise_args(args, cfg)

    headers = {
        "Accept": "application/json",
        "User-Agent": cfg.user_agent,
    }
    if cfg.auth_token:
        headers["Authorization"] = f"Bearer {cfg.auth_token}"

    url = f"{cfg.searxng_url}/search"
    timeout = httpx.Timeout(cfg.timeout_s)

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post(url, data=_build_form(norm), headers=headers)
    except httpx.TimeoutException as exc:
        raise SearchError(
            "NetworkError", f"SearXNG request timed out after {cfg.timeout_s}s"
        ) from exc
    except httpx.HTTPError as exc:
        raise SearchError("NetworkError", f"SearXNG request failed: {exc}") from exc

    if response.status_code == 403:
        raise SearchError(
            "RemoteError",
            "SearXNG returned 403 — check that 'json' is in `search.formats` of settings.yml",
        )
    if response.status_code >= 400:
        raise SearchError(
            "RemoteError",
            f"SearXNG returned HTTP {response.status_code}",
        )

    body = response.content
    if len(body) > cfg.max_response_bytes:
        raise SearchError(
            "RemoteError",
            f"SearXNG response exceeded {cfg.max_response_bytes} bytes "
            f"(got {len(body)})",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise SearchError(
            "RemoteError",
            "SearXNG returned a non-JSON body — `format=json` may be disabled",
        ) from exc

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return {
            "query": norm["query"],
            "count": 0,
            "results": [],
            "engines_unresponsive": payload.get("unresponsive_engines", []),
        }

    shaped = _shape_results(raw_results, max_snippet=cfg.max_snippet)
    shaped = filter_search_results(shaped, cfg)
    shaped = shaped[: norm["max_results"]]

    return {
        "query": norm["query"],
        "count": len(shaped),
        "results": shaped,
        "engines_unresponsive": payload.get("unresponsive_engines", []),
    }
