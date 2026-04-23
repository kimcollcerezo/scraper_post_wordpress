# ADR-0011 — Content Blocks Strategy

**Data:** 2026-04-23
**Estat:** Acceptat
**Autors:** CTO / Arquitectura
**Projecte:** scraper-post-wordpress / sistema d'importació editorial Despertare

---

## Context

La fase Transform de la pipeline (ADR-0004) ha de convertir contingut legacy de diverses fonts (HTML pla, Gutenberg blocks, Elementor) al model de blocs editorials de Despertare.

El risc principal és acabar amb contingut majoritàriament en blocs `raw_html` (opacs, no editables, no governats). Sense una estratègia de conversió explícita i exhaustiva, això és el resultat inevitable.

Cal definir:

1. Quins blocs existeixen al model Despertare.
2. Com es mapegen des de Gutenberg.
3. Com es mapegen des de HTML pla.
4. Quan i com s'usa `raw_html` com a fallback.
5. Com es mesura i limita l'ús de `raw_html`.

---

## Decisió

**La fase Transform aplica un transformador de blocs amb mapping explícit per cada font (Gutenberg, HTML, Elementor), mesura el percentatge de `raw_html` resultant, i falla si supera el llindar configurat.**

L'objectiu és que `raw_html` sigui l'excepció mesurable, no el resultat per defecte.

---

## Blocs nadius de Despertare

Aquests són els blocs que el model editorial Despertare suporta:

### Blocs de contingut

| Tipus | Descripció |
|---|---|
| `heading` | Títol de secció (h1–h6) |
| `paragraph` | Paràgraf de text |
| `quote` | Cita destacada |
| `list` | Llista ordenada o desordenada |
| `code` | Bloc de codi |
| `separator` | Separador visual |
| `spacer` | Espai vertical |

### Blocs de media

| Tipus | Descripció |
|---|---|
| `image` | Imatge amb alt, caption, url |
| `gallery` | Galeria d'imatges |
| `video` | Vídeo embed o natiu |
| `audio` | Àudio embed o natiu |
| `file` | Fitxer adjunt descarregable |

### Blocs estructurals

| Tipus | Descripció |
|---|---|
| `hero` | Hero image amb títol i subtítol opcional |
| `columns` | Contingut en columnes (2 o 3) |
| `group` | Agrupació de blocs |
| `table` | Taula de dades |

### Blocs d'integració

| Tipus | Descripció |
|---|---|
| `embed` | Embed extern (YouTube, Vimeo, Twitter, etc.) |
| `html` | HTML nadiu permès (IFrame, SVG, etc.) — diferent de `raw_html` |

### Bloc de fallback

| Tipus | Descripció |
|---|---|
| `raw_html` | HTML legacy no convertible; marcat `legacy: true`; auditat |

---

## Mapping Gutenberg → Despertare

| Bloc Gutenberg | Bloc Despertare | Notes |
|---|---|---|
| `core/heading` | `heading` | Conservar `level` (h1–h6) |
| `core/paragraph` | `paragraph` | Conservar HTML intern permès |
| `core/quote` | `quote` | Conservar `citation` si existeix |
| `core/list` | `list` | Conservar `ordered` boolean |
| `core/list-item` | element de `list` | |
| `core/code` | `code` | Conservar `language` si disponible |
| `core/separator` | `separator` | |
| `core/spacer` | `spacer` | Conservar `height` |
| `core/image` | `image` | Conservar `alt`, `caption`, `url`, `width`, `height` |
| `core/gallery` | `gallery` | Array d'imatges |
| `core/video` | `video` | `url` o `embed` |
| `core/audio` | `audio` | `url` |
| `core/file` | `file` | `url`, `filename` |
| `core/cover` | `hero` | Imatge de fons + text sobreposat |
| `core/columns` | `columns` | Array de columnes amb blocs fills |
| `core/column` | columna dins `columns` | |
| `core/group` | `group` | Array de blocs fills |
| `core/table` | `table` | HTML de taula net |
| `core/html` | `html` | HTML nadiu declarat |
| `core/embed` | `embed` | `url`, `provider` detectat |
| `core/shortcode` | `raw_html` + warning | `SHORTCODE_UNRESOLVED` |
| `core/button` | `paragraph` amb link | Best-effort |
| `core/buttons` | array de `paragraph` | Best-effort |
| `core/media-text` | `columns` (2 col) | Imatge + text |
| Bloc Gutenberg desconegut | `raw_html` + warning | `RAW_HTML_BLOCK_USED` |

---

## Mapping HTML pla → Despertare

Per contingut de Classic Editor o HTML genèric. El transformador usa un parser HTML (ex: `beautifulsoup4`, `lxml`) per detectar patrons i convertir a blocs.

| Patró HTML | Bloc Despertare | Condicions |
|---|---|---|
| `<h1>` – `<h6>` | `heading` | `level` extret del tag |
| `<p>` | `paragraph` | Text interior net |
| `<blockquote>` | `quote` | `<cite>` → `citation` |
| `<ul>`, `<ol>` | `list` | `ordered` basat en `<ol>` |
| `<pre><code>` | `code` | |
| `<hr>` | `separator` | |
| `<img>` isolada | `image` | `alt`, `src`, dimensions si disponibles |
| `<figure><img>` | `image` | `<figcaption>` → `caption` |
| `<figure><img>+<img>+...` | `gallery` | Múltiples imatges dins figure |
| `<table>` | `table` | HTML de taula sanititzat |
| `<iframe>` YouTube/Vimeo | `embed` | Detecció per URL |
| `<iframe>` altres | `html` | Si en allowlist; sinó `raw_html` |
| `<div>` genèric | `raw_html` + warning | Intentar parsing recursiu primer |
| `<script>` | eliminat + warning | `SCRIPT_REMOVED` |
| `<style>` inline | eliminat + warning | `INLINE_STYLE_REMOVED` |

