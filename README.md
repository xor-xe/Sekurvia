# Sekurvia

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Sekurvia** is a Hermes Agent **skill** that gives the agent privacy-respecting web search through a self-hosted [SearXNG](https://searxng.org/) instance — no third-party API key, no SaaS round-trip.

> **Skill, not plugin.** Hermes [skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills) are markdown documents the agent loads on demand (via `skill_view`) and a bundle of supporting helper scripts. They wrap CLIs/APIs without compiling Python code into Hermes core. Sekurvia is the SearXNG counterpart to the bundled `duckduckgo-search` skill.

This repo is a **skill tap** — one repo, one or more `<skill-name>/SKILL.md` directories — so it can grow to include `searxng-images`, `searxng-news`, etc. without restructuring.

---

## What's in v0.1.0

A single skill, `searxng-search`, focused on general web search:

```text
sekurvia/
├── README.md                          ← this file
├── LICENSE                            ← MIT
├── .gitignore
└── searxng-search/                    ← installable skill
    ├── SKILL.md                       ← skill body (loaded by skill_view)
    ├── scripts/
    │   ├── searxng-query.sh           ← hardened curl+jq wrapper around the JSON API
    │   └── searxng-health.sh          ← 10-second connectivity probe
    └── references/
        └── searxng-api.md             ← on-demand deeper API reference
```

Future siblings under the same root (planned):

- `searxng-images/` — image-search shape with `categories=images`.
- `searxng-news/` — fresh-news shape with `categories=news` + `time_range=day`.
- `searxng-videos/` — video-search shape.

Each is its own SKILL.md directory, installed independently.

---

## Install

### 1. From this GitHub repo (recommended)

```bash
hermes skills install xor-xe/sekurvia/searxng-search
```

Hermes fetches the skill from `github.com/xor-xe/sekurvia` at the
`searxng-search/` subpath, runs its security scanner, and copies it
to `~/.hermes/skills/research/searxng-search/`.

### 2. Direct URL (single-file SKILL.md)

```bash
hermes skills install \
  https://raw.githubusercontent.com/xor-xe/sekurvia/main/searxng-search/SKILL.md \
  --name searxng-search
```

This installs only `SKILL.md`. The helper scripts under `scripts/` are
**not** included via direct URL install — use the GitHub path above for
the full bundle.

### 3. Manual / dev install

```bash
git clone https://github.com/xor-xe/sekurvia ~/code/sekurvia
mkdir -p ~/.hermes/skills/research
ln -s ~/code/sekurvia/searxng-search ~/.hermes/skills/research/searxng-search
```

A symlink is preferred for development so edits in your checkout take
effect immediately. For a copy install, replace `ln -s` with `cp -r`.

### 4. NixOS via [nyxorn](https://github.com/xor-xe/nyxorn)

`services.aiAgent.enableSearxng = true;` already starts a local SearXNG
on `127.0.0.1:8888` and exposes `SEARXNG_URL` to Hermes. You only need
to install the skill itself:

```nix
{ config, ... }: {
  services.aiAgent = {
    enable = true;
    engine = "hermes";

    enableSearxng = true;
    searxng.secretKey = "<openssl rand -hex 32>";

    hermes = {
      # nyxorn already exposes SEARXNG_URL=http://127.0.0.1:8888 to Hermes
      # automatically when enableSearxng = true. The skill picks it up.

      documents = {
        # Drop the skill bundle into HERMES_HOME at activation time.
        "skills/research/searxng-search" = {
          source = pkgs.fetchFromGitHub {
            owner = "user";
            repo  = "sekurvia";
            rev   = "v0.1.0";
            hash  = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
          } + "/searxng-search";
        };
      };
    };
  };
}
```

(If your nyxorn version doesn't expose `documents` for nested-path
mounts, fall back to the manual install in Section 3 — it's a one-line
symlink against `/var/lib/nyxorn-agent/.hermes/skills/research/`.)

---

## Configuration

The skill needs **one** environment variable to function. Hermes prompts
for it the first time the skill is loaded if it isn't already set.

| Variable | Required | Description |
| --- | --- | --- |
| `SEARXNG_URL` | yes | Base URL of your SearXNG instance. Must include scheme. Example: `http://127.0.0.1:8888`. |
| `SEKURVIA_AUTH_TOKEN` | no | `Authorization: Bearer …` for protected SearXNG instances. Skip for local use. |

Optional tuning vars (the skill picks sensible defaults; only set when
you know you need them):

| Variable | Default | Description |
| --- | --- | --- |
| `SEKURVIA_TIMEOUT_S` | `10` | Per-request timeout in seconds. |
| `SEKURVIA_MAX_RESULTS` | `10` | Default `--max-results` for the helper. Hard cap: 50. |
| `SEKURVIA_SAFESEARCH` | `1` | Default safesearch level: 0 off / 1 moderate / 2 strict. |
| `SEKURVIA_LANGUAGE` | `auto` | Default ISO language code. |
| `SEKURVIA_USER_AGENT` | `hermes-searxng-skill/0.1` | UA sent to SearXNG. |
| `SEKURVIA_ALLOWED_DOMAINS` | unset | Comma-separated allowlist; if set, only matching hosts are returned. |
| `SEKURVIA_BLOCKED_DOMAINS` | unset | Comma-separated blocklist. |
| `SEKURVIA_MAX_RESPONSE_BYTES` | `2097152` (2 MiB) | Response size cap. Hard cap: 16 MiB. |
| `SEKURVIA_MAX_SNIPPET` | `500` | Per-result snippet truncation length. |
| `SEKURVIA_HEALTH_TIMEOUT_S` | `5` | Timeout for `searxng-health.sh`. |

Hermes `required_environment_variables` machinery handles the
`SEARXNG_URL` and `SEKURVIA_AUTH_TOKEN` prompts on first use; the rest
are read from the agent's environment if set, otherwise the bundled
defaults apply.

---

## How the skill is used

Once installed, the agent can:

1. Run `/searxng-search` as a slash command — Hermes loads the SKILL.md
   into the model's context.
2. **If an `mcp_searxng_*` MCP toolset is exposed** (e.g. via the
   upstream [`mcp-searxng`](https://github.com/ihor-sokoliuk/mcp-searxng)
   server), call `mcp_searxng_searxng_web_search` directly with
   `{query, pageno?, time_range?, language?, safesearch?}` — no shell
   needed. SKILL.md teaches the model the correct argument shape so it
   doesn't hallucinate a tool literally named `searxng-search` or pass
   non-existent fields like `recency_days` / `categories` / `max_results`.
3. Otherwise, have the model call the bundled helper via `terminal`:
   ```bash
   bash "$HERMES_HOME/skills/research/searxng-search/scripts/searxng-query.sh" \
        -q "fastapi deployment guide" -n 5
   ```
   …and pipe the JSON to `jq` for parsing.
4. Run `searxng-health.sh` first if it suspects the instance is down.
5. Load `references/searxng-api.md` via
   `skill_view("searxng-search", "references/searxng-api.md")` for
   deeper API detail (engines, categories, response shape).

The skill auto-hides itself when Hermes' built-in `web_search` tool is
available (via `fallback_for_toolsets: [web]`), so it doesn't clutter
the context for users who already have a SaaS web tool wired up. When
only the MCP `searxng` tools are present (no `web_search`), the skill
stays loaded — its job there is precisely to teach the model the right
argument shape for those MCP tools.

> **`searxng-search` is the skill name, not a tool name.** A common
> failure mode is the model emitting a tool call with
> `name: "searxng-search"`, which Hermes rejects with
> `Tool 'searxng-search' does not exist.` The SKILL.md body now has a
> prominent "Not a tool" callout instructing the model to invoke
> `mcp_searxng_searxng_web_search` (or `terminal` running the helper)
> instead. If you still see the hallucination on a small model, prefer
> a stricter / instruction-tuned model and confirm the skill is
> actually being loaded into context.

---

## Security model

Defense-in-depth, defined as conventions the skill teaches the agent and
hard-enforced inside the helper scripts:

- **Localhost by default** — operators are guided to set
  `SEARXNG_URL=http://127.0.0.1:8888`. Queries never leave the host.
- **No redirect following** — `curl --fail` plus explicit non-redirect
  flags prevent being bounced off-instance.
- **Response size cap** — 2 MiB via `curl --max-filesize`; refuse
  larger bodies as `RemoteError` instead of trying to parse them.
- **HTML stripping** — every `title` / `snippet` is run through `jq`
  filters to drop tag soup before the model sees it.
- **URL filtering** — the helper drops result URLs whose host resolves
  to loopback / link-local / private / multicast / reserved space
  unless explicitly allowlisted.
- **Optional bearer auth** — `SEKURVIA_AUTH_TOKEN` is only sent when
  set, never logged, and surfaced via Hermes' secure setup prompt.
- **No content fetching** — the skill never visits result URLs.
  Agents that want page bodies must use a separate fetcher
  (`web_extract`, browser tools) with its own SSRF guard.
- **Strict timeouts** — every curl invocation has `--max-time` bounded.
- **JSON-only output** — every error path emits a typed JSON object
  (`{"error": "...", "kind": "..."}`), never a partial body.

---

## Verifying the install

After installing, run from a Hermes session:

```text
/searxng-search "what is hermes agent"
```

The agent should:

1. See `SEARXNG_URL` is set (or prompt you to set it).
2. Call `searxng-health.sh` and confirm the instance is up + JSON enabled.
3. Call `searxng-query.sh -q "what is hermes agent" -n 5` and return a
   list of titles + URLs + snippets.

If step 2 fails with `JSON format is NOT enabled`, add `json` to your
SearXNG instance's `settings.yml`:

```yaml
search:
  formats:
    - html
    - json
```

…and restart SearXNG. (nyxorn does this for you when
`services.aiAgent.enableSearxng = true`.)

---

## Extending — adding image / news / video skills

The repo is a tap, so adding a sibling skill is a matter of dropping a
new directory next to `searxng-search/`. Recommended layout for a new
skill `searxng-news`:

```text
sekurvia/
├── searxng-search/
└── searxng-news/
    ├── SKILL.md                       ← describe news-specific flow
    └── scripts/
        └── searxng-news.sh            ← thin wrapper that calls
                                        searxng-query.sh with
                                        --categories news --time-range day
```

Reuse the existing `scripts/searxng-query.sh` — it already supports
`--categories` and `--time-range`. The new SKILL.md mostly explains
when the agent should reach for news vs general search, what fields to
expect, and how to format the answer.

Install paths stay independent:

```bash
hermes skills install xor-xe/sekurvia/searxng-news
```

That's the whole expansion story — no shared Python package, no
versioned plugin entry point, no rebuild.

---

## Migration from the v0.1.0 plugin shape

Earlier drafts of Sekurvia shipped as a Hermes **plugin** (a Python
package registering a `web_search` tool). That's a valid pattern but
overkill for "wrap a CLI/API and tell the agent how to use it" — which
is exactly what skills are designed for.

If you installed the previous plugin shape:

```bash
# remove the old plugin install, if any
rm -rf ~/.hermes/plugins/sekurvia
sed -i '/^\s*-\s*sekurvia\s*$/d' ~/.hermes/config.yaml   # drop from plugins.enabled
pip uninstall -y sekurvia 2>/dev/null || true

# install the skill
hermes skills install xor-xe/sekurvia/searxng-search
```

Your `SEARXNG_URL` env var carries over unchanged.

---

## Development

```bash
git clone https://github.com/xor-xe/sekurvia
cd sekurvia

# Validate SKILL.md frontmatter
python3 -c '
import re, sys, yaml, pathlib
p = pathlib.Path("searxng-search/SKILL.md").read_text()
m = re.match(r"^---\n(.*?)\n---\n", p, re.S)
assert m, "frontmatter missing"
fm = yaml.safe_load(m.group(1))
assert fm["name"] == "searxng-search"
assert len(fm["description"]) <= 1024
print("ok:", fm["name"], "v" + fm["version"])
'

# Lint the helpers
shellcheck searxng-search/scripts/*.sh

# Smoke-test the helper end-to-end against your SearXNG
SEARXNG_URL=http://127.0.0.1:8888 \
  bash searxng-search/scripts/searxng-health.sh

SEARXNG_URL=http://127.0.0.1:8888 \
  bash searxng-search/scripts/searxng-query.sh -q "hermes agent" -n 3 \
  | jq .
```

---

## License

MIT — see [LICENSE](LICENSE).
