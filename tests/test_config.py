"""Settings parsing & validation."""

from __future__ import annotations

import pytest

from sekurvia import config
from sekurvia.errors import ConfigError


def test_missing_searxng_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    config.reset_cache()
    with pytest.raises(ConfigError, match="SEARXNG_URL"):
        config.Settings.from_env()


def test_invalid_scheme_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARXNG_URL", "ftp://example.com")
    with pytest.raises(ConfigError, match="http"):
        config.Settings.from_env()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:8888/")
    s = config.Settings.from_env()
    assert s.base_url == "http://127.0.0.1:8888"
    assert s.timeout_s == 10.0
    assert s.max_results == 10
    assert s.default_safesearch == 1
    assert s.default_language == "auto"
    assert s.auth_token is None
    assert s.verify_tls is True
    assert s.domain_allowlist == frozenset()
    assert s.domain_blocklist == frozenset()
    assert s.retries == 2


def test_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARXNG_URL", "https://search.example.com")
    monkeypatch.setenv("SEKURVIA_TIMEOUT_S", "5.5")
    monkeypatch.setenv("SEKURVIA_MAX_RESULTS", "25")
    monkeypatch.setenv("SEKURVIA_SAFESEARCH", "2")
    monkeypatch.setenv("SEKURVIA_LANGUAGE", "de")
    monkeypatch.setenv("SEKURVIA_AUTH_TOKEN", "  secret-token  ")
    monkeypatch.setenv("SEKURVIA_VERIFY_TLS", "false")
    monkeypatch.setenv("SEKURVIA_ALLOWED_DOMAINS", "Example.com, foo.org ,")
    monkeypatch.setenv("SEKURVIA_BLOCKED_DOMAINS", "bad.example")

    s = config.Settings.from_env()
    assert s.timeout_s == 5.5
    assert s.max_results == 25
    assert s.default_safesearch == 2
    assert s.default_language == "de"
    assert s.auth_token == "secret-token"
    assert s.verify_tls is False
    assert s.domain_allowlist == frozenset({"example.com", "foo.org"})
    assert s.domain_blocklist == frozenset({"bad.example"})


def test_max_results_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:8888")
    monkeypatch.setenv("SEKURVIA_MAX_RESULTS", "999")
    with pytest.raises(ConfigError, match="maximum"):
        config.Settings.from_env()


def test_bad_int_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:8888")
    monkeypatch.setenv("SEKURVIA_MAX_RESULTS", "not-a-number")
    with pytest.raises(ConfigError, match="not an integer"):
        config.Settings.from_env()


def test_bad_bool_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:8888")
    monkeypatch.setenv("SEKURVIA_VERIFY_TLS", "maybe")
    with pytest.raises(ConfigError, match="boolean"):
        config.Settings.from_env()


def test_get_settings_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:8888")
    config.reset_cache()
    a = config.get_settings()
    b = config.get_settings()
    assert a is b
    config.reset_cache()
    c = config.get_settings()
    assert c is not a
