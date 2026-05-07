"""MCP server entry point.

Registers two tools whose descriptions are written to be assertive enough
that the model picks them over Hermes' auto-registered ``mcp_searxng_*``
when the user asks for live web information. The schemas are strict so a
small model cannot smuggle in invented fields like ``recency_days`` or
``categories: []`` — the server returns a structured error envelope
instead.

The actual work happens in :mod:`sekurvia_mcp.search` and
:mod:`sekurvia_mcp.read`. This module is just the MCP wiring.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import __version__
from .config import (
    HARD_MAX_OUTPUT_CHARS,
    HARD_MAX_RESULTS,
    HARD_MIN_RESULTS,
    Config,
    ConfigError,
    load_config,
)
from .read import ReadError, read_url
from .search import SearchError, searxng_search

log = logging.getLogger("sekurvia_mcp")

SEARCH_DESCRIPTION = (
    "Search the live web via a self-hosted SearXNG instance. Use this for ANY "
    "query requiring real-time data: latest news, current prices, recent events, "
    "library or API documentation lookup, fact-checking. Returns a list of "
    "{title, url, snippet} entries. Pair with `sekurvia_read` to fetch full page "
    "content for the most relevant result(s). Always prefer this over guessing "
    "facts you don't already know — when the user asks about anything time-"
    "sensitive, call this tool first."
)

READ_DESCRIPTION = (
    "Fetch a URL and return the main article text as cleaned markdown — ads, "
    "navigation, comment threads, and footer boilerplate are stripped via "
    "trafilatura. Use after `sekurvia_search` on the most relevant result(s). "
    "Default returns up to 8000 chars; pass `max_chars` (up to 50000) to extend. "
    "Refuses non-routable / private hosts and `file://` schemes."
)


def _search_schema(cfg: Config | None) -> dict[str, Any]:
    """Build the JSON schema for the search tool, baking server defaults in.

    ``cfg`` is optional so we can describe the schema even before the env
    has been validated; we fall back to the documented defaults in that case.
    """

    default_results = cfg.default_max_results if cfg else 10
    default_safesearch = cfg.default_safesearch if cfg else 1
    default_language = cfg.default_language if cfg else "auto"

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1024,
                "description": "Search query. Plain text; SearXNG handles quoting and operators.",
            },
            "max_results": {
                "type": "integer",
                "minimum": HARD_MIN_RESULTS,
                "maximum": HARD_MAX_RESULTS,
                "default": default_results,
                "description": "Cap on returned results after filtering.",
            },
            "time_range": {
                "type": "string",
                "enum": ["", "day", "week", "month", "year"],
                "default": "",
                "description": (
                    "Optional freshness filter. Use 'day' for breaking news, "
                    "'week' for recent updates, etc. Empty for all time. Engine-dependent."
                ),
            },
            "language": {
                "type": "string",
                "default": default_language,
                "description": "ISO 639-1 code or 'auto' / 'all'.",
            },
            "safesearch": {
                "type": "integer",
                "enum": [0, 1, 2],
                "default": default_safesearch,
                "description": "0 off, 1 moderate, 2 strict.",
            },
            "categories": {
                "type": "string",
                "default": "",
                "description": (
                    "Comma-separated SearXNG categories: general (default), news, "
                    "it, science, images, videos. Leave empty for general."
                ),
            },
            "page": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "default": 1,
                "description": "Pagination; 1 is the first page.",
            },
        },
    }


def _read_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["url"],
        "properties": {
            "url": {
                "type": "string",
                "format": "uri",
                "description": "Absolute http(s) URL of a result returned by sekurvia_search.",
            },
            "max_chars": {
                "type": "integer",
                "minimum": 500,
                "maximum": HARD_MAX_OUTPUT_CHARS,
                "default": 8000,
                "description": "Truncate the extracted markdown at this many characters.",
            },
            "include_links": {
                "type": "boolean",
                "default": False,
                "description": "Preserve inline links in the markdown output.",
            },
        },
    }


def _build_tools(cfg: Config | None) -> list[Tool]:
    return [
        Tool(
            name="search",
            description=SEARCH_DESCRIPTION,
            inputSchema=_search_schema(cfg),
        ),
        Tool(
            name="read",
            description=READ_DESCRIPTION,
            inputSchema=_read_schema(),
        ),
    ]


def _error_envelope(kind: str, message: str) -> dict[str, str]:
    """Standard error shape — same as `searxng-query.sh` for parity."""

    return {"error": message, "kind": kind}


def _serialize(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def build_server() -> Server:
    """Build a fresh :class:`mcp.server.Server` instance with both tools wired up."""

    server: Server = Server("sekurvia")

    # Try to load config eagerly so the schema can include the operator's defaults.
    # Failure is tolerated here — the actual validation happens on each tool call.
    try:
        eager_cfg: Config | None = load_config()
    except ConfigError as exc:
        log.warning("config not yet valid at startup: %s", exc)
        eager_cfg = None

    tools = _build_tools(eager_cfg)

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return tools

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[TextContent]:
        args = arguments or {}

        try:
            cfg = load_config()
        except ConfigError as exc:
            return _serialize(_error_envelope("ConfigError", str(exc)))

        try:
            if name == "search":
                payload = await searxng_search(args, cfg)
            elif name == "read":
                payload = await read_url(args, cfg)
            else:
                payload = _error_envelope(
                    "ValidationError",
                    f"unknown tool {name!r}; available tools: search, read",
                )
        except SearchError as exc:
            payload = _error_envelope(exc.kind, exc.message)
        except ReadError as exc:
            payload = _error_envelope(exc.kind, exc.message)
        except Exception as exc:
            log.exception("unhandled error in tool %s", name)
            payload = _error_envelope("InternalError", f"{type(exc).__name__}: {exc}")

        return _serialize(payload)

    return server


async def _run() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="sekurvia",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> int:
    """Console-script entry point. Returns a process exit code."""

    log_level = os.environ.get("SEKURVIA_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        # MCP uses stdout for the protocol; logs MUST go to stderr.
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        return 130
    return 0
