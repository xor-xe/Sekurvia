"""URL reader tests — trafilatura extraction + SSRF rejection + truncation."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
import respx

from sekurvia_mcp.config import Config
from sekurvia_mcp.read import ReadError, read_url

SAMPLE_HTML = """<!doctype html>
<html>
<head>
  <title>Sample article — Hello, World</title>
  <meta name="author" content="Ada Lovelace">
  <meta property="article:published_time" content="2026-04-01T12:00:00Z">
</head>
<body>
  <nav>Home | About | Contact</nav>
  <article>
    <h1>Sample article — Hello, World</h1>
    <p>This is the first paragraph of the body. It contains
    enough words for trafilatura to recognise it as the main article
    block, separate from the navigation and footer boilerplate.</p>
    <p>Second paragraph with some additional context. Lorem ipsum dolor
    sit amet, consectetur adipiscing elit, sed do eiusmod tempor
    incididunt ut labore et dolore magna aliqua.</p>
    <p>Third paragraph. Ut enim ad minim veniam, quis nostrud exercitation
    ullamco laboris nisi ut aliquip ex ea commodo consequat.</p>
  </article>
  <footer>(c) 2026 example.org · advertisement here · cookie banner</footer>
</body>
</html>
"""


@respx.mock
async def test_read_extracts_main_article(cfg: Config) -> None:
    respx.get("https://example.org/article").mock(
        return_value=httpx.Response(
            200,
            text=SAMPLE_HTML,
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )

    payload = await read_url({"url": "https://example.org/article"}, cfg)

    assert payload["url"] == "https://example.org/article"
    assert "first paragraph" in payload["content"]
    # Boilerplate ought to be stripped.
    assert "advertisement here" not in payload["content"]
    assert payload["content_length"] > 0
    assert payload["truncated"] is False


@respx.mock
async def test_read_respects_max_chars(cfg: Config) -> None:
    """Build an article large enough to exceed the 500-char schema minimum."""

    paragraphs = "".join(
        f"<p>Paragraph {i}: " + "lorem ipsum dolor sit amet " * 20 + "</p>\n"
        for i in range(8)
    )
    html = f"""<!doctype html>
<html><head><title>Long Article</title></head>
<body><article><h1>Long Article</h1>{paragraphs}</article></body></html>
"""
    respx.get("https://example.org/long").mock(
        return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )

    payload = await read_url(
        {"url": "https://example.org/long", "max_chars": 500}, cfg
    )
    assert payload["truncated"] is True
    # 500 + ellipsis marker, allow some slack from rstrip().
    assert payload["content_length"] <= 500 + len("\n\n…[truncated]") + 5


@respx.mock
async def test_read_rejects_redirect(cfg: Config) -> None:
    respx.get("https://example.org/start").mock(
        return_value=httpx.Response(302, headers={"location": "https://elsewhere.test/"})
    )
    with pytest.raises(ReadError) as excinfo:
        await read_url({"url": "https://example.org/start"}, cfg)
    assert excinfo.value.kind == "RemoteError"
    assert "redirect" in excinfo.value.message


async def test_read_rejects_loopback(cfg: Config) -> None:
    with pytest.raises(ReadError) as excinfo:
        await read_url({"url": "http://127.0.0.1/admin"}, cfg)
    assert excinfo.value.kind == "ValidationError"
    assert "non-routable" in excinfo.value.message


async def test_read_rejects_file_scheme(cfg: Config) -> None:
    with pytest.raises(ReadError) as excinfo:
        await read_url({"url": "file:///etc/passwd"}, cfg)
    assert excinfo.value.kind == "ValidationError"


async def test_read_validates_max_chars(cfg: Config) -> None:
    with pytest.raises(ReadError) as excinfo:
        await read_url(
            {"url": "https://example.org/x", "max_chars": 50}, cfg
        )
    assert excinfo.value.kind == "ValidationError"


async def test_read_validates_include_links_type(cfg: Config) -> None:
    with pytest.raises(ReadError) as excinfo:
        await read_url(
            {"url": "https://example.org/x", "include_links": "yes"}, cfg
        )
    assert excinfo.value.kind == "ValidationError"


@respx.mock
async def test_read_handles_404(cfg: Config) -> None:
    respx.get("https://example.org/missing").mock(
        return_value=httpx.Response(404, text="not found")
    )
    with pytest.raises(ReadError) as excinfo:
        await read_url({"url": "https://example.org/missing"}, cfg)
    assert excinfo.value.kind == "RemoteError"
    assert "404" in excinfo.value.message


@respx.mock
async def test_read_handles_oversized_body(cfg: Config) -> None:
    cfg2 = replace(cfg, max_response_bytes=1024)
    big = ("<html><body>" + ("x" * 4096) + "</body></html>").encode()
    respx.get("https://example.org/big").mock(
        return_value=httpx.Response(200, content=big, headers={"content-type": "text/html"})
    )
    with pytest.raises(ReadError) as excinfo:
        await read_url({"url": "https://example.org/big"}, cfg2)
    assert excinfo.value.kind == "RemoteError"
    assert "exceeded" in excinfo.value.message.lower()


@respx.mock
async def test_read_skips_non_html(cfg: Config) -> None:
    respx.get("https://example.org/file.pdf").mock(
        return_value=httpx.Response(
            200,
            content=b"%PDF-1.7 ...",
            headers={"content-type": "application/pdf"},
        )
    )
    payload = await read_url({"url": "https://example.org/file.pdf"}, cfg)
    assert payload["content"] == ""
    assert "warning" in payload
    assert payload["content_type"] == "application/pdf"
