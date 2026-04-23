# Agent Bootstrap — Scraper Post WordPress

Minimal entry point for agent operations.

---

# Read First

For any non-trivial task:

1. `PROJECT_CONTEXT.md`
2. `~/.claude/CODEX_CONTEXT.md`
3. `~/.claude/CLAUDE.md`
4. `~/.claude/governance/runtime/agent-kernel.md`
5. `~/.claude/governance/runtime/documentation-impact-map.md`

Load additional context ONLY if required.

---

# Local Contract

- `PROJECT_CONTEXT.md` defines project reality
- local rules override global ONLY for project specifics
- security rules are never weakened
- conflicts → must be surfaced before acting

---

# Execution

All work MUST follow global governance runtime:

- classify task
- evaluate tracking (Redmine)
- evaluate documentation impact (ADR / docs / contracts / wiki)
- implement minimal scope
- validate
- complete governance obligations

→ Defined in:

- `agent-kernel.md`
- `documentation-impact-map.md`

---

# Python Worker Safety (MANDATORY)

Stop immediately if:

- target CMS / API endpoint is unclear
- credentials or auth method not confirmed
- environment unknown (prod/staging/dev)
- action impact is unclear (destructive insert, deduplication state)

---

# Hard Stop Conditions

Require explicit confirmation before:

- destructive operations on data (`delete`, `truncate`, `overwrite`)
- modification of credentials or `.env`
- changes to rate limiting or retry logic in production
- any production-impact action

---

# Quality Gates

- data operations → validate idempotency
- validation failure → fix, never bypass

---

# Execution Policy

- act autonomously
- avoid micro-confirmations
- prefer safe, reversible actions
- production risk → always confirm

---

# Session

- start: `./codex-start.sh` if present
- no assumption of persistence outside explicit context

---

# Principle

Worker = correctness + idempotency + governance
