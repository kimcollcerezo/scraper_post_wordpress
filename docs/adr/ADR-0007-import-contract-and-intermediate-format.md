# ADR-0007 — Import Contract and Intermediate Format

**Data:** 2026-04-23
**Estat:** Acceptat
**Autors:** CTO / Arquitectura
**Projecte:** scraper-post-wordpress / sistema d'importació editorial Despertare

---

## Context

La pipeline d'importació (ADR-0004) separa la fase d'extracció de la fase d'importació. Entre les dues cal un format intermedi estable que:

1. Sigui independent del CMS origen (WordPress o qualsevol altre).
2. Sigui independent del model intern de Despertare.
3. Permeti auditar, versionar i reprendre importacions.
4. Contingui tots els camps necessaris per a la transformació i validació.
5. Sigui un snapshot immutable del contingut en el moment de l'extracció.

---

## Decisió

**El format intermedi canònic és la unitat de transferència entre l'adapter de font i la Import API de Despertare. És un JSON estructurat, versionat i immutable per extracció.**

Cap fase de la pipeline opera sobre el CMS origen directament més d'una vegada. Un cop extret el format intermedi, totes les fases restants (Transform, Validate, Import) operen sobre ell.

---

## Estructura del format intermedi

### Nivell arrel

```json
{
  "schema_version": "1.0",
  "import_batch_id": "uuid",
  "extracted_at": "ISO8601",
  "source": { ... },
  "routing": { ... },
  "content": { ... },
  "hero": { ... },
  "media": [ ... ],
  "author": { ... },
  "taxonomies": { ... },
  "seo": { ... },
  "dates": { ... },
  "custom_fields": { ... },
  "integrity": { ... },
  "import_state": { ... }
}
```

---

### `source` — Identificació de l'origen

```json
{
  "system": "wordpress",
  "site_url": "https://example.com",
  "id": 123,
  "type": "post",
  "status": "publish",
  "url": "https://example.com/noticies/post-exemple/",
  "parent_id": null,
  "menu_order": 0,
  "template": "default",
  "locale": "ca"
}
```

- `system`: identificador del CMS origen (`wordpress`, `drupal`, `custom`, etc.)
- `id`: ID intern al CMS origen
- `type`: tipus de contingut (`post`, `page`, `custom_post_type`)
- `status`: estat al CMS origen (`publish`, `draft`, `private`, `trash`)
- `locale`: locale detectat a l'origen; `null` si no disponible

---

### `routing` — URLs i slug

```json
{
  "slug": "post-exemple",
  "path": "/noticies/post-exemple/",
  "legacy_url": "https://example.com/noticies/post-exemple/",
  "desired_url": "/noticies/post-exemple/",
  "canonical_url": "https://example.com/noticies/post-exemple/"
}
```

- `slug`: slug del contingut a l'origen
- `legacy_url`: URL pública a l'origen (base per a redirects 301)
- `desired_url`: URL que es vol al destí (pot coincidir o diferir)
- `canonical_url`: canonical declarat a l'origen (pot diferir de `legacy_url`)

---

### `content` — Contingut principal

```json
{
  "title": {
    "rendered": "Títol del post",
    "raw": "Títol del post"
  },
  "excerpt": {
    "rendered": "<p>Resum breu...</p>",
    "raw": "Resum breu..."
  },
  "html": "<p>Contingut complet...</p>",
  "raw": "Contingut complet...",
  "blocks": [
    {
      "type": "heading",
      "level": 2,
      "content": "Títol de secció"
    },
    {
      "type": "paragraph",
      "content": "<p>Text del paràgraf.</p>"
    },
    {
      "type": "image",
      "src": "https://example.com/wp-content/uploads/imatge.jpg",
      "alt": "Descripció",
      "caption": "Peu de foto"
    },
    {
      "type": "raw_html",
      "html": "<div class='elementor-widget'>...</div>",
      "legacy": true,
      "source": "elementor",
      "warning": "RAW_HTML_BLOCK_USED"
    }
  ],
  "shortcodes_detected": ["gallery", "contact-form-7"],
  "embeds_detected": ["youtube.com/watch?v=..."]
}
```

- `blocks`: resultat de la fase Transform. Si la font és HTML pla, la fase Transform genera els blocs. Si la font és Gutenberg, es mapen els blocs originals. Els blocs `raw_html` amb `legacy: true` indiquen contingut no convertible.
- `shortcodes_detected`: shortcodes detectats però no resolts.
- `embeds_detected`: URLs d'embeds detectats.

---

### `hero` — Imatge principal

```json
{
  "source_url": "https://example.com/wp-content/uploads/hero.jpg",
  "alt": "Alt text",
  "caption": "Peu de foto",
  "title": "Títol de la imatge",
  "width": 1200,
  "height": 900,
  "mime_type": "image/jpeg",
  "import_status": "pending"
}
```

- `import_status`: `pending` | `imported` | `failed` | `review_required`

---

### `media` — Tots els assets detectats

```json
[
  {
    "source_url": "https://example.com/wp-content/uploads/imatge.jpg",
    "filename": "imatge.jpg",
    "alt": "Alt text",
    "caption": "Peu de foto",
    "mime_type": "image/jpeg",
    "width": 800,
    "height": 600,
    "hash": "sha256:...",
    "role": "inline",
    "import_status": "pending",
    "new_url": null,
    "media_asset_id": null
  }
]
```

