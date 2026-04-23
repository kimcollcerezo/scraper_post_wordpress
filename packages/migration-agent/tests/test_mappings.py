"""Tests del MappingResolver i integració amb validate — ADR-0010."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from migration_agent.pipeline.mappings import MappingResolver
from migration_agent.pipeline.validate import validate
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
    TaxonomyTerm,
    Taxonomies,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _make_item(
    source_id: int = 42,
    slug: str = "test-post",
    author_source_id: int | None = 5,
    locale: str | None = None,
) -> IntermediateItem:
    author = (
        AuthorRef(source_id=author_source_id, name="Joan Doe", slug="joan-doe")
        if author_source_id is not None
        else None
    )
    return IntermediateItem(
        import_batch_id="batch-test",
        extracted_at="2026-04-24T10:00:00Z",
        source=SourceInfo(
            system="wordpress",
            site_url="https://example.com",
            id=source_id,
            type="post",
            status="publish",
            url=f"https://example.com/{slug}/",
            locale=locale,
        ),
        routing=Routing(
            slug=slug,
            path=f"/{slug}/",
            legacy_url=f"https://example.com/{slug}/",
            desired_url=f"/{slug}/",
        ),
        content=ContentBody(
            title="Test Post",
            blocks=[{"type": "paragraph", "data": {"text": "Hello"}, "legacy": False}],
        ),
        author=author,
        seo=SeoMetadata(title="Test", description="Desc"),
        dates=Dates(published_at="2026-04-24T10:00:00Z"),
        integrity=Integrity(extracted_at="2026-04-24T10:00:00Z"),
    )


def _make_resolver(tmp_path: Path, authors: str = "", taxonomies: str = "",
                   slugs: str = "", locales: str = "") -> MappingResolver:
    mappings_dir = tmp_path / "mappings"
    mappings_dir.mkdir()
    if authors:
        _write(mappings_dir / "authors.yml", authors)
    if taxonomies:
        _write(mappings_dir / "taxonomies.yml", taxonomies)
    if slugs:
        _write(mappings_dir / "slugs.yml", slugs)
    if locales:
        _write(mappings_dir / "locales.yml", locales)
    return MappingResolver(mappings_dir)


# ── Tests MappingResolver — Authors ───────────────────────────────────────────

def test_author_map_action(tmp_path):
    r = _make_resolver(tmp_path, authors="""
        mappings:
          - source_id: 5
            source_name: Joan Doe
            action: map
            target_author_id: uuid-joan
    """)
    author = AuthorRef(source_id=5, name="Joan Doe", slug="joan-doe")
    action = r.resolve_author(author)
    assert action == "map"
    assert author.mapping_status == "complete"


def test_author_skip_action(tmp_path):
    r = _make_resolver(tmp_path, authors="""
        mappings:
          - source_id: 99
            source_name: Bot
            action: skip
    """)
    author = AuthorRef(source_id=99, name="Bot", slug="bot")
    action = r.resolve_author(author)
    assert action == "skip"


def test_author_default_action(tmp_path):
    r = _make_resolver(tmp_path, authors="""
        mappings:
          - source_id: 12
            source_name: Redacció
            action: default
    """)
    author = AuthorRef(source_id=12, name="Redacció", slug="redaccio")
    action = r.resolve_author(author)
    assert action == "default"
    assert author.source_id == "__default__"


def test_author_unknown_goes_pending(tmp_path):
    r = _make_resolver(tmp_path)
    author = AuthorRef(source_id=999, name="Unknown", slug="unknown")
    action = r.resolve_author(author)
    assert action == "pending"
    assert len(r._pending_authors) == 1


# ── Tests MappingResolver — Taxonomies ────────────────────────────────────────

def test_taxonomy_map_action(tmp_path):
    r = _make_resolver(tmp_path, taxonomies="""
        mappings:
          - source_taxonomy: category
            source_id: 10
            source_name: Notícies
            action: map
            target_taxonomy: category
            target_term_id: uuid-noticies
    """)
    term = TaxonomyTerm(source_id=10, name="Notícies", slug="noticies")
    action = r.resolve_taxonomy_term(term, "category")
    assert action == "map"
    assert term.mapping_status == "complete"


def test_taxonomy_skip_action(tmp_path):
    r = _make_resolver(tmp_path, taxonomies="""
        mappings:
          - source_taxonomy: post_tag
            source_id: 99
            source_name: test
            action: skip
    """)
    term = TaxonomyTerm(source_id=99, name="test", slug="test")
    action = r.resolve_taxonomy_term(term, "post_tag")
    assert action == "skip"


def test_taxonomy_unknown_goes_pending(tmp_path):
    r = _make_resolver(tmp_path)
    term = TaxonomyTerm(source_id=55, name="Nova", slug="nova")
    action = r.resolve_taxonomy_term(term, "category")
    assert action == "pending"
    assert len(r._pending_taxonomies) == 1


# ── Tests MappingResolver — Slugs ─────────────────────────────────────────────

def test_slug_suffix_action(tmp_path):
    r = _make_resolver(tmp_path, slugs="""
        resolutions:
          - source_id: 45
            source_slug: contact
            action: suffix
            resolved_slug: contact-importat
    """)
    item = _make_item(source_id=45, slug="contact")
    action = r.resolve_slug(item)
    assert action == "suffix"
    assert item.routing.slug == "contact-importat"


def test_slug_no_conflict_returns_ok(tmp_path):
    r = _make_resolver(tmp_path)
    item = _make_item(source_id=1, slug="slug-lliure")
    action = r.resolve_slug(item)
    assert action == "ok"


def test_slug_skip_action(tmp_path):
    r = _make_resolver(tmp_path, slugs="""
        resolutions:
          - source_id: 90
            source_slug: blog
            action: skip
    """)
    item = _make_item(source_id=90, slug="blog")
    action = r.resolve_slug(item)
    assert action == "skip"


# ── Tests MappingResolver — Locales ───────────────────────────────────────────

def test_locale_mapped(tmp_path):
    r = _make_resolver(tmp_path, locales="""
        default_locale: ca
        mappings:
          - source_locale: en_US
            target_locale: en
    """)
    assert r.resolve_locale("en_US") == "en"


def test_locale_skip(tmp_path):
    r = _make_resolver(tmp_path, locales="""
        default_locale: ca
        mappings:
          - source_locale: fr_FR
            action: skip
    """)
    assert r.resolve_locale("fr_FR") is None


def test_locale_unknown_uses_default(tmp_path):
    r = _make_resolver(tmp_path, locales="""
        default_locale: ca
        mappings: []
    """)
    assert r.resolve_locale("unknown") == "ca"


def test_locale_null_uses_default(tmp_path):
    r = _make_resolver(tmp_path, locales="""
        default_locale: ca
        mappings:
          - source_locale: null
            target_locale: ca
    """)
    assert r.resolve_locale(None) == "ca"


# ── Tests pending file generation ─────────────────────────────────────────────

def test_write_pending_creates_file(tmp_path):
    r = _make_resolver(tmp_path)
    author = AuthorRef(source_id=1, name="Unknown", slug="unknown")
    r.resolve_author(author)
    out = r.write_pending("batch-xyz")
    assert out is not None
    assert out.exists()
    content = out.read_text()
    assert "pending_authors" in content
    assert "Unknown" in content


def test_write_pending_no_file_when_empty(tmp_path):
    r = _make_resolver(tmp_path)
    out = r.write_pending("batch-empty")
    assert out is None


# ── Tests integració validate + MappingResolver ────────────────────────────────

def test_validate_author_skip_blocks_item(tmp_path):
    r = _make_resolver(tmp_path, authors="""
        mappings:
          - source_id: 99
            action: skip
    """)
    item = _make_item(author_source_id=99)
    result = validate(item, {}, resolver=r)
    assert result.import_state.import_status == "blocked"
    assert "AUTHOR_SKIP_MAPPING" in result.import_state.errors


def test_validate_author_map_resolves(tmp_path):
    r = _make_resolver(tmp_path, authors="""
        mappings:
          - source_id: 5
            action: map
            target_author_id: uuid-joan
    """)
    item = _make_item(author_source_id=5)
    result = validate(item, {}, resolver=r)
    assert "AUTHOR_PENDING" not in result.import_state.warnings
    assert result.import_state.import_status in ("ready", "ready_with_warnings")


def test_validate_slug_suffix_applied(tmp_path):
    r = _make_resolver(tmp_path, slugs="""
        resolutions:
          - source_id: 42
            source_slug: test-post
            action: suffix
            resolved_slug: test-post-importat
    """)
    item = _make_item(source_id=42, slug="test-post")
    result = validate(item, {}, resolver=r)
    assert result.routing.slug == "test-post-importat"


def test_validate_locale_skip_blocks_item(tmp_path):
    r = _make_resolver(tmp_path, locales="""
        default_locale: ca
        mappings:
          - source_locale: fr_FR
            action: skip
    """)
    item = _make_item(locale="fr_FR")
    result = validate(item, {}, resolver=r)
    assert result.import_state.import_status == "blocked"
    assert "LOCALE_SKIP_MAPPING" in result.import_state.errors


def test_validate_no_resolver_unchanged(tmp_path):
    """Sense resolver, validate funciona com abans."""
    item = _make_item()
    result = validate(item, {})
    assert result.import_state.import_status in ("ready", "ready_with_warnings")
