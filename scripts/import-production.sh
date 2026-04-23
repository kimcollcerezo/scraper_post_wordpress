#!/usr/bin/env bash
# import-production.sh — Import a producció (requereix ENV=production i --confirm-production)
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/session-env.sh"

if [[ "${ENV:-}" != "production" ]]; then
  printf 'ERROR: ENV=production requerit\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT/packages/migration-agent"
exec python3 -m migration_agent.cli --mode import-production --confirm-production "$@"
