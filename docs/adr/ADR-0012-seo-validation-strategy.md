# ADR-0012 — SEO Validation Strategy

**Data:** 2026-04-23
**Estat:** Acceptat
**Autors:** CTO / Arquitectura
**Projecte:** scraper-post-wordpress / sistema d'importació editorial Despertare

---

## Context

La pipeline garanteix la preservació de les metadades SEO durant l'extracció i la importació (ADR-0004, ADR-0007). Però "preservar" no és suficient: cal verificar que el contingut importat és realment accessible, indexable i SEO-correcte al destí.

El risc és tenir un sistema que preservi intencionalment el SEO però que en la pràctica:
- Generi meta tags incorrectes al HTML final
- Trenqui URLs sense crear redirects
- No validi que canonicals apuntin correctament
- No detecti pèrdues de senyals de SEO entre origen i destí

Cal passar de **intenció SEO** a **garantia SEO verificada**.

---

## Decisió

**La validació SEO és una fase post-import independent que verifica el resultat real al destí, no el payload d'entrada. Opera sobre URLs en staging o producció i genera un informe comparatiu entre origen i destí.**

No és part de la fase Validate de la pipeline (que valida el payload). És una fase addicional que valida el resultat final accessible via HTTP.

---

## Fases de validació SEO

### Fase 1 — Pre-migració: crawl de l'origen

Abans de migrar, es fa un crawl de l'origen per capturar l'estat SEO de referència.

Per cada URL de l'origen:
- `status_code` (HTTP)
- `title` (tag `<title>`)
- `meta_description`
- `canonical` (tag `<link rel="canonical">`)
- `robots` (meta robots)
- `og_title`, `og_description`, `og_image`, `og_url`
- `h1` (primer h1 de la pàgina)
- `structured_data` (JSON-LD detectat)
- `hreflang` (si existeix)
- `redirect_chain` (si redirigeix)

Resultat: `artifacts/seo/pre-migration-crawl.json`

---

### Fase 2 — Post-import: crawl del destí

Després de l'import (staging o producció), es fa un crawl de les URLs importades al destí.

Per cada URL importada (de `migration_source_map.target_url`):
- Mateixos camps que la Fase 1
- Afegir: `images_with_alt` / `images_without_alt` (count)
- Afegir: `internal_links` (count)
- Afegir: `broken_images` (count)

Resultat: `artifacts/seo/post-migration-crawl.json`

---

### Fase 3 — Comparació i informe

Comparació ítem per ítem entre pre i post crawl.

Per cada ítem:

```json
{
  "source_url": "https://old-site.com/noticies/post-exemple/",
  "target_url": "https://new-site.com/noticies/post-exemple/",
  "status": "ok" | "warning" | "error",
  "checks": {
    "url_accessible": true,
    "title_preserved": true,
    "title_match": { "source": "Títol original", "target": "Títol original" },
    "meta_description_preserved": true,
    "canonical_valid": true,
    "canonical_self_referencing": true,
    "robots_preserved": true,
    "og_image_accessible": true,
    "h1_present": true,
    "redirect_exists": false,
    "redirect_correct": null
  },
  "warnings": [],
  "errors": []
}
```

Resultat: `artifacts/seo/seo-validation-report.json` + `seo-validation-report.csv`

---

## Checks de validació

### Checks bloquejants (error)

| Check | Condició d'error |
|---|---|
| `url_accessible` | URL retorna 4xx o 5xx |
| `canonical_valid` | Canonical apunta a domini antic sense redirect |
| `redirect_loop` | Cadena de redirects detectada |
| `no_index_unexpected` | `noindex` al destí quan l'origen era indexable |

### Checks d'advertència (warning)

| Check | Condició de warning |
|---|---|
| `title_missing` | `<title>` absent o buit |
| `title_too_long` | `<title>` > 60 caràcters |
| `meta_description_missing` | `<meta name="description">` absent |
| `meta_description_too_long` | Meta description > 160 caràcters |
| `h1_missing` | Cap `<h1>` a la pàgina |
| `multiple_h1` | Més d'un `<h1>` |
| `og_image_missing` | OG image absent |
| `og_image_inaccessible` | OG image retorna error |
| `canonical_different_from_target` | Canonical no apunta a la URL del destí |
| `images_without_alt` | Imatges sense `alt` text |
| `title_changed` | Títol diferent entre origen i destí (pot ser intencional) |

---

