"""SearxngClient integration tests (httpx mocked via respx)."""

from __future__ import annotations

import httpx
import pytest
import respx

from sekurvia.client import SearxngClient
from sekurvia.config import Settings
from sekurvia.errors import NetworkError, RemoteError

from .conftest import make_searxng_payload


def _settings(**overrides) -> Settings:
    base = {
        "base_url": "http://127.0.0.1:8888",
        "timeout_s": 1.0,
        "retries": 1,
        "retry_backoff_s": 0.0,
        "max_response_bytes": 64 * 1024,
    }
    base.update(overrides)
    return Settings(**base)


@respx.mock
async def test_search_happy_path() -> None:
    payload = make_searxng_payload(
        results=[{"title": "T", "url": "https://example.com", "content": "C"}],
    )
    route = respx.post("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, json=payload),
    )

    async with SearxngClient(_settings()) as client:
        results = await client.search("hello")

    assert route.called
    assert results == payload["results"]
    request = route.calls.last.request
    assert b"q=hello" in request.content
    assert b"format=json" in request.content
    assert b"safesearch=1" in request.content
    assert "Authorization" not in request.headers


@respx.mock
async def test_auth_header_added_when_token_set() -> None:
    respx.post("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, json=make_searxng_payload()),
    )

    s = _settings(auth_token="hunter2")
    async with SearxngClient(s) as client:
        await client.search("q")

    sent = respx.calls.last.request
    assert sent.headers["Authorization"] == "Bearer hunter2"


@respx.mock
async def test_5xx_retried_then_succeeds() -> None:
    route = respx.post("http://127.0.0.1:8888/search").mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(200, json=make_searxng_payload()),
        ],
    )

    async with SearxngClient(_settings(retries=1)) as client:
        results = await client.search("q")

    assert results == []
    assert route.call_count == 2


@respx.mock
async def test_5xx_exhausts_retries() -> None:
    respx.post("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(500, text="boom"),
    )

    async with SearxngClient(_settings(retries=1)) as client:
        with pytest.raises(RemoteError) as excinfo:
            await client.search("q")
    assert excinfo.value.status_code == 500


@respx.mock
async def test_4xx_not_retried() -> None:
    route = respx.post("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(403, text="nope"),
    )

    async with SearxngClient(_settings(retries=2)) as client:
        with pytest.raises(RemoteError):
            await client.search("q")
    assert route.call_count == 1


@respx.mock
async def test_timeout_becomes_network_error() -> None:
    respx.post("http://127.0.0.1:8888/search").mock(
        side_effect=httpx.TimeoutException("slow"),
    )

    async with SearxngClient(_settings(retries=0)) as client:
        with pytest.raises(NetworkError, match="timed out"):
            await client.search("q")


@respx.mock
async def test_transport_error_becomes_network_error() -> None:
    respx.post("http://127.0.0.1:8888/search").mock(
        side_effect=httpx.ConnectError("refused"),
    )

    async with SearxngClient(_settings(retries=0)) as client:
        with pytest.raises(NetworkError):
            await client.search("q")


@respx.mock
async def test_non_json_body_rejected() -> None:
    respx.post("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, text="<html>not json</html>"),
    )

    async with SearxngClient(_settings()) as client:
        with pytest.raises(RemoteError, match="non-JSON"):
            await client.search("q")


@respx.mock
async def test_missing_results_key_rejected() -> None:
    respx.post("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, json={"query": "x"}),
    )

    async with SearxngClient(_settings()) as client:
        with pytest.raises(RemoteError, match="results"):
            await client.search("q")


@respx.mock
async def test_response_size_cap() -> None:
    huge = "x" * 200_000
    respx.post("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, text=huge),
    )

    async with SearxngClient(_settings(max_response_bytes=1024)) as client:
        with pytest.raises(RemoteError, match="exceeded"):
            await client.search("q")


@respx.mock
async def test_categories_and_time_range_serialized() -> None:
    route = respx.post("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, json=make_searxng_payload()),
    )

    async with SearxngClient(_settings()) as client:
        await client.search(
            "q",
            categories=["general", "it"],
            time_range="week",
            language="en",
            safesearch=2,
        )

    body = route.calls.last.request.content
    assert b"categories=general%2Cit" in body
    assert b"time_range=week" in body
    assert b"language=en" in body
    assert b"safesearch=2" in body


@respx.mock
async def test_invalid_safesearch_falls_back_to_default() -> None:
    respx.post("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, json=make_searxng_payload()),
    )

    s = _settings(default_safesearch=2)
    async with SearxngClient(s) as client:
        await client.search("q", safesearch=99)

    assert b"safesearch=2" in respx.calls.last.request.content
