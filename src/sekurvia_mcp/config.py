"""Environment-driven configuration for the Sekurvia MCP server.

Mirrors the `SEKURVIA_*` tuning surface of `searxng-search/scripts/searxng-query.sh`
so operators familiar with the bash helper get the same knobs here. All values
have safe defaults; only `SEARXNG_URL` is required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


class ConfigError(ValueError):
    """Raised when an environment variable is missing or malformed.

    Surfaced into MCP tool responses as ``{"error": "...", "kind": "ConfigError"}``
    so the model gets a structured signal instead of a stack trace.
    """


# Defaults match searxng-search/scripts/searxng-query.sh exactly.
DEFAULT_TIMEOUT_S = 10
DEFAULT_MAX_RESULTS = 10
DEFAULT_SAFESEARCH = 1
DEFAULT_LANGUAGE = "auto"
DEFAULT_USER_AGENT = "sekurvia-mcp/0.3"
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MiB
DEFAULT_MAX_SNIPPET = 500
DEFAULT_HEALTH_TIMEOUT_S = 5

# Hard ceilings independent of operator config.
HARD_MAX_RESULTS = 50
HARD_MIN_RESULTS = 1
HARD_MAX_RESPONSE_BYTES = 16 * 1024 * 1024  # 16 MiB
HARD_MAX_OUTPUT_CHARS = 50_000  # `read` tool truncation ceiling.


@dataclass(frozen=True)
class Config:
    """Resolved, validated configuration."""

    searxng_url: str
    auth_token: str | None = None
    timeout_s: int = DEFAULT_TIMEOUT_S
    health_timeout_s: int = DEFAULT_HEALTH_TIMEOUT_S
    default_max_results: int = DEFAULT_MAX_RESULTS
    default_safesearch: int = DEFAULT_SAFESEARCH
    default_language: str = DEFAULT_LANGUAGE
    user_agent: str = DEFAULT_USER_AGENT
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_snippet: int = DEFAULT_MAX_SNIPPET
    allowed_domains: tuple[str, ...] = field(default_factory=tuple)
    blocked_domains: tuple[str, ...] = field(default_factory=tuple)


def _require_positive_int(name: str, raw: str, *, lo: int = 1, hi: int | None = None) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive integer (got: {raw!r})") from exc
    if value < lo:
        raise ConfigError(f"{name} must be >= {lo} (got: {value})")
    if hi is not None and value > hi:
        raise ConfigError(f"{name} must be <= {hi} (got: {value})")
    return value


def _parse_domain_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    items = [chunk.strip().lower() for chunk in raw.split(",")]
    return tuple(item for item in items if item)


def _validate_url(url: str) -> str:
    """Validate scheme/host and strip a trailing slash so callers can append `/search`."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ConfigError(
            f"SEARXNG_URL must start with http:// or https:// (got: {url!r})"
        )
    if not parsed.netloc:
        raise ConfigError(f"SEARXNG_URL must include a host (got: {url!r})")
    return url.rstrip("/")


def load_config(env: dict[str, str] | None = None) -> Config:
    """Read and validate config from ``env`` (defaults to ``os.environ``).

    Tests pass an explicit dict so we don't have to monkeypatch the process
    environment. Production callers (``server.py``) pass nothing and pick up
    whatever the agent's environment provides — on nyxorn that includes
    ``SEARXNG_URL=http://127.0.0.1:8888`` automatically when
    ``services.aiAgent.enableSearxng = true``.
    """

    src = env if env is not None else dict(os.environ)

    raw_url = src.get("SEARXNG_URL", "").strip()
    if not raw_url:
        raise ConfigError(
            "SEARXNG_URL is not set; point it at your SearXNG instance, "
            "e.g. http://127.0.0.1:8888"
        )
    searxng_url = _validate_url(raw_url)

    auth_token = src.get("SEKURVIA_AUTH_TOKEN", "").strip() or None

    timeout_s = _require_positive_int(
        "SEKURVIA_TIMEOUT_S",
        src.get("SEKURVIA_TIMEOUT_S", str(DEFAULT_TIMEOUT_S)),
        lo=1,
        hi=120,
    )
    health_timeout_s = _require_positive_int(
        "SEKURVIA_HEALTH_TIMEOUT_S",
        src.get("SEKURVIA_HEALTH_TIMEOUT_S", str(DEFAULT_HEALTH_TIMEOUT_S)),
        lo=1,
        hi=60,
    )
    default_max_results = _require_positive_int(
        "SEKURVIA_MAX_RESULTS",
        src.get("SEKURVIA_MAX_RESULTS", str(DEFAULT_MAX_RESULTS)),
        lo=HARD_MIN_RESULTS,
        hi=HARD_MAX_RESULTS,
    )
    default_safesearch = _require_positive_int(
        "SEKURVIA_SAFESEARCH",
        src.get("SEKURVIA_SAFESEARCH", str(DEFAULT_SAFESEARCH)),
        lo=0,
        hi=2,
    )

    language_raw = src.get("SEKURVIA_LANGUAGE", DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE

    user_agent = src.get("SEKURVIA_USER_AGENT", DEFAULT_USER_AGENT).strip() or DEFAULT_USER_AGENT

    max_response_bytes = _require_positive_int(
        "SEKURVIA_MAX_RESPONSE_BYTES",
        src.get("SEKURVIA_MAX_RESPONSE_BYTES", str(DEFAULT_MAX_RESPONSE_BYTES)),
        lo=1024,
        hi=HARD_MAX_RESPONSE_BYTES,
    )
    max_snippet = _require_positive_int(
        "SEKURVIA_MAX_SNIPPET",
        src.get("SEKURVIA_MAX_SNIPPET", str(DEFAULT_MAX_SNIPPET)),
        lo=80,
        hi=4000,
    )

    allowed = _parse_domain_list(src.get("SEKURVIA_ALLOWED_DOMAINS"))
    blocked = _parse_domain_list(src.get("SEKURVIA_BLOCKED_DOMAINS"))

    return Config(
        searxng_url=searxng_url,
        auth_token=auth_token,
        timeout_s=timeout_s,
        health_timeout_s=health_timeout_s,
        default_max_results=default_max_results,
        default_safesearch=default_safesearch,
        default_language=language_raw,
        user_agent=user_agent,
        max_response_bytes=max_response_bytes,
        max_snippet=max_snippet,
        allowed_domains=allowed,
        blocked_domains=blocked,
    )
