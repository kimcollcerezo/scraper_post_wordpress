"""Validate — Fase 4. Valida invariants editorials i resol mappings. ADR-0004 / ADR-0010."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from migration_agent.models.intermediate import IntermediateItem
from migration_agent.pipeline.mappings import MappingResolver


SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate(
    item: IntermediateItem,
    policy: dict[str, Any] | None = None,
    mappings_dir: Path | None = None,
    resolver: MappingResolver | None = None,
) -> IntermediateItem:
    """Valida l'ítem i actualitza import_state. Modifica in-place.

    mappings_dir: directori config/mappings/ — si s'indica, es crea un MappingResolver.
    resolver: MappingResolver precarregat (prioritat sobre mappings_dir).
    """
    policy = policy or {}
    errors_before = len(item.import_state.errors)

    # Mapping resolution (ADR-0010)
    if resolver is None and mappings_dir is not None:
        resolver = MappingResolver(mappings_dir)

    _validate_source(item)
    _validate_routing(item, resolver)
    _validate_content(item)
    _validate_seo(item)
    _validate_author(item, policy, resolver)
    _validate_taxonomies(item, policy, resolver)
    _validate_locale(item, resolver)

    # Determinar estat final
    has_errors = len(item.import_state.errors) > errors_before or bool(item.import_state.errors)
    has_warnings = bool(item.import_state.warnings)

    if has_errors:
        item.set_status("blocked")
    elif item.import_state.import_status == "pending_review":
        pass  # ja marcat per transform
    elif has_warnings:
        item.set_status("ready_with_warnings")
    else:
        item.set_status("ready")

    return item


def _validate_source(item: IntermediateItem) -> None:
    if not item.source.system:
        item.add_error("INVALID_SOURCE_ITEM")
    if not item.source.id:
        item.add_error("INVALID_SOURCE_ITEM")
    if not item.source.url:
        item.add_error("INVALID_SOURCE_ITEM")


def _validate_routing(item: IntermediateItem, resolver: MappingResolver | None = None) -> None:
    # Resolució de slug conflict (ADR-0010)
    if resolver is not None:
        action = resolver.resolve_slug(item)
        if action == "skip":
            item.set_status("blocked")
            item.add_error("SLUG_SKIP_MAPPING")
            return
        if action == "pending":
            item.add_error("SLUG_COLLISION")
            return

    slug = item.routing.slug
    if not slug:
        item.add_error("INVALID_SLUG")
        return
    if not SLUG_PATTERN.match(slug):
        item.add_warning("SLUG_FORMAT_WARNING")


def _validate_content(item: IntermediateItem) -> None:
    if not item.content.title or not item.content.title.strip():
        item.add_error("INVALID_SOURCE_ITEM")
    if not item.content.blocks:
        item.add_warning("CONTENT_EMPTY_BLOCKS")


def _validate_seo(item: IntermediateItem) -> None:
    if not item.seo.title:
        item.add_warning("SEO_INCOMPLETE")
    if not item.seo.description:
        item.add_warning("SEO_INCOMPLETE")


def _validate_author(
    item: IntermediateItem,
    policy: dict[str, Any],
    resolver: MappingResolver | None = None,
) -> None:
    on_missing = policy.get("author", {}).get("on_missing", "pending")

    if item.author is not None and resolver is not None:
        action = resolver.resolve_author(item.author)
        if action == "skip":
            # Tot l'ítem s'omet si l'autor té action=skip
            item.set_status("blocked")
            item.add_error("AUTHOR_SKIP_MAPPING")
            return
        if action in ("map", "default"):
            return  # resolt
        if action == "create":
            return  # l'API crearà l'autor
        # action == "pending" → cau al comportament per defecte

    # "create" significa que tenim dades suficients — l'Import API el crearà
    if item.author is None or item.author.mapping_status == "pending":
        if not item.author or not item.author.name:
            if on_missing == "fail":
                item.add_error("AUTHOR_MAPPING_REQUIRED")
            else:
                item.add_warning("AUTHOR_PENDING")


def _validate_taxonomies(
    item: IntermediateItem,
    policy: dict[str, Any],
    resolver: MappingResolver | None = None,
) -> None:
    on_missing = policy.get("taxonomy", {}).get("on_missing", "pending")

    if resolver is not None:
        for cat in item.taxonomies.categories:
            action = resolver.resolve_taxonomy_term(cat, "category")
            if action == "skip":
                cat.mapping_status = "complete"  # s'ometrà silenciosament
        for tag in item.taxonomies.tags:
            action = resolver.resolve_taxonomy_term(tag, "post_tag")
            if action == "skip":
                tag.mapping_status = "complete"

    has_pending = any(
        c.mapping_status == "pending"
        for c in (item.taxonomies.categories + item.taxonomies.tags)
    )
    if has_pending:
        if on_missing == "fail":
            item.add_error("TAXONOMY_MAPPING_REQUIRED")
        else:
            item.add_warning("TAXONOMY_PENDING")


def _validate_locale(item: IntermediateItem, resolver: MappingResolver | None = None) -> None:
    if resolver is None:
        return
    source_locale = item.source.locale
    target_locale = resolver.resolve_locale(source_locale)
    if target_locale is None:
        item.set_status("blocked")
        item.add_error("LOCALE_SKIP_MAPPING")
    else:
        item.source.locale = target_locale
