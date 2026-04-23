# ADR-0010 — Conflict Resolution Strategy

**Data:** 2026-04-23
**Estat:** Acceptat
**Autors:** CTO / Arquitectura
**Projecte:** scraper-post-wordpress / sistema d'importació editorial Despertare

---

## Context

Durant la fase Validate de la pipeline (ADR-0004) apareixen conflictes que no es poden resoldre automàticament:

- **Autors** no reconeguts al destí
- **Taxonomies** (categories, tags, customs) sense mapping al model Despertare
- **Slugs** en conflicte amb contingut existent
- **Locales** no actius al projecte

Si cada execució de la pipeline ha de demanar resolució manual per als mateixos conflictes, el procés és inviable per a migracions grans o multi-site.

Cal un sistema de resolució persistent: les decisions preses una vegada es reutilitzen en execucions futures.

---

## Decisió

**La resolució de conflictes es gestiona via fitxers de mapping persistents i versionats que l'agent llegeix durant la fase Validate. Les decisions s'acumulen entre execucions i entre migrations de sites diferents.**

Els mappings no es defineixen per codi: es generen i editen com a fitxers de configuració humans + màquina.

---

## Fitxers de mapping

Ubicació: `config/mappings/`

```
config/mappings/
  authors.yml        # mapping autor origen → autor Despertare
  taxonomies.yml     # mapping categoria/tag/custom → terme Despertare
  slugs.yml          # resolució de col·lisions de slug
  locales.yml        # mapping locale origen → locale Despertare
```

Aquests fitxers es versionen al repositori. Són la memòria operativa de les decisions de migració.

---

## `config/mappings/authors.yml`

Estructura:

```yaml
version: "1.0"
source_system: wordpress
source_site_url: https://example.com

mappings:
  - source_id: 5
    source_name: "Joan Puig"
    source_email: "joan@example.com"
    source_slug: "joan-puig"
    action: map                        # map | create | default | skip
    target_author_id: "uuid-despertare"
    notes: "Ja existeix a Despertare com a joan.puig@conekta.net"

  - source_id: 8
    source_name: "Anna Mas"
    source_slug: "anna-mas"
    action: create
    target_author_data:
      name: "Anna Mas"
      slug: "anna-mas"
      email: "anna.mas@conekta.net"

  - source_id: 12
    source_name: "Redacció"
    action: default
    notes: "Usar autor per defecte del projecte"

  - source_id: 99
    source_name: "Bot importador"
    action: skip
    notes: "No importar contingut d'aquest autor"
```

### Accions possibles

| Acció | Comportament |
|---|---|
| `map` | Mapeja a `target_author_id` existent a Despertare |
| `create` | Crea nou autor amb `target_author_data` |
| `default` | Usa l'autor per defecte del projecte |
| `skip` | Ometre tots els ítems d'aquest autor |
| `pending` | No resolt; ítem queda `pending_review` |

Si un autor no apareix al fitxer → `pending` per defecte.

---

## `config/mappings/taxonomies.yml`

Estructura:

```yaml
version: "1.0"
source_system: wordpress
source_site_url: https://example.com

mappings:
  - source_taxonomy: category
    source_id: 10
    source_name: "Notícies"
    source_slug: "noticies"
    action: map
    target_taxonomy: category
    target_term_id: "uuid-despertare"

  - source_taxonomy: category
    source_id: 15
    source_name: "Opinió"
    source_slug: "opinio"
    action: create
    target_taxonomy: category
    target_term_data:
      name: "Opinió"
      slug: "opinio"

  - source_taxonomy: post_tag
    source_id: 20
    source_name: "Cultura"
    action: map
    target_taxonomy: tag
    target_term_id: "uuid-despertare"

  - source_taxonomy: seccio          # taxonomia custom WordPress
    source_id: 30
    source_name: "Economia"
    action: map
    target_taxonomy: category        # mapeja a category de Despertare
    target_term_id: "uuid-despertare"

  - source_taxonomy: post_tag
    source_id: 99
    source_name: "test"
    action: skip
    notes: "No importar aquest tag"
```

