"""Tests de transformació HTML → blocs."""

from __future__ import annotations

import pytest
from migration_agent.models.intermediate import (
    ContentBody, Integrity, IntermediateItem, Routing, SourceInfo,
)
from migration_agent.pipeline.transform import transform, _html_to_blocks


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
