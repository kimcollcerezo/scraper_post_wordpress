"""Tests de validació del schema intermedi."""

from __future__ import annotations

import pytest
from migration_agent.models.intermediate import IntermediateItem, SourceInfo, Routing, ContentBody, Integrity


def _make_item(**kwargs) -> IntermediateItem:
    defaults = dict(
        import_batch_id="test-batch-001",
        extracted_at="2026-04-23T10:00:00+00:00",
        source=SourceInfo(
            system="wordpress",
            site_url="https://example.com",
            id=1,
            type="post",
            status="publish",
            url="https://example.com/post-1/",
        ),
        routing=Routing(
            slug="post-1",
            path="/post-1/",
            legacy_url="https://example.com/post-1/",
            desired_url="/post-1/",
        ),
        content=ContentBody(title="Post de prova"),
        integrity=Integrity(extracted_at="2026-04-23T10:00:00+00:00"),
    )
    defaults.update(kwargs)
    return IntermediateItem(**defaults)


def test_intermediate_item_default_status():
    item = _make_item()
    assert item.import_state.import_status == "pending"


def test_intermediate_item_add_warning():
    item = _make_item()
    item.add_warning("SEO_INCOMPLETE")
    assert "SEO_INCOMPLETE" in item.import_state.warnings
    # No duplicar
    item.add_warning("SEO_INCOMPLETE")
    assert item.import_state.warnings.count("SEO_INCOMPLETE") == 1


def test_intermediate_item_add_error():
    item = _make_item()
    item.add_error("INVALID_SLUG")
    assert "INVALID_SLUG" in item.import_state.errors


def test_intermediate_item_set_status():
    item = _make_item()
    item.set_status("ready")
    assert item.import_state.import_status == "ready"


def test_intermediate_item_schema_version():
    item = _make_item()
    assert item.schema_version == "1.0"


def test_intermediate_item_serializable():
    item = _make_item()
    d = item.model_dump()
    assert d["source"]["system"] == "wordpress"
    assert d["routing"]["slug"] == "post-1"
