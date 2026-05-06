# SearXNG JSON API — Reference

This document is loaded on demand by the `searxng-search` skill via
`skill_view("searxng-search", "references/searxng-api.md")`. Keep the
parent `SKILL.md` lean by deferring rare-but-useful detail here.

Source of truth: [SearXNG developer docs — Search API](https://docs.searxng.org/dev/search_api).

---

## Endpoints

SearXNG accepts the search query at either `/` or `/search`. They are
equivalent. The skill uses `/search` because some reverse-proxy setups
route only `/search` and HTML on `/`.

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/search` | Preferred for structured data; bypasses URL length limits. |
| `GET`  | `/search` | Works too; query and params go in the query string. |

The helper script (`scripts/searxng-query.sh`) always uses POST.

---

## Request parameters

All parameters are flat key/value pairs; arrays use comma-joined strings.

| Param | Required | Description |
| --- | --- | --- |
| `q` | Yes | The search query string. URL-encode it. |
| `format` | Yes (for JSON) | `json`, `csv`, or `rss`. Must be enabled in the instance's `settings.yml`. |
| `pageno` | No | 1-indexed page number. Default 1. |
| `language` | No | ISO code (`en`, `de`, `fr`, …) or `auto`. Default from instance. |
| `safesearch` | No | `0` off, `1` moderate, `2` strict. |
| `time_range` | No | One of `day`, `week`, `month`, `year`, or empty for no restriction. |
| `categories` | No | Comma-separated list (e.g. `general,it`). |
| `engines` | No | Comma-separated list of explicit engine names (e.g. `duckduckgo,bing`). Overrides `categories`. |
| `theme` | No | UI theme; not relevant for JSON output. |

If `categories` and `engines` are both unset, SearXNG uses its instance
default category (typically `general`).

### Enabling `format=json`

Public mirrors and many Docker quick-starts disable JSON. Symptom:
HTTP 403 on every query. Fix in the instance's `settings.yml`:

```yaml
search:
  formats:
    - html
    - json
```

On nyxorn (`services.aiAgent.enableSearxng = true;`), JSON is enabled
by default — no manual config needed.

---

## Categories

Built-in categories that ship with most SearXNG installs:

| Category | Typical engines |
| --- | --- |
| `general` | DuckDuckGo, Brave, Mojeek, Qwant, Mwmbl, Wikipedia, … |
| `news` | Yahoo News, Reuters (where enabled), Bing News, … |
| `it` | Stack Overflow, GitHub, MDN, ArchWiki, npm, PyPI, … |
| `science` | arXiv, PubMed, Semantic Scholar, Crossref, … |
| `science.scientific publications` | Subset of `science` focused on papers. |
| `images` | Bing Images, Brave Images, DuckDuckGo Images, … |
| `videos` | YouTube, Vimeo, Bilibili (region-dependent). |
| `music` | SoundCloud, Bandcamp, Genius, MixCloud, … |
| `map` | OpenStreetMap. |
| `social media` | Reddit, Lemmy, Mastodon, Hacker News. |
| `files` | Software/torrent search engines (often disabled by default). |
| `dictionaries` | Wiktionary, Etymonline, … |

Different SearXNG instances enable different subsets. Check
`/preferences` (HTML) on the instance to see exactly which categories
and engines are active.

---

## Engines

Override category-based selection by listing engine names directly:

```text
engines=duckduckgo,brave,mojeek
```

Pros: deterministic, faster (skips engines that often time out).
Cons: brittle — if an engine is disabled or removed, the request still
succeeds but those slots return nothing.

The skill prefers `categories` (or no override at all) so the operator
can tune which engines are used at the instance level without changing
agent code.

---

## Response shape

A successful JSON response looks like:

```json
{
  "query": "rust ownership",
  "number_of_results": 0,
  "results": [
    {
      "url": "https://doc.rust-lang.org/book/ch04-00-understanding-ownership.html",
      "title": "Understanding Ownership - The Rust Programming Language",
      "content": "Ownership is a set of rules that govern how a Rust program manages memory.",
      "engine": "duckduckgo",
      "score": 0.83,
      "category": "general",
      "engines": ["duckduckgo", "brave"],
      "positions": [1, 2],
      "publishedDate": null,
      "thumbnail": null
    }
  ],
  "answers": [],
  "corrections": [],
  "infoboxes": [],
  "suggestions": ["rust borrowing", "rust lifetimes"],
  "unresponsive_engines": []
}
```

### Field-by-field

| Field | Type | Notes |
| --- | --- | --- |
| `query` | string | Echo of the original query. |
| `number_of_results` | int | Often `0` — most engines don't expose this. Don't rely on it for pagination. |
| `results[].url` | string | Result URL. The skill validates these and drops anything pointing at private/loopback hosts. |
| `results[].title` | string | May contain HTML — strip before showing the user. |
| `results[].content` | string | Snippet. May contain HTML. |
| `results[].engine` | string | The single engine that produced this hit. |
| `results[].engines` | array | All engines that returned this URL. Only present after deduplication. |
| `results[].score` | float | SearXNG's blended relevance score across engines. |
| `results[].category` | string | Category the result was drawn from. |
| `results[].positions` | array | Per-engine ranks before deduplication. |
| `results[].publishedDate` | string \| null | ISO timestamp when the engine provides one. |
| `results[].thumbnail` | string \| null | Image URL for image/video results. |
| `answers` | array | Direct-answer engines (Wikipedia infobox, calculator). Often empty. |
| `corrections` | array | "Did you mean?" suggestions. |
| `infoboxes` | array | Wikipedia/Wikidata-style structured cards. |
| `suggestions` | array | Related query suggestions. |
| `unresponsive_engines` | array | `[engine_name, reason]` pairs for engines that errored or timed out. Useful for telling the user "results may be incomplete". |

### Suggestions and infoboxes

The skill currently ignores `suggestions` and `infoboxes` for
simplicity — the agent gets a clean ranked list of result URLs and can
follow up with a refined query if it wants. A future skill version can
opt into surfacing those via a `--include-extras` flag.

---

## Pagination

Use `pageno=2`, `pageno=3`, … to walk further. SearXNG limits how deep
you can go (typically 10 pages); past that the upstream engines stop
returning new results.

The helper script defaults to `pageno=1` and exposes `--page` for
explicit pagination. There is no auto-iteration — paginate explicitly
to keep token usage predictable.

---

## Rate limiting

SearXNG itself doesn't rate-limit by default, but:

- Upstream engines (DuckDuckGo, Brave, …) throttle the SearXNG IP, not
  the end user. Hitting a self-hosted instance hard with sequential
  queries can cause some upstream engines to return empty for several
  minutes.
- If the operator enabled the SearXNG `limiter` (an optional
  Redis-backed rate-limiter), per-IP and per-user throttling kicks in
  with HTTP 429.

If you see a sudden empty-results pattern, wait 30 seconds and retry
once. Repeated empties suggest configured engines are throttled — pick
different categories or different engines.

---

## Errors and HTTP status codes

| Status | Meaning | Likely fix |
| --- | --- | --- |
| `200` | Success — body is valid JSON. | — |
| `403` | `format=json` not enabled, **or** limiter rejected the request. | Enable JSON in `settings.yml`; check rate-limiter config. |
| `404` | Wrong path. Hit `/search`, not `/api/search`. | — |
| `429` | Rate limit. | Back off; retry once after 30s. |
| `5xx` | Instance error or all upstream engines failed. | Check the instance logs and `unresponsive_engines` field. |

The helper script and inline curl recipe both use `curl --fail`, so
non-2xx responses become typed `RemoteError` (with `status_code`)
instead of silently-wrong bodies.

---

## Authentication

Plain SearXNG has no built-in auth. Operators commonly put it behind:

- **Reverse-proxy bearer auth** — nginx/Caddy checks `Authorization:
  Bearer …` before forwarding. Set `SEKURVIA_AUTH_TOKEN` and the
  helper sends it on every request.
- **Reverse-proxy basic auth** — not directly supported by the helper.
  Use a curl `--user user:pass` recipe instead, or move to bearer.
- **Network-level isolation** — SearXNG only listens on localhost or a
  private subnet. No app-level auth needed.

Never send `SEKURVIA_AUTH_TOKEN` to a plain `http://` URL. Use HTTPS
for any non-local instance.

---

## Useful debugging recipes

```bash
# What categories does this instance enable?
curl -s "$SEARXNG_URL/preferences" | grep -oE 'name="category_[^"]+"' | sort -u

# Which engines are wired into the "general" category?
curl -s "$SEARXNG_URL/" | grep -oE 'data-engine="[^"]+"' | sort -u

# Was my last request rate-limited?
curl -s -o /dev/null -w '%{http_code}\n' \
     -d "q=test" -d "format=json" "$SEARXNG_URL/search"
```

These poke at HTML / config endpoints, so they may need adjustment if
the operator runs a custom theme.
