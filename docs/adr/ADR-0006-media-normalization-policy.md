# ADR-0006 — Media Normalization Policy

**Data:** 2026-04-23
**Actualitzat:** 2026-04-24
**Estat:** Acceptat
**Autors:** CTO / Arquitectura
**Projecte:** scraper-post-wordpress / sistema d'importació editorial Despertare

---

## Context

Despertare gestiona els assets de media de forma governada per projecte. Cada projecte pot tenir polítiques d'aspecte, formats, variants i mides diferents.

Durant la importació, el contingut legacy conté assets que provenen de fonts externes (WordPress o altres CMSs) amb formats, mides i aspectes variats, sense garantia de qualitat ni coherència.

La política de normalització de media ha de:

1. No destruir assets originals.
2. No assumir que els assets compliran les polítiques del projecte destí.
3. Generar variants correctes o marcar per revisió manual.
4. Ser configurable per projecte, no hardcodejada.
5. Garantir deduplicació.
6. Ser auditable.

---

## Decisió

**La normalització de media és una sub-pipeline separada, executada entre la fase Transform i la fase Import, governada per la política de media del projecte destí.**

La pipeline central no hardcodeja cap política d'imatge. Llegeix la política del projecte i aplica les regles definides.

---

## Tipus d'assets en importació

### Hero image

- Imatge principal del contingut (featured image a WordPress).
- Té aspecte i mida recomanats per projecte.
- Si no compleix la política: generar variant recomanada o marcar `MEDIA_REVIEW_REQUIRED`.

### Imatges internes

- Imatges embegudes dins el contingut (bloc `image`, galeries, etc.).
- Poden tenir qualsevol mida i aspecte.
- No se'ls aplica aspecte fix; sí validació de format i mida màxima.

### OG image / SEO image

- Imatge Open Graph per a compartir en xarxes.
- Aspecte recomanat: 1200×630 (aproximadament 16:9 o 1.91:1).
- Si no existeix, derivar de la hero image.

### Assets annexos

- Arxius adjunts no imatge (PDF, video embed, etc.).
- Política específica per projecte.
- Si no hi ha política, registrar com `asset_pending_policy`.

---

## Política de media per projecte

La política és externa al codi de la pipeline i es defineix per projecte a `config/media-policy.yml` (o equivalent al projecte Despertare).

Exemple de política:

```yaml
hero:
  aspect_ratio: "4:3"
  min_width: 1200
  min_height: 900
  formats: [webp, jpg, png]
  max_bytes: 5242880  # 5MB
  variants:
    - name: hero
      width: 1200
      height: 900
    - name: hero_mobile
      width: 600
      height: 450

thumbnail:
  aspect_ratio: "16:9"
  variants:
    - name: card
      width: 800
      height: 450
    - name: card_sm
      width: 400
      height: 225

og_image:
  aspect_ratio: "1.91:1"
  width: 1200
  height: 630

formats_allowed: [webp, jpg, jpeg, png, gif, svg]
max_bytes_default: 10485760  # 10MB
```

La pipeline llegeix aquesta política i no opera si no la troba.

---

## Flux de normalització per asset

```
1. Descarregar original de la font
2. Detectar MIME real (no confiar en MIME declarat)
3. Validar extensió vs MIME detectat
4. Validar format permès (allowlist de la política)
5. Validar mida en bytes (màxim de la política)
6. Calcular hash (SHA-256)
7. Verificar deduplicació per hash + original_url
8. Si duplicat → reutilitzar asset existent, no reimportar
9. Si nou → desar original
10. Detectar dimensions reals
11. Avaluar compliment de la política d'aspecte
12. Si compleix → generar variants
13. Si no compleix → intentar crop/resize no destructiu
14. Si crop no possible sense perdre qualitat → marcar MEDIA_REVIEW_REQUIRED
15. Registrar mapping: original_url → storage_url + asset_id
16. Registrar import_status de l'asset
```

---

## Detecció de MIME real

- No confiar en el MIME declarat per la font.
- Detectar MIME real llegint els primers bytes del fitxer (magic bytes).
- Si MIME detectat no coincideix amb extensió declarada → warning i validació contra allowlist del MIME detectat.
- Si MIME detectat no és permès → `MEDIA_POLICY_VIOLATION`.

Eines recomanades: `python-magic`, `filetype`, o equivalent.

---

## Crops i variants

### Principi: crops no destructius

- No retallar l'original. Sempre operar sobre còpia.
- El crop ha de ser semànticament sensible: centrat per defecte, ajustable per metadata si existeix focal point.
- Si no hi ha informació de focal point, crop centrat.
- Si el crop resultant perd més del 30% de l'àrea original, marcar `MEDIA_REVIEW_REQUIRED` en comptes d'aplicar el crop.

