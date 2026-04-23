# Worker Contract — Despertare Migration Engine

Aquest document defineix el contracte d'execució del Migration Engine. És la font de veritat per a decisions d'implementació.

> **Nota d'arquitectura:** Aquest projecte implementa un sistema d'ingestió editorial reutilitzable (Despertare Migration Engine), no un script puntual. El primer adapter suportat és WordPress, però el sistema és multi-CMS i multi-projecte per disseny (veure ADR-0005).

---

## Objectiu

Migrar contingut editorial des de fonts CMS externes (WordPress i altres) cap al model editorial de Despertare de forma idempotent, auditable i governada.

---

## Pipeline d'execució

El worker implementa la pipeline completa:

```
Extract → Snapshot → Transform → Validate → Import → Validate Post-Import
```

Cap fase pot saltar-se. Cap contingut arriba a Despertare sense passar per totes les fases.

### Fase 1 — Extract

- Obté contingut del CMS origen via l'adapter configurat.
- No interpreta ni transforma: captura l'estat de l'origen.
- Registra `extracted_at`, `source_system`, `source_id`, `content_hash`.

### Fase 2 — Snapshot

- Persisteix el resultat d'Extract com a fitxer JSON local immutable (ADR-0007).
- Format: `snapshots/{source_system}/{source_id}.json`
- Desacobla l'extracció de la transformació: les fases següents operen sobre el snapshot, mai sobre el CMS origen directament.
- Permet re-executar Transform/Validate/Import sense re-contactar l'origen.

### Fase 3 — Transform

- Llegeix els snapshots de la Fase 2.
- Converteix contingut legacy al model editorial Despertare:
  - HTML / Gutenberg / Elementor → blocs JSON (ADR-0011)
  - hero image → bloc `hero`
  - taxonomies → estructura normalitzada
  - SEO → `seo_metadata`
  - autor → referència resoluble
  - dates → conservació de `published_at`, `created_at`
- Genera warnings per contingut no convertible a blocs nadius.
- Contingut no transformable → bloc `raw_html` marcat `legacy: true`, mai silenciós.
- Mesura `raw_html_ratio`; aplica llindar configurat (ADR-0011).

### Fase 4 — Validate

- Valida el resultat de Transform contra les regles del projecte destí.
- Aplica resolució de conflictes persistents (ADR-0010): autors, taxonomies, slugs.
- Classifica cada ítem: `ready` | `ready_with_warnings` | `pending_review` | `blocked`.
- Items `blocked` no avancen a Import sense intervenció manual.

### Fase 5 — Import

- Importa ítems validats via la Import API de Despertare (ADR-0009).
- Crea `content_item`, `content_localization`, `content_version`.
- No accedeix directament a PostgreSQL.
- Registra `migration_source_map` per idempotència.
- Importa assets via media sub-pipeline (ADR-0006).

### Fase 6 — Validate Post-Import

- Verifica el resultat real al destí via HTTP (no el payload enviat).
- Crawl de les URLs importades: status, meta tags, canonical, OG, redirects (ADR-0012).
- Compara amb l'estat pre-migració capturat a la Fase 1.
- Genera informe SEO: `artifacts/seo/seo-summary-{batch_id}.json`
- Errors de post-validació no bloquegen el batch completat, però queden registrats i alertats.
- Pas obligatori per a `import-production`; opcional per a `import-staging`.

---

## Modes d'execució

Definits a ADR-0008:

- `dry-run` — verifica sense escriure (obligatori com a primer pas)
- `extract-only` — genera snapshots locals
- `import-staging` — importa a staging
- `import-production` — importa a producció (requereix confirmació explícita)
- `validate` — re-valida snapshots existents
- `resume` — reprèn execució interrompuda
- `rollback-plan` — genera pla de reversió (no executa)

---

## Invariants (no negociables)

1. **No import without validation.** Cap ítem entra a Despertare sense passar per Validate.
2. **No direct DB access.** Tota importació passa per la Import API (ADR-0009).
3. **No credentials outside `.env`.** Cap secret al codi ni a config versionada.
4. **No silent failures.** Tot error loggat i propagat.
5. **No external mutation without dry-run.** Tota operació d'escriptura ha de tenir mode dry-run.
6. **No retry loop without max attempts.** Màxim definit a configuració.
7. **No production execution without explicit environment.** `ENV=production` explícit.
8. **No import without idempotency check.** `migration_source_map` sempre consultat.
9. **No raw_html without warning.** Bloc `raw_html` sempre marcat i registrat.
10. **No media import without deduplication.** Hash verificat abans de cada asset.

---

## Logs estructurats

Format obligatori per tota operació:

```
{"ts": "ISO8601", "level": "info|warn|error", "event": "...", "batch_id": "...", "source_id": "...", "detail": "..."}
```

Secrets mai als logs.

---

## Errors i warnings

Definits a ADR-0004. Errors bloquejants i warnings no bloquejants.

---

## Idempotència

- Clau: `(source_system, source_id, source_url)`
- `migration_source_map` consultat abans de cada import.
- Política de duplicat configurable: `skip` | `update_draft` | `create_version` | `fail`

---

## Seguretat

- Credencials via `.env`
- Timeouts configurables per request
- Retries amb backoff exponencial i límit màxim
- Rate limiting respectat (per font a `config/sources.yml`)
- Validació SSL obligatòria
- Allowlist de dominis per descàrrega d'assets
- MIME real detectat, no declarat

---

## Scripts d'entrada

- `scripts/run-worker.sh` — execució del worker
- `scripts/validate.sh` — validació d'entorn
- `scripts/test.sh` — lint + tests
- `scripts/check-idempotency.sh` — verificació d'idempotència en dry-run

---

## Relació amb ADRs

| ADR | Relació |
|---|---|
| ADR-0004 | Pipeline ETL — aquest contracte l'implementa |
| ADR-0005 | WordPress Source Adapter — primer adapter suportat |
| ADR-0006 | Media Normalization Policy — sub-pipeline de la fase Import |
| ADR-0007 | Format intermedi canònic — unitat de transferència entre fases |
| ADR-0008 | Estratègia d'execució — modes i estat persistent |
| ADR-0009 | Import API de Despertare — connector de la fase Import |
| ADR-0010 | Resolució de conflictes — autors, taxonomies, slugs |
| ADR-0011 | Content Blocks Strategy — fase Transform |
| ADR-0012 | SEO Validation Strategy — validació post-import |

---

## Principle

Minimal context. Explicit contracts. Idempotent execution. Fail-closed always.
