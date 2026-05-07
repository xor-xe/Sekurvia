"""URL hardening — SSRF guard, scheme check, allow/blocklist matching."""

from __future__ import annotations

import socket
from dataclasses import replace

import pytest

from sekurvia_mcp.config import Config
from sekurvia_mcp.filters import UrlRejected, _domain_matches, check_url, filter_search_results


def test_rejects_non_http_scheme(cfg: Config) -> None:
    with pytest.raises(UrlRejected, match="scheme not allowed"):
        check_url("file:///etc/passwd", cfg)


def test_rejects_javascript_scheme(cfg: Config) -> None:
    with pytest.raises(UrlRejected, match="scheme not allowed"):
        check_url("javascript:alert(1)", cfg)


def test_rejects_missing_host(cfg: Config) -> None:
    with pytest.raises(UrlRejected, match="missing host"):
        check_url("http://", cfg)


def test_rejects_loopback_literal(cfg: Config) -> None:
    with pytest.raises(UrlRejected, match="non-routable"):
        check_url("http://127.0.0.1/secret", cfg)


def test_rejects_private_literal(cfg: Config) -> None:
    with pytest.raises(UrlRejected, match="non-routable"):
        check_url("http://10.0.0.5/admin", cfg)


def test_rejects_link_local_literal(cfg: Config) -> None:
    with pytest.raises(UrlRejected, match="non-routable"):
        check_url("http://169.254.169.254/latest/meta-data/", cfg)


def test_allow_private_bypasses_ssrf(cfg: Config) -> None:
    """The internal SearXNG client uses ``allow_private=True``."""

    checked = check_url("http://127.0.0.1:8888/search", cfg, allow_private=True)
    assert checked.host == "127.0.0.1"
    assert checked.port == 8888


def test_blocklist_wins(cfg: Config) -> None:
    cfg2 = replace(cfg, blocked_domains=("evil.test",))
    with pytest.raises(UrlRejected, match="BLOCKED_DOMAINS"):
        check_url("http://evil.test/whatever", cfg2)


def test_allowlist_required_when_set(cfg: Config) -> None:
    cfg2 = replace(cfg, allowed_domains=("example.com",))
    with pytest.raises(UrlRejected, match="ALLOWED_DOMAINS"):
        check_url("http://other.example.org/", cfg2)


def test_allowlist_subdomain_match(cfg: Config) -> None:
    cfg2 = replace(cfg, allowed_domains=("example.com",))
    checked = check_url("http://news.example.com/article", cfg2)
    assert checked.host == "news.example.com"


def test_allowlist_overrides_ssrf_for_intranet(cfg: Config) -> None:
    cfg2 = replace(cfg, allowed_domains=("intranet.local",))
    # Even though intranet.local would normally fail DNS (or resolve private),
    # an explicit allowlist entry is the operator opting in.
    checked = check_url("http://intranet.local/wiki", cfg2)
    assert checked.host == "intranet.local"


def test_filter_search_results_drops_bad_urls(cfg: Config) -> None:
    results = [
        {"title": "ok", "url": "https://example.org/a"},
        {"title": "ssrf", "url": "http://127.0.0.1/admin"},
        {"title": "scheme", "url": "file:///etc/passwd"},
        {"title": "no-url"},
    ]
    kept = filter_search_results(results, cfg)
    assert [r["title"] for r in kept] == ["ok"]


def test_domain_match_helper() -> None:
    assert _domain_matches("example.com", ("example.com",))
    assert _domain_matches("a.b.example.com", ("example.com",))
    assert not _domain_matches("notexample.com", ("example.com",))
    assert not _domain_matches("example.com", ())


def test_unresolvable_host_is_not_implicitly_blocked(
    cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolution failure means 'let httpx surface it', not 'reject silently'."""

    def fail(*_a, **_kw):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    checked = check_url("http://does-not-exist.example/", cfg)
    assert checked.host == "does-not-exist.example"
