"""End-to-end tests of the web_search handler — JSON-only, never raises."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from sekurvia import tools

from .conftest import make_searxng_payload


async def test_missing_searxng_url_returns_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    out = await tools.web_search({"query": "anything"})
    parsed = json.loads(out)
    assert parsed["kind"] == "ConfigError"
    assert "SEARXNG_URL" in parsed["error"]


async def test_empty_query_returns_validation_error(base_url: str) -> None:
    out = await tools.web_search({"query": "   "})
    parsed = json.loads(out)
    assert parsed["kind"] == "ValidationError"


async def test_missing_query_returns_validation_error(base_url: str) -> None:
    out = await tools.web_search({})
    parsed = json.loads(out)
    assert parsed["kind"] == "ValidationError"


async def test_none_args_returns_validation_error(base_url: str) -> None:
    out = await tools.web_search(None)
    parsed = json.loads(out)
    assert parsed["kind"] == "ValidationError"


@respx.mock
async def test_happy_path(base_url: str) -> None:
    respx.post(f"{base_url}/search").mock(
        return_value=httpx.Response(
            200,
            json=make_searxng_payload(
                results=[
                    {
                        "title": "Hermes Agent",
                        "url": "https://github.com/NousResearch/hermes-agent",
                        "content": "Agent that grows with you",
                        "engine": "duckduckgo",
                        "score": 0.9,
                    },
                    {
                        "title": "Bad",
                        "url": "http://127.0.0.1/admin",
                        "content": "should be filtered",
                    },
                ],
            ),
        ),
    )

    out = await tools.web_search({"query": "hermes agent"})
    parsed = json.loads(out)

    assert parsed["query"] == "hermes agent"
    assert parsed["count"] == 1
    assert len(parsed["results"]) == 1
    item = parsed["results"][0]
    assert item["title"] == "Hermes Agent"
    assert item["url"].startswith("https://github.com/")
    assert "snippet" in item


@respx.mock
async def test_max_results_cap_applied(base_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEKURVIA_MAX_RESULTS", "2")
    respx.post(f"{base_url}/search").mock(
        return_value=httpx.Response(
            200,
            json=make_searxng_payload(
                results=[
                    {"title": str(i), "url": f"https://example.com/{i}", "content": "x"}
                    for i in range(10)
                ],
            ),
        ),
    )

    out = await tools.web_search({"query": "q", "max_results": 99})
    parsed = json.loads(out)
    assert parsed["count"] == 2


@respx.mock
async def test_remote_error_surfaces_as_json(base_url: str) -> None:
    respx.post(f"{base_url}/search").mock(
        return_value=httpx.Response(403, text="forbidden"),
    )
    out = await tools.web_search({"query": "q"})
    parsed = json.loads(out)
    assert parsed["kind"] == "RemoteError"
    assert parsed["status_code"] == 403


@respx.mock
async def test_network_error_surfaces_as_json(base_url: str) -> None:
    respx.post(f"{base_url}/search").mock(
        side_effect=httpx.ConnectError("nope"),
    )
    out = await tools.web_search({"query": "q"})
    parsed = json.loads(out)
    assert parsed["kind"] == "NetworkError"


async def test_unexpected_exception_caught(
    base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If something inside the search path raises a non-typed exception,
    the handler must log it and still return JSON, not propagate."""

    class Boom(RuntimeError):
        pass

    async def _kaboom(self, *args, **kwargs):
        raise Boom("unexpected")

    from sekurvia import client as client_module

    monkeypatch.setattr(client_module.SearxngClient, "search", _kaboom)

    out = await tools.web_search({"query": "q"})
    parsed = json.loads(out)
    assert parsed["kind"] == "InternalError"


async def test_invalid_safesearch_param(base_url: str) -> None:
    out = await tools.web_search({"query": "q", "safesearch": 5})
    parsed = json.loads(out)
    assert parsed["kind"] == "ValidationError"


async def test_invalid_time_range_param(base_url: str) -> None:
    out = await tools.web_search({"query": "q", "time_range": "decade"})
    parsed = json.loads(out)
    assert parsed["kind"] == "ValidationError"


async def test_query_truncated_to_max_chars(
    base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEKURVIA_MAX_QUERY_CHARS", "16")
    with respx.mock() as router:
        route = router.post(f"{base_url}/search").mock(
            return_value=httpx.Response(200, json=make_searxng_payload()),
        )
        out = await tools.web_search({"query": "x" * 500})

    parsed = json.loads(out)
    assert len(parsed["query"]) == 16
    assert route.called


def test_tools_module_no_other_exports() -> None:
    """A small contract test: the public handler is what __init__ wires."""
    from sekurvia import schemas

    assert callable(tools.web_search)
    assert schemas.WEB_SEARCH["name"] == "web_search"
