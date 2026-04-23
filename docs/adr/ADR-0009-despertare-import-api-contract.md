# ADR-0009 — Despertare Import API Contract

**Data:** 2026-04-23
**Estat:** Acceptat
**Autors:** CTO / Arquitectura
**Projecte:** scraper-post-wordpress / sistema d'importació editorial Despertare

---

## Context

La fase Import de la pipeline (ADR-0004) no pot accedir directament a PostgreSQL. Tota importació ha de passar per una API governada al projecte Despertare que:

1. Validi el payload contra el schema editorial.
2. Comprovi permisos.
3. Garanteixi idempotència.
4. Apliqui les regles de versions i publicació.
5. Retorni errors contractats.
6. Deixi audit trail.

Sense aquest contracte, la pipeline no és executable.

---

## Decisió

**La Import API de Despertare és un conjunt d'endpoints interns d'administració, autenticats per token de sistema, que accepten el format intermedi canònic (ADR-0007) i creen les entitats editorials corresponents.**

Aquesta API viu al projecte Despertare (Next.js / NestJS), no a l'agent migrador.

---

## Autenticació

- **Token de sistema intern** — header `Authorization: Bearer <IMPORT_TOKEN>`
- El token és diferent dels tokens d'usuari final.
- Es configura via variable d'entorn `DESPERTARE_IMPORT_TOKEN` al costat de l'agent.
- Al costat de Despertare: `IMPORT_API_SECRET` validat pel middleware d'import.
- **No s'usa sessió de navegador ni token d'usuari.**
- El token ha de tenir scope `import:write` explícit.

---

## Endpoints

### `POST /api/admin/import/content`

Importa un ítem de contingut (post, page, etc.).

**Payload:**

```typescript
{
  batch_id: string                    // UUID del batch
  source: {
    system: string                    // "wordpress" | "drupal" | ...
    site_url: string
    id: number | string
    type: string                      // "post" | "page" | ...
    status: string                    // "publish" | "draft" | ...
    url: string
    locale: string | null
  }
  routing: {
    slug: string
    path: string
    legacy_url: string
    desired_url: string
  }
  content: {
    title: string
    excerpt: string | null
    blocks: Block[]                   // format de blocs Despertare (ADR-0011)
  }
  hero: MediaRef | null
  author: AuthorRef | null
  taxonomies: TaxonomiesRef
  seo: SeoMetadata
  dates: {
    created_at: string               // ISO8601
    published_at: string             // ISO8601
    modified_at: string              // ISO8601
  }
  on_duplicate: "skip" | "update_draft" | "create_version" | "fail"
  import_as_status: "published" | "draft"
}
```

**Validació (Zod):**

- `batch_id`: UUID vàlid
- `source.system`: string no buit
- `source.id`: number o string no buit
- `source.url`: URL vàlida
- `routing.slug`: string, format slug (minúscules, guions, sense espais)
- `content.blocks`: array, mínim 1 element
- `dates.published_at`: ISO8601 vàlid
- `on_duplicate`: enum estricte
- `import_as_status`: enum estricte

**Resposta 200 — creat o actualitzat:**

```json
{
  "result": "created" | "updated" | "skipped",
  "content_item_id": "uuid",
  "content_localization_id": "uuid",
  "content_version_id": "uuid",
  "target_url": "/noticies/post-exemple/",
  "warnings": []
}
```

**Resposta 409 — duplicat amb política `fail`:**

```json
{
  "error": "DUPLICATE_ITEM",
  "source_id": "123",
  "existing_content_item_id": "uuid"
}
```

---

### `POST /api/admin/import/media`

Registra i importa un asset de media.

**Payload:**

```typescript
{
  batch_id: string
  source_url: string
  filename: string
  mime_type: string                  // MIME detectat (no declarat)
  size_bytes: number
  width: number | null
  height: number | null
  alt: string | null
  caption: string | null
  hash: string                       // "sha256:..."
  role: "hero" | "inline" | "gallery" | "og_image" | "attachment"
  binary: string | null              // base64 si s'envia contingut; null si URL accessible
  source_url_accessible: boolean
}
```

**Resposta 200:**

```json
{
  "result": "imported" | "deduplicated",
  "media_asset_id": "uuid",
  "storage_url": "https://cdn.despertare.com/media/...",
  "variants": {
    "hero": "...",
    "card": "...",
    "og_image": "..."
  }
}
```

**Resposta 422 — violació de política:**

```json
{
  "error": "MEDIA_POLICY_VIOLATION",
  "detail": "mime_type 'application/x-php' not allowed"
}
```

---

### `POST /api/admin/import/authors`

Registra o mapeja un autor.

**Payload:**

```typescript
{
  batch_id: string
  source_id: number | string
  name: string
  slug: string
  email: string | null
  bio: string | null
  avatar_url: string | null
  on_duplicate: "skip" | "merge"
}
```

**Resposta 200:**

```json
{
  "result": "created" | "merged" | "skipped",
  "author_id": "uuid"
}
```

---

### `POST /api/admin/import/taxonomies`

Registra o mapeja categories, tags i taxonomies personalitzades.

**Payload:**

