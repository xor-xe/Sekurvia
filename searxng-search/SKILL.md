---
name: searxng-search
description: Guidance (not a tool) for hitting a self-hosted SearXNG instance from Hermes. Teaches the model to call the real `mcp_searxng_searxng_web_search` MCP tool when present, or `terminal` running the bundled `searxng-query.sh` helper as a fallback. Use when an `mcp_searxng_*` tool is advertised, or when SEARXNG_URL is set.
version: 0.2.0
author: xor-xe
license: MIT
metadata:
  hermes:
    tags: [search, searxng, web-search, privacy, self-hosted, fallback, mcp]
    related_skills: [duckduckgo-search]
    fallback_for_toolsets: [web]
    fallback_for_tools: [web_search]
required_environment_variables:
  - name: SEARXNG_URL
    prompt: "Base URL of your SearXNG instance (e.g. http://127.0.0.1:8888)"
    help: "Run a local instance with `services.searx.enable = true;` on NixOS, the upstream Docker image, or point at any reachable SearXNG. The URL must include scheme (http:// or https://) and host."
    required_for: full functionality
  - name: SEKURVIA_AUTH_TOKEN
    prompt: "Bearer token for authenticated SearXNG instances (optional)"
    help: "Only needed if your SearXNG instance is gated behind a reverse proxy that checks Authorization Bearer headers. Leave unset for local instances."
    required_for: protected SearXNG only
---

# SearXNG Search

