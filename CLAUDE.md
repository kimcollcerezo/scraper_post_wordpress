# Scraper Post WordPress

Agent per extreure posts de WordPress o altres CMS i inserir-los en projectes destí.

---

# Principles

1. Fail-closed — errors explícits, mai silenciosos
2. Idempotent — cap inserció sense deduplicació prèvia
3. Minimal context — carregar només el necessari
4. Credentials outside code — sempre via `.env`
5. No external mutation without dry-run support

---

# Precedence

`docs/worker-contract.md` → `CLAUDE.md` → `PROJECT_CONTEXT.md` → global `~/.claude/CLAUDE.md`

Conflicte → indicar abans d'actuar.

---

# Execution Flow

1. Llegir `AGENT_BOOTSTRAP.md` i classificar la tasca
2. Validar entorn i credencials (`.env`)
3. Executar amb scope mínim
4. Verificar idempotència abans de qualsevol inserció
5. Logs estructurats de tota operació
6. Validar resultat (`scripts/validate.sh`)
7. Avaluar obligació Redmine (veure `docs/redmine-policy.md`)

---

# Worker Rules (MANDATORY)

- No `except: pass` ni `except Exception` sense log explícit
- No credencials hardcodejades — sempre `.env`
- No inserció sense comprovació de duplicat
- No retry sense límit màxim de reintents
- No scraping sense rate limiting
- No mutació de dades externes sense confirmació explícita
- No execució en producció sense `ENV=production` explícit
- Logs estructurats (JSON o clau=valor) en tota operació
- Dry-run ha de ser possible per a qualsevol operació d'escriptura

---

# Critical Areas

No modificar sense context complet:

- lògica de deduplicació
- schema de dades
- configuració de fonts CMS (`config/sources.yml`)
- credencials i `.env`
- retry / backoff logic
- connexió al destí d'inserció

---

# Tooling

- Lint / format → `ruff`
- Tests → `pytest`
- Validació → `scripts/validate.sh`
- Idempotència → `scripts/check-idempotency.sh`

---

# Principle

Minimal context. Explicit contracts. Idempotent execution. Fail-closed always.
