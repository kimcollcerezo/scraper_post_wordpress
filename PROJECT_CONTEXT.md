# Project Context — Scraper Post WordPress

## Identity

- Name: Scraper Post WordPress
- Slug: scraper-post-wordpress
- Type: Python worker
- Status: active
- Redmine: agent-scrapper-post-wordpress-cms

---

## Stack

Python · worker · Docker local · agents-prod-01 (178.104.54.56)

---

## Precedence

`docs/worker-contract.md` → code → `PROJECT_CONTEXT.md` → `CLAUDE.md` → global

Conflicte → indicar abans d'actuar.

---

## Critical Areas

No modificar sense context complet:

- deduplicació · schema de dades · `config/sources.yml` · `.env` · retry logic · connexió destí

---

## Key Scripts

- `scripts/run-worker.sh` — execució del worker
- `scripts/validate.sh` — validació d'entorn i dependències
- `scripts/test.sh` — tests (ruff + pytest)
- `scripts/check-idempotency.sh` — verificació idempotència

---

## Bootstrap

- Entry: `AGENT_BOOTSTRAP.md`
- Session: `./codex-start.sh`

---

## Deep Docs (load on demand only)

- `docs/worker-contract.md` — contracte d'execució
- `docs/redmine-policy.md` — política de tracking
- `docs/architecture.md` — arquitectura (quan existeixi)

---

## Principle

Minimal context. Explicit contracts. Idempotent execution. Fail-closed always.
