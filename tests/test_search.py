"""SearXNG client tests using respx to stub httpx."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from sekurvia_mcp.config import Config
from sekurvia_mcp.search import SearchError, searxng_search


def _searxng_payload(results: list[dict]) -> dict:
    return {"query": "x", "results": results, "unresponsive_engines": []}


@respx.mock
async def test_happy_path_strips_html_and_caps_snippet(cfg: Config) -> None:
    cfg2 = Config(**{**cfg.__dict__, "max_snippet": 30})
    long_snippet = "<b>" + ("a" * 100) + "</b>"
    route = respx.post("http://searxng.test/search").mock(
        return_value=httpx.Response(
            200,
            json=_searxng_payload(
                [
                    {
                        "title": "<em>Hello</em>",
                        "url": "https://example.org/article",
                        "content": long_snippet,
                        "engine": "duckduckgo",
                        "score": 0.42,
                    }
                ]
            ),
        )
    )

    payload = await searxng_search({"query": "rust ownership"}, cfg2)

    assert route.called
    assert payload["count"] == 1
    result = payload["results"][0]
    assert result["title"] == "Hello"
    assert "<" not in result["snippet"]
    assert len(result["snippet"]) <= 31  # 30 chars + ellipsis
    assert result["engine"] == "duckduckgo"
    assert result["score"] == pytest.approx(0.42)


@respx.mock
async def test_jsonless_response_becomes_remote_error(cfg: Config) -> None:
    respx.post("http://searxng.test/search").mock(
        return_value=httpx.Response(200, text="<html>nope</html>")
    )

    with pytest.raises(SearchError) as excinfo:
        await searxng_search({"query": "x"}, cfg)
    assert excinfo.value.kind == "RemoteError"
    assert "non-JSON" in excinfo.value.message


@respx.mock
async def test_403_signals_json_disabled(cfg: Config) -> None:
    respx.post("http://searxng.test/search").mock(
        return_value=httpx.Response(403, text="forbidden")
    )

    with pytest.raises(SearchError) as excinfo:
        await searxng_search({"query": "x"}, cfg)
    assert excinfo.value.kind == "RemoteError"
    assert "json" in excinfo.value.message.lower()


@respx.mock
async def test_500_is_remote_error(cfg: Config) -> None:
    respx.post("http://searxng.test/search").mock(
        return_value=httpx.Response(500, text="boom")
    )

    with pytest.raises(SearchError) as excinfo:
        await searxng_search({"query": "x"}, cfg)
    assert excinfo.value.kind == "RemoteError"
    assert "500" in excinfo.value.message


@respx.mock
async def test_timeout_becomes_network_error(cfg: Config) -> None:
    respx.post("http://searxng.test/search").mock(
        side_effect=httpx.ConnectTimeout("timeout")
    )

    with pytest.raises(SearchError) as excinfo:
        await searxng_search({"query": "x"}, cfg)
    assert excinfo.value.kind == "NetworkError"


async def test_validation_error_on_blank_query(cfg: Config) -> None:
    with pytest.raises(SearchError) as excinfo:
        await searxng_search({"query": "   "}, cfg)
    assert excinfo.value.kind == "ValidationError"


async def test_validation_error_on_bad_time_range(cfg: Config) -> None:
    with pytest.raises(SearchError) as excinfo:
        await searxng_search({"query": "x", "time_range": "1d"}, cfg)
    assert excinfo.value.kind == "ValidationError"


async def test_validation_error_on_bad_safesearch(cfg: Config) -> None:
    with pytest.raises(SearchError) as excinfo:
        await searxng_search({"query": "x", "safesearch": 9}, cfg)
    assert excinfo.value.kind == "ValidationError"


@respx.mock
async def test_results_filtered_for_ssrf(cfg: Config) -> None:
    respx.post("http://searxng.test/search").mock(
        return_value=httpx.Response(
            200,
            json=_searxng_payload(
                [
                    {"title": "ok", "url": "https://example.org/a", "content": ""},
                    {"title": "ssrf", "url": "http://127.0.0.1/admin", "content": ""},
                ]
            ),
        )
    )
    payload = await searxng_search({"query": "x"}, cfg)
    assert [r["title"] for r in payload["results"]] == ["ok"]


@respx.mock
async def test_max_results_caps_output(cfg: Config) -> None:
    raw = [
        {"title": f"r{i}", "url": f"https://example.org/{i}", "content": ""}
        for i in range(20)
    ]
    respx.post("http://searxng.test/search").mock(
        return_value=httpx.Response(200, json=_searxng_payload(raw))
    )
    payload = await searxng_search({"query": "x", "max_results": 3}, cfg)
    assert payload["count"] == 3


@respx.mock
async def test_auth_token_sent_when_configured(cfg: Config) -> None:
    cfg2 = Config(**{**cfg.__dict__, "auth_token": "abc-123"})
    route = respx.post("http://searxng.test/search").mock(
        return_value=httpx.Response(200, json=_searxng_payload([]))
    )

    await searxng_search({"query": "x"}, cfg2)

    assert route.called
    sent_request = route.calls[0].request
    assert sent_request.headers.get("authorization") == "Bearer abc-123"


@respx.mock
async def test_form_includes_query_and_format_json(cfg: Config) -> None:
    route = respx.post("http://searxng.test/search").mock(
        return_value=httpx.Response(200, json=_searxng_payload([]))
    )

    await searxng_search({"query": "S&P 500", "time_range": "day"}, cfg)

    body = route.calls[0].request.content.decode()
    assert "q=S%26P+500" in body or "q=S%26P%20500" in body
    assert "format=json" in body
    assert "time_range=day" in body


@respx.mock
async def test_empty_results_returns_zero_count(cfg: Config) -> None:
    respx.post("http://searxng.test/search").mock(
        return_value=httpx.Response(200, json={"results": [], "unresponsive_engines": []})
    )
    payload = await searxng_search({"query": "x"}, cfg)
    assert payload["count"] == 0
    assert payload["results"] == []


@respx.mock
async def test_oversized_response_rejected(cfg: Config) -> None:
    cfg2 = Config(**{**cfg.__dict__, "max_response_bytes": 1024})
    huge = json.dumps(_searxng_payload([{"title": "x" * 5000, "url": "https://e.org/", "content": "y" * 5000}] * 5))
    respx.post("http://searxng.test/search").mock(
        return_value=httpx.Response(200, content=huge.encode(), headers={"content-type": "application/json"})
    )
    with pytest.raises(SearchError) as excinfo:
        await searxng_search({"query": "x"}, cfg2)
    assert excinfo.value.kind == "RemoteError"
    assert "exceeded" in excinfo.value.message.lower()
