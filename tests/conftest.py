"""Test fixtures: a clean env baseline and a fake SearXNG response factory."""

from __future__ import annotations

from typing import Any

import pytest

from sekurvia import config

_SEKURVIA_ENV_KEYS = (
    "SEARXNG_URL",
    "SEKURVIA_TIMEOUT_S",
    "SEKURVIA_MAX_RESULTS",
    "SEKURVIA_SAFESEARCH",
    "SEKURVIA_LANGUAGE",
    "SEKURVIA_AUTH_TOKEN",
    "SEKURVIA_VERIFY_TLS",
    "SEKURVIA_USER_AGENT",
    "SEKURVIA_ALLOWED_DOMAINS",
    "SEKURVIA_BLOCKED_DOMAINS",
    "SEKURVIA_MAX_SNIPPET",
    "SEKURVIA_MAX_QUERY_CHARS",
    "SEKURVIA_MAX_RESPONSE_BYTES",
    "SEKURVIA_RETRIES",
    "SEKURVIA_RETRY_BACKOFF_S",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every Sekurvia env var so tests start from a known state."""
    for key in _SEKURVIA_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    config.reset_cache()
    yield
    config.reset_cache()


@pytest.fixture
def base_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """A safe default SearXNG base URL for tests that need one."""
    url = "http://127.0.0.1:8888"
    monkeypatch.setenv("SEARXNG_URL", url)
    return url


def make_searxng_payload(
    *,
    results: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal SearXNG-shaped JSON payload for respx mocks."""
    payload: dict[str, Any] = {
        "query": "test",
        "number_of_results": 0,
        "results": results or [],
        "answers": [],
        "corrections": [],
        "infoboxes": [],
        "suggestions": [],
        "unresponsive_engines": [],
    }
    if extra:
        payload.update(extra)
    return payload