- `role`: `hero` | `inline` | `gallery` | `og_image` | `attachment`
- `new_url`: omplert per la media pipeline un cop importat
- `media_asset_id`: ID al sistema de media de Despertare un cop importat

---

### `author` — Autor

```json
{
  "source_id": 5,
  "name": "Nom Autor",
  "slug": "nom-autor",
  "email": "autor@example.com",
  "bio": "Biografia...",
  "avatar_url": "https://example.com/avatar.jpg",
  "mapping_status": "pending"
}
```

- `mapping_status`: `pending` | `mapped` | `default_applied`
- `email`: null si no disponible o si la política de privadesa no l'exposa

---

### `taxonomies` — Categories, tags i taxonomies personalitzades

```json
{
  "categories": [
    { "source_id": 10, "name": "Notícies", "slug": "noticies", "mapping_status": "pending" }
  ],
  "tags": [
    { "source_id": 20, "name": "Cultura", "slug": "cultura", "mapping_status": "pending" }
  ],
  "custom": [
    {
      "taxonomy": "seccio",
      "source_id": 30,
      "name": "Opinió",
      "slug": "opinio",
      "mapping_status": "pending"
    }
  ]
}
```

- `mapping_status` per terme: `pending` | `mapped` | `created` | `skipped`

---

### `seo` — Metadades SEO

```json
{
  "title": "Meta title del post",
  "description": "Meta description del post.",
  "canonical": "https://example.com/noticies/post-exemple/",
  "robots": "index, follow",
  "og_title": "OG title",
  "og_description": "OG description.",
  "og_image": "https://example.com/wp-content/uploads/og.jpg",
  "twitter_card": "summary_large_image",
  "twitter_title": null,
  "twitter_description": null,
  "source": "yoast"
}
```

- `source`: `yoast` | `rankmath` | `derived` | `manual`
- `derived` indica que els valors s'han generat a partir de `title` + `excerpt` + `hero` per absència de plugin SEO.

---

### `dates` — Dates

```json
{
  "created_at": "2024-01-15T10:30:00Z",
  "published_at": "2024-01-16T08:00:00Z",
  "modified_at": "2024-03-10T14:22:00Z"
}
```

Totes en ISO 8601 UTC.

---

### `custom_fields` — Camps personalitzats

```json
{
  "acf_field_name": "valor",
  "meta_key": "meta_value"
}
```

- Contingut brut de l'origen.
- No s'interpreta automàticament.
- Requereix mapping manual o configuració d'adapter per a camps amb semàntica coneguda.

---

### `integrity` — Integritat i traçabilitat

```json
{
  "content_hash": "sha256:...",
  "extracted_at": "2026-04-23T12:00:00Z",
  "adapter_version": "1.0.0",
  "schema_version": "1.0"
}
```

- `content_hash`: hash del contingut principal en el moment de l'extracció.
- Permet detectar si el contingut ha canviat entre execucions.

---

### `import_state` — Estat de la importació

```json
{
  "import_status": "pending",
  "mapping_status": "pending",
  "warnings": [],
  "errors": [],
  "imported_at": null,
  "target_entity_type": null,
  "target_entity_id": null,
  "target_url": null,
  "import_batch_id": null
}
```

- `import_status`: `pending` | `ready` | `ready_with_warnings` | `pending_review` | `blocked` | `imported` | `skipped` | `failed`
- `mapping_status`: `pending` | `complete` | `partial` (referent a autors, taxonomies, assets)
- `warnings`: llista de codis `Warning` acumulats durant totes les fases
- `errors`: llista de codis `Error` acumulats

---

## Versionat del format

- `schema_version` al camp arrel identifica la versió del format.
- Canvis retrocompatibles: increment de versió menor.
- Canvis trencadors: increment de versió major; migració de snapshots necessària.
- Els snapshots versionats es desen localment per permet re-importació sense re-extracció.

---

## Emmagatzematge de snapshots

- Cada ítem extret es desa com a fitxer JSON individual:
  `snapshots/{source_system}/{source_id}.json`
- Els snapshots son immutables un cop generats per l'adapter.
- Poden ser sobreescrits explícitament amb `--force-extract`.
- La carpeta `snapshots/` no s'ha de versionar (`.gitignore`).

---

## Alternatives descartades

| Alternativa | Motiu del descart |
|---|---|
| Format propietari per WordPress | No extensible a altres fonts; acoblament a l'origen |
| Importació directa sense format intermedi | No auditable; no repetible; impossible resumir |
| Format XML/WXR de WordPress directament | Acoblat a WordPress; no normalitzat per Despertare |
| Base de dades com a format intermedi | Afegeix dependència d'infraestructura; snapshot no portable |

---

## Relació amb altres ADR

- ADR-0004 — Editorial Import Pipeline (el format és la sortida de la fase Extract)
- ADR-0005 — WordPress Source Adapter (genera aquest format)
- ADR-0006 — Media Normalization Policy (opera sobre el camp `media` d'aquest format)
- ADR-0008 — Import Execution Strategy (llegeix i actualitza `import_state`)
