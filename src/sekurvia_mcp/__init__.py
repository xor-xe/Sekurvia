"""Sekurvia MCP server.

Exposes two tools to a Hermes Agent (or any MCP-compatible client) over stdio:

- ``search`` – SearXNG-backed web search, surfaces in clients as
  ``mcp_sekurvia_search``.
- ``read`` – URL fetcher with trafilatura-based main-content extraction,
  surfaces as ``mcp_sekurvia_read``.

The package is intentionally additive: it does not require the Hermes-Agent
built-in ``mcp_searxng_*`` toolset to be disabled and does not collide with
it on tool names.
"""

from .config import Config, ConfigError, load_config

__all__ = ["Config", "ConfigError", "__version__", "load_config"]

__version__ = "0.3.0"
