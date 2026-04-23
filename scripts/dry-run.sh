#!/usr/bin/env bash
# dry-run.sh — Executa dry-run complet
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/session-env.sh"
cd "$PROJECT_ROOT/packages/migration-agent"
exec python3 -m migration_agent.cli --mode dry-run "$@"