```typescript
{
  batch_id: string
  taxonomy: string                   // "category" | "tag" | nom de taxonomia custom
  source_id: number | string
  name: string
  slug: string
  on_duplicate: "skip" | "merge"
}
```

**Resposta 200:**

```json
{
  "result": "created" | "merged" | "skipped",
  "taxonomy_term_id": "uuid"
}
```

---

### `POST /api/admin/import/redirects`

Registra redirects 301 entre URL legacy i URL nova.

**Payload:**

```typescript
{
  batch_id: string
  redirects: Array<{
    from: string                     // path o URL legacy
    to: string                       // path o URL nova
    type: "301" | "302"
  }>
}
```

**Resposta 200:**

```json
{
  "created": 12,
  "skipped": 3,
  "conflicts": []
}
```

---

### `POST /api/admin/import/batch`

Import en lot d'un conjunt d'ítems.

**Payload:**

```typescript
{
  batch_id: string
  items: ImportContentPayload[]      // array del payload de /content
  on_error: "stop" | "continue"     // política d'error per lot
}
```

**Resposta 200:**

```json
{
  "batch_id": "uuid",
  "total": 50,
  "created": 45,
  "skipped": 3,
  "failed": 2,
  "errors": [
    { "source_id": "45", "error": "SLUG_COLLISION" }
  ]
}
```

---

### `GET /api/admin/import/status/{batch_id}`

Consulta l'estat d'un batch en curs o completat.

**Resposta 200:**

```json
{
  "batch_id": "uuid",
  "status": "in_progress" | "completed" | "failed",
  "progress": { "total": 100, "processed": 67, "failed": 2 },
  "started_at": "...",
  "finished_at": null
}
```

---

## Idempotència a nivell API

- Cada endpoint comprova `migration_source_map` per `(source_system, source_id)` abans d'operar.
- Si l'ítem ja existeix, aplica la política `on_duplicate` del payload.
- El `batch_id` és idempotent: re-enviar el mateix batch amb el mateix `batch_id` no duplica dades.
- Idempotència garantida per hash de contingut + source identity.

---

## Política de versions

| `on_duplicate` | `import_as_status` | Resultat |
|---|---|---|
| `skip` | qualsevol | `result: skipped`; sense canvis |
| `update_draft` | `draft` | Actualitza el draft existent si és draft |
| `update_draft` | `published` | Crea draft nou sense publicar |
| `create_version` | qualsevol | Crea `content_version` nova; no publica automàticament |
| `fail` | qualsevol | `409 DUPLICATE_ITEM` |

**Cap import crea contingut publicat sense `import_as_status: published` explícit.**

---

## Errors contractats

| Codi | HTTP | Significat |
|---|---|---|
| `INVALID_PAYLOAD` | 400 | Payload no passa validació Zod |
| `MISSING_REQUIRED_FIELD` | 400 | Camp obligatori absent |
| `INVALID_SLUG` | 400 | Slug amb format invàlid |
| `SLUG_COLLISION` | 409 | Slug ja existeix per aquest scope + locale |
| `DUPLICATE_ITEM` | 409 | Ítem ja existeix i política és `fail` |
| `UNSUPPORTED_LOCALE` | 422 | Locale no actiu al projecte |
| `AUTHOR_NOT_FOUND` | 422 | Autor referenciat no existeix |
| `MEDIA_NOT_FOUND` | 422 | Asset referenciat no existeix |
| `MEDIA_POLICY_VIOLATION` | 422 | Asset viola política de media del projecte |
| `PERMISSION_DENIED` | 403 | Token sense scope `import:write` |
| `INVALID_TOKEN` | 401 | Token absent o invàlid |
| `CONTENT_INVARIANT_VIOLATION` | 422 | Contingut viola invariant editorial |
| `BATCH_NOT_FOUND` | 404 | `batch_id` desconegut |

---

## Permisos

- Només accessible amb token de sistema (`import:write`).
- No accessible per tokens d'usuari final.
- No accessible sense autenticació.
- Middleware valida token abans de qualsevol operació.
- Rate limiting per token configurable.

---

## Audit trail

Cada operació exitosa registra:

- `import_batch_id`
- `actor` (token de sistema identificat)
- `timestamp`
- `source_system`, `source_id`, `source_url`
- `operation`: `created` | `updated` | `skipped` | `version_created`
- `target_entity_type`, `target_entity_id`
- `warnings` si n'hi ha

L'audit trail és immutable i persistent.

---

## Alternatives descartades

| Alternativa | Motiu del descart |
|---|---|
| Accés directe a PostgreSQL des de l'agent | Bypassa governança editorial; invalida invariants |
| Usar API pública de Despertare | No té permisos d'import; no suporta idempotència per batch |
| GraphQL mutation directa | Acoblament a schema intern; no governada per middleware d'import |
| Import via fitxer (upload CSV/JSON directe) | No auditable en temps real; no suporta streaming de grans volums |

---

## Relació amb altres ADR

- ADR-0004 — Editorial Import Pipeline (fase Import usa aquesta API)
- ADR-0007 — Import Contract and Intermediate Format (el payload deriva del format intermedi)
- ADR-0008 — Import Execution Strategy (els modes d'execució criden aquesta API)