### Accions possibles

| Acció | Comportament |
|---|---|
| `map` | Mapeja a terme existent a Despertare |
| `create` | Crea nou terme amb `target_term_data` |
| `skip` | No importar aquest terme |
| `pending` | No resolt; `TAXONOMY_PENDING` warning |

---

## `config/mappings/slugs.yml`

Estructura:

```yaml
version: "1.0"

resolutions:
  - source_id: 45
    source_slug: "contact"
    source_url: "https://example.com/contact/"
    conflict_with: "uuid-existing-content"
    action: suffix
    resolved_slug: "contact-importat"
    notes: "Slug 'contact' ja ocupat per pàgina nativa"

  - source_id: 78
    source_slug: "about"
    action: map_to_existing
    existing_content_id: "uuid-despertare"
    notes: "Aquesta pàgina substitueix l'existent"

  - source_id: 90
    source_slug: "blog"
    action: skip
    notes: "No importar aquesta pàgina"
```

### Accions possibles

| Acció | Comportament |
|---|---|
| `suffix` | Afegir sufix al slug (`contact-importat`) |
| `rename` | Usar `resolved_slug` com a slug final |
| `map_to_existing` | L'import actualitza el contingut existent |
| `skip` | No importar aquest ítem |
| `pending` | No resolt; ítem queda `blocked` |

---

## `config/mappings/locales.yml`

Estructura:

```yaml
version: "1.0"

default_locale: "ca"

mappings:
  - source_locale: "ca"
    target_locale: "ca"
  - source_locale: "es"
    target_locale: "es"
  - source_locale: "en_US"
    target_locale: "en"
  - source_locale: "fr_FR"
    action: skip
    notes: "Locale no actiu al projecte destí"
  - source_locale: null
    target_locale: "ca"
    notes: "Posts sense locale explícit → locale per defecte"
```

---

## Generació automàtica de mappings pendents

La pipeline genera automàticament un fitxer `config/mappings/pending-{batch_id}.yml` amb tots els conflictes no resolts detectats durant l'execució:

```yaml
# Generat automàticament per batch abc-123
# Editar i moure a config/mappings/ per resoldre

pending_authors:
  - source_id: 5
    source_name: "Joan Puig"
    source_email: "joan@example.com"
    action: pending    # canviar a: map | create | default | skip

pending_taxonomies:
  - source_taxonomy: custom_type
    source_id: 88
    source_name: "Especial"
    action: pending

pending_slugs:
  - source_id: 45
    source_slug: "contact"
    conflict_with: "uuid-existing"
    action: pending
```

El workflow és:

1. Executar `dry-run`
2. Revisar `config/mappings/pending-{batch_id}.yml`
3. Editar i moure resolucions a `config/mappings/authors.yml`, `taxonomies.yml`, `slugs.yml`
4. Re-executar `dry-run` fins que no quedi `pending`
5. Executar import real

---

## Reutilització entre sites

Els fitxers de mapping per defecte estan vinculats a `source_site_url`. Quan es migra un segon site:

- Es pot crear un nou fitxer de mapping específic: `config/mappings/authors-site2.yml`
- O extends del base per no repetir decisions comunes.
- La pipeline permet especificar quin fitxer de mapping llegir per execució.

---

## Alternatives descartades

| Alternativa | Motiu del descart |
|---|---|
| Resolució interactiva per consola en cada execució | No repetible; no versionable; inviable per grans volums |
| Taula de mapping a base de dades | Afegeix dependència d'infraestructura; no portable; no versionable amb git |
| Mapping hardcodejar al codi | No configurable per projecte; no reutilitzable entre migrations |
| Auto-resolució per nom normalitzat | Risc de falsos positius; decisions silencioses |

---

## Relació amb altres ADR

- ADR-0004 — Editorial Import Pipeline (fase Validate llegeix els mappings)
- ADR-0008 — Import Execution Strategy (dry-run genera `pending-{batch_id}.yml`)
- ADR-0009 — Import API Contract (els IDs resolts s'envien a la Import API)
