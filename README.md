# Sekurvia

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

**Sekurvia** is a privacy-respecting web search plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent), backed by a [SearXNG](https://searxng.org/) instance. It exposes a single, well-described `web_search` tool, a hardened HTTP client, and an env-driven config — designed to drop into any Hermes deployment regardless of where it's hosted.

> **v0.1.1** — single `web_search` tool. Image / news / video / `fetch_url` are deliberately deferred so the surface area stays small and auditable. The architecture is built to extend cleanly (see [Extending](#extending) below).

---

## Why a separate plugin?

Hermes core ships strong primitives but no SearXNG integration. Sekurvia gives you:

- **One narrowly-scoped LLM-facing tool** — the model picks it for general web queries with no ambiguity.
- **Full control of the SearXNG endpoint** — works with `127.0.0.1:8888`, a LAN box, a public mirror, or an authenticated private instance.
- **Defense in depth** — the search client only talks JSON, refuses to follow redirects, caps response size, validates result URLs against an allow/block-list, and never returns loopback/private/link-local hosts unless you explicitly allowlist them.
- **Stateless, no on-disk state** — safe to run as the locked-down `nyxorn-agent` service user out of the box.

---

## Features

- Single tool: `web_search` — query, max_results, language, safesearch, time_range, categories.
- Hardened HTTP client: per-request timeout, exponential-backoff retries on 5xx / network errors, response-size cap, no redirect-follow, optional Bearer auth, configurable TLS verification.
- Sanitized output: HTML stripped via stdlib, snippet length-capped, URLs validated, allow/block-list applied to every result.
- Robust handler: always returns a JSON string (never raises), with a typed `kind` field (`ConfigError`, `ValidationError`, `NetworkError`, `RemoteError`, `InternalError`).
- Dual distribution: works as a Hermes **directory plugin** (clone into `~/.hermes/plugins/`) **and** as an **entry-point Python package** (pip-installable / NixOS `extraPythonPackages`) — same `register(ctx)` contract on both paths thanks to a small repo-root `__init__.py` shim.
- Zero external dependencies beyond `httpx` and `pyyaml` (which Hermes ships already).
- 59 offline tests, no live SearXNG required.

---

## Install

Three install paths. Pick whichever fits your Hermes deployment.

### 1. Directory plugin (any Hermes install)

```bash
git clone https://github.com/xor-xe/sekurvia ~/.hermes/plugins/sekurvia
export SEARXNG_URL=http://127.0.0.1:8888
```

Then enable it in your Hermes `config.yaml`:

```yaml
plugins:
  enabled:
    - sekurvia
```

Verify:

```bash
hermes plugins
# Plugins (1):
#   ✓ sekurvia v0.1.1 (1 tools)
```

> The repo ships a tiny root [`__init__.py`](__init__.py) shim so Hermes' directory-plugin loader (which imports `<plugin-dir>/__init__.py` directly) finds Sekurvia's real package under `src/sekurvia/`. The shim is excluded from the built wheel by `setuptools.packages.find { where = ["src"] }`, so the pip / `extraPythonPackages` path is unchanged. Same `register(ctx)` works on both layouts.

### 2. Pip-installable package

```bash
pip install sekurvia
```

The `hermes_agent.plugins` entry point in `pyproject.toml` makes it auto-discoverable on the next `hermes` startup. Set `SEARXNG_URL` in the same shell / unit / `.env` Hermes loads, and add `sekurvia` to `plugins.enabled` as above.

### 3. NixOS via [nyxorn](https://github.com/xor-xe/nyxorn)

Sekurvia drops into the existing `services.aiAgent.hermes.extraPlugins` slot — no module changes needed in nyxorn.

```nix
{ pkgs, config, ... }:
{
  services.aiAgent = {
    enable = true;
    engine = "hermes";

    enableSearxng = true;
    searxng.secretKey = "<openssl rand -hex 32>";

    hermes = {
      extraPlugins = [
        (pkgs.fetchFromGitHub {
          owner = "user";
          repo = "sekurvia";
          rev = "v0.1.1";
          hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
        })
      ];

      settings.plugins.enabled = [ "sekurvia" ];

      environment = {
        SEARXNG_URL = "http://127.0.0.1:8888";
      };
    };
  };
}
```

If you'd rather install via the entry point, swap `extraPlugins` for `extraPythonPackages` and build a `pkgs.python312Packages.buildPythonPackage` against this repo (see the upstream [Hermes Nix-setup guide](https://hermes-agent.nousresearch.com/docs/getting-started/nix-setup#plugins)).

---

## Configuration

All knobs are environment variables. Only `SEARXNG_URL` is required; everything else has sensible defaults.

| Variable | Default | Description |
| --- | --- | --- |
| `SEARXNG_URL` | *(required)* | Base URL of your SearXNG instance. Must be `http://` or `https://`. |
| `SEKURVIA_TIMEOUT_S` | `10` | Per-request timeout in seconds (float). |
| `SEKURVIA_MAX_RESULTS` | `10` | Default max results returned. Hard cap: 50. |
| `SEKURVIA_SAFESEARCH` | `1` | Default safesearch level: `0` off, `1` moderate, `2` strict. |
| `SEKURVIA_LANGUAGE` | `auto` | Default ISO language code passed to SearXNG (`en`, `de`, `auto`, ...). |
| `SEKURVIA_AUTH_TOKEN` | *(unset)* | Optional `Authorization: Bearer ...` for protected SearXNG instances. |
| `SEKURVIA_VERIFY_TLS` | `true` | Set to `false` only for self-signed dev instances. |
| `SEKURVIA_USER_AGENT` | `sekurvia/0.1 (+hermes-plugin)` | UA sent to SearXNG. |
| `SEKURVIA_ALLOWED_DOMAINS` | *(unset)* | Comma-separated domain allowlist. Subdomains match. If set, **only** these are returned. |
| `SEKURVIA_BLOCKED_DOMAINS` | *(unset)* | Comma-separated domain blocklist. Subdomains match. |
| `SEKURVIA_MAX_SNIPPET` | `500` | Max characters per result snippet (HTML stripped, then truncated). |
| `SEKURVIA_MAX_QUERY_CHARS` | `1024` | Max query length; longer queries are truncated. |
| `SEKURVIA_MAX_RESPONSE_BYTES` | `2097152` (2 MiB) | Refuse SearXNG responses larger than this. Hard cap: 16 MiB. |
| `SEKURVIA_RETRIES` | `2` | Retries on 5xx / network errors. |
| `SEKURVIA_RETRY_BACKOFF_S` | `0.25` | Base backoff in seconds; doubled per attempt. |

Settings are parsed once per process and validated up-front; bad values fail fast with a `ConfigError`.

---

## Usage

Once enabled, the agent sees `web_search` in its tool list. Typical prompts that should trigger it:

```
What's the latest stable Hermes Agent release?
Find the upstream docs for SearXNG's JSON API.
Recent NixOS news this week
```

The handler returns a single JSON string of this shape:

```json
{
  "query": "hermes agent",
  "count": 2,
  "results": [
    {
      "title": "NousResearch/hermes-agent",
      "url": "https://github.com/NousResearch/hermes-agent",
      "snippet": "The agent that grows with you.",
      "engine": "github",
      "score": 0.83
    },
    {
      "title": "Hermes Agent Docs",
      "url": "https://hermes-agent.nousresearch.com/",
      "snippet": "Official Hermes Agent documentation site.",
      "engine": "duckduckgo"
    }
  ]
}
```

On any failure the handler still returns JSON, never raises:

```json
{ "error": "SearXNG request timed out: ...", "kind": "NetworkError" }
```

| `kind` | Meaning |
| --- | --- |
| `ConfigError` | `SEARXNG_URL` missing or some env var failed validation. |
| `ValidationError` | Tool args were malformed (empty query, bad `safesearch`, etc.). |
| `NetworkError` | Timeout, connection error, DNS failure. |
| `RemoteError` | SearXNG returned non-2xx, non-JSON, oversized, or malformed body. The `status_code` field is included when available. |
| `InternalError` | Unexpected exception. Logged with full traceback at `ERROR` level; never propagates. |

---

## Security model

Defense-in-depth is the explicit design goal. Each layer is small enough to audit on its own:

- **Loading-gate** — `requires_env: SEARXNG_URL` in `plugin.yaml` lets Hermes disable the plugin cleanly when unconfigured rather than fail-open.
- **Transport** — `httpx.AsyncClient` with explicit timeout, `follow_redirects=False`, `verify_tls=True` by default, optional `Bearer` token, response size capped via streaming.
- **Retries** — bounded exponential backoff on 5xx / network errors only; 4xx never retried.
- **Input validation** — query length cap, integer/enum bounds on every parameter; bad values surface as `ValidationError` JSON.
- **Output sanitization** — every result row passes through `clean_result`:
  - HTML stripped via stdlib `html.parser` (no extra deps), `<script>`/`<style>` content dropped, whitespace collapsed, snippet truncated.
  - URLs revalidated through `is_safe_url` — http/https only, hostname not loopback/link-local/private/multicast/reserved unless explicitly allowlisted.
  - Domain allowlist / blocklist applied last.
- **Error surface** — `Exception` is swallowed and logged, never returned to the agent. Typed errors carry only their human-readable message.
- **Logging** — query lengths only at `DEBUG`; raw queries, results, or tokens are **never** logged.
- **No SSRF in v0.1.0** — `web_search` only returns metadata. `is_safe_url` is in place ready for a future `fetch_url` companion tool.
- **Stateless** — no on-disk state, no global singletons beyond the validated `Settings` cache.

---

## Layout

```text
sekurvia/
├── plugin.yaml                  # Hermes manifest (directory-plugin form)
├── pyproject.toml               # Pip / NixOS form + hermes_agent.plugins entry point
├── README.md
├── LICENSE
├── src/
│   └── sekurvia/
│       ├── __init__.py          # register(ctx)
│       ├── plugin.yaml          # Same manifest, shipped inside the wheel
│       ├── config.py            # Settings dataclass + env parsing
│       ├── client.py            # Async SearXNG HTTP client
│       ├── sanitize.py          # HTML strip, URL safety, result cleaner
│       ├── schemas.py           # WEB_SEARCH tool schema (LLM-facing)
│       ├── tools.py             # web_search async handler
│       └── errors.py            # Typed errors
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_sanitize.py
    ├── test_client.py
    └── test_tools.py
```

---

## Development

```bash
git clone https://github.com/xor-xe/sekurvia
cd sekurvia
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest        # 55 tests, all offline (respx mocks httpx)
ruff check src tests
```

Tests don't need a live SearXNG; `respx` intercepts every HTTP call.

---

## Extending

The architecture is intentionally split so each new feature is a small, isolated addition.

### Add another tool (e.g. `image_search`)

1. Drop a new schema into `schemas.py` (one constant per tool).
2. Add an async handler to `tools.py` — same `(args, **kwargs) -> JSON-string` contract.
3. Register it in `__init__.py`:

   ```python
   ctx.register_tool(
       name="image_search",
       toolset="sekurvia",
       schema=schemas.IMAGE_SEARCH,
       handler=tools.image_search,
       is_async=True,
       requires_env=["SEARXNG_URL"],
   )
   ```

4. List it in `plugin.yaml#provides_tools`.

The `SearxngClient` already accepts a `categories` argument (`["images"]`, `["news"]`, `["videos"]`, …), so most new tools are a thin wrapper plus a tighter result schema.

### Add config

Extend the `Settings` dataclass in `config.py`, add a `_get_*` line in `from_env`, and document the env var here.

### Add a hook (caching, query redaction, …)

Create `hooks.py`, register the callback in `__init__.py`:

```python
ctx.register_hook("post_tool_call", hooks.cache_result)
```

…and list the hook name under `provides_hooks` in `plugin.yaml`.

### Add a `fetch_url` tool

`is_safe_url` is already designed for this. The recommended shape is a separate handler that:

1. Re-validates the URL (defense in depth — the agent might pass any URL).
2. Uses a fresh `httpx.AsyncClient` with the same hardening profile (no redirects, response cap, timeout).
3. Strips HTML before returning.

Out of scope for v0.1.0; planned for a later release.

---

## Roadmap

- v0.2: `image_search`, `news_search`, `video_search`.
- v0.3: optional `fetch_url` with SSRF guards and content-type allowlist.
- v0.4: `flake.nix` (plugin + python-package derivations), GitHub Actions CI, bundled `SKILL.md`, `/sekurvia` slash command for diagnostics.

---

## License

MIT — see [LICENSE](LICENSE).
