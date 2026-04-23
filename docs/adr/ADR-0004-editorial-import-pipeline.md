# ADR-0004 — Editorial Import Pipeline

**Data:** 2026-04-23
**Estat:** Acceptat
**Autors:** CTO / Arquitectura
**Projecte:** scraper-post-wordpress / sistema d'importació editorial Despertare

---

## Context

El sistema editorial de Despertare disposa d'un model governat basat en `content_item`, `content_localization` i `content_version`. Cal poder importar contingut provinent de CMSs externs (inicialment WordPress, potencialment altres) cap a aquest model sense comprometre la seva integritat.

El risc principal no és tècnic: és que la importació repliqui el caos del CMS origen directament al model destí. Calen fases de transformació i validació explícites que impedeixin que el contingut legacy entri sense passar per les regles editorials de Despertare.

---

## Decisió

**La importació editorial s'implementa com una pipeline de fases separades: Extract → Transform → Validate → Import.**

Cap fase pot saltar-se. Cap contingut pot arribar a Despertare sense passar per totes les fases.

---

## Fases de la pipeline

### Fase 1 — Extract

- Obté contingut del CMS origen via l'adapter corresponent.
- Genera un snapshot del contingut en format intermedi canònic (veure ADR-0007).
- No interpreta ni transforma el contingut: el captura tal com és.
- El snapshot és immutable un cop generat.
- Registra `extracted_at`, `source_system`, `source_id`, `source_url`, `content_hash`.

**Responsabilitat:** l'adapter de font (veure ADR-0005 per WordPress).

---

### Fase 2 — Transform

- Llegeix el snapshot intermedi generat per Extract.
- Converteix el contingut legacy al model editorial de Despertare:
  - HTML → blocs JSON governats
  - hero image → bloc `hero`
  - taxonomies → estructura normalitzada
  - SEO → `seo_metadata`
  - autor → referència a `editorial-authors`
  - dates → conservació de `published_at`, `created_at`
- Genera warnings explícits per tot contingut que no es pugui transformar a blocs nadius.
- El contingut no transformable pot quedar com a bloc `raw_html` marcat `legacy: true`, però mai silenciosament.
- No escriu a cap sistema destí.

**Responsabilitat:** el transformador canònic, independent de la font origen.

---

### Fase 3 — Validate

- Valida el resultat de Transform contra les regles editorials de Despertare:
  - slug únic per scope + locale
  - locale dins dels locales actius del projecte
  - media policy respectada (veure ADR-0006)
  - SEO base present o derivable
  - autor mapejat o marcat com `pending`
  - taxonomies normalitzades
  - contingut no buit
  - invariants editorials respectats
- Classifica cada item com: `ready` | `ready_with_warnings` | `pending_review` | `blocked`
- Items `blocked` no poden avançar a Import sense intervenció manual.
- Genera informe de validació complet abans d'iniciar cap Import.

**Responsabilitat:** el validador, independent de font i destí.

---

### Fase 4 — Import

- Executa la importació dels items validats cap a Despertare.
- Només accepta items en estat `ready` o `ready_with_warnings` (amb política explícita).
- Crea `content_item`, `content_localization`, `content_version` via contractes governats.
- **No accedeix directament a PostgreSQL.** Tota importació passa per la Import API o contractes de Despertare.
- Registra `migration_source_map` per idempotència i traçabilitat.
- Importa assets de media prèviament processats per la media pipeline (veure ADR-0006).

**Responsabilitat:** el connector Despertare Import, independent de la font origen.

---

## Dry-run obligatori

Tota execució ha de suportar mode `dry-run`:

- Executa Extract, Transform i Validate completament.
- No executa Import.
- Genera informe complet: items detectats, importables, warnings, errors, assets, slugs, locales, redirects estimats.
- El dry-run ha de ser repetible sense efectes secundaris.

El dry-run no és opcional. És la porta d'entrada obligatòria a qualsevol import real.

---

## Idempotència

