# ADR-0008 — Import Execution Strategy

**Data:** 2026-04-23
**Estat:** Acceptat
**Autors:** CTO / Arquitectura
**Projecte:** scraper-post-wordpress / sistema d'importació editorial Despertare

---

## Context

La pipeline d'importació (ADR-0004) necessita una estratègia d'execució que permeti:

- verificar sense escriure (dry-run)
- executar de forma segura i repetible
- reprendre execucions interrompudes
- gestionar errors per ítem sense aturar tot el batch
- saber exactament l'estat de cada ítem en tot moment
- aplicar polítiques configurables quan un ítem ja existeix al destí

L'execució és un aspecte transversal: no pertany a l'adapter de font ni al connector Despertare. Viu a la capa d'orquestració de la pipeline.

---

## Decisió

**La pipeline d'importació suporta modes d'execució explícits, configurables per invocació, amb estat persistent per ítem i batch.**

Cap execució pot ser ambigua respecte al seu mode. El mode s'especifica sempre explícitament.

---

## Modes d'execució

### `dry-run`

- Executa les fases Extract, Transform i Validate completament.
- No executa Import.
- No escriu cap dada al sistema destí.
- No modifica snapshots existents (tret que `--force-extract`).
- Genera informe complet (veure secció Informe).
- Repetible sense efectes secundaris.
- **Obligatori com a primer pas de qualsevol import real.**

Invocació: `--mode dry-run`

---

### `extract-only`

- Executa únicament la fase Extract.
- Genera i desa snapshots JSON locals.
- No transforma, no valida, no importa.
- Útil per capturar l'estat del CMS origen en un moment concret.
- Els snapshots queden disponibles per a execucions posteriors sense re-extracció.

Invocació: `--mode extract-only`

---

### `import-staging`

- Executa totes les fases: Extract (o usa snapshots), Transform, Validate, Import.
- Importa cap a l'entorn de staging de Despertare.
- Requereix `ENV=staging` configurat.
- Genera informe complet.
- Recomanat com a validació pre-producció.

Invocació: `--mode import-staging`

---

### `import-production`

- Executa totes les fases cap a l'entorn de producció.
- Requereix `ENV=production` configurat explícitament.
- Requereix que s'hagi executat prèviament `dry-run` o `import-staging` per al mateix batch.
- Si no hi ha execució prèvia registrada, falla amb error explícit.
- Genera informe complet.

Invocació: `--mode import-production`

---

### `validate`

- Executa Transform i Validate sobre snapshots existents.
- No extreu de l'origen. No importa.
- Útil per re-validar snapshots ja extrets sense contactar l'origen.

Invocació: `--mode validate`

---

### `resume`

- Reprèn una execució interrompuda a partir de l'estat persistent.
- Omite els ítems amb `import_status: imported` o `import_status: skipped`.
- Processa els ítems en estat `pending`, `failed` o `pending_review`.
- Usa el `import_batch_id` original.

Invocació: `--mode resume --batch-id <uuid>`

---

### `rollback-plan`

- No executa cap import.
- Analitza els ítems importats en un batch i genera un pla de rollback:
  - llista d'ítems a eliminar al destí
  - llista de redirects a revertir
  - llista d'assets a eliminar
- **No executa el rollback automàticament.** Genera un pla que s'ha d'executar manualment o via script específic.
- El rollback real queda fora de l'abast de la pipeline; cada component (Import API, media sistema) té la seva pròpia lògica de reversió.

Invocació: `--mode rollback-plan --batch-id <uuid>`

---

## Estat persistent per ítem

Cada ítem té `import_state` (definit a ADR-0007) que es manté actualitzat durant tota l'execució:

| `import_status` | Significat |
|---|---|
| `pending` | No processat |
| `ready` | Validat, sense warnings |
| `ready_with_warnings` | Validat, amb warnings no bloquejants |
| `pending_review` | Requereix revisió manual abans d'importar |
| `blocked` | Error bloquejant; no pot importar sense resolució |
| `imported` | Importat correctament |
| `skipped` | Omès per política (duplicat, etc.) |
| `failed` | Error durant l'import; pot reprendre's |

---

## Batch ID i traçabilitat

- Cada execució genera un `import_batch_id` UUID únic.
- El batch ID agrupa tots els ítems d'una execució.
- Es desa a `artifacts/import-batches/{batch_id}/`:
  - `manifest.json` — configuració, mode, timestamps, resum
  - `items.jsonl` — un ítem per línia amb `import_state` final
  - `report.json` — informe complet
  - `errors.jsonl` — ítems amb errors
  - `warnings.jsonl` — ítems amb warnings

