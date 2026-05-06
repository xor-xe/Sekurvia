#!/usr/bin/env bash
# searxng-query.sh — hardened wrapper around the SearXNG JSON API.
#
# Used by the `searxng-search` Hermes skill. Always returns valid JSON on
# stdout: a result envelope on success, or `{"error": "...", "kind": "..."}`
# on failure. Exit code is 0 on success, non-zero on any failure.
#
# Required tools: bash >=4, curl, jq.
# Required env:   SEARXNG_URL.
# Optional env:   SEKURVIA_AUTH_TOKEN, SEKURVIA_TIMEOUT_S, SEKURVIA_MAX_RESULTS,
#                 SEKURVIA_SAFESEARCH, SEKURVIA_LANGUAGE, SEKURVIA_USER_AGENT,
#                 SEKURVIA_ALLOWED_DOMAINS, SEKURVIA_BLOCKED_DOMAINS,
#                 SEKURVIA_MAX_RESPONSE_BYTES, SEKURVIA_MAX_SNIPPET.

set -o errexit
set -o nounset
set -o pipefail

readonly HARD_MAX_RESULTS=50
readonly HARD_MIN_RESULTS=1
readonly HARD_MAX_RESPONSE_BYTES=$((16 * 1024 * 1024))
readonly DEFAULT_TIMEOUT=10
readonly DEFAULT_MAX_RESULTS=10
readonly DEFAULT_SAFESEARCH=1
readonly DEFAULT_LANGUAGE="auto"
readonly DEFAULT_MAX_RESPONSE_BYTES=$((2 * 1024 * 1024))
readonly DEFAULT_MAX_SNIPPET=500
readonly DEFAULT_USER_AGENT="hermes-searxng-skill/0.1"
readonly VALID_TIME_RANGES=(" " "day" "week" "month" "year")
readonly VALID_SAFESEARCH=(0 1 2)

json_escape() {
    # Escape a single string value for embedding in a JSON literal.
    # Avoids depending on jq for the missing-jq error path.
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

emit_error() {
    local kind="$1" msg="$2"
    # Emit one-line JSON so callers piping through `tail -1` / `head -1`
    # always see the full envelope.
    if command -v jq >/dev/null 2>&1; then
        jq -cn --arg error "$msg" --arg kind "$kind" '{error: $error, kind: $kind}'
    else
        printf '{"error":"%s","kind":"%s"}\n' "$(json_escape "$msg")" "$(json_escape "$kind")"
    fi
}

die() {
    local kind="$1" msg="$2"
    emit_error "$kind" "$msg" >&2
    emit_error "$kind" "$msg"
    exit 1
}

require_cmd() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1 || die "ConfigError" "required command not found: $cmd (install it via your package manager; on NixOS add it to systemPackages)"
}

usage() {
    cat <<'EOF'
searxng-query.sh — query a SearXNG instance, return sanitized JSON.

Usage:
  searxng-query.sh -q "your query" [options]

Options:
  -q, --query QUERY            Search query (required, max 1024 chars).
  -n, --max-results N          Max results to return (1-50, default 10).
  -s, --safesearch LEVEL       0 off, 1 moderate, 2 strict (default 1).
  -l, --language CODE          ISO language code or "auto" (default auto).
  -t, --time-range RANGE       day|week|month|year, or empty (default empty).
  -c, --categories LIST        Comma-separated SearXNG categories.
  -p, --page N                 Page number (default 1).
      --format {json,compact}  Output mode (default json).
  -h, --help                   This message.

Environment:
  SEARXNG_URL                  Required. Base URL of the SearXNG instance.
  SEKURVIA_AUTH_TOKEN          Optional. Bearer token for protected instances.
  SEKURVIA_*                   Optional tuning vars; see SKILL.md.
EOF
}

# -- dependency checks (run before anything else so error JSON works) ---------

require_cmd curl
require_cmd jq

# -- input parsing ------------------------------------------------------------

QUERY=""
MAX_RESULTS=""
SAFESEARCH=""
LANGUAGE=""
TIME_RANGE=""
CATEGORIES=""
PAGE=1
FORMAT="json"

while [ $# -gt 0 ]; do
    case "$1" in
        -q|--query)        QUERY="${2:-}"; shift 2 ;;
        -n|--max-results)  MAX_RESULTS="${2:-}"; shift 2 ;;
        -s|--safesearch)   SAFESEARCH="${2:-}"; shift 2 ;;
        -l|--language)     LANGUAGE="${2:-}"; shift 2 ;;
        -t|--time-range)   TIME_RANGE="${2:-}"; shift 2 ;;
        -c|--categories)   CATEGORIES="${2:-}"; shift 2 ;;
        -p|--page)         PAGE="${2:-1}"; shift 2 ;;
        --format)          FORMAT="${2:-json}"; shift 2 ;;
        -h|--help)         usage; exit 0 ;;
        --)                shift; break ;;
        *)                 die "ValidationError" "unknown argument: $1" ;;
    esac