- Cada item d'origen té identificador únic: `(source_system, source_id, source_url)`.
- La pipeline registra l'estat de cada item a `migration_source_map`.
- Si un item ja existeix al destí, la política configurable determina:
  - `skip` — ignorar (default)
  - `update_draft` — actualitzar si és draft
  - `create_version` — crear nova versió
  - `fail` — aturar i reportar
- Re-executar la pipeline no duplica contingut.

---

## Audit trail

Cada execució de la pipeline genera:

- `import_batch_id` únic
- `actor` (sistema o usuari que llança l'import)
- `timestamp` d'inici i fi
- resum de resultat per ítem: `status`, `warnings`, `errors`
- llista d'assets importats
- slugs modificats
- redirects generats
- versions creades
- política aplicada per cada decisió rellevant

L'audit trail és immutable i persistent.

---

## Errors i warnings

### Errors (bloquejants)

Aturen l'ítem. No es pot importar sense resolució:

- `INVALID_SOURCE_ITEM` — item malformat o incomplet a l'origen
- `UNSUPPORTED_LOCALE` — locale no actiu al projecte destí
- `SLUG_COLLISION` — slug en conflicte sense estratègia de resolució
- `CONTENT_TRANSFORM_FAILED` — transformació impossible i sense fallback
- `AUTHOR_MAPPING_REQUIRED` — autor no resolt i política és `fail`
- `TAXONOMY_MAPPING_REQUIRED` — taxonomia no resolta i política és `fail`
- `PERMISSION_DENIED` — l'Import API rebutja l'operació
- `MEDIA_POLICY_VIOLATION` — asset viola invariant de media no salvable

### Warnings (no bloquejants per defecte)

Permeten continuar però queden registrats:

- `RAW_HTML_BLOCK_USED` — contingut no convertible a blocs nadius
- `MEDIA_DOWNLOAD_FAILED` — asset no descarregat, contingut importat sense imatge
- `SEO_INCOMPLETE` — SEO parcial, valors derivats aplicats
- `AUTHOR_PENDING` — autor marcat com a pendent de mapping manual
- `TAXONOMY_PENDING` — taxonomia marcada com a pendent
- `MEDIA_REVIEW_REQUIRED` — imatge importada però amb política d'aspecte no complerta
- `SHORTCODE_UNRESOLVED` — shortcode WordPress no convertit
- `REDIRECT_SUGGESTED` — URL pública canvia, redirect recomanat

---

## Batch imports

- La pipeline pot executar-se sobre subconjunts de contingut:
  - rang de dates (`published_after`, `modified_after`)
  - tipus de contingut (`post`, `page`)
  - llista d'IDs
  - estat (`publish`, `draft`)
- Cada batch té el seu `import_batch_id`.
- Els batches poden reprendre's si s'interrompen (veure ADR-0008).

---

## Principi

La pipeline d'importació no és un script de còpia. És un sistema de normalització governada.

La seva responsabilitat és transformar contingut legacy en contingut Despertare coherent, auditable i compatible amb les polítiques del projecte destí.

**El contingut de l'origen s'adapta a Despertare. Despertare no s'adapta a l'origen.**

---

## Alternatives descartades

| Alternativa | Motiu del descart |
|---|---|
| Importació directa a PostgreSQL | Bypassa la governança editorial; invalida invariants |
| Còpia HTML directa sense transformació | Replica el caos del CMS origen; impedeix governança futura |
| Import sense dry-run | No verificable ni reversible; risc editorial alt |
| Import sense audit trail | No auditable; no repetible de forma segura |

---

## Relació amb altres ADR

- ADR-0005 — WordPress Source Adapter (primer adapter de la fase Extract)
- ADR-0006 — Media Normalization Policy (gestió d'assets a les fases Transform i Import)
- ADR-0007 — Import Contract and Intermediate Format (format de sortida de la fase Extract)
- ADR-0008 — Import Execution Strategy (modes d'execució de la pipeline)
