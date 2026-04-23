#!/usr/bin/env bash
# codex-start.sh — Scraper Post WordPress
# Delegates to global Codex launcher with minimal governed context.

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLOBAL_CODEX_START="$HOME/.claude/tools/codex-start.sh"
SESSION_ENV="$PROJECT_ROOT/scripts/session-env.sh"

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
has_file() { [ -f "$1" ]; }

has_file "$GLOBAL_CODEX_START" || fail "missing global launcher: $GLOBAL_CODEX_START"
has_file "$PROJECT_ROOT/PROJECT_CONTEXT.md" || fail "missing PROJECT_CONTEXT.md"
has_file "$PROJECT_ROOT/AGENT_BOOTSTRAP.md" || fail "missing AGENT_BOOTSTRAP.md"
has_file "$SESSION_ENV" || fail "missing scripts/session-env.sh"

# shellcheck source=scripts/session-env.sh
source "$SESSION_ENV"

# ── Domain inference (max 2) ───────────────────────────────────────────────────
detect_domains() {
  local input norm result=""
  input="${1:-}"; norm="$(printf '%s' "$input" | tr '[:upper:]' '[:lower:]')"

  add() { [[ " $result " != *" $1 "* ]] && result="${result:+$result }$1"; }

  [[ "$norm" == *"crawl"* || "$norm" == *"fetch"* || "$norm" == *"extract"* || "$norm" == *"html"* || "$norm" == *"cms"* || "$norm" == *"wordpress"* ]] && add "scraping"
  [[ "$norm" == *"insert"* || "$norm" == *"post"* || "$norm" == *"sync"* || "$norm" == *"push"* || "$norm" == *"target"* ]] && add "insertion"
  [[ "$norm" == *"pipeline"* || "$norm" == *"queue"* || "$norm" == *"schedule"* || "$norm" == *"worker"* || "$norm" == *"retry"* ]] && add "pipeline"
  [[ "$norm" == *"docker"* || "$norm" == *"deploy"* || "$norm" == *"server"* || "$norm" == *"env"* || "$norm" == *"config"* ]] && add "infra"

  local trimmed="" count=0
  for d in $result; do
    count=$((count+1)); [[ $count -le 2 ]] && trimmed="${trimmed:+$trimmed }$d"
  done
  printf '%s' "$trimmed"
}

# ── Context history (one line) ─────────────────────────────────────────────────
record_context() {
  local domains="$1"; [[ -n "$domains" ]] || return 0
  local dir="$PROJECT_ROOT/artifacts/context-history"
  mkdir -p "$dir"
  printf '{"ts":"%s","domains":"%s","user":"%s"}\n' \
    "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$domains" "${USER:-unknown}" \
    >> "$dir/$(date -u +"%Y-%m-%d").jsonl"
}

DOMAINS="$(detect_domains "$*")"
DOMAIN_HINT="Load minimum context only."
[[ -n "$DOMAINS" ]] && DOMAIN_HINT="Domains detected (max 2): $DOMAINS. Load only what the task requires."

record_context "$DOMAINS"

# ── Bootstrap prompt (minimal) ─────────────────────────────────────────────────
export CODEX_BOOTSTRAP_PROMPT="Follow AGENT_BOOTSTRAP.md.
Read PROJECT_CONTEXT.md only if the task requires it.
Do not explore the project without need.
Fail-closed: errors must be explicit, never silent.
Idempotency is mandatory before any insert.
${DOMAIN_HINT}
Governance: if task changes architecture, schema, CMS source, retry logic or deploy — evaluate Redmine before finishing."

exec "$GLOBAL_CODEX_START" "$@"
