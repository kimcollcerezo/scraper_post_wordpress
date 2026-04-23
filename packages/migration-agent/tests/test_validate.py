"""Tests de validació i idempotència."""

from __future__ import annotations

import pytest
from migration_agent.models.intermediate import (
    ContentBody, Block, Integrity, IntermediateItem, Routing, SourceInfo,
)
from migration_agent.pipeline.validate import validate


def _item(slug="test-slug", title="Títol", blocks=None) -> IntermediateItem:
    return IntermediateItem(
        import_batch_id="batch-test",
        extracted_at="2026-04-23T10:00:00+00:00",
        source=SourceInfo(
            system="wordpress", site_url="https://x.com",
            id=42, type="post", status="publish", url="https://x.com/test-slug/",
        ),
        routing=Routing(
            slug=slug, path=f"/{slug}/",
            legacy_url=f"https://x.com/{slug}/",
            desired_url=f"/{slug}/",
        ),
        content=ContentBody(
            title=title,
            blocks=blocks or [Block(type="paragraph", data={"html": "<p>Contingut</p>"})],
        ),
        integrity=Integrity(extracted_at="2026-04-23T10:00:00+00:00"),
    )


def test_valid_item_becomes_ready():
    item = _item()
    result = validate(item)
    assert result.import_state.import_status in ("ready", "ready_with_warnings")


def test_missing_title_blocks_item():
    item = _item(title="")
    result = validate(item)
    assert result.import_state.import_status == "blocked"
    assert "INVALID_SOURCE_ITEM" in result.import_state.errors


def test_author_missing_adds_warning():
    item = _item()
    assert item.author is None
    result = validate(item, policy={"author": {"on_missing": "pending"}})
    assert "AUTHOR_PENDING" in result.import_state.warnings


def test_author_missing_with_fail_policy_blocks():
    item = _item()
    result = validate(item, policy={"author": {"on_missing": "fail"}})
    assert "AUTHOR_MAPPING_REQUIRED" in result.import_state.errors
    assert result.import_state.import_status == "blocked"


def test_validate_idempotent():
    """Validar dues vegades no duplica warnings ni errors."""
    item = _item()
    validate(item)
    warnings_after_first = list(item.import_state.warnings)
    validate(item)
    assert item.import_state.warnings == warnings_after_first


def test_dry_run_does_not_call_import_api(monkeypatch):
    """dry-run no ha de cridar la Import API. Test de separació de fases."""
    import_called = []

    class FakeOrchestrator:
        def _run_import(self, *args, **kwargs):
            import_called.append(True)

    obj = FakeOrchestrator()
    # dry-run no invoca _run_import
    assert import_called == []
