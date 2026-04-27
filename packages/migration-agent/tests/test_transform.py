"""Tests de transformació HTML → blocs."""

from __future__ import annotations

import pytest
from migration_agent.models.intermediate import (
    ContentBody, Integrity, IntermediateItem, Routing, SourceInfo,
)
from migration_agent.pipeline.transform import transform, _html_to_blocks, _serialize_anchor
from migration_agent.models.intermediate import SeoMetadata, Dates
from bs4 import BeautifulSoup


def _item_with_html(html: str) -> IntermediateItem:
    return IntermediateItem(
        import_batch_id="test-batch",
        extracted_at="2026-04-23T10:00:00+00:00",
        source=SourceInfo(
            system="wordpress", site_url="https://x.com",
            id=1, type="post", status="publish", url="https://x.com/p/",
        ),
        routing=Routing(slug="p", path="/p/", legacy_url="https://x.com/p/", desired_url="/p/"),
        content=ContentBody(title="Test", html=html),
        integrity=Integrity(extracted_at="2026-04-23T10:00:00+00:00"),
    )


def test_paragraph_transform():
    item = _item_with_html("<p>Hola món</p>")
    result = transform(item)
    assert len(result.content.blocks) == 1
    assert result.content.blocks[0].type == "paragraph"
    assert "Hola món" in result.content.blocks[0].data["html"]


def test_heading_transform():
    item = _item_with_html("<h2>Títol de secció</h2>")
    result = transform(item)
    assert result.content.blocks[0].type == "heading"
    assert result.content.blocks[0].data["level"] == 2
    assert result.content.blocks[0].data["text"] == "Títol de secció"


def test_list_transform():
    item = _item_with_html("<ul><li>Element A</li><li>Element B</li></ul>")
    result = transform(item)
    assert result.content.blocks[0].type == "list"
    assert result.content.blocks[0].data["ordered"] is False
    assert len(result.content.blocks[0].data["items"]) == 2


def test_ordered_list_transform():
    item = _item_with_html("<ol><li>Primer</li><li>Segon</li></ol>")
    result = transform(item)
    assert result.content.blocks[0].data["ordered"] is True


def test_image_transform():
    item = _item_with_html('<img src="https://x.com/img.jpg" alt="text" />')
    result = transform(item)
    assert result.content.blocks[0].type == "image"
    assert result.content.blocks[0].data["src"] == "https://x.com/img.jpg"


def test_raw_html_ratio_warning():
    """Si >20% de blocs són raw_html, generar HIGH_RAW_HTML_RATIO."""
    html = "<p>Normal</p>" + "<div class='custom'>A</div>" * 5
    item = _item_with_html(html)
    policy = {"transform": {"raw_html_warning_threshold": 0.20, "raw_html_block_threshold": 0.50}}
    result = transform(item, policy)
    assert "HIGH_RAW_HTML_RATIO" in result.import_state.warnings


def test_no_raw_html_for_simple_content():
    """Contingut simple no ha de generar raw_html."""
    html = "<h2>Títol</h2><p>Text</p><ul><li>a</li></ul>"
    item = _item_with_html(html)
    result = transform(item)
    raw_blocks = [b for b in result.content.blocks if b.type == "raw_html"]
    assert len(raw_blocks) == 0


def test_seo_derived_from_title():
    """Si no hi ha SEO, s'ha de derivar del title."""
    item = _item_with_html("<p>Text</p>")
    item.content.title = "El meu títol"
    result = transform(item)
    assert result.seo.title == "El meu títol"


# ── Tests nofollow ─────────────────────────────────────────────────────────────

def test_nofollow_added_to_external_link():
    """Enllaços externs han de rebre rel="nofollow"."""
    html = '<p><a href="https://external.com/page">text</a></p>'
    item = _item_with_html(html)
    item.source.site_url = "https://x.com"
    result = transform(item)
    block_html = result.content.blocks[0].data["html"]
    assert 'nofollow' in block_html


