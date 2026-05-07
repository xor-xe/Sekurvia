"""Env-var validation for `load_config`."""

from __future__ import annotations

import pytest

from sekurvia_mcp.config import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_SAFESEARCH,
    ConfigError,
    load_config,
)


def test_minimal_env_succeeds() -> None:
    cfg = load_config({"SEARXNG_URL": "http://127.0.0.1:8888"})
    assert cfg.searxng_url == "http://127.0.0.1:8888"
    assert cfg.auth_token is None
    assert cfg.default_max_results == DEFAULT_MAX_RESULTS
    assert cfg.default_safesearch == DEFAULT_SAFESEARCH
    assert cfg.allowed_domains == ()
    assert cfg.blocked_domains == ()


def test_strips_trailing_slash() -> None:
    cfg = load_config({"SEARXNG_URL": "http://127.0.0.1:8888/"})
    assert cfg.searxng_url == "http://127.0.0.1:8888"


def test_missing_searxng_url() -> None:
    with pytest.raises(ConfigError, match="SEARXNG_URL is not set"):
        load_config({})


def test_blank_searxng_url() -> None:
    with pytest.raises(ConfigError, match="SEARXNG_URL is not set"):
        load_config({"SEARXNG_URL": "   "})


def test_invalid_scheme() -> None:
    with pytest.raises(ConfigError, match="must start with http"):
        load_config({"SEARXNG_URL": "ftp://example.com"})


def test_no_host() -> None:
    with pytest.raises(ConfigError, match="must include a host"):
        load_config({"SEARXNG_URL": "http://"})


def test_max_results_out_of_range() -> None:
    with pytest.raises(ConfigError, match="SEKURVIA_MAX_RESULTS"):
        load_config(
            {
                "SEARXNG_URL": "http://127.0.0.1:8888",
                "SEKURVIA_MAX_RESULTS": "999",
            }
        )


def test_max_results_non_integer() -> None:
    with pytest.raises(ConfigError, match="SEKURVIA_MAX_RESULTS"):
        load_config(
            {
                "SEARXNG_URL": "http://127.0.0.1:8888",
                "SEKURVIA_MAX_RESULTS": "abc",
            }
        )


def test_safesearch_out_of_range() -> None:
    with pytest.raises(ConfigError, match="SEKURVIA_SAFESEARCH"):
        load_config(
            {
                "SEARXNG_URL": "http://127.0.0.1:8888",
                "SEKURVIA_SAFESEARCH": "5",
            }
        )


def test_response_bytes_out_of_range() -> None:
    with pytest.raises(ConfigError, match="SEKURVIA_MAX_RESPONSE_BYTES"):
        load_config(
            {
                "SEARXNG_URL": "http://127.0.0.1:8888",
                "SEKURVIA_MAX_RESPONSE_BYTES": "100",
            }
        )


def test_domain_lists_parsed_and_lowercased() -> None:
    cfg = load_config(
        {
            "SEARXNG_URL": "http://127.0.0.1:8888",
            "SEKURVIA_ALLOWED_DOMAINS": "Example.com, news.example.com",
            "SEKURVIA_BLOCKED_DOMAINS": " evil.test ,",
        }
    )
    assert cfg.allowed_domains == ("example.com", "news.example.com")
    assert cfg.blocked_domains == ("evil.test",)


def test_auth_token_trimmed() -> None:
    cfg = load_config(
        {
            "SEARXNG_URL": "http://127.0.0.1:8888",
            "SEKURVIA_AUTH_TOKEN": "  abc-123  ",
        }
    )
    assert cfg.auth_token == "abc-123"


def test_auth_token_blank_becomes_none() -> None:
    cfg = load_config(
        {
            "SEARXNG_URL": "http://127.0.0.1:8888",
            "SEKURVIA_AUTH_TOKEN": "   ",
        }
    )
    assert cfg.auth_token is None


def test_user_agent_default_when_unset() -> None:
    cfg = load_config({"SEARXNG_URL": "http://127.0.0.1:8888"})
    assert cfg.user_agent.startswith("sekurvia-mcp/")
