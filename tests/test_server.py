"""Server wiring — schemas, error envelope shape, missing-config handling."""

from __future__ import annotations

import json

from sekurvia_mcp.server import (
    READ_DESCRIPTION,
    SEARCH_DESCRIPTION,
    _error_envelope,
    _read_schema,
    _search_schema,
)


def test_search_schema_is_strict() -> None:
    schema = _search_schema(None)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["query"]
    assert "query" in schema["properties"]
    assert "max_results" in schema["properties"]
    # The hallucinated fields the model kept inventing must NOT be in the schema.
    assert "recency_days" not in schema["properties"]


def test_read_schema_is_strict() -> None:
    schema = _read_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["url"]
    assert schema["properties"]["max_chars"]["maximum"] == 50_000


def test_error_envelope_shape() -> None:
    env = _error_envelope("ConfigError", "SEARXNG_URL is not set")
    # MCP transport wraps this in TextContent; the inner dict is what the model sees.
    assert env == {"error": "SEARXNG_URL is not set", "kind": "ConfigError"}
    # Round-trip JSON to ensure the model can parse it.
    assert json.loads(json.dumps(env)) == env


def test_descriptions_mention_pairing() -> None:
    """Tool descriptions are read by the model on every turn — make sure they
    actually steer toward the paired-call pattern."""

    assert "sekurvia_read" in SEARCH_DESCRIPTION
    assert "sekurvia_search" in READ_DESCRIPTION
    assert "real-time" in SEARCH_DESCRIPTION.lower() or "live" in SEARCH_DESCRIPTION.lower()
