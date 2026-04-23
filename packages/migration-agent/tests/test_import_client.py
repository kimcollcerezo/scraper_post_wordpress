"""Tests del Import API client — ADR-0009."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from migration_agent.pipeline.import_client import (
    ImportApiClient,
    _build_content_payload,
    _filename_from_url,
)
from migration_agent.pipeline.media import AssetResult
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
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_item() -> IntermediateItem:
    return IntermediateItem(
        import_batch_id="batch-001",
        extracted_at="2026-04-24T10:00:00Z",
        source=SourceInfo(
            system="wordpress",
            site_url="https://example.com",
            id=42,
            type="post",
            status="publish",
            url="https://example.com/post-42/",
        ),
        routing=Routing(
            slug="post-42",
            path="/post-42/",
            legacy_url="https://example.com/post-42/",
            desired_url="/noticies/post-42/",
        ),
        content=ContentBody(
            title="Test Post",
            blocks=[{"type": "paragraph", "data": {"text": "Hello"}, "legacy": False}],
        ),
        seo=SeoMetadata(title="Test Post"),
        dates=Dates(published_at="2026-04-24T10:00:00Z"),
        integrity=Integrity(extracted_at="2026-04-24T10:00:00Z"),
    )


def _make_client() -> ImportApiClient:
    return ImportApiClient(base_url="https://api.despertare.test", token="test-token")


def _make_200(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    return resp


def _make_error(status: int, error: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"error": error}
    return resp


# ── Tests helpers ──────────────────────────────────────────────────────────────

def test_filename_from_url_normal():
    assert _filename_from_url("https://example.com/img/photo.jpg") == "photo.jpg"

def test_filename_from_url_with_querystring():
    assert _filename_from_url("https://cdn.example.com/img.png?v=2") == "img.png"

def test_filename_from_url_empty():
    assert _filename_from_url("https://example.com/") == "asset"  # fallback


# ── Tests build_content_payload ────────────────────────────────────────────────

def test_build_content_payload_structure():
    item = _make_item()
    payload = _build_content_payload(item, "skip", "draft")
    assert payload["batch_id"] == "batch-001"
    assert payload["source"]["system"] == "wordpress"
    assert payload["source"]["id"] == 42
    assert payload["routing"]["slug"] == "post-42"
    assert payload["on_duplicate"] == "skip"
    assert payload["import_as_status"] == "draft"
    assert isinstance(payload["content"]["blocks"], list)

def test_build_content_payload_no_hero():
    item = _make_item()
    payload = _build_content_payload(item, "skip", "draft")
    assert payload["hero"] is None

def test_build_content_payload_with_hero():
    item = _make_item()
    item.hero = MediaRef(source_url="https://example.com/img.jpg", role="hero", media_asset_id="uuid-media-1")
    payload = _build_content_payload(item, "skip", "draft")
    assert payload["hero"]["media_asset_id"] == "uuid-media-1"
    assert payload["hero"]["role"] == "hero"


# ── Tests import_content ───────────────────────────────────────────────────────

def test_import_content_created():
    client = _make_client()
    item = _make_item()
    resp = _make_200({
        "result": "created",
        "content_item_id": "cid-001",
        "content_localization_id": "clid-001",
        "content_version_id": "cvid-001",
        "target_url": "/noticies/post-42/",
        "warnings": [],
    })
    with patch.object(client._client, "post", return_value=resp):
        result = client.import_content(item)
    assert result.result == "created"
    assert result.content_item_id == "cid-001"
    assert result.target_url == "/noticies/post-42/"
    assert result.errors == []

def test_import_content_skipped_on_409_with_skip_policy():
    client = _make_client()
    item = _make_item()
    resp = _make_error(409, "DUPLICATE_ITEM")
    with patch.object(client._client, "post", return_value=resp):
        result = client.import_content(item, on_duplicate="skip")
    assert result.result == "skipped"
    assert result.errors == []

def test_import_content_fail_on_409_with_fail_policy():
    client = _make_client()
    item = _make_item()
    resp = _make_error(409, "DUPLICATE_ITEM")
    with patch.object(client._client, "post", return_value=resp):
        result = client.import_content(item, on_duplicate="fail")
    assert result.result == "failed"
    assert "DUPLICATE_ITEM" in result.errors

def test_import_content_api_unreachable():
    import httpx
    client = _make_client()
    item = _make_item()
    with patch.object(client._client, "post", side_effect=httpx.RequestError("timeout")):
        result = client.import_content(item)
    assert result.result == "failed"
    assert "IMPORT_API_UNREACHABLE" in result.errors


# ── Tests import_media ─────────────────────────────────────────────────────────

def test_import_media_success():
    client = _make_client()
    media_ref = MediaRef(source_url="https://example.com/img.jpg", role="hero")
    asset = AssetResult(
        source_url="https://example.com/img.jpg",
        mime_type="image/jpeg",
        width=1200,
        height=900,
        hash="sha256:abc123",
        size_bytes=50000,
        import_status="imported",
    )
    resp = _make_200({
        "result": "imported",
        "media_asset_id": "mid-001",
        "storage_url": "https://cdn.despertare.com/img.jpg",
        "variants": {},
    })
    with patch.object(client._client, "post", return_value=resp):
        result = client.import_media(media_ref, asset, "batch-001")
    assert result.result == "imported"
    assert result.media_asset_id == "mid-001"
    assert result.storage_url == "https://cdn.despertare.com/img.jpg"

def test_import_media_policy_violation():
    client = _make_client()
    media_ref = MediaRef(source_url="https://example.com/script.php", role="inline")
    asset = AssetResult(source_url="https://example.com/script.php", import_status="failed")
    resp = _make_error(422, "MEDIA_POLICY_VIOLATION")
    with patch.object(client._client, "post", return_value=resp):
        result = client.import_media(media_ref, asset, "batch-001")
    assert result.result == "failed"
    assert "MEDIA_POLICY_VIOLATION" in result.errors


# ── Tests import_author ────────────────────────────────────────────────────────

def test_import_author_created():
    client = _make_client()
    author = AuthorRef(source_id=5, name="Joan Doe", slug="joan-doe", email="joan@example.com")
    resp = _make_200({"result": "created", "author_id": "aid-001"})
    with patch.object(client._client, "post", return_value=resp):
        result = client.import_author(author, "batch-001")
    assert result.result == "created"
    assert result.author_id == "aid-001"

def test_import_author_merged():
    client = _make_client()
    author = AuthorRef(source_id=5, name="Joan Doe", slug="joan-doe")
    resp = _make_200({"result": "merged", "author_id": "aid-002"})
    with patch.object(client._client, "post", return_value=resp):
        result = client.import_author(author, "batch-001")
    assert result.result == "merged"


# ── Tests import_taxonomy_term ─────────────────────────────────────────────────

def test_import_taxonomy_term_created():
    client = _make_client()
    term = TaxonomyTerm(source_id=10, name="Cultura", slug="cultura")
    resp = _make_200({"result": "created", "taxonomy_term_id": "tid-001"})
    with patch.object(client._client, "post", return_value=resp):
        result = client.import_taxonomy_term(term, "category", "batch-001")
    assert result.result == "created"
    assert result.taxonomy_term_id == "tid-001"


# ── Tests from_env ─────────────────────────────────────────────────────────────

def test_from_env_missing_url(monkeypatch):
    monkeypatch.delenv("DESPERTARE_IMPORT_API_URL", raising=False)
    monkeypatch.delenv("DESPERTARE_IMPORT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="DESPERTARE_IMPORT_API_URL"):
        ImportApiClient.from_env()

def test_from_env_missing_token(monkeypatch):
    monkeypatch.setenv("DESPERTARE_IMPORT_API_URL", "https://api.test")
    monkeypatch.delenv("DESPERTARE_IMPORT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="DESPERTARE_IMPORT_TOKEN"):
        ImportApiClient.from_env()

def test_from_env_ok(monkeypatch):
    monkeypatch.setenv("DESPERTARE_IMPORT_API_URL", "https://api.test")
    monkeypatch.setenv("DESPERTARE_IMPORT_TOKEN", "tok-123")
    client = ImportApiClient.from_env()
    client.close()
    assert client._base_url == "https://api.test"