**Estratègia de parsing recursiu:** Abans de convertir un `<div>` a `raw_html`, el transformador intenta parse dels fills. Si tots els fills es converteixen a blocs nadius, el `<div>` desapareix. Només si els fills no son convertibles → `raw_html`.

---

## Mapping Elementor → Despertare

Elementor emmagatzema el contingut com a JSON a `_elementor_data`. La conversió és best-effort.

| Widget Elementor | Bloc Despertare | Notes |
|---|---|---|
| `heading` | `heading` | |
| `text-editor` | `paragraph` (o múltiples) | Parser HTML intern |
| `image` | `image` | |
| `image-box` | `image` + `paragraph` | |
| `image-gallery` | `gallery` | |
| `video` | `video` | |
| `icon-list` | `list` | Best-effort |
| `button` | `paragraph` amb link | Best-effort |
| `spacer` | `spacer` | |
| `divider` | `separator` | |
| `text-path` | `raw_html` + warning | |
| `accordion` | `raw_html` + warning | `ELEMENTOR_COMPLEX_WIDGET` |
| `tabs` | `raw_html` + warning | `ELEMENTOR_COMPLEX_WIDGET` |
| `carousel` | `raw_html` + warning | |
| Widget desconegut | `raw_html` + warning | `RAW_HTML_BLOCK_USED` |

Sections i Columns d'Elementor: el transformador aplanitza l'estructura Elementor (sections > rows > columns > widgets) i genera blocs Despertare plans o `columns` quan la columna és simple. Layouts complexos → `raw_html`.

---

## Llindar de `raw_html`

Per mesurar la qualitat de la conversió, la fase Transform calcula:

```
raw_html_ratio = nombre_blocs_raw_html / nombre_total_blocs
```

Configuració a `config/import-policy.yml`:

```yaml
transform:
  raw_html_warning_threshold: 0.20   # Warning si >20% blocs són raw_html
  raw_html_block_threshold: 0.50     # Bloqueja ítem si >50% blocs són raw_html
```

- Si `raw_html_ratio > warning_threshold` → warning `HIGH_RAW_HTML_RATIO`
- Si `raw_html_ratio > block_threshold` → ítem marcat `pending_review` (no `blocked`; pot sobrepassar-se amb flag)

L'informe final inclou estadístiques d'ús de `raw_html` per ítem i global.

---

## Format de bloc Despertare

Estructura comuna:

```json
{
  "type": "paragraph",
  "id": "uuid-opcional",
  "data": { }
}
```

### Exemples

```json
{ "type": "heading", "data": { "level": 2, "text": "Títol de secció" } }

{ "type": "paragraph", "data": { "html": "<p>Text amb <strong>negreta</strong>.</p>" } }

{ "type": "image", "data": { "src": "https://cdn.../imatge.jpg", "alt": "Alt text", "caption": "Peu de foto", "width": 1200, "height": 800 } }

{ "type": "quote", "data": { "html": "<p>Text de la cita.</p>", "citation": "Autor" } }

{ "type": "list", "data": { "ordered": false, "items": ["Element 1", "Element 2"] } }

{ "type": "embed", "data": { "url": "https://www.youtube.com/watch?v=...", "provider": "youtube" } }

{ "type": "raw_html", "data": { "html": "<div class='widget'>...</div>", "legacy": true, "source": "elementor", "warning": "ELEMENTOR_COMPLEX_WIDGET" } }
```

---

## HTML permès dins blocs

Els blocs `paragraph` i `quote` poden contenir HTML inline net:

Permès: `<strong>`, `<em>`, `<a>`, `<br>`, `<span>`, `<code>`, `<s>`, `<u>`

No permès: `<script>`, `<style>`, `<iframe>`, `<object>`, `<embed>`, atributs `on*`, `javascript:`

Sanitització: `bleach` (Python) o equivalent, amb allowlist estricta.

---

## Alternatives descartades

| Alternativa | Motiu del descart |
|---|---|
| Importar tot com `raw_html` | Contingut opac, no editable, no governat |
| Conversió sense llindar de mesura | No detecta degradació silenciosa de qualitat |
| Mapping Elementor complet | Massa complex i fràgil; Elementor és un DSL de presentació, no editorial |
| Parser HTML genèric sense mapping explícit | Resultats impredictibles; difícil d'auditar |

---

## Relació amb altres ADR

- ADR-0004 — Editorial Import Pipeline (fase Transform usa aquesta estratègia)
- ADR-0005 — WordPress Source Adapter (detecta la font: Gutenberg, Classic, Elementor)
- ADR-0007 — Import Contract and Intermediate Format (el camp `content.blocks` segueix aquest format)
- ADR-0009 — Import API Contract (la Import API rep blocs en aquest format)
