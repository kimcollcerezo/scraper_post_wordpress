# Scraper Post WordPress

Agent per extreure posts de WordPress o altres CMS i poder inserir en projectes

---

## Context

Aquest fitxer defineix **regles operatives locals** per a aquest projecte Python.

La governança global (ADR, Redmine, documentació, enforcement) es gestiona des de:
→ `~/.claude/governance`

---

## Principis

- No inventar comportament no verificat
- Context insuficient → STOP i demanar informació
- Decisions rellevants → documentar a `docs_custom/`
- Commits nets (sense referències a IA)

---

## Execution model

- Entendre mínim context necessari
- Executar sense exploració innecessària
- Respectar contractes i estructura existent
- Validar abans de considerar la tasca completada

---

## Python rules

- Codi clar, explícit i determinista
- Errors explícits (no silenciosos)
- Evitar side-effects ocults
- Separar:
  - IO / infra
  - lògica de negoci

---

## Tooling

- Lint → ruff
- Format → ruff format
- Tests → pytest
- Types → mypy (si aplica)

---

## Notes

- Redmine, ADR, documentació i tracking:
  → gestionats automàticament pel sistema de governança

- Aquest fitxer NO defineix governança
  → només comportament local de desenvolupament
