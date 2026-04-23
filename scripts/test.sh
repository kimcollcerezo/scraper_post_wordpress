#!/usr/bin/env bash
# test.sh — Lint i tests
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/session-env.sh"

printf '→ ruff format check\n'
ruff format --check "$PROJECT_ROOT/src"

printf '→ ruff lint\n'
ruff check "$PROJECT_ROOT/src"

printf '→ pytest\n'
pytest "$PROJECT_ROOT/tests" -v

printf '\nAll checks passed.\n'
