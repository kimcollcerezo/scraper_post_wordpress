# Worker Contract — Scraper Post WordPress

Aquest document defineix el contracte d'execució del worker. És la font de veritat per a decisions d'implementació.

---

## Objectiu

Extreure posts de fonts CMS (WordPress REST API, altres) i inserir-los en projectes destí de forma idempotent, controlada i auditable.

---

## Invariants (no negociables)

1. **No insert without deduplication.** Tota inserció ha de verificar duplicat abans d'executar.
2. **No destructive operation without explicit confirmation.** Esborrats i sobreescriptures requereixen confirmació.
3. **No credentials outside `.env`.** Cap secret al codi ni a config versionada.
4. **No silent failures.** Tot error ha de ser loggat i propagar-se.
5. **No external CMS mutation without dry-run support.** Tota operació d'escriptura externa ha de tenir mode `--dry-run`.
6. **No retry loop without max attempts.** Màxim definit a configuració, no hardcodejar.
7. **No worker run without structured log output.** Format JSON o clau=valor.
8. **No production execution without explicit environment.** `ENV=production` ha de ser explícit.

---

## Execution Flow

```
1. Carregar entorn (.env via session-env.sh)
2. Llegir fonts actives (config/sources.yml)
3. Fetch de posts de la font CMS
4. Deduplicació (comparar amb destí)
5. Dry-run si és la primera execució o si s'especifica
6. Inserció idempotent al destí
7. Log estructurat del resultat
8. Validació post-inserció
```

---

## Rate Limiting

- Respectar `robots.txt` i límits de l'API
- Delay configurable entre requests (`config/sources.yml`)
- Backoff exponencial en errors de xarxa

---

## Retry Policy

- Màxim de reintents: definit per font a `config/sources.yml`
- Backoff: exponencial amb jitter
- Errors fatals (401, 403, 404): no reintentar

---

## Deduplication

- Clau de deduplicació: `(source_id, source_url)` o equivalent
- Verificar abans de cada inserció
- Registrar resultat: `inserted` | `skipped` | `updated`

---

## Dry-Run

- Disponible per a tota operació d'escriptura
- Mode: `--dry-run` o `DRY_RUN=true`
- Output: log de què s'hauria inserit/modificat, sense executar

---

## Logging

```
{"ts": "...", "level": "info|warn|error", "event": "...", "source": "...", "post_id": "...", "result": "inserted|skipped|error"}
```

---

## Principle

Minimal context. Explicit contracts. Idempotent execution. Fail-closed always.
