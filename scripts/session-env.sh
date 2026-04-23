#!/usr/bin/env bash
# session-env.sh — Scraper Post WordPress
# Load minimal environment for worker session.

export PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export ENV="${ENV:-development}"
export LOG_LEVEL="${LOG_LEVEL:-info}"

# Validate .env exists if production
if [[ "$ENV" == "production" ]] && [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  printf 'ERROR: .env required in production\n' >&2
  exit 1
fi

# Load .env if present (never override existing env vars)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck source=.env
  source "$PROJECT_ROOT/.env"
  set +a
fi
