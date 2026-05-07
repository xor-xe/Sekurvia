---
name: searxng-search
description: Routes the model to the Sekurvia MCP web-search and web-read tools. Not a callable tool itself — invoke `mcp_sekurvia_search` (preferred) or `mcp_searxng_searxng_web_search` (fallback) instead. Sized to fit in any model's working context without crowding the toolset.
version: 0.3.0
author: xor-xe
license: MIT
metadata:
  hermes:
    tags: [search, searxng, sekurvia, mcp, web-search, privacy, self-hosted]
    related_skills: [duckduckgo-search]
    fallback_for_toolsets: [web]
    fallback_for_tools: [web_search]
---

# Web search on this host

`searxng-search` is a SKILL (markdown), **not a tool**. Do **not** emit a tool
call with `name: "searxng-search"` — the runtime will reject it. Call one of
the real tools listed below.

## Preferred (use these — they always work on this stack)

- `mcp_sekurvia_search` `{ "query": "..." }` → `{count, results: [{title, url, snippet}]}`
- `mcp_sekurvia_read`   `{ "url": "..." }`   → `{title, content, ...}` cleaned markdown

These are exposed by the Sekurvia MCP server. Their **full input schema is
already in your tool list** — read it there. Do not invent fields.

## Hermes built-in (acceptable fallback if Sekurvia is absent)

- `mcp_searxng_searxng_web_search`
- `mcp_searxng_web_url_read`

## Procedure for "latest / current / recent X" questions

1. Call `mcp_sekurvia_search` with the user's question as `query`. For news
   or stock-price questions add `time_range: "day"`.
2. Pick the 1–3 most relevant URLs from the response.
3. Call `mcp_sekurvia_read` on each. Increase `max_chars` (up to 50000) for
   long-form articles.
4. Synthesize an answer that cites each URL.

## Don't

- Do not pass `recency_days`, `categories: []`, or `max_results` blindly —
  the schema in your tool list is authoritative.
- Do not speculate about whether `SEARXNG_URL` is set or invent variables
  like `REQUIRED_ENVIRONMENT_VARIABLES` or `SEKURVIA_ENABLED`. They don't
  exist. The MCP server fails with a structured error if misconfigured;
  surface that error verbatim instead of guessing.
- Do not chain multiple search backends in one turn. Pick `sekurvia` or
  `searxng`, not both.

## On error

If a Sekurvia tool returns `{"error": "...", "kind": "..."}`:

| `kind`            | Meaning                                          | What to do                                                          |
|-------------------|--------------------------------------------------|---------------------------------------------------------------------|
| `ConfigError`     | `SEARXNG_URL` missing/invalid                    | Tell the user to set it (or `services.aiAgent.enableSearxng = true` on nyxorn). Do not retry blindly. |
| `NetworkError`    | timeout / DNS / connection refused               | Try the Hermes built-in fallback once; if that also fails, surface the error. |
| `RemoteError`     | 4xx / 5xx / non-JSON / `format=json` disabled    | Surface the error; suggest `searxng-search/scripts/searxng-health.sh` if it's a 403. |
| `ValidationError` | bad arguments (URL filter, schema, etc.)         | Re-issue with corrected args; do not retry the same payload.        |

That is the entire flow. Anything longer is room for hallucination.
