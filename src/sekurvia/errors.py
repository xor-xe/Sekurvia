"""Typed errors surfaced by Sekurvia.

Handlers translate these into structured JSON responses; the LLM sees
`error` + `kind` instead of opaque tracebacks. Anything else that escapes
is logged and reported as ``InternalError``.
"""

from __future__ import annotations


class SekurviaError(Exception):
    """Base class for all Sekurvia-specific errors."""


class ConfigError(SekurviaError):
    """Raised when environment / configuration is missing or invalid."""


class ValidationError(SekurviaError):
    """Raised when a value (URL, parameter) fails a safety check."""


class NetworkError(SekurviaError):
    """Raised on timeouts, connection failures, DNS errors, etc."""


class RemoteError(SekurviaError):
    """Raised when SearXNG returns a non-2xx response or malformed body."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
