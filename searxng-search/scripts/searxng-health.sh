#!/usr/bin/env bash
# searxng-health.sh — fast probe for the SearXNG instance referenced by
# SEARXNG_URL. Prints one human-readable status line per check and exits
# 0 only if every check passes.
#
# Used by the `searxng-search` Hermes skill before issuing real queries.

set -o errexit
set -o nounset
set -o pipefail

readonly TIMEOUT="${SEKURVIA_HEALTH_TIMEOUT_S:-5}"
readonly USER_AGENT="${SEKURVIA_USER_AGENT:-hermes-searxng-skill/0.1}"

ok()   { printf '%-4s %s\n' "OK"   "$*"; }
warn() { printf '%-4s %s\n' "WARN" "$*" >&2; }
fail() { printf '%-4s %s\n' "FAIL" "$*" >&2; }

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        fail "required command not found: $1 (install via your package manager; on NixOS add to systemPackages)"
        exit 2
    fi
}

# Check dependencies first so failure messages are clean.
require_cmd curl
require_cmd jq

if [ -z "${SEARXNG_URL:-}" ]; then
    fail "SEARXNG_URL is not set"
    exit 2
fi

case "$SEARXNG_URL" in
    http://*|https://*) ;;
    *)
        fail "SEARXNG_URL must start with http:// or https:// (got: $SEARXNG_URL)"
        exit 2
        ;;
esac

base="${SEARXNG_URL%/}"
ok "SEARXNG_URL=${base}"

# -- 1. is the instance up? ---------------------------------------------------

set +e
status="$(curl --silent --show-error \
               --max-time "$TIMEOUT" \
               --user-agent "$USER_AGENT" \
               --output /dev/null \
               --write-out '%{http_code}' \
               "${base}/" 2>&1)"
curl_exit=$?
set -e

if [ "$curl_exit" -ne 0 ]; then
    case "$curl_exit" in
        6)  fail "could not resolve host in SEARXNG_URL" ;;
        7)  fail "connection refused at ${base}" ;;
        28) fail "timed out after ${TIMEOUT}s contacting ${base}" ;;
        *)  fail "curl exit ${curl_exit} contacting ${base}: ${status}" ;;
    esac
    exit 1
fi

if [ "$status" -lt 200 ] || [ "$status" -ge 500 ]; then
    fail "instance returned HTTP ${status} on /"
    exit 1
fi
ok "instance is reachable (HTTP ${status} on /)"

# -- 2. is format=json enabled? -----------------------------------------------

set +e
json_status="$(curl --silent --show-error \
                     --max-time "$TIMEOUT" \
                     --user-agent "$USER_AGENT" \
                     --output /tmp/sekurvia-health.$$ \
                     --write-out '%{http_code}' \
                     --data-urlencode "q=hermes-searxng-skill-healthcheck" \
                     --data "format=json" \
                     --data "safesearch=1" \
                     --data "pageno=1" \
                     "${base}/search" 2>&1)"
json_exit=$?
set -e
trap 'rm -f /tmp/sekurvia-health.$$' EXIT

if [ "$json_exit" -ne 0 ]; then
    fail "json health probe failed (curl exit ${json_exit}): ${json_status}"
    exit 1
fi

if [ "$json_status" = "403" ]; then
    fail "JSON format is NOT enabled on this instance (HTTP 403 on /search?format=json)"
    fail "fix: add 'json' under 'search.formats' in the instance's settings.yml"
    exit 1
fi

if [ "$json_status" -ne 200 ]; then
    warn "instance returned HTTP ${json_status} on /search?format=json (expected 200)"
fi

if jq -e '.results | type == "array"' /tmp/sekurvia-health.$$ >/dev/null 2>&1; then
    ok "JSON format is enabled (got valid results array)"
else
    body_preview="$(head -c 200 /tmp/sekurvia-health.$$)"
    fail "instance returned non-JSON or unexpected JSON: ${body_preview}"
    exit 1
fi

ok "all checks passed"
exit 0