## Validació de redirects

Per cada `legacy_url` del `migration_source_map`:

1. Fer request HTTP a `legacy_url`
2. Verificar que retorna 301 (o 302 si configuració ho indica)
3. Verificar que el `Location` header apunta a `target_url` (o a la URL final correcta)
4. Verificar que `target_url` retorna 200

```json
{
  "legacy_url": "https://old-site.com/noticies/post/",
  "expected_target": "https://new-site.com/noticies/post/",
  "redirect_status": 301,
  "redirect_location": "https://new-site.com/noticies/post/",
  "target_status": 200,
  "check": "ok" | "missing_redirect" | "wrong_target" | "target_broken"
}
```

Informe de redirects: `artifacts/seo/redirects-validation.json`

---

## Comparació de sitemaps

Si l'origen té `sitemap.xml`:

1. Descarregar sitemap origen
2. Generar sitemap destí (via Despertare)
3. Comparar:
   - URLs presents a l'origen però absents al destí → `missing_from_sitemap`
   - URLs presents al destí però no a l'origen → `new_in_sitemap` (esperat)
   - `lastmod` conservat o actualitzat

Informe: `artifacts/seo/sitemap-diff.json`

---

## Validació OG i structured data

### Open Graph

Per cada ítem verificar:
- `og:title` present i no buit
- `og:description` present i no buit
- `og:image` present, accessible i amb mida adequada (mínim 200×200, recomanat 1200×630)
- `og:url` coincideix amb `canonical`
- `og:type` declarat

### JSON-LD / Structured Data

Si l'origen tenia structured data (Article, NewsArticle, BreadcrumbList, etc.):
- Detectar si el destí genera structured data equivalent
- No validar esquema complet; verificar presència i tipus

---

## Modes d'execució de la validació SEO

```
scripts/seo-validate.sh --mode pre-migration --source-url https://old-site.com
scripts/seo-validate.sh --mode post-migration --batch-id <uuid>
scripts/seo-validate.sh --mode redirects --batch-id <uuid>
scripts/seo-validate.sh --mode sitemap --source-sitemap https://old-site.com/sitemap.xml
scripts/seo-validate.sh --mode full --batch-id <uuid>
```

---

## Eines i implementació

La validació SEO s'implementa com a mòdul separat de la pipeline:

- **Crawler HTTP**: `httpx` (Python) o equivalent; suport de redirects, SSL, timeouts
- **Parser HTML**: `beautifulsoup4` per extreure meta tags, h1, canonical, OG
- **Sitemap parser**: `usp` o parser XML estàndard
- **Output**: JSON + CSV per integrar amb eines externes (Screaming Frog, etc.)

El mòdul és independent de la pipeline principal: es pot executar sense haver llançat un import complet.

---

## Informe final SEO

`artifacts/seo/seo-summary-{batch_id}.json`:

```json
{
  "batch_id": "uuid",
  "validated_at": "...",
  "summary": {
    "total_urls": 150,
    "accessible": 148,
    "with_errors": 2,
    "with_warnings": 25,
    "redirects_ok": 145,
    "redirects_missing": 3,
    "redirects_broken": 2,
    "og_image_ok": 140,
    "og_image_missing": 10,
    "h1_ok": 148,
    "h1_missing": 2,
    "sitemap_urls_origin": 155,
    "sitemap_urls_destination": 150,
    "sitemap_missing": 5
  },
  "errors": [...],
  "warnings": [...]
}
```

---

## Alternatives descartades

| Alternativa | Motiu del descart |
|---|---|
| Validar SEO durant la fase Validate (payload) | Valida intenció, no resultat real al navegador |
| Integrar Lighthouse a la pipeline | Massa lent per a centenars d'URLs; ús puntual per a pàgines clau |
| Assumir que la preservació de metadata garanteix SEO | No detecta errors de renderització, redirects trencats, canonicals incorrectes |
| Delegar validació SEO a eina externa manualment | No auditable; no repetible; fora del sistema de governança |

---

## Relació amb altres ADR

- ADR-0004 — Editorial Import Pipeline (la validació SEO és post-Import)
- ADR-0007 — Import Contract and Intermediate Format (el camp `seo` és la font de les metadades a verificar)
- ADR-0008 — Import Execution Strategy (el mode `validate` pot incloure validació SEO)
- ADR-0009 — Import API Contract (genera `target_url` que és l'entrada del crawl de destí)
