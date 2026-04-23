#!/usr/bin/env bash
# DevGov OS — codex-start template
# Version: 1.1.0
#
# Purpose:
# - start Codex with minimal, mode-aware bootstrap
# - align with DevGov runtime model
# - avoid unnecessary context loading
#
# Usage:
#   ./codex-start.sh [ultra|fast|normal|deep] [extra codex args...]

set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
PROJECT_NAME="$(basename "$PROJECT_ROOT")"
MODE="${1:-}"

GLOBAL_CLAUDE_MD="$HOME/.claude/CLAUDE.md"
GLOBAL_CODEX_CONTEXT="$HOME/.claude/CODEX_CONTEXT.md"
GLOBAL_AGENT_KERNEL="$HOME/.claude/governance/runtime/agent-kernel.md"
GLOBAL_DOC_IMPACT="$HOME/.claude/governance/runtime/documentation-impact-map.md"

log() {
  printf '→ %s\n' "$1"
}

fail() {
  printf '✗ %s\n' "$1" >&2
  exit 1
}

has_file() {
  [ -f "$1" ]
}

print_menu() {
  echo "Mode Codex ($PROJECT_NAME):"
  echo
  echo "  0) ultra   - Micro task, single target, zero exploration"
  echo "  1) fast    - Small local change"
  echo "  2) normal  - Standard project work"
  echo "  3) deep    - Deep task with targeted extra context"
  echo
  read -r -p "Option [2]: " choice

  case "${choice:-2}" in
    0) MODE="ultra" ;;
    1) MODE="fast" ;;
    2) MODE="normal" ;;
    3) MODE="deep" ;;
    ultra|fast|normal|deep) MODE="$choice" ;;
    *) MODE="normal" ;;
  esac
}

validate_runtime_contract() {
  has_file "$PROJECT_ROOT/PROJECT_CONTEXT.md" \
    || fail "Missing PROJECT_CONTEXT.md in $PROJECT_ROOT"

  has_file "$GLOBAL_CLAUDE_MD" \
    || fail "Missing global CLAUDE.md at $GLOBAL_CLAUDE_MD"

  has_file "$GLOBAL_CODEX_CONTEXT" \
    || fail "Missing global CODEX_CONTEXT.md at $GLOBAL_CODEX_CONTEXT"

  has_file "$GLOBAL_AGENT_KERNEL" \
    || fail "Missing runtime agent-kernel.md at $GLOBAL_AGENT_KERNEL"

  has_file "$GLOBAL_DOC_IMPACT" \
    || fail "Missing runtime documentation-impact-map.md at $GLOBAL_DOC_IMPACT"
}

validate_deep_mode() {
  has_file "$PROJECT_ROOT/AGENT_BOOTSTRAP.md" \
    || fail "Deep mode requires AGENT_BOOTSTRAP.md in $PROJECT_ROOT"
}

normalize_mode_arg() {
  if [[ "$MODE" == "ultra" || "$MODE" == "fast" || "$MODE" == "normal" || "$MODE" == "deep" ]]; then
    shift || true
  else
    MODE=""
  fi

  REMAINING_ARGS=("$@")
}

build_bootstrap_prefix() {
  BOOTSTRAP_PREFIX=""
  if [ -n "${CODEX_BOOTSTRAP_PROMPT:-}" ]; then
    BOOTSTRAP_PREFIX="${CODEX_BOOTSTRAP_PROMPT}

"
  fi
}

build_mode_prompt() {
  case "$MODE" in
    ultra)
      MODE_PROMPT="Micro task. Do not explore the project. Read only the minimum required files. Make only the exact requested change."
      ;;
    fast)
      MODE_PROMPT="Small local task. Avoid broad exploration. Read only the files required to complete the change safely."
      ;;
    normal)
      MODE_PROMPT="Before acting, read PROJECT_CONTEXT.md, then follow the DevGov runtime model: minimal context, classify the task, evaluate Redmine need, evaluate documentation impact, then execute only what is necessary."
      ;;
    deep)
      MODE_PROMPT="Before acting, read AGENT_BOOTSTRAP.md and PROJECT_CONTEXT.md, then follow AGENT_BOOTSTRAP.md strictly. Load additional reference or engineering standards only if required by the task."
      ;;
    *)
      fail "Unknown mode: $MODE"
      ;;
  esac

  FINAL_PROMPT="${BOOTSTRAP_PREFIX}${MODE_PROMPT}"
}

main() {
  normalize_mode_arg "$@"

  if [[ -z "$MODE" ]]; then
    print_menu
  fi

  validate_runtime_contract

  if [[ "$MODE" == "deep" ]]; then
    validate_deep_mode
  fi

  build_bootstrap_prefix
  build_mode_prompt

  cd "$PROJECT_ROOT"

  log "Starting Codex in '$MODE' mode for $PROJECT_NAME"

  exec codex --profile "$MODE" "${REMAINING_ARGS[@]}" "$FINAL_PROMPT"
}

main "$@"
