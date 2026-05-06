"""Tool schemas — what the LLM reads to decide when to call our tools.

Per the Hermes plugin guide, the ``description`` is the model's main
signal for tool selection, so it must be specific about what the tool
does, when to use it, and what it returns.
"""

from __future__ import annotations

WEB_SEARCH: dict = {
    "name": "web_search",
    "description": (
        "Search the public web via a privacy-respecting SearXNG instance. "
        "Returns a ranked list of results, each with a title, URL, and short "
        "snippet. Use for general factual queries, recent events, library or "
        "API documentation, and looking up authoritative URLs to cite. "
        "Does NOT fetch full page content — call this first, then use a "
        "page-fetching tool on a chosen result if you need the body. "
        "Results are sanitized: HTML stripped, snippets length-capped, "
        "loopback/private hosts filtered out."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The search query. Use natural language or keywords; "
                    "SearXNG aggregates across multiple upstream engines."
                ),
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": (
                    "How many results to return (default: configured "
                    "SEKURVIA_MAX_RESULTS, typically 10)."
                ),
            },
            "language": {
                "type": "string",
                "description": (
                    "ISO language code such as 'en', 'de', 'fr'. Use 'auto' "
                    "(default) to let SearXNG pick based on the query."
                ),
            },
            "safesearch": {
                "type": "integer",
                "enum": [0, 1, 2],
                "description": (
                    "0 = off, 1 = moderate (default), 2 = strict. Use 0 only "
                    "when the user explicitly requests unfiltered results."
                ),
            },
            "time_range": {
                "type": "string",
                "enum": ["", "day", "week", "month", "year"],
                "description": (
                    "Restrict results to recent content. Empty string (default) "
                    "means no restriction. Use 'day' or 'week' for breaking news."
                ),
            },
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional SearXNG categories to query (e.g. ['general'], "
                    "['it'], ['science']). Defaults to SearXNG's configured "
                    "default category."
                ),
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}
