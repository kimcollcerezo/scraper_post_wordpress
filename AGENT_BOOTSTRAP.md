# Agent Bootstrap — Scraper Post WordPress

Worker Python per extreure posts de CMS i inserir-los en projectes destí.

---

# Reading Order

1. `AGENT_BOOTSTRAP.md` (aquest fitxer)
2. `CLAUDE.md`
3. `PROJECT_CONTEXT.md` — només si la tasca ho requereix
4. `docs/worker-contract.md` — per a tasques d'inserció o deduplicació
5. `docs/redmine-policy.md` — per avaluar obligació de tracking

No carregar context addicional sense necessitat.

---

# What the Agent Cannot Do

- Inserir dades sense deduplicació verificada
- Executar en producció sense `ENV=production` explícit
- Modificar dades externes sense dry-run disponible
- Silenciar errors (`except: pass`)
- Hardcodejar credencials
- Fer retries infinits

---

# Stop Conditions

Aturar i reportar si:

- font CMS no definida o no accessible
- credencials absents o invàlides
- entorn de destí no confirmat
- acció destructiva sense confirmació explícita
- idempotència no verificable

---

# When to Create/Update Redmine

Consultar `docs/redmine-policy.md`.

Resum: arquitectura, nova font, canvi de schema, canvi de retry, bug reproductible → Redmine obligatori.

---

# Pipeline

```
ruff → pytest → validate.sh → check-idempotency.sh → execució
```

Error en qualsevol fase → STOP. No bypass.

---

# File Priority

```
docs/worker-contract.md  → contracte d'execució
CLAUDE.md                → regles operatives
PROJECT_CONTEXT.md       → context del projecte
.env                     → credencials (mai al codi)
config/sources.yml       → fonts CMS actives
```

---

# Principle

Minimal context. Explicit contracts. Idempotent execution. Fail-closed always.
