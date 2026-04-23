"""Snapshot — Fase 2. Persisteix format intermedi immutable. ADR-0007."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from migration_agent.models.intermediate import (
    AuthorRef,
    ContentBody,
    Dates,
    Integrity,
    IntermediateItem,
    MediaRef,
    Routing,
    SeoMetadata,
    SourceInfo,
    Taxonomies,
    TaxonomyTerm,
)
from migration_agent.logger import log


def _snapshots_dir() -> Path:
    here = Path(__file__).resolve()
    return here.parents[5] / "artifacts" / "snapshots"


def build_intermediate(
    normalized: dict[str, Any],
    batch_id: str,
) -> IntermediateItem:
    """Construeix un IntermediateItem a partir del dict normalitzat per l'adapter."""
    now = datetime.now(timezone.utc).isoformat()
    content_html = normalized.get("content_html", "")
    content_hash = hashlib.sha256(content_html.encode()).hexdigest()

    source = SourceInfo(
        system=normalized["source_system"],
        site_url=normalized["source_site_url"],
        id=normalized["source_id"],
        type=normalized["source_type"],
        status=normalized["source_status"],
        url=normalized["source_url"],
        parent_id=normalized.get("parent_id"),
        menu_order=normalized.get("menu_order", 0),
        template=normalized.get("template"),
        locale=normalized.get("locale"),
    )

    routing = Routing(
        slug=normalized["slug"],
        path=f"/{normalized['slug']}/",
        legacy_url=normalized["source_url"],
        desired_url=f"/{normalized['slug']}/",
        canonical_url=normalized["source_url"],
    )

    content = ContentBody(
        title=normalized["title"],
        excerpt=normalized.get("excerpt"),
        html=content_html,
        raw=normalized.get("content_raw"),
        blocks=[],  # Transform omple els blocs
    )

    hero: MediaRef | None = None
    if fm := normalized.get("featured_media"):
        hero = MediaRef(
            source_url=fm.get("source_url", ""),
            alt=fm.get("alt"),
            caption=fm.get("caption"),
            title=fm.get("title"),
            mime_type=fm.get("mime_type"),
            width=fm.get("width"),
            height=fm.get("height"),
            role="hero",
        )

    author: AuthorRef | None = None
    if a := normalized.get("author"):
        author = AuthorRef(
            source_id=a.get("source_id"),
            name=a.get("name"),
            slug=a.get("slug"),
            email=a.get("email"),
            bio=a.get("bio"),
            avatar_url=a.get("avatar_url"),
        )

    cats = [
        TaxonomyTerm(source_id=c["source_id"], name=c["name"], slug=c["slug"])
        for c in normalized.get("categories", [])
    ]
    tags = [
        TaxonomyTerm(source_id=t["source_id"], name=t["name"], slug=t["slug"])
        for t in normalized.get("tags", [])
    ]
    taxonomies = Taxonomies(categories=cats, tags=tags)

    seo_raw = normalized.get("seo", {})
    seo = SeoMetadata(
        title=seo_raw.get("title"),
        description=seo_raw.get("description"),
        canonical=seo_raw.get("canonical"),
        robots=seo_raw.get("robots"),
        og_title=seo_raw.get("og_title"),
        og_description=seo_raw.get("og_description"),
        og_image=seo_raw.get("og_image"),
        twitter_card=seo_raw.get("twitter_card"),
        source=seo_raw.get("source", "derived"),
    )

    dates_raw = normalized.get("dates", {})
    dates = Dates(
        created_at=dates_raw.get("created_at"),
        published_at=dates_raw.get("published_at"),
        modified_at=dates_raw.get("modified_at"),
    )

    integrity = Integrity(
        content_hash=f"sha256:{content_hash}",
        extracted_at=now,
    )

    return IntermediateItem(
        import_batch_id=batch_id,
        extracted_at=now,
        source=source,
        routing=routing,
        content=content,
        hero=hero,
        author=author,
        taxonomies=taxonomies,
        seo=seo,
        dates=dates,
        custom_fields=normalized.get("custom_fields") or {},
        integrity=integrity,
    )


def save_snapshot(item: IntermediateItem, force: bool = False) -> Path:
    """Desa snapshot immutable. No sobreescriu tret que force=True."""
    snapshots_dir = _snapshots_dir()
    dest = snapshots_dir / item.source.system / f"{item.source.id}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not force:
        log.info("snapshot_exists", source_id=str(item.source.id), path=str(dest))
        return dest

    dest.write_text(
        json.dumps(item.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("snapshot_saved", source_id=str(item.source.id), path=str(dest))
    return dest


def load_snapshot(source_system: str, source_id: int | str) -> IntermediateItem:
    """Carrega un snapshot existent."""
    dest = _snapshots_dir() / source_system / f"{source_id}.json"
    if not dest.exists():
        raise FileNotFoundError(f"Snapshot not found: {dest}")
    data = json.loads(dest.read_text(encoding="utf-8"))
    return IntermediateItem.model_validate(data)


def snapshot_exists(source_system: str, source_id: int | str) -> bool:
    dest = _snapshots_dir() / source_system / f"{source_id}.json"
    return dest.exists()
