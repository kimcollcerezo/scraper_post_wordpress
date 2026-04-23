#!/usr/bin/env bash
# validate.sh — Validació d'entorn i dependències
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/session-env.sh"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
ok()   { printf 'OK:   %s\n' "$1"; }

# .env
[ -f "$PROJECT_ROOT/.env" ] && ok ".env present" || printf 'WARN: .env absent (using environment variables)\n'

# config/sources.yml
[ -f "$PROJECT_ROOT/config/sources.yml" ] && ok "config/sources.yml present" || fail "config/sources.yml missing"

# Python
command -v python3 >/dev/null 2>&1 && ok "python3 found" || fail "python3 not found"

# ruff
command -v ruff >/dev/null 2>&1 && ok "ruff found" || fail "ruff not found"

# pytest
command -v pytest >/dev/null 2>&1 && ok "pytest found" || fail "pytest not found"

# ruff check
ruff check "$PROJECT_ROOT/src" 2>/dev/null && ok "ruff lint passed" || fail "ruff lint failed"

printf '\nValidation complete.\n'