done

# -- env normalisation --------------------------------------------------------

if [ -z "${SEARXNG_URL:-}" ]; then
    die "ConfigError" "SEARXNG_URL is not set; point it at your SearXNG instance, e.g. http://127.0.0.1:8888"
fi

case "$SEARXNG_URL" in
    http://*|https://*) ;;
    *) die "ConfigError" "SEARXNG_URL must start with http:// or https:// (got: $SEARXNG_URL)" ;;
esac

# Strip trailing slash so we can append /search predictably.
SEARXNG_URL="${SEARXNG_URL%/}"

TIMEOUT="${SEKURVIA_TIMEOUT_S:-$DEFAULT_TIMEOUT}"
case "$TIMEOUT" in
    ''|*[!0-9]*) die "ConfigError" "SEKURVIA_TIMEOUT_S must be a positive integer (got: $TIMEOUT)" ;;
esac

MAX_RESPONSE_BYTES="${SEKURVIA_MAX_RESPONSE_BYTES:-$DEFAULT_MAX_RESPONSE_BYTES}"
case "$MAX_RESPONSE_BYTES" in
    ''|*[!0-9]*) die "ConfigError" "SEKURVIA_MAX_RESPONSE_BYTES must be a positive integer" ;;
esac
if [ "$MAX_RESPONSE_BYTES" -lt 1024 ] || [ "$MAX_RESPONSE_BYTES" -gt "$HARD_MAX_RESPONSE_BYTES" ]; then
    die "ConfigError" "SEKURVIA_MAX_RESPONSE_BYTES out of range (1024..${HARD_MAX_RESPONSE_BYTES})"
fi

MAX_SNIPPET="${SEKURVIA_MAX_SNIPPET:-$DEFAULT_MAX_SNIPPET}"
case "$MAX_SNIPPET" in
    ''|*[!0-9]*) die "ConfigError" "SEKURVIA_MAX_SNIPPET must be a positive integer" ;;
esac

USER_AGENT="${SEKURVIA_USER_AGENT:-$DEFAULT_USER_AGENT}"

# -- argument validation ------------------------------------------------------

if [ -z "$QUERY" ]; then
    die "ValidationError" "query is required (use -q or --query)"
fi
if [ "${#QUERY}" -gt 1024 ]; then
    QUERY="${QUERY:0:1024}"
fi

if [ -z "$MAX_RESULTS" ]; then
    MAX_RESULTS="${SEKURVIA_MAX_RESULTS:-$DEFAULT_MAX_RESULTS}"
fi
case "$MAX_RESULTS" in
    ''|*[!0-9]*) die "ValidationError" "max_results must be an integer (got: $MAX_RESULTS)" ;;
esac
if [ "$MAX_RESULTS" -lt "$HARD_MIN_RESULTS" ] || [ "$MAX_RESULTS" -gt "$HARD_MAX_RESULTS" ]; then
    die "ValidationError" "max_results out of range (${HARD_MIN_RESULTS}..${HARD_MAX_RESULTS})"
fi

if [ -z "$SAFESEARCH" ]; then
    SAFESEARCH="${SEKURVIA_SAFESEARCH:-$DEFAULT_SAFESEARCH}"
fi
case "$SAFESEARCH" in
    0|1|2) ;;
    *) die "ValidationError" "safesearch must be 0, 1, or 2 (got: $SAFESEARCH)" ;;
esac

if [ -z "$LANGUAGE" ]; then
    LANGUAGE="${SEKURVIA_LANGUAGE:-$DEFAULT_LANGUAGE}"
fi

case "$TIME_RANGE" in
    ""|day|week|month|year) ;;
    *) die "ValidationError" "time_range must be one of '', day, week, month, year (got: $TIME_RANGE)" ;;
esac

case "$PAGE" in
    ''|*[!0-9]*) die "ValidationError" "page must be a positive integer (got: $PAGE)" ;;
esac
[ "$PAGE" -lt 1 ] && PAGE=1

case "$FORMAT" in
    json|compact) ;;
    *) die "ValidationError" "format must be json or compact (got: $FORMAT)" ;;
esac

# -- request ------------------------------------------------------------------

curl_args=(
    --silent
    --show-error
    --fail
    --max-time "$TIMEOUT"
    --max-filesize "$MAX_RESPONSE_BYTES"
    --no-progress-meter
    --no-keepalive
    --header "Accept: application/json"
    --header "User-Agent: ${USER_AGENT}"
    --data-urlencode "q=${QUERY}"
    --data "format=json"
    --data "safesearch=${SAFESEARCH}"
    --data "language=${LANGUAGE}"
    --data "pageno=${PAGE}"
)

if [ -n "$TIME_RANGE" ]; then
    curl_args+=(--data "time_range=${TIME_RANGE}")
fi

