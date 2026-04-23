#!/usr/bin/env bash
# check-idempotency.sh — Verificació d'idempotència
# Executa el worker en dry-run dues vegades i compara output.
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/session-env.sh"

TMP_DIR="$(mktemp -d)"
RUN1="$TMP_DIR/run1.jsonl"
RUN2="$TMP_DIR/run2.jsonl"

cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

printf '→ Run 1 (dry-run)\n'
DRY_RUN=true python3 "$PROJECT_ROOT/src/main.py" > "$RUN1"

printf '→ Run 2 (dry-run)\n'
DRY_RUN=true python3 "$PROJECT_ROOT/src/main.py" > "$RUN2"

if diff -q "$RUN1" "$RUN2" >/dev/null 2>&1; then
  printf 'OK: idempotency verified (both runs identical)\n'
else
  printf 'FAIL: runs differ — idempotency not guaranteed\n' >&2
  diff "$RUN1" "$RUN2" >&2
  exit 1
fi
