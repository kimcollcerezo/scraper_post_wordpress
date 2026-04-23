# Redmine Policy — Scraper Post WordPress

Projecte Redmine: `agent-scrapper-post-wordpress-cms`

---

## Crear o actualitzar Redmine quan hi hagi

- Canvi d'arquitectura del worker
- Nova font CMS afegida o eliminada
- Canvi de schema de dades (estructura de posts)
- Canvi en lògica de deduplicació
- Canvi en política de retries o backoff
- Canvi en lògica d'inserció al destí
- Canvi de credencials o configuració de deploy
- Bug reproductible identificat
- Decisió funcional rellevant (dry-run, idempotència, rate limiting)

---

## No cal Redmine per

- Correccions de format o estil (ruff)
- Refactors interns sense canvi de comportament
- Millores de log sense canvi de lògica
- Actualitzacions de dependències menors sense impacte

---

## Format mínim d'una issue

```
Títol: [worker] Descripció breu
Descripció: Què, per què, impacte
Estat inicial: New
```

---

## Regla operativa

Si el canvi afecta el comportament observable del worker (fetch, dedup, insert, retry, deploy) → Redmine obligatori abans de tancar la tasca.

En cas de dubte → crear issue.