if [ -n "$CATEGORIES" ]; then
    # Strip whitespace, comma-join.
    CATEGORIES_CLEAN="$(printf '%s' "$CATEGORIES" | tr -d '[:space:]')"
    curl_args+=(--data "categories=${CATEGORIES_CLEAN}")
fi

if [ -n "${SEKURVIA_AUTH_TOKEN:-}" ]; then
    curl_args+=(--header "Authorization: Bearer ${SEKURVIA_AUTH_TOKEN}")
fi

# Capture response body and exit code separately so we can map curl errors
# to typed JSON errors.
set +e
RESPONSE="$(curl "${curl_args[@]}" "${SEARXNG_URL}/search" 2>&1)"
CURL_EXIT=$?
set -e

if [ "$CURL_EXIT" -ne 0 ]; then
    case "$CURL_EXIT" in
        6)        die "NetworkError" "couldn't resolve host in SEARXNG_URL ($SEARXNG_URL)" ;;
        7)        die "NetworkError" "connection refused at $SEARXNG_URL" ;;
        22)       die "RemoteError"  "SearXNG returned a non-2xx response (curl exit 22)" ;;
        28)       die "NetworkError" "request timed out after ${TIMEOUT}s" ;;
        35|60|77) die "NetworkError" "TLS error contacting SearXNG: $RESPONSE" ;;
        63)       die "RemoteError"  "response exceeded max size (${MAX_RESPONSE_BYTES} bytes)" ;;
        *)        die "NetworkError" "curl failed with exit code ${CURL_EXIT}: $RESPONSE" ;;
    esac
fi

# -- post-processing ----------------------------------------------------------

# Normalise allow/block-list env into compact CSV jq can split on.
ALLOWLIST="${SEKURVIA_ALLOWED_DOMAINS:-}"
BLOCKLIST="${SEKURVIA_BLOCKED_DOMAINS:-}"

# Sanitize, length-cap, and filter results in a single jq pass. The filter:
#   * keeps only http/https URLs;
#   * drops loopback / link-local / private IP literals (best-effort regex);
#   * applies allow/block list on hostnames (sub-domain match);
#   * strips HTML and length-caps title/snippet.
processed="$(
    printf '%s' "$RESPONSE" | jq \
        --arg query        "$QUERY" \
        --argjson maxsnippet "$MAX_SNIPPET" \
        --argjson maxres     "$MAX_RESULTS" \
        --arg allowlist    "$ALLOWLIST" \
        --arg blocklist    "$BLOCKLIST" \
        '
def host_of(url):
    (url | capture("^[^:]+://(?<h>[^/:?#]+)").h) // "";

def matches_set(host; csv):
    if (csv | length) == 0 then false
    else
        csv | split(",") | map(ascii_downcase | gsub("\\s"; ""))
            | map(select(. != ""))
            | any(. as $d | (host == $d) or (host | endswith("." + $d)))
    end;

def is_dangerous(host):
    (host | test("^(localhost|ip6-localhost|ip6-loopback)$"))
    or (host | test("^127\\."))
    or (host | test("^10\\."))
    or (host | test("^192\\.168\\."))
    or (host | test("^169\\.254\\."))
    or (host | test("^172\\.(1[6-9]|2[0-9]|3[0-1])\\."))
    or (host == "0.0.0.0")
    or (host | test("^\\[?::1\\]?$"));

def strip_html(s; cap):
    (s // "")
    | tostring
    | gsub("<[^>]+>"; "")
    | gsub("&amp;"; "&") | gsub("&lt;"; "<") | gsub("&gt;"; ">")
    | gsub("&quot;"; "\"") | gsub("&#39;"; "'\''")
    | gsub("[[:space:]]+"; " ")
    | sub("^ +"; "") | sub(" +$"; "")
    | if (cap > 0 and length > cap) then (.[0:(cap-1)] + "…") else . end;

def is_safe(url):
    (url // "" | test("^https?://")) as $scheme_ok
    | (host_of(url) | ascii_downcase) as $h
    | $scheme_ok
      and ($h | length > 0)
      and (matches_set($h; $blocklist) | not)
      and (
        if ($allowlist | length) > 0
        then matches_set($h; $allowlist)
        else (is_dangerous($h) | not)
        end
      );

(.results // []) as $raw
| [ $raw[]
    | select(.url and is_safe(.url))
    | {
        title:   strip_html(.title; 300),
        url:     .url,
        snippet: strip_html(.content; $maxsnippet),
        engine:  (
            if (.engine | type) == "string" then .engine
            elif (.engines | type) == "array" then (.engines | join(", "))
            else ""
            end
        ),
        score:   (if (.score | type) == "number" then .score else null end)
      }
  ]
| .[0:$maxres] as $cleaned
| {query: $query, count: ($cleaned | length), results: $cleaned}
'
)"

if [ "$FORMAT" = "compact" ]; then
    printf '%s\n' "$processed" | jq -r '.results[] | "\(.title)\t\(.url)\t\(.snippet)"'
else
    printf '%s\n' "$processed"
fi
