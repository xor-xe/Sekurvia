"""Sanitization helpers — HTML stripping, URL safety, result cleaning."""

from __future__ import annotations

from sekurvia import sanitize
from sekurvia.config import Settings


def _settings(**overrides) -> Settings:
    base = {
        "base_url": "http://127.0.0.1:8888",
        "max_snippet_chars": 100,
    }
    base.update(overrides)
    return Settings(**base)


class TestStripHtml:
    def test_plain_text(self) -> None:
        assert sanitize.strip_html("hello world", max_chars=100) == "hello world"

    def test_strips_tags(self) -> None:
        out = sanitize.strip_html("<p>Hello <b>world</b></p>", max_chars=100)
        assert out == "Hello world"

    def test_collapses_whitespace(self) -> None:
        out = sanitize.strip_html("a   b\n\n\tc", max_chars=100)
        assert out == "a b c"

    def test_drops_script(self) -> None:
        out = sanitize.strip_html("ok<script>alert(1)</script>more", max_chars=100)
        assert "alert" not in out
        assert "ok" in out and "more" in out

    def test_handles_entities(self) -> None:
        assert sanitize.strip_html("Tom &amp; Jerry", max_chars=100) == "Tom & Jerry"

    def test_truncates(self) -> None:
        out = sanitize.strip_html("a" * 50, max_chars=10)
        assert len(out) == 10
        assert out.endswith("…")

    def test_none_and_non_str(self) -> None:
        assert sanitize.strip_html(None, max_chars=10) == ""
        assert sanitize.strip_html("", max_chars=10) == ""
        assert sanitize.strip_html(42, max_chars=10) == "42"

    def test_malformed_html_does_not_raise(self) -> None:
        out = sanitize.strip_html("<<<not html>>", max_chars=100)
        assert isinstance(out, str)


class TestIsSafeUrl:
    def test_accepts_https(self) -> None:
        assert sanitize.is_safe_url("https://example.com/path", _settings()) is True

    def test_accepts_http(self) -> None:
        assert sanitize.is_safe_url("http://example.com", _settings()) is True

    def test_rejects_other_schemes(self) -> None:
        for url in ("ftp://example.com", "javascript:alert(1)", "file:///etc/passwd"):
            assert sanitize.is_safe_url(url, _settings()) is False

    def test_rejects_loopback(self) -> None:
        assert sanitize.is_safe_url("http://127.0.0.1/", _settings()) is False
        assert sanitize.is_safe_url("http://localhost/", _settings()) is False
        assert sanitize.is_safe_url("http://[::1]/", _settings()) is False

    def test_rejects_private(self) -> None:
        assert sanitize.is_safe_url("http://10.0.0.5", _settings()) is False
        assert sanitize.is_safe_url("http://192.168.1.1", _settings()) is False
        assert sanitize.is_safe_url("http://169.254.0.1", _settings()) is False

    def test_blocklist_blocks(self) -> None:
        s = _settings(domain_blocklist=frozenset({"bad.example"}))
        assert sanitize.is_safe_url("http://bad.example/x", s) is False
        assert sanitize.is_safe_url("http://sub.bad.example/x", s) is False
        assert sanitize.is_safe_url("http://good.example/x", s) is True

    def test_allowlist_restricts(self) -> None:
        s = _settings(domain_allowlist=frozenset({"trusted.com"}))
        assert sanitize.is_safe_url("http://trusted.com/x", s) is True
        assert sanitize.is_safe_url("http://api.trusted.com/x", s) is True
        assert sanitize.is_safe_url("http://other.com/x", s) is False

    def test_allowlist_overrides_loopback_filter(self) -> None:
        s = _settings(domain_allowlist=frozenset({"localhost"}))
        assert sanitize.is_safe_url("http://localhost:9000/", s) is True

    def test_rejects_empty(self) -> None:
        assert sanitize.is_safe_url("", _settings()) is False
        assert sanitize.is_safe_url(None, _settings()) is False
        assert sanitize.is_safe_url("not a url", _settings()) is False


class TestCleanResult:
    def test_minimal_happy_path(self) -> None:
        raw = {
            "title": "<b>Hello</b>",
            "url": "https://example.com/page",
            "content": "A <i>great</i> page.",
            "engine": "duckduckgo",
            "score": 0.83,
        }
        out = sanitize.clean_result(raw, _settings())
        assert out == {
            "title": "Hello",
            "url": "https://example.com/page",
            "snippet": "A great page.",
            "engine": "duckduckgo",
            "score": 0.83,
        }

    def test_drops_unsafe_url(self) -> None:
        raw = {"title": "x", "url": "http://127.0.0.1/", "content": "y"}
        assert sanitize.clean_result(raw, _settings()) is None

    def test_engine_list_joined(self) -> None:
        raw = {"title": "t", "url": "https://example.com", "content": "c", "engine": ["a", "b"]}
        out = sanitize.clean_result(raw, _settings())
        assert out is not None and out["engine"] == "a, b"

    def test_published_optional(self) -> None:
        raw = {
            "title": "t",
            "url": "https://example.com",
            "content": "c",
            "publishedDate": "2026-05-06",
        }
        out = sanitize.clean_result(raw, _settings())
        assert out is not None and out["published"] == "2026-05-06"

    def test_non_dict_returns_none(self) -> None:
        assert sanitize.clean_result("nope", _settings()) is None  # type: ignore[arg-type]
