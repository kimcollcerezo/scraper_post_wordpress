"""Conflict resolution via persistent YAML mappings — ADR-0010.

Llegeix config/mappings/{authors,taxonomies,slugs,locales}.yml
i resol conflictes d'autor, taxonomia, slug i locale durant la fase Validate.

Genera config/mappings/pending-{batch_id}.yml amb els conflictes no resolts.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any

from migration_agent.logger import log
from migration_agent.models.intermediate import (
    AuthorRef,
    IntermediateItem,
    TaxonomyTerm,
)


# ── Loader ─────────────────────────────────────────────────────────────────────

def _load_yaml_safe(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class MappingResolver:
    """Resoledor de conflictes basat en fitxers de mapping persistents."""

    def __init__(self, mappings_dir: Path) -> None:
        self._dir = mappings_dir
        self._authors = _load_yaml_safe(mappings_dir / "authors.yml")
        self._taxonomies = _load_yaml_safe(mappings_dir / "taxonomies.yml")
        self._slugs = _load_yaml_safe(mappings_dir / "slugs.yml")
        self._locales = _load_yaml_safe(mappings_dir / "locales.yml")

        # Índexs ràpids per source_id
        self._author_idx: dict[str, dict[str, Any]] = {
            str(m["source_id"]): m
            for m in self._authors.get("mappings", [])
            if "source_id" in m
        }
        self._taxonomy_idx: dict[str, dict[str, Any]] = {
            f"{m.get('source_taxonomy','*')}:{m['source_id']}": m
            for m in self._taxonomies.get("mappings", [])
            if "source_id" in m
        }
        self._slug_idx: dict[str, dict[str, Any]] = {
            str(r["source_id"]): r
            for r in self._slugs.get("resolutions", [])
            if "source_id" in r
        }

        # Índex locale: source_locale → entry
        self._locale_idx: dict[str | None, dict[str, Any]] = {}
        for m in self._locales.get("mappings", []):
            key = m.get("source_locale")  # pot ser null/None
            self._locale_idx[key] = m
        self._default_locale: str = self._locales.get("default_locale", "ca")

        # Acumulador de conflictes pendents per generar el fitxer pending
        self._pending_authors: list[dict[str, Any]] = []
        self._pending_taxonomies: list[dict[str, Any]] = []
        self._pending_slugs: list[dict[str, Any]] = []

    # ── Author resolution ──────────────────────────────────────────────────────

    def resolve_author(self, author: AuthorRef) -> str:
        """
        Retorna l'acció: 'map' | 'create' | 'default' | 'skip' | 'pending'.
        Modifica author in-place si hi ha mapping resolt.
        """
        sid = str(author.source_id) if author.source_id is not None else ""
        entry = self._author_idx.get(sid)

        if entry is None:
            self._pending_authors.append({
                "source_id": author.source_id,
                "source_name": author.name,
                "source_email": author.email,
                "action": "pending",
            })
            return "pending"

        action = entry.get("action", "pending")

        if action == "map":
            author.mapping_status = "complete"
            # Guardem target_author_id per si l'API el necessita
            author.source_id = entry.get("target_author_id", author.source_id)

        elif action == "create":
            author.mapping_status = "pending"  # crearà l'API

        elif action == "default":
            author.mapping_status = "complete"
            # Senyal que cal usar l'autor per defecte del projecte
            author.source_id = "__default__"

        elif action == "skip":
            pass  # l'orchestrator saltarà l'ítem

        return action

    # ── Taxonomy resolution ────────────────────────────────────────────────────

    def resolve_taxonomy_term(
        self, term: TaxonomyTerm, source_taxonomy: str
    ) -> str:
        """Retorna l'acció: 'map' | 'create' | 'skip' | 'pending'."""
        key = f"{source_taxonomy}:{term.source_id}"
        entry = self._taxonomy_idx.get(key)

        if entry is None:
            self._pending_taxonomies.append({
                "source_taxonomy": source_taxonomy,
                "source_id": term.source_id,
                "source_name": term.name,
                "action": "pending",
            })
            return "pending"

        action = entry.get("action", "pending")

        if action == "map":
            term.mapping_status = "complete"
            # Actualitzar slug/nom si el mapping el redefineix
            if "target_term_data" in entry:
                d = entry["target_term_data"]
                term.name = d.get("name", term.name)
                term.slug = d.get("slug", term.slug)

        elif action == "create":
            term.mapping_status = "pending"

        elif action == "skip":
            term.mapping_status = "complete"  # es marcarà per ometre

        return action

    # ── Slug resolution ────────────────────────────────────────────────────────

    def resolve_slug(self, item: IntermediateItem) -> str:
        """
        Retorna l'acció: 'suffix' | 'rename' | 'map_to_existing' | 'skip' | 'ok'.
        Modifica routing.slug in-place si cal.
        """
        sid = str(item.source.id)
        entry = self._slug_idx.get(sid)

        if entry is None:
            return "ok"  # sense conflicte conegut

        action = entry.get("action", "pending")

        if action == "suffix":
            resolved = entry.get("resolved_slug", item.routing.slug + "-importat")
            item.routing.slug = resolved
            item.routing.path = f"/{resolved}/"
            item.routing.desired_url = f"/{resolved}/"

        elif action == "rename":
            resolved = entry.get("resolved_slug", item.routing.slug)
            item.routing.slug = resolved
            item.routing.path = f"/{resolved}/"
            item.routing.desired_url = f"/{resolved}/"

        elif action == "map_to_existing":
            pass  # l'Import API rebrà existing_content_id si cal

        elif action == "skip":
            pass

        elif action == "pending":
            self._pending_slugs.append({
                "source_id": item.source.id,
                "source_slug": item.routing.slug,
                "action": "pending",
            })

        return action

    # ── Locale resolution ──────────────────────────────────────────────────────

    def resolve_locale(self, source_locale: str | None) -> str | None:
        """Retorna el locale destí o None si s'ha de saltar."""
        entry = self._locale_idx.get(source_locale)
        if entry is None:
            # Intentar amb el default (source_locale=None)
            default_entry = self._locale_idx.get(None)
            if default_entry:
                return default_entry.get("target_locale", self._default_locale)
            return self._default_locale

        action = entry.get("action", "map")
        if action == "skip":
            return None
        return entry.get("target_locale", self._default_locale)

    # ── Generació pending file ─────────────────────────────────────────────────

    def write_pending(self, batch_id: str) -> Path | None:
        """Escriu config/mappings/pending-{batch_id}.yml si hi ha pendents."""
        if not (self._pending_authors or self._pending_taxonomies or self._pending_slugs):
            return None

        content: dict[str, Any] = {}
        if self._pending_authors:
            content["pending_authors"] = self._pending_authors
        if self._pending_taxonomies:
            content["pending_taxonomies"] = self._pending_taxonomies
        if self._pending_slugs:
            content["pending_slugs"] = self._pending_slugs

        out = self._dir / f"pending-{batch_id}.yml"
        out.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# Generat automàticament per batch {batch_id}\n"
            "# Editar i moure resolucions a config/mappings/authors.yml, "
            "taxonomies.yml, slugs.yml\n\n"
        )
        out.write_text(header + yaml.dump(content, allow_unicode=True, sort_keys=False), encoding="utf-8")
        log.info("pending_mappings_written", batch_id=batch_id, path=str(out))
        return out
