#!/usr/bin/env bash
# run-worker.sh — Execució del worker
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/session-env.sh"

DRY_RUN="${DRY_RUN:-false}"

if [[ "$ENV" == "production" ]]; then
  printf '→ Production mode. ENV=production confirmed.\n'
fi

if [[ "$DRY_RUN" == "true" ]]; then
  printf '→ DRY_RUN mode enabled. No writes will be executed.\n'
fi

exec python3 "$PROJECT_ROOT/src/main.py" "$@"