Privacy-respecting web search using a self-hosted [SearXNG](https://searxng.org/) instance. **No third-party API key required** — all queries go to the operator's own SearXNG, which aggregates results from upstream engines without leaking the user's identity to them.

> ## ⚠ This is a SKILL, not a tool
>
> `searxng-search` is the *name of this guidance document*, not a callable function. **Do not** emit a tool call with `name: "searxng-search"` — the runtime will reject it with:
>
> ```text
> Tool 'searxng-search' does not exist.
> ```
>
> Instead, invoke one of the real tools your runtime advertises (in priority order):
>
> 1. **`mcp_searxng_searxng_web_search`** + **`mcp_searxng_web_url_read`** — preferred when these MCP tools are exposed. See [Method 0](#method-0-mcp-searxng-tool-preferred).
> 2. **`terminal`** (or `execute_code`) running the bundled `searxng-query.sh` helper. See [Method 1](#method-1-bundled-helper-fallback).
> 3. **`terminal`** running the hardened inline `curl` recipe. See [Method 2](#method-2-direct-curl-last-resort).
>
> Pick exactly **one** method per query — do not chain them. If none are available, surface that to the user; never invent a tool name.

Preferred when:

- An `mcp_searxng_*` toolset is exposed and the agent needs the right argument shape (this skill teaches it so the model doesn't hallucinate `recency_days` / `categories` / `max_results`).
- `web_search` is unavailable (no `FIRECRAWL_API_KEY`).
- The user explicitly wants self-hosted / privacy-respecting search.
- Working in air-gapped or compliance-sensitive contexts where queries must not hit a SaaS provider.

Sibling skill: [`duckduckgo-search`](https://hermes-agent.nousresearch.com/docs/user-guide/skills/optional/research/research-duckduckgo-search) — same role, different backend. Prefer SearXNG when one is reachable; fall back to DuckDuckGo only if no SearXNG is configured.

## When to Use

Use `searxng-search` for:

- General factual queries, recent events, library and API documentation.
- Looking up authoritative URLs to cite.
- Cases where the user has a local SearXNG (`SEARXNG_URL` is set).

Do **not** use this skill for:

- Fetching full page content — this skill returns titles, URLs, and snippets only. Hand the chosen URL to `web_extract`, `terminal` + `curl`, or a browser tool.
- Image / news / video search — those need a separate sibling skill (planned in a later release).

## Detection Flow

Always check what's actually reachable before issuing a query:

```text
# 0. Are MCP SearXNG tools advertised by the runtime?
#    Look for `mcp_searxng_searxng_web_search` (and optionally
#    `mcp_searxng_web_url_read`) in the available-tools list you were given
#    at the start of the turn. If yes → use Method 0 and stop here.
```

```bash
# 1. Is the env var set? (only relevant for Methods 1 & 2)
[ -n "${SEARXNG_URL:-}" ] && echo "SEARXNG_URL=set" || echo "SEARXNG_URL=missing"

# 2. Is the helper script available?
HELPER="$(dirname "$(realpath "$0")")/scripts/searxng-query.sh" 2>/dev/null
[ -x "${HERMES_HOME:-$HOME/.hermes}/skills/research/searxng-search/scripts/searxng-query.sh" ] \
  && echo "HELPER=installed" || echo "HELPER=missing"

# 3. Is the instance up and JSON-enabled?
bash "${HERMES_HOME:-$HOME/.hermes}/skills/research/searxng-search/scripts/searxng-health.sh"
```

Decision tree:

0. `mcp_searxng_searxng_web_search` is in the advertised tool list → call it directly with the schema in [Method 0](#method-0-mcp-searxng-tool-preferred). Stop. Do not also shell out.
1. MCP tool absent and `SEARXNG_URL` missing → ask the user to set it (or run `hermes setup`); do not guess.
2. `searxng-health.sh` returns non-zero → tell the user the instance is unreachable or doesn't have `format=json` enabled, then fall back to `duckduckgo-search` if that's available.
3. Helper script is installed → prefer it; it handles encoding, retries, size caps, and result validation for you.
4. Helper missing but instance is up → use the inline `curl` recipe in [Method 2](#method-2-direct-curl-last-resort) below.

## Method 0: MCP `searxng` tool (Preferred)

When the runtime exposes an `mcp_searxng_*` toolset, prefer it over shelling out — the MCP server already handles encoding, JSON parsing, and timeout enforcement, and it returns structured data the model can read directly. Two tools are typically available:

| Tool | Purpose |
|------|---------|
| `mcp_searxng_searxng_web_search` | Run a query; returns titles, URLs, and snippets. |
| `mcp_searxng_web_url_read` | Fetch and return cleaned text from a single URL. |

### `mcp_searxng_searxng_web_search` arguments

The exact schema is published by the MCP server in your tool list — **read it from there before calling**. The standard shape exposed by the upstream `mcp-searxng` server is:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `query` | string | yes | The search query. |
| `pageno` | integer | no | Page number, default `1`. |
| `time_range` | string | no | One of `day`, `month`, `year` (some servers also accept `week`). Engine-dependent — many engines silently ignore it. |
| `language` | string | no | ISO 639-1 code, or `all` / `auto`. |
| `safesearch` | string | no | `"0"`, `"1"`, or `"2"`. **Note**: usually a *string*, not an integer. |

There is **no** `recency_days`, `categories` array, or `max_results` field on this tool — those are flags of the bundled `searxng-query.sh` helper, **not** MCP arguments. Do not pass them. If you need category filtering or a hard result cap, use [Method 1](#method-1-bundled-helper-fallback).

Correct example:

```json
{
  "name": "mcp_searxng_searxng_web_search",
  "arguments": {
    "query": "S&P 500 current price",
    "time_range": "day",
    "language": "en",
    "safesearch": "1"
  }
}
```

Incorrect example (this is what the model has been hallucinating — **do not do this**):

```json
{
  "name": "searxng-search",
  "arguments": {
    "query": "S&P 500 current price",
    "recency_days": 0,
    "categories": [],
    "max_results": 5
  }
}
```

The `name` is the wrong tool, and `recency_days` / `categories` / `max_results` aren't part of the MCP schema.

### `mcp_searxng_web_url_read` arguments

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `url` | string | yes | Absolute URL of a result returned by the search tool. |

Use this only after a search; do not feed it arbitrary URLs the user typed without confirming the host.

### Search-then-read pattern

```text
1. Call mcp_searxng_searxng_web_search { "query": "..." }
2. Pick the most relevant result URL from the response.
3. Call mcp_searxng_web_url_read { "url": "..." } to read that page.
4. Cite the URL in the answer.
```

### When to fall through to Method 1

Use the bash helper instead when:

- You need result filtering by category (`it`, `science`, `news`, `images`, …) — most MCP servers don't expose `categories`.
- You need the helper's domain allow/block-list enforcement (`SEKURVIA_ALLOWED_DOMAINS` / `SEKURVIA_BLOCKED_DOMAINS`).
- You need a hard `--max-results` cap or the `compact` output format for downstream shell parsing.
- The MCP server returns an error indicating SearXNG is misconfigured (e.g. `format=json` disabled). The bash helper's error envelope is more diagnostic in that case.

## Method 1: Bundled Helper (Fallback)

The skill ships with `scripts/searxng-query.sh` — a hardened wrapper around the SearXNG JSON API. Prefer it (over Method 2) when MCP isn't available, because it:

- URL-encodes the query correctly (no shell-injection risk).
- Sends `Authorization: Bearer …` when `SEKURVIA_AUTH_TOKEN` is set.
- Caps response size (refuses bodies larger than 2 MiB).
- Filters out result URLs that point at loopback / link-local / private IPs.
- Returns clean JSON that `jq` can parse without errors.

### Usage

```bash
# Basic text search (returns JSON)
bash "$HERMES_HOME/skills/research/searxng-search/scripts/searxng-query.sh" \
    --query "fastapi deployment guide" \
    --max-results 5

# With safesearch and language
bash "$HERMES_HOME/skills/research/searxng-search/scripts/searxng-query.sh" \
    --query "openssl rand hex 32" \
    --max-results 10 \
    --safesearch 1 \
    --language en

# Restrict to a time range (day, week, month, year)
bash "$HERMES_HOME/skills/research/searxng-search/scripts/searxng-query.sh" \
    --query "nixos 25.05 release notes" \
    --time-range month

# Specific category (default is general; SearXNG also supports it, science, news, …)
bash "$HERMES_HOME/skills/research/searxng-search/scripts/searxng-query.sh" \
    --query "rust async runtime benchmarks" \
    --categories it
```

### Helper flags

| Flag | Description | Default |
|------|-------------|---------|
| `--query` / `-q` | Search query (**required**). | — |
| `--max-results` / `-n` | Max results to keep after filtering (1–50). | 10 |
| `--safesearch` / `-s` | 0 off, 1 moderate, 2 strict. | 1 |
| `--language` / `-l` | ISO language code or `auto`. | auto |
| `--time-range` / `-t` | `day`, `week`, `month`, `year`, or empty. | empty |
| `--categories` / `-c` | Comma-separated SearXNG categories. | empty |
| `--page` / `-p` | Page number for pagination. | 1 |
| `--format` | `json` (default) or `compact` (one-line-per-result for shell parsing). | json |

### Parsing results

The helper emits valid JSON that mirrors SearXNG's own shape, but with results pre-sanitized (HTML stripped, snippet length-capped, unsafe URLs removed). Pipe to `jq`:

```bash
# Just the URLs
bash …/searxng-query.sh -q "rust ownership" -n 5 \
  | jq -r '.results[].url'

# Title + URL pairs
bash …/searxng-query.sh -q "rust ownership" -n 5 \
  | jq -r '.results[] | "\(.title)\n  \(.url)\n"'

# Pretty-printed top result
bash …/searxng-query.sh -q "rust ownership" -n 1 \
  | jq '.results[0]'
```

### Response shape

```json
{
  "query": "rust ownership",
  "count": 3,
  "results": [
    {
      "title": "The Rust Programming Language - Chapter 4",
      "url": "https://doc.rust-lang.org/book/ch04-00-understanding-ownership.html",
      "snippet": "Ownership is a set of rules that govern how a Rust program manages memory.",
      "engine": "duckduckgo",
      "score": 0.83
    }
  ]
}
```

On any error the helper exits non-zero and emits a single JSON object with `error` + `kind`:

```json
{ "error": "SEARXNG_URL is not set", "kind": "ConfigError" }
```

| `kind` | Meaning | Recovery |
|--------|---------|----------|
| `ConfigError` | `SEARXNG_URL` missing/malformed. | Ask the user; `hermes setup` if interactive. |
| `NetworkError` | Timeout, connection refused, DNS failure. | Check `searxng-health.sh`; the instance may be down. |
| `RemoteError` | Non-2xx, non-JSON, or oversized response. | If 403, JSON format is probably disabled in `settings.yml`. |
| `ValidationError` | Bad query / args. | Re-issue the call with corrected flags. |

## Method 2: Direct `curl` (Last Resort)

If neither the MCP tool (Method 0) nor the helper script (Method 1) is installed (e.g. the agent is running the skill content directly without supporting files), use this hardened one-liner:

```bash
# Set defaults; override per call as needed
: "${SEARXNG_URL:?SEARXNG_URL must be set}"
QUERY="rust async runtime benchmarks"

curl --silent --show-error --fail \
     --max-time 10 \
     --max-filesize 2097152 \
     --no-progress-meter \
     --data-urlencode "q=${QUERY}" \
     --data "format=json" \
     --data "safesearch=1" \
     --data "language=auto" \
     --data "pageno=1" \
     --header "Accept: application/json" \
     --header "User-Agent: hermes-searxng-skill/0.1" \
     ${SEKURVIA_AUTH_TOKEN:+--header "Authorization: Bearer ${SEKURVIA_AUTH_TOKEN}"} \
     "${SEARXNG_URL%/}/search" \
  | jq '{
      query: .query,
      count: (.results | length),
      results: [.results[] | {
        title: (.title // "" | gsub("<[^>]+>"; "")),
        url,
        snippet: (.content // "" | gsub("<[^>]+>"; "") | .[0:500]),
        engine: (.engine // (.engines // [] | join(", "))),
        score: (.score // null)
      }]
    }'
```

What this protects against:

- `--max-time 10` — bounded wait; SearXNG hangs don't stall the agent.
- `--max-filesize 2097152` — 2 MiB cap; prevents memory blowups from a hostile / misbehaving instance.
- `--fail` — non-2xx becomes an exit-code error instead of a silently-wrong body.
- `--data-urlencode` — query is encoded properly; no risk of breaking out of the param.
- The `jq` post-filter strips HTML and length-caps snippets before the agent ever reads them.

Do **not** simplify this by inlining the query into `--data "q=${QUERY}"` without `--data-urlencode`. Spaces, `&`, and `=` in the user's query will break the request or — worse — silently change its meaning.

## Health Check

`scripts/searxng-health.sh` is a 10-second probe you can run before depending on SearXNG. It verifies:

1. `SEARXNG_URL` is set and well-formed.
2. The instance answers HTTP within the timeout.
3. `format=json` is enabled (a 403 here means SearXNG's `settings.yml` doesn't list `json` under `search.formats`).

```bash
bash "$HERMES_HOME/skills/research/searxng-search/scripts/searxng-health.sh"
# OK   SearXNG reachable at http://127.0.0.1:8888
# OK   JSON format is enabled
```

Run it once at the start of a session if you plan to use SearXNG repeatedly — failing fast saves the agent from issuing five queries before realizing the instance is down.

## Security Considerations

This skill defines, by convention, the same defense-in-depth posture the original Sekurvia plugin enforced:

- **Localhost by default** — agents and operators are encouraged to point `SEARXNG_URL` at `127.0.0.1` so queries never leave the host.
- **No redirect-following** — `curl --fail` plus the helper's explicit non-redirect mode prevents being bounced off-instance.
- **Response size cap** — 2 MiB hard limit; reject larger bodies as `RemoteError` instead of trying to parse them.
- **HTML stripping** — every `title` / `snippet` is run through `gsub("<[^>]+>"; "")` to drop tag soup before the model sees it.
- **URL filtering** — the helper drops any result whose host resolves to a loopback / link-local / private IP unless explicitly allowlisted via `SEKURVIA_ALLOWED_DOMAINS`.
- **Optional bearer auth** — `SEKURVIA_AUTH_TOKEN` is only sent when set, never logged, and surfaced via Hermes' secure prompt.
- **No content fetching** — this skill never visits result URLs. Agents that need page bodies must use a separate fetcher with its own SSRF guard.

When wiring SearXNG into [nyxorn](https://github.com/xor-xe/nyxorn), `services.aiAgent.enableSearxng = true` already exposes `SEARXNG_URL=http://127.0.0.1:8888` to Hermes — no extra config needed.

## Configuration Knobs

In addition to the two `required_environment_variables`, the helper script honors a handful of optional tuning vars (all read from the agent's environment):

| Variable | Default | Description |
|----------|---------|-------------|
| `SEKURVIA_TIMEOUT_S` | `10` | Per-request timeout (seconds, integer). |
| `SEKURVIA_MAX_RESULTS` | `10` | Default max results when `--max-results` is not passed. |
| `SEKURVIA_SAFESEARCH` | `1` | Default safesearch level when `--safesearch` is not passed. |
| `SEKURVIA_LANGUAGE` | `auto` | Default language when `--language` is not passed. |
| `SEKURVIA_USER_AGENT` | `hermes-searxng-skill/0.1` | UA string sent to SearXNG. |
| `SEKURVIA_ALLOWED_DOMAINS` | *(unset)* | Comma-separated domain allowlist. Subdomains match. If set, **only** matching results are returned. |
| `SEKURVIA_BLOCKED_DOMAINS` | *(unset)* | Comma-separated domain blocklist. Subdomains match. |
| `SEKURVIA_MAX_RESPONSE_BYTES` | `2097152` (2 MiB) | Max response size. Hard cap: 16 MiB. |

These fall back to sane defaults if unset; agents should rarely need to override them at runtime.

## Workflow: Search then Extract

SearXNG returns metadata only. To read a result, search first and then extract:

```bash
# Step 1: search and pick the best URL
TARGET=$(bash …/searxng-query.sh -q "fastapi deployment guide" -n 3 \
         | jq -r '.results[0].url')

# Step 2: hand the URL to a content fetcher (web_extract, browser, curl, …)
# DO NOT just `curl "$TARGET"` here without the same hardening as above.
```

Hermes core has dedicated extraction tools (`web_extract`, browser sessions); prefer those over reinventing curl-based scraping in this skill.

## Pitfalls

- **`format=json` not enabled** — public SearXNG mirrors and many Docker quick-starts disable JSON. Symptoms: 403 on every query. Fix: add `formats: [html, json]` under `search:` in the instance's `settings.yml`. nyxorn's `services.aiAgent.enableSearxng` does this for you.
- **Trailing slash in `SEARXNG_URL`** — both `http://127.0.0.1:8888` and `http://127.0.0.1:8888/` are accepted by the helper, but inline curl recipes should use `${SEARXNG_URL%/}/search` to avoid double slashes.
- **Forgetting `--data-urlencode`** — using `--data "q=$QUERY"` instead lets `&`, `=`, `+` in the query break the request. Always url-encode.
- **Treating the wrapper output as text** — it's JSON. Pipe to `jq`, don't `grep`.
- **Mixing up `time_range` values** — SearXNG accepts `day` / `week` / `month` / `year`, not `1d` / `1w` / `1m` / `1y`.
- **Ignoring rate limits** — even self-hosted SearXNG can be throttled by the upstream engines it queries. If results suddenly stop arriving, wait a few seconds before retrying.
- **Sending the bearer token to a `http://` URL** — only set `SEKURVIA_AUTH_TOKEN` for `https://` instances; over plaintext HTTP the token is on the wire.

## Verification Checklist

Before declaring "search worked":

- [ ] `searxng-health.sh` exits 0.
- [ ] The query response includes `count >= 1`.
- [ ] At least one result has both a non-empty `title` and a `url` starting with `https://` (or `http://` for an explicitly intranet target).
- [ ] No `error` key at the top level of the response.
- [ ] If you used `time_range`, dates in the snippets actually fall in that range (best-effort — some engines ignore `time_range`).

## One-Shot Recipes

### "Get me the top 5 hits for X"

```bash
bash "$HERMES_HOME/skills/research/searxng-search/scripts/searxng-query.sh" -q "X" -n 5 \
  | jq -r '.results[] | "\(.title)\n  \(.url)\n  \(.snippet)\n"'
```

### "What's the official Hermes Agent docs URL?"

```bash
bash "$HERMES_HOME/skills/research/searxng-search/scripts/searxng-query.sh" \
     -q "Hermes Agent NousResearch docs" -n 1 \
  | jq -r '.results[0].url'
```

### "Recent NixOS news this week"

```bash
bash "$HERMES_HOME/skills/research/searxng-search/scripts/searxng-query.sh" \
     -q "NixOS news" -n 5 -t week \
  | jq '.results[] | {title, url}'
```

### "Strict safesearch, English only"

```bash
bash "$HERMES_HOME/skills/research/searxng-search/scripts/searxng-query.sh" \
     -q "kid-safe science experiments" -n 8 -s 2 -l en
```

## References

For deeper SearXNG API details (every supported parameter, category list, engine selection, response field semantics), load the supporting reference:

```text
skill_view("searxng-search", "references/searxng-api.md")
```

That file is loaded only on demand, keeping the main skill body small.
