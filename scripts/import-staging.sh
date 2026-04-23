#!/usr/bin/env bash
# import-staging.sh — Import cap a staging
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/session-env.sh"
cd "$PROJECT_ROOT/packages/migration-agent"
exec python3 -m migration_agent.cli --mode import-staging "$@"
