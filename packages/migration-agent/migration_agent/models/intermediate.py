"""Models del format intermedi canònic — ADR-0007."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


SCHEMA_VERSION = "1.0"


class SourceInfo(BaseModel):
    system: str
    site_url: str
    id: int | str
    type: str
    status: str
    url: str
    parent_id: int | str | None = None
    menu_order: int = 0
    template: str | None = None
    locale: str | None = None


class Routing(BaseModel):
    slug: str
    path: str
    legacy_url: str
    desired_url: str
    canonical_url: str | None = None


class Block(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    legacy: bool = False
    warning: str | None = None


class ContentBody(BaseModel):
    title: str
    excerpt: str | None = None
    html: str | None = None
    raw: str | None = None
    blocks: list[Block] = Field(default_factory=list)
    shortcodes_detected: list[str] = Field(default_factory=list)
    embeds_detected: list[str] = Field(default_factory=list)


class MediaRef(BaseModel):
    source_url: str
    filename: str | None = None
    alt: str | None = None
    caption: str | None = None
    title: str | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    hash: str | None = None
    role: str = "inline"
    import_status: str = "pending"
    new_url: str | None = None
    media_asset_id: str | None = None


class AuthorRef(BaseModel):
    source_id: int | str | None = None
    name: str | None = None
    slug: str | None = None
    email: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    mapping_status: str = "pending"


class TaxonomyTerm(BaseModel):
    source_id: int | str
    name: str
    slug: str
    mapping_status: str = "pending"


class Taxonomies(BaseModel):
    categories: list[TaxonomyTerm] = Field(default_factory=list)
    tags: list[TaxonomyTerm] = Field(default_factory=list)
    custom: list[dict[str, Any]] = Field(default_factory=list)


class SeoMetadata(BaseModel):
    title: str | None = None
    description: str | None = None
    canonical: str | None = None
    robots: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image: str | None = None
    twitter_card: str | None = None
    twitter_title: str | None = None
    twitter_description: str | None = None
    source: str = "derived"  # yoast | rankmath | derived | manual


class Dates(BaseModel):
    created_at: str | None = None
    published_at: str | None = None
    modified_at: str | None = None


class Integrity(BaseModel):
    content_hash: str | None = None
    extracted_at: str
    adapter_version: str = "1.0.0"
    schema_version: str = SCHEMA_VERSION


class ImportState(BaseModel):
    import_status: Literal[
        "pending", "ready", "ready_with_warnings",
        "pending_review", "blocked", "imported", "skipped", "failed"
    ] = "pending"
    mapping_status: Literal["pending", "complete", "partial"] = "pending"
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    imported_at: str | None = None
    target_entity_type: str | None = None
    target_entity_id: str | None = None
    target_url: str | None = None
    import_batch_id: str | None = None


class IntermediateItem(BaseModel):
    schema_version: str = SCHEMA_VERSION
    import_batch_id: str
    extracted_at: str
    source: SourceInfo
    routing: Routing
    content: ContentBody
    hero: MediaRef | None = None
    media: list[MediaRef] = Field(default_factory=list)
    author: AuthorRef | None = None
    taxonomies: Taxonomies = Field(default_factory=Taxonomies)
    seo: SeoMetadata = Field(default_factory=SeoMetadata)
    dates: Dates = Field(default_factory=Dates)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    integrity: Integrity
    import_state: ImportState = Field(default_factory=ImportState)

    def add_warning(self, code: str) -> None:
        if code not in self.import_state.warnings:
            self.import_state.warnings.append(code)

    def add_error(self, code: str) -> None:
        if code not in self.import_state.errors:
            self.import_state.errors.append(code)

    def set_status(self, status: str) -> None:
        self.import_state.import_status = status  # type: ignore[assignment]
