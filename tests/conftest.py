"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from sekurvia_mcp.config import Config


@pytest.fixture()
def cfg() -> Config:
    """A baseline config that points at a fake local SearXNG.

    Tests that need different env values build their own Config — this is
    just the convenient default.
    """

    return Config(
        searxng_url="http://searxng.test",
        auth_token=None,
        timeout_s=5,
        health_timeout_s=5,
        default_max_results=5,
        default_safesearch=1,
        default_language="auto",
        user_agent="sekurvia-mcp/test",
        max_response_bytes=1_000_000,
        max_snippet=200,
        allowed_domains=(),
        blocked_domains=(),
    )
