"""Env-driven, validated, immutable settings for Sekurvia.

Settings are parsed once per process via :meth:`Settings.from_env`. Tests
should call :func:`reset_cache` between cases that mutate the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlparse

from .errors import ConfigError

_DEFAULT_USER_AGENT = "sekurvia/0.1 (+hermes-plugin)"
_HARD_MAX_RESULTS = 50
_HARD_MIN_RESULTS = 1
_HARD_MAX_QUERY_CHARS = 1024
_HARD_MAX_RESPONSE_BYTES = 16 * 1024 * 1024  # 16 MiB absolute ceiling


def _get_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip()


def _get_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}: not an integer ({raw!r})") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name}: {value} below minimum {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name}: {value} above maximum {maximum}")
    return value


def _get_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}: not a float ({raw!r})") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name}: {value} below minimum {minimum}")
    return value


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in {"1", "true", "yes", "y", "on"}:
        return True
    if val in {"0", "false", "no", "n", "off", ""}:
        return False
    raise ConfigError(f"{name}: not a boolean ({raw!r})")


def _get_csv_set(name: str) -> frozenset[str]:
    raw = os.environ.get(name, "")
    parts = (p.strip().lower() for p in raw.split(","))
    return frozenset(p for p in parts if p)


@dataclass(frozen=True)
class Settings:
    """All runtime knobs in one immutable bag."""

    base_url: str
    timeout_s: float = 10.0
    max_results: int = 10
    default_safesearch: int = 1
    default_language: str = "auto"
    auth_token: str | None = None
    verify_tls: bool = True
    user_agent: str = _DEFAULT_USER_AGENT
    domain_allowlist: frozenset[str] = field(default_factory=frozenset)
    domain_blocklist: frozenset[str] = field(default_factory=frozenset)
    max_snippet_chars: int = 500
    max_query_chars: int = _HARD_MAX_QUERY_CHARS
    max_response_bytes: int = 2 * 1024 * 1024
    retries: int = 2
    retry_backoff_s: float = 0.25

    @classmethod
    def from_env(cls) -> Settings:
        base_url = _get_str("SEARXNG_URL", "")
        if not base_url:
            raise ConfigError(
                "SEARXNG_URL is not set. Point it at your SearXNG instance, "
                "e.g. http://127.0.0.1:8888"
            )
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(
                f"SEARXNG_URL must be http:// or https:// with a host (got {base_url!r})"
            )
        base_url = base_url.rstrip("/")

        safesearch = _get_int("SEKURVIA_SAFESEARCH", 1, minimum=0, maximum=2)

        max_results = _get_int(
            "SEKURVIA_MAX_RESULTS",
            10,
            minimum=_HARD_MIN_RESULTS,
            maximum=_HARD_MAX_RESULTS,
        )

        max_response_bytes = _get_int(
            "SEKURVIA_MAX_RESPONSE_BYTES",
            2 * 1024 * 1024,
            minimum=1024,
            maximum=_HARD_MAX_RESPONSE_BYTES,
        )

        max_snippet = _get_int("SEKURVIA_MAX_SNIPPET", 500, minimum=32, maximum=4096)

        max_query_chars = _get_int(
            "SEKURVIA_MAX_QUERY_CHARS",
            _HARD_MAX_QUERY_CHARS,
            minimum=8,
            maximum=_HARD_MAX_QUERY_CHARS,
        )

        timeout_s = _get_float("SEKURVIA_TIMEOUT_S", 10.0, minimum=0.1)

        retries = _get_int("SEKURVIA_RETRIES", 2, minimum=0, maximum=5)
        retry_backoff_s = _get_float("SEKURVIA_RETRY_BACKOFF_S", 0.25, minimum=0.0)

        verify_tls = _get_bool("SEKURVIA_VERIFY_TLS", True)

        language = _get_str("SEKURVIA_LANGUAGE", "auto") or "auto"

        user_agent = _get_str("SEKURVIA_USER_AGENT", _DEFAULT_USER_AGENT) or _DEFAULT_USER_AGENT

        token_raw = os.environ.get("SEKURVIA_AUTH_TOKEN")
        auth_token: str | None = token_raw.strip() if token_raw and token_raw.strip() else None

        allowlist = _get_csv_set("SEKURVIA_ALLOWED_DOMAINS")
        blocklist = _get_csv_set("SEKURVIA_BLOCKED_DOMAINS")

        return cls(
            base_url=base_url,
            timeout_s=timeout_s,
            max_results=max_results,
            default_safesearch=safesearch,
            default_language=language,
            auth_token=auth_token,
            verify_tls=verify_tls,
            user_agent=user_agent,
            domain_allowlist=allowlist,
            domain_blocklist=blocklist,
            max_snippet_chars=max_snippet,
            max_query_chars=max_query_chars,
            max_response_bytes=max_response_bytes,
            retries=retries,
            retry_backoff_s=retry_backoff_s,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached :class:`Settings` accessor (one validated copy per process)."""
    return Settings.from_env()


def reset_cache() -> None:
    """Drop the cached :class:`Settings`. Tests use this when mutating env."""
    get_settings.cache_clear()