---

## Política quan un ítem ja existeix al destí

Configurable per invocació o per `config/import-policy.yml`:

| Política | Comportament |
|---|---|
| `skip` | Ometre l'ítem; `import_status: skipped` (default) |
| `update_draft` | Actualitzar el contingut si és draft al destí |
| `create_version` | Crear nova versió del contingut existent |
| `fail` | Aturar l'ítem amb error `DUPLICATE_ITEM` |

La política es pot definir per tipus de contingut:

```yaml
on_duplicate:
  post: skip
  page: update_draft
  media: skip
```

---

## Progress reporting

- Log estructurat en temps real (JSON o clau=valor).
- Format: `{"ts": "...", "level": "info", "event": "item_imported", "batch_id": "...", "source_id": "...", "status": "..."}`
- Progress counter: `[N/TOTAL] status source_id`
- Errors i warnings s'emeten en temps real, no al final.
- Compatible amb pipes i redireccions de log.

---

## Logs estructurats

Format obligatori per tota operació:

```
{"ts": "ISO8601", "level": "info|warn|error", "event": "...", "batch_id": "...", "source_system": "...", "source_id": "...", "detail": "..."}
```

Events definits:

- `batch_started`
- `item_extracted`
- `item_transformed`
- `item_validated`
- `item_imported`
- `item_skipped`
- `item_failed`
- `asset_downloaded`
- `asset_imported`
- `asset_failed`
- `batch_completed`
- `batch_resumed`

Secrets no han d'aparèixer mai als logs.

---

## Informe final

Cada execució genera un informe `report.json` amb:

```json
{
  "batch_id": "uuid",
  "mode": "dry-run",
  "started_at": "...",
  "finished_at": "...",
  "duration_seconds": 120,
  "source": {
    "system": "wordpress",
    "site_url": "https://example.com"
  },
  "summary": {
    "total_detected": 150,
    "total_importable": 142,
    "total_imported": 0,
    "total_skipped": 5,
    "total_with_warnings": 30,
    "total_blocked": 3,
    "total_failed": 0
  },
  "assets": {
    "total_detected": 320,
    "total_imported": 0,
    "total_failed": 12,
    "total_deduplicated": 8
  },
  "seo": {
    "slugs_preserved": 140,
    "slugs_conflicted": 2,
    "redirects_suggested": 10,
    "seo_incomplete": 5
  },
  "warnings": { "RAW_HTML_BLOCK_USED": 15, "MEDIA_REVIEW_REQUIRED": 7, "SEO_INCOMPLETE": 5 },
  "errors": { "SLUG_COLLISION": 2, "UNSUPPORTED_LOCALE": 1 },
  "items_blocked": [ { "source_id": 45, "error": "SLUG_COLLISION" } ],
  "shortcodes_unresolved": ["gallery", "contact-form-7"],
  "redirects_generated": []
}
```

---

## Selecció de subconjunts

La pipeline accepta filtres per limitar el scope d'una execució:

- `--ids 1,2,3` — ítems específics
- `--published-after 2024-01-01` — filtre per data
- `--modified-after 2024-06-01` — incremental
- `--post-type post,page` — filtre per tipus
- `--status publish` — filtre per estat
- `--limit 50` — màxim d'ítems per execució

---

## Seguretat d'execució

- `import-production` requereix confirmació explícita o flag `--confirm-production`.
- Qualsevol mode d'escriptura requereix `ENV` configurat.
- Secrets via `.env`, mai via arguments CLI.
- El `rollback-plan` no pot executar el rollback directament.

---

## Alternatives descartades

| Alternativa | Motiu del descart |
|---|---|
| Un sol mode d'execució | No permet verificació prèvia segura; risc editorial alt |
| Rollback automàtic | Risc de destruir contingut legítim; requereix revisió humana |
| Import sense batch ID | No auditable; no reprensible |
| Progress reporting al final | Opac durant execució llarga; dificulta diagnosi |
| Política de duplicat hardcodejada | No configurable per projecte; massa restrictiu o massa permissiu |

---

## Relació amb altres ADR

- ADR-0004 — Editorial Import Pipeline (l'estratègia d'execució orquestra les fases)
- ADR-0007 — Import Contract and Intermediate Format (l'`import_state` forma part del format intermedi)
