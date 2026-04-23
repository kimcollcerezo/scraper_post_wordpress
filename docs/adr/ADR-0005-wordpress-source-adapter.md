# ADR-0005 — WordPress Source Adapter

**Data:** 2026-04-23
**Estat:** Acceptat
**Autors:** CTO / Arquitectura
**Projecte:** scraper-post-wordpress / sistema d'importació editorial Despertare

---

## Context

WordPress és el primer CMS origen suportat per la pipeline d'importació (ADR-0004). Però el sistema d'importació no ha d'acoblar-se exclusivament a WordPress: futurs adapters han de poder afegir-se sense modificar la pipeline central.

A més, un WordPress real no és homogeni. Depenent de la instal·lació pot tenir:

- editors de contingut diferents (Gutenberg, Classic Editor, Elementor)
- plugins SEO diferents (Yoast, RankMath, cap)
- camps personalitzats (ACF, meta fields, cap)
- plugins de traducció (WPML, Polylang, cap)
- accessos disponibles variats (REST API, WP-CLI, plugin propi, export JSON)

El WordPress Source Adapter ha de gestionar tota aquesta variabilitat sense que la pipeline central ho noti.

---

## Decisió

**El WordPress Source Adapter és una implementació de la interfície `SourceAdapter`, que normalitza qualsevol WordPress real cap al format intermedi canònic (ADR-0007), independentment dels plugins instal·lats.**

La pipeline central no sap que l'origen és WordPress. Només rep el format intermedi.

---

## Interfície SourceAdapter

Tot adapter de font ha d'implementar el contracte mínim:

```
SourceAdapter:
  extract(config) → Iterator[IntermediateItem]
  detect_capabilities() → SourceCapabilities
  paginate(cursor) → PaginationResult
  health_check() → HealthStatus
```

El WordPress Source Adapter implementa aquest contracte per a fonts WordPress.

---

## Estratègies d'accés

L'adapter ha de suportar múltiples estratègies d'accés, seleccionables per configuració:

### 1. REST API nativa de WordPress

- `GET /wp-json/wp/v2/posts`
- `GET /wp-json/wp/v2/pages`
- `GET /wp-json/wp/v2/media`
- `GET /wp-json/wp/v2/users`
- `GET /wp-json/wp/v2/categories`
- `GET /wp-json/wp/v2/tags`
- Autenticació: WordPress Application Passwords o token bàsic.
- Limitacions: no exposa tots els camps de plugins SEO/builders per defecte.
- Ús recomanat: quan no es pot instal·lar plugin propi i el contingut és estàndard.

### 2. Plugin exportador propi (`despertare-content-exporter`)

- Plugin WordPress de només lectura que exposa endpoints privats enriquits.
- Exposa camps de Yoast, RankMath, ACF, WPML, Polylang, Gutenberg blocks, Elementor data.
- Autenticació: header `X-Despertare-Export-Token`.
- Ús recomanat: quan es té accés admin i es vol màxima fidelitat.
- El plugin és una opció, no un requisit.

### 3. Export JSON / WXR

- Fitxer d'export generat per WordPress (XML/WXR o JSON personalitzat).
- Ús recomanat: quan no hi ha accés REST directe o el site és offline.
- Limitacions: pot no incloure assets ni camps de plugins.

### 4. WP-CLI

- Accés per línia de comandes al servidor WordPress.
- Ús recomanat: quan hi ha accés SSH al servidor i es vol export complet.
- Permet extreure dades no accessibles via REST.

**Cada estratègia genera el mateix format intermedi canònic. La pipeline no distingeix quina estratègia s'ha usat.**

---

## Detecció de capacitats

Abans d'iniciar l'extracció, l'adapter executa `detect_capabilities()` per determinar quins plugins estan actius i ajustar l'extracció en conseqüència.

### Plugins SEO

| Plugin | Detecció | Camps extrets |
|---|---|---|
| Yoast SEO | `/_yoast_wpseo_*` meta fields | `title`, `description`, `canonical`, `robots`, `og_title`, `og_description`, `og_image`, `twitter_*` |
| RankMath | `rank_math_*` meta fields | equivalent a Yoast |
| Cap plugin | — | SEO derivat de `title` + `excerpt` + `featured_image` |

