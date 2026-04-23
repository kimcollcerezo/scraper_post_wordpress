"""Tests del media URL rewriting — ADR-0006."""

from __future__ import annotations

from migration_agent.pipeline.rewrite import (
    build_url_map,
    rewrite_blocks,
    rewrite_item_urls,
    _rewrite_html_urls,
)
from migration_agent.models.intermediate import (
    Block,
    ContentBody,
    Dates,
    Integrity,
    IntermediateItem,
    MediaRef,
    Routing,
    SeoMetadata,
    SourceInfo,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_item(blocks: list[dict] | None = None) -> IntermediateItem:
    return IntermediateItem(
        import_batch_id="batch-rw",
        extracted_at="2026-04-24T10:00:00Z",
        source=SourceInfo(
            system="wordpress",
            site_url="https://old.com",
            id=1,
            type="post",
            status="publish",
            url="https://old.com/post/",
        ),
        routing=Routing(
            slug="post",
            path="/post/",
            legacy_url="https://old.com/post/",
            desired_url="/post/",
        ),
        content=ContentBody(
            title="Post",
            blocks=[Block(**b) for b in (blocks or [])],
        ),
        seo=SeoMetadata(title="Post", description="Desc"),
        dates=Dates(published_at="2026-04-24T10:00:00Z"),
        integrity=Integrity(extracted_at="2026-04-24T10:00:00Z"),
    )


OLD = "https://old.com/wp-content/uploads/img.jpg"
NEW = "https://cdn.despertare.com/media/img.jpg"
URL_MAP = {OLD: NEW}


# ── Tests build_url_map ────────────────────────────────────────────────────────

def test_build_url_map_hero():
    item = _make_item()
    item.hero = MediaRef(source_url=OLD, role="hero", new_url=NEW)
    m = build_url_map(item)
    assert m[OLD] == NEW

def test_build_url_map_media_list():
    item = _make_item()
    item.media = [MediaRef(source_url=OLD, role="inline", new_url=NEW)]
    m = build_url_map(item)
    assert m[OLD] == NEW

def test_build_url_map_no_new_url():
    item = _make_item()
    item.hero = MediaRef(source_url=OLD, role="hero")  # new_url=None
    m = build_url_map(item)
    assert OLD not in m

def test_build_url_map_empty():
    item = _make_item()
    assert build_url_map(item) == {}


# ── Tests rewrite_blocks — image ───────────────────────────────────────────────

def test_rewrite_image_block_url():
    item = _make_item(blocks=[
        {"type": "image", "data": {"url": OLD, "alt": "foto"}, "legacy": False}
    ])
    n, pending = rewrite_blocks(item, URL_MAP)
    assert n == 1
    assert item.content.blocks[0].data["url"] == NEW
    assert pending == []

def test_rewrite_image_block_src_key():
    item = _make_item(blocks=[
        {"type": "image", "data": {"src": OLD}, "legacy": False}
    ])
    n, pending = rewrite_blocks(item, URL_MAP)
    assert n == 1
    assert item.content.blocks[0].data["url"] == NEW
    assert "src" not in item.content.blocks[0].data

def test_rewrite_image_block_unknown_url_goes_pending():
    item = _make_item(blocks=[
        {"type": "image", "data": {"url": "https://other.com/img.jpg"}, "legacy": False}
    ])
    n, pending = rewrite_blocks(item, URL_MAP)
    assert n == 0
    assert "https://other.com/img.jpg" in pending


# ── Tests rewrite_blocks — gallery ────────────────────────────────────────────

def test_rewrite_gallery_block():
    item = _make_item(blocks=[
        {"type": "gallery", "data": {"images": [{"url": OLD, "alt": "a"}]}, "legacy": False}
    ])
    n, pending = rewrite_blocks(item, URL_MAP)
    assert n == 1
    assert item.content.blocks[0].data["images"][0]["url"] == NEW

def test_rewrite_gallery_partial():
    other = "https://other.com/other.jpg"
    item = _make_item(blocks=[
        {"type": "gallery", "data": {"images": [
            {"url": OLD},
            {"url": other},
        ]}, "legacy": False}
    ])
    n, pending = rewrite_blocks(item, URL_MAP)
    assert n == 1
    assert other in pending


# ── Tests rewrite_blocks — raw_html ───────────────────────────────────────────

def test_rewrite_raw_html_block():
    html = f'<img src="{OLD}" alt="x">'
    item = _make_item(blocks=[
        {"type": "raw_html", "data": {"html": html}, "legacy": True}
    ])
    n, pending = rewrite_blocks(item, URL_MAP)
    assert n == 1
    assert NEW in item.content.blocks[0].data["html"]

def test_rewrite_raw_html_no_match():
    html = '<p>Hello world</p>'
    item = _make_item(blocks=[
        {"type": "raw_html", "data": {"html": html}, "legacy": True}
    ])
    n, pending = rewrite_blocks(item, URL_MAP)
    assert n == 0


# ── Tests _rewrite_html_urls ───────────────────────────────────────────────────

def test_rewrite_html_replaces_url():
    html = f'<img src="{OLD}">'
    new_html, n, pending = _rewrite_html_urls(html, URL_MAP)
    assert n == 1
    assert NEW in new_html
    assert pending == []

def test_rewrite_html_pending_external_src():
    ext = "https://external.com/img.jpg"
    html = f'<img src="{ext}">'
    new_html, n, pending = _rewrite_html_urls(html, URL_MAP)
    assert n == 0
    assert ext in pending

def test_rewrite_html_multiple_occurrences():
    html = f'<img src="{OLD}"><img src="{OLD}">'
    new_html, n, _ = _rewrite_html_urls(html, URL_MAP)
    assert n == 1  # replace compta 1 substitució per URL única
    assert new_html.count(NEW) == 2


# ── Tests rewrite_item_urls ────────────────────────────────────────────────────

def test_rewrite_item_urls_full():
    item = _make_item(blocks=[
        {"type": "image", "data": {"url": OLD}, "legacy": False}
    ])
    item.hero = MediaRef(source_url=OLD, role="hero", new_url=NEW)
    result = rewrite_item_urls(item)
    assert result["rewritten"] == 1
    assert result["pending_count"] == 0
    assert "MEDIA_REWRITE_PENDING" not in item.import_state.warnings

def test_rewrite_item_urls_pending_adds_warning():
    ext = "https://external.com/img.jpg"
    item = _make_item(blocks=[
        {"type": "image", "data": {"url": ext}, "legacy": False}
    ])
    item.hero = MediaRef(source_url=OLD, role="hero", new_url=NEW)
    result = rewrite_item_urls(item)
    assert result["pending_count"] == 1
    assert "MEDIA_REWRITE_PENDING" in item.import_state.warnings

def test_rewrite_item_urls_no_map_noop():
    item = _make_item(blocks=[
        {"type": "image", "data": {"url": OLD}, "legacy": False}
    ])
    result = rewrite_item_urls(item)
    assert result["rewritten"] == 0
    assert result["pending_count"] == 0
    # URL no tocada
    assert item.content.blocks[0].data["url"] == OLD

def test_rewrite_item_urls_paragraph_untouched():
    """Els blocs paragraph no tenen URLs — no s'han de modificar."""
    item = _make_item(blocks=[
        {"type": "paragraph", "data": {"text": f"See {OLD}"}, "legacy": False}
    ])
    item.hero = MediaRef(source_url=OLD, role="hero", new_url=NEW)
    result = rewrite_item_urls(item)
    # El text del paragraph no es reescriu (no és un block d'imatge)
    assert item.content.blocks[0].data["text"] == f"See {OLD}"