def test_nofollow_not_added_to_internal_link():
    """Enllaços interns NO han de rebre rel="nofollow"."""
    html = '<p><a href="https://x.com/altra-pagina/">text</a></p>'
    item = _item_with_html(html)
    item.source.site_url = "https://x.com"
    result = transform(item)
    block_html = result.content.blocks[0].data["html"]
    assert 'nofollow' not in block_html


def test_nofollow_not_added_to_relative_link():
    """Enllaços relatius (sense domini) NO han de rebre rel="nofollow"."""
    html = '<p><a href="/pagina-interna/">text</a></p>'
    item = _item_with_html(html)
    item.source.site_url = "https://x.com"
    result = transform(item)
    block_html = result.content.blocks[0].data["html"]
    assert 'nofollow' not in block_html


def test_nofollow_preserves_existing_rel():
    """Si ja té rel="ugc", ha d'afegir nofollow sense eliminar l'existent."""
    a_tag = BeautifulSoup('<a href="https://ext.com/" rel="ugc">x</a>', "lxml").find("a")
    result = _serialize_anchor(a_tag, internal_domain="x.com")
    assert "nofollow" in result
    assert "ugc" in result


# ── Tests autor mapping_status ─────────────────────────────────────────────────

def test_author_with_name_slug_is_create(tmp_path):
    """Autor amb nom i slug ha de tenir mapping_status='create' després del snapshot."""
    from migration_agent.pipeline.snapshot import build_intermediate
    normalized = {
        "source_system": "wordpress",
        "source_site_url": "https://x.com",
        "source_id": 1,
        "source_type": "post",
        "source_status": "publish",
        "source_url": "https://x.com/p/",
        "slug": "test-post",
        "title": "Test",
        "content_html": "<p>text</p>",
        "author": {"source_id": 5, "name": "Joan", "slug": "joan", "email": None, "bio": "", "avatar_url": None},
        "dates": {},
        "seo": {},
    }
    item = build_intermediate(normalized, "batch-test")
    assert item.author is not None
    assert item.author.mapping_status == "create"


def test_author_without_name_is_pending(tmp_path):
    """Autor sense nom ha de quedar mapping_status='pending'."""
    from migration_agent.pipeline.snapshot import build_intermediate
    normalized = {
        "source_system": "wordpress",
        "source_site_url": "https://x.com",
        "source_id": 1,
        "source_type": "post",
        "source_status": "publish",
        "source_url": "https://x.com/p/",
        "slug": "test-post",
        "title": "Test",
        "content_html": "<p>text</p>",
        "author": {"source_id": 5, "name": None, "slug": None, "email": None, "bio": "", "avatar_url": None},
        "dates": {},
        "seo": {},
    }
    item = build_intermediate(normalized, "batch-test")
    assert item.author is not None
    assert item.author.mapping_status == "pending"


def test_validate_author_create_no_warning():
    """Autor amb mapping_status='create' no ha de generar AUTHOR_PENDING."""
    from migration_agent.pipeline.validate import validate
    from migration_agent.models.intermediate import AuthorRef, Integrity, Routing, SourceInfo, ContentBody
    item = IntermediateItem(
        import_batch_id="b",
        extracted_at="2026-04-27T10:00:00Z",
        source=SourceInfo(system="wordpress", site_url="https://x.com", id=1,
                          type="post", status="publish", url="https://x.com/p/"),
        routing=Routing(slug="p", path="/p/", legacy_url="https://x.com/p/", desired_url="/p/"),
        content=ContentBody(title="T", blocks=[{"type": "paragraph", "data": {"text": "x"}, "legacy": False}]),
        author=AuthorRef(source_id=5, name="Joan", slug="joan", mapping_status="create"),
        seo=SeoMetadata(title="T", description="D"),
        dates=Dates(published_at="2026-04-27T10:00:00Z"),
        integrity=Integrity(extracted_at="2026-04-27T10:00:00Z"),
    )
    result = validate(item, {})
    assert "AUTHOR_PENDING" not in result.import_state.warnings