Si no es detecta cap plugin SEO, l'adapter marca `seo_source: derived` i genera valors base. No falla.

### Editors / builders

| Editor | Detecció | Tractament |
|---|---|---|
| Gutenberg | presència de blocs `<!-- wp:` | Extracció de blocs JSON; transformació per la fase Transform |
| Classic Editor | absència de blocs; HTML pla | HTML → fase Transform intenta parsing a blocs |
| Elementor | meta `_elementor_data` | Extracció de data JSON Elementor; transformació best-effort; `raw_html` si no resoluble |

Si l'editor no és identificable, el contingut es tracta com HTML pla.

### Camps personalitzats

| Sistema | Detecció | Tractament |
|---|---|---|
| ACF | presència de grup ACF via REST o meta | Extracció de tots els camps ACF al format `custom_fields` del format intermedi |
| Meta fields estàndard | `meta` via REST | Extracció de tots els meta rellevants |
| Cap | — | `custom_fields: {}` |

Els camps personalitzats no es mapegen automàticament al model Despertare. Es guarden al format intermedi com a `custom_fields` per a mapping manual o posterior.

### Multidioma

| Plugin | Detecció | Tractament |
|---|---|---|
| WPML | presència de `wpml_language` | Extracció de locale per post; agrupació de traduccions |
| Polylang | presència de `lang` via REST | Equivalent a WPML |
| Cap plugin | — | `locale: default` (configuració del projecte destí) |

Si un post té locale no actiu al projecte Despertare destí, es marca `UNSUPPORTED_LOCALE` i no s'importa.

---

## Paginació i extracció incremental

L'adapter suporta:

- `page` / `per_page` (REST API)
- `modified_after` — incremental per data de modificació
- `published_after` — incremental per data de publicació
- `post_type` — filtre per tipus
- `status` — filtre per estat (`publish`, `draft`)
- `ids` — llista explícita d'IDs
- `include_drafts` — false per defecte

L'extracció incremental permet re-executar la pipeline sense re-extreure tot el contingut.

---

## Seguretat de l'adapter

- No escriu mai res al WordPress origen.
- Autenticació obligatòria per a totes les estratègies.
- Timeouts configurables per request.
- Retries amb backoff exponencial i límit màxim.
- Rate limiting respectat (configurable per font).
- Validació de certificat SSL obligatòria.
- No es descarreguen assets de dominis no inclosos a l'allowlist de `config/sources.yml`.
- No s'exposen credencials als logs.

---

## Sortida normalitzada

L'adapter **sempre** genera el format intermedi canònic definit a ADR-0007, independentment de l'estratègia d'accés i els plugins detectats.

Camps que no es poden extreure → `null` o valor buit documentat. Mai error fatal per camp absent opcional.

---

## Degradació controlada

| Situació | Comportament |
|---|---|
| Plugin SEO absent | SEO derivat; `seo_source: derived`; cap error |
| Elementor no resoluble | `raw_html` block amb `legacy: true`; warning `RAW_HTML_BLOCK_USED` |
| ACF absent | `custom_fields: {}`; sense error |
| Multidioma absent | `locale: default`; sense error |
| Asset no descarregable | Warning `MEDIA_DOWNLOAD_FAILED`; import continua sense asset |
| REST API no accessible | Fallback a estratègia alternativa si configurada; error si cap estratègia disponible |

El principi és: **cap contingut es perd silenciosament. Tot el que no es pot extreure queda documentat.**

---

## Alternatives descartades

| Alternativa | Motiu del descart |
|---|---|
| Adapter acoblat directament a la pipeline | No extensible a altres CMSs; viola separació de responsabilitats |
| Scraping HTML com a font principal | Fràgil, no estructurat, dependent de presentació visual |
| Accés directe a base de dades WordPress | Acoblament a schema intern; risc de seguretat; no portable |
| Assumir sempre Yoast instal·lat | Falla en instal·lacions sense plugin SEO; no degradable |

---

## Relació amb altres ADR

- ADR-0004 — Editorial Import Pipeline (la pipeline que usa aquest adapter)
- ADR-0007 — Import Contract and Intermediate Format (el format que l'adapter genera)
