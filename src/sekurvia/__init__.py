"""Sekurvia — privacy-respecting web search plugin for Hermes Agent.

Hermes calls :func:`register` exactly once at startup with a
``PluginContext`` that wires our schema, handler, and any future hooks
into the agent. This module is the entry point both for the directory
plugin layout (``~/.hermes/plugins/sekurvia/``) and for the pip
distribution (via the ``hermes_agent.plugins`` entry point in
``pyproject.toml``).
"""

from __future__ import annotations

from typing import Any

from . import schemas, tools

__all__ = ["__version__", "register"]

__version__ = "0.1.1"


def register(ctx: Any) -> None:
    """Register Sekurvia's tools with the Hermes plugin manager."""
    ctx.register_tool(
        name="web_search",
        toolset="sekurvia",
        schema=schemas.WEB_SEARCH,
        handler=tools.web_search,
        is_async=True,
        requires_env=["SEARXNG_URL"],
        description="Privacy-respecting web search via SearXNG",
        emoji="🔎",
    )
