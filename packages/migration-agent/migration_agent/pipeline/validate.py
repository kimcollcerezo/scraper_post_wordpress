"""Validate — Fase 4. Valida invariants editorials. ADR-0004."""

from __future__ import annotations

import re
from typing import Any

from migration_agent.models.intermediate import IntermediateItem


SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate(item: IntermediateItem, policy: dict[str, Any] | None = None) -> IntermediateItem:
    """Valida l'ítem i actualitza import_state. Modifica in-place."""
    policy = policy or {}
    errors_before = len(item.import_state.errors)

    _validate_source(item)
    _validate_routing(item)
    _validate_content(item)
    _validate_seo(item)
    _validate_author(item, policy)
    _validate_taxonomies(item, policy)

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


def _validate_routing(item: IntermediateItem) -> None:
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


def _validate_author(item: IntermediateItem, policy: dict[str, Any]) -> None:
    on_missing = policy.get("author", {}).get("on_missing", "pending")
    if item.author is None or item.author.mapping_status == "pending":
        if on_missing == "fail":
            item.add_error("AUTHOR_MAPPING_REQUIRED")
        else:
            item.add_warning("AUTHOR_PENDING")


def _validate_taxonomies(item: IntermediateItem, policy: dict[str, Any]) -> None:
    on_missing = policy.get("taxonomy", {}).get("on_missing", "pending")
    has_pending = any(
        c.mapping_status == "pending"
        for c in (item.taxonomies.categories + item.taxonomies.tags)
    )
    if has_pending:
        if on_missing == "fail":
            item.add_error("TAXONOMY_MAPPING_REQUIRED")
        else:
            item.add_warning("TAXONOMY_PENDING")