### Variants obligatòries

Les variants es generen per la hero image i l'OG image. Les imatges internes no requereixen variants tret que la política ho especifiqui.

Si una variant no es pot generar correctament:
- L'import del contingut **no falla** per defecte.
- L'asset es marca `import_status: imported_with_warnings`.
- Es genera `MEDIA_REVIEW_REQUIRED`.
- La política del projecte pot canviar aquest comportament a `fail_on_variant_error: true`.

---

## Deduplicació

Clau de deduplicació: `SHA-256(original_bytes)` + `original_url`.

- Si el hash ja existeix al sistema media de Despertare → reutilitzar `media_asset_id` existent.
- Si la `original_url` ja existeix però amb hash diferent → nou asset (contingut canviat a l'origen).
- Registrar sempre la relació: `source_url` → `media_asset_id`.

---

## Reescriptura d'URLs de contingut

Després d'importar els assets, la pipeline ha de reescriure les URLs d'imatges dins el contingut:

```
De: https://old-site.com/wp-content/uploads/2024/imatge.jpg
A:  https://new-site.com/media/2024/imatge.jpg
```

- El mapping `old_url → new_url → media_asset_id` es registra a `migration_source_map`.
- Les URLs no reescrites queden com a `MEDIA_REWRITE_PENDING` i es registren a l'informe.
- El contingut no s'importa amb URLs externes sense registre explícit.

---

## Metadades d'asset

Per cada asset importat es conserven:

- `original_url`
- `storage_url` / path nou
- `mime_type` (detectat)
- `size_bytes`
- `width`
- `height`
- `alt` (si existeix)
- `caption` (si existeix)
- `title`
- `description`
- `filename` (original)
- `hash` (SHA-256)
- `import_status`
- `source_system`
- `source_id` (ID a l'origen si disponible)
- variants generades (llista)

---

## Política de fallada per assets

| Situació | Comportament per defecte | Configurable |
|---|---|---|
| Asset no descarregable | Warning; import continua sense asset | `fail_on_media_error: true` |
| MIME no permès | Error `MEDIA_POLICY_VIOLATION`; asset bloquejat | No configurable |
| Mida màxima superada | Warning; asset marcat per revisió | `fail_on_size_exceeded: true` |
| Variant no generada | Warning `MEDIA_REVIEW_REQUIRED` | `fail_on_variant_error: true` |
| Crop perd >30% àrea | No es fa crop; `MEDIA_REVIEW_REQUIRED` | `crop_loss_threshold` configurable |
| Hash duplicat | Reutilitzar asset existent; sense error | No configurable |

---

## Seguretat

- Validar MIME real (no declaració de la font).
- Validar extensió.
- Controlar mida màxima de descàrrega (evitar bombes de fitxer).
- Allowlist de dominis origen per descàrrega (configurable a `config/sources.yml`).
- Sanititzar noms de fitxer (evitar path traversal).
- No executar fitxers descarregats.
- Timeouts per descàrrega configurables.

---

## Adaptation Strategy (addició 2026-04-24)

### Context de l'addició

Durant la migració real, moltes imatges legacy no compliran la media policy:
- aspect ratio incorrecte (imatge vertical en layout horitzontal)
- resolució insuficient
- subjecte desplaçat (no centrat)
- banners amb text incrustat
- composicions no recropables sense pèrdua significativa

El crop simple (fins i tot no destructiu) no és suficient. Cal una estratègia de **visual adaptation non-destructive** que permeti que qualsevol imatge es mostri correctament als layouts de Despertare sense destruir informació visual.

---

### Nou camp: `adaptation_strategy`

Cada asset processrat rep un camp `adaptation_strategy` que documenta com s'ha adaptat:

| Valor | Condició | Descripció |
|---|---|---|
| `exact_fit` | Compleix ratio i mida | Cap modificació d'aspecte |
| `crop_safe` | Crop perd <30% àrea | Crop centrat acceptable |
| `fit_with_background` | Crop perdria >30% o imatge massa petita | Canvas + background adaptat |
| `review_required` | No es pot adaptar correctament | Marcat per revisió manual |

---

### Política de decisió

```
if aspect_ratio_ok and size_ok:
    strategy = exact_fit
elif crop_loss < crop_loss_threshold:
    strategy = crop_safe
elif enable_background_fit:
    strategy = fit_with_background
else:
    strategy = review_required
```

`crop_loss_threshold` per defecte: `0.30` (30%).

---

### Estratègia `fit_with_background`

Quan el crop destruiria massa informació visual, s'aplica `fit_with_background`:

#### Pas 1 — Canvas

Crear canvas amb les dimensions target (ex: 1200×900 per hero 4:3, 1200×630 per og-image).

#### Pas 2 — Escalat i centrat

- Escalar la imatge original mantenint el seu aspect ratio fins que càpiga al canvas.
- Centrar la imatge escalada dins el canvas.
- No estirar mai (distorsió prohibida).

#### Pas 3 — Background (ordre de preferència)

**Opció A — Blur background (default)**

1. Duplicar la imatge original.
2. Escalar-la per cobrir el canvas complet (sense mantenir ratio).
3. Aplicar blur gaussià fort (σ ≥ 20px).
4. Usar com a fons del canvas.
5. Posar la imatge original escalada centrada al damunt.

**Opció B — Color dominant**

1. Extreure el color dominant de la imatge (kmeans o histograma).
2. Generar fons sòlid o gradient radial amb aquest color.

**Opció C — Color de projecte (fallback)**

1. Usar `fallback_background_color` de `media-policy.yml`.
2. Default: `#f5f5f5`.

La selecció entre opcions es configura a `media-policy.yml`:

```yaml
adaptation:
  enable_background_fit: true
  default_background: blur      # blur | color_dominant | project_color
  allow_color_background: true
  crop_loss_threshold: 0.30
  fallback_background_color: "#f5f5f5"
```

---

### Metadades addicionals per asset adaptat

```json
{
  "adaptation_strategy": "fit_with_background",
  "background_type": "blur",
  "original_aspect_ratio": "3:2",
  "target_aspect_ratio": "4:3",
  "padding_applied": true,
  "crop_loss_estimated": 0.42
}
```

---

### Flux de normalització actualitzat

```
1.  Descarregar original
2.  Detectar MIME real
3.  Validar extensió vs MIME
4.  Validar format permès
5.  Validar mida màxima
6.  Calcular SHA-256
7.  Verificar deduplicació
8.  Desar original (immutable)
9.  Detectar dimensions reals
10. Calcular aspect ratio real
11. Comparar amb target ratio de la política
12. Determinar adaptation_strategy:
    → exact_fit → escalar directament
    → crop_safe → crop centrat
    → fit_with_background → canvas + background
    → review_required → marcar, no bloquejar per defecte
13. Generar variants per cada mida definida a la política
14. Guardar metadades d'adaptació
15. Log estructurat amb strategy i background_type
16. Registrar mapping original_url → storage_url
```

---

### Logs

```json
{
  "event": "media_adapted",
  "strategy": "fit_with_background",
  "background_type": "blur",
  "source_url": "...",
  "target_variant": "hero",
  "original_ratio": "3:2",
  "target_ratio": "4:3",
  "crop_loss_estimated": 0.42
}
```

---

### Warnings i mètriques

Nou warning: `MEDIA_ADAPTED_WITH_BACKGROUND`

Noves mètriques al `report.json`:

```json
{
  "assets": {
    "strategy_exact_fit": 80,
    "strategy_crop_safe": 25,
    "strategy_fit_with_background": 12,
    "strategy_review_required": 3
  }
}
```

---

### Prohibicions explícites

- NO estirar imatges (distorsió).
- NO crop agressiu sense control.
- NO descartar imatges automàticament per ratio incorrecte.
- NO deixar espais buits sense estil al canvas.
- NO modificar l'original descarregat.

---

### Impacte en frontend

Els layouts de Despertare (hero, card, og-image) han de:

- Acceptar imatges que poden tenir padding visual (no assumir crop perfecte).
- No re-escalar destructivament al frontend.
- Respectar la composició generada per la media pipeline.

La metadata `adaptation_strategy` i `padding_applied` es transmeten al model d'asset per permetre que el frontend prengui decisions de presentació si cal.

---

## Alternatives descartades

| Alternativa | Motiu del descart |
|---|---|
| Importar URLs externes sense descarregar | Dependència d'assets externs; risc de trencament futur |
| Hardcodejar política d'aspecte al codi | No reutilitzable entre projectes; viola configurabilitat |
| Confiar en MIME declarat per la font | Risc de seguretat; fonts no fiables |
| Aplicar crop sempre sense límit | Pot destruir qualitat visual sense revisió humana |
| Fallar tot el batch si un asset falla | Massa restrictiu; perd contingut valuable per un asset |

---

## Relació amb altres ADR

- ADR-0004 — Editorial Import Pipeline (la pipeline que crida la media sub-pipeline)
- ADR-0007 — Import Contract and Intermediate Format (els assets viatgen en el format intermedi)
