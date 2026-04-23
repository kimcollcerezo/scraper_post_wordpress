"""Tests de SEO validation — ADR-0012."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from migration_agent.seo.crawler import CrawlResult, crawl_url, _domain
from migration_agent.seo.validator import (
    SeoValidationReport,
    diff_sitemaps,
    validate_item,
    validate_redirect,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _source() -> CrawlResult:
    return CrawlResult(
        url="https://old.com/post/",
        status_code=200,
        final_url="https://old.com/post/",
        title="Títol del post",
        meta_description="Descripció del post amb contingut adequat.",
        canonical="https://old.com/post/",
        robots="index, follow",
        og_title="Títol del post",
        og_description="Descripció",
        og_image="https://old.com/img.jpg",
        og_url="https://old.com/post/",
        og_type="article",
        h1="Títol del post",
        h1_count=1,
        images_with_alt=3,
        images_without_alt=0,
    )


def _target_ok() -> CrawlResult:
    return CrawlResult(
        url="https://new.com/post/",
        status_code=200,
        final_url="https://new.com/post/",
        title="Títol del post",
        meta_description="Descripció del post amb contingut adequat.",
        canonical="https://new.com/post/",
        robots="index, follow",
        og_title="Títol del post",
        og_description="Descripció",
        og_image="https://cdn.new.com/img.jpg",
        og_url="https://new.com/post/",
        og_type="article",
        h1="Títol del post",
        h1_count=1,
        images_with_alt=3,
        images_without_alt=0,
    )


# ── Tests validate_item ────────────────────────────────────────────────────────

def test_validate_item_ok():
    iv = validate_item(_source(), _target_ok())
    assert iv.status == "ok"
    assert iv.errors == []
    assert iv.checks["url_accessible"] is True
    assert iv.checks["title_preserved"] is True
    assert iv.checks["h1_present"] is True


def test_validate_item_url_not_accessible():
    target = _target_ok()
    target.status_code = 404
    iv = validate_item(_source(), target)
    assert iv.status == "error"
    assert "url_not_accessible" in iv.errors


def test_validate_item_noindex_unexpected():
    source = _source()
    source.robots = "index, follow"
    target = _target_ok()
    target.robots = "noindex, follow"
    iv = validate_item(source, target)
    assert "noindex_unexpected" in iv.errors


def test_validate_item_title_missing():
    target = _target_ok()
    target.title = None
    iv = validate_item(_source(), target)
    assert "title_missing" in iv.warnings
    assert iv.status in ("warning", "error")


def test_validate_item_title_too_long():
    target = _target_ok()
    target.title = "A" * 61
    iv = validate_item(_source(), target)
    assert "title_too_long" in iv.warnings


def test_validate_item_title_changed():
    target = _target_ok()
    target.title = "Títol diferent"
    iv = validate_item(_source(), target)
    assert "title_changed" in iv.warnings
    assert iv.checks["title_preserved"] is False


def test_validate_item_meta_description_missing():
    target = _target_ok()
    target.meta_description = None
    iv = validate_item(_source(), target)
    assert "meta_description_missing" in iv.warnings


def test_validate_item_meta_description_too_long():
    target = _target_ok()
    target.meta_description = "X" * 161
    iv = validate_item(_source(), target)
    assert "meta_description_too_long" in iv.warnings


def test_validate_item_canonical_different():
    target = _target_ok()
    target.canonical = "https://other.com/post/"
    iv = validate_item(_source(), target)
    assert "canonical_different_from_target" in iv.warnings


def test_validate_item_canonical_points_to_old_domain():
    target = _target_ok()
    target.canonical = "https://old.com/post/"  # domini antic
    iv = validate_item(_source(), target)
    assert "canonical_points_to_old_domain" in iv.errors


def test_validate_item_og_image_missing():
    target = _target_ok()
    target.og_image = None
    iv = validate_item(_source(), target)
    assert "og_image_missing" in iv.warnings


def test_validate_item_h1_missing():
    target = _target_ok()
    target.h1 = None
    target.h1_count = 0
    iv = validate_item(_source(), target)
    assert "h1_missing" in iv.warnings


def test_validate_item_multiple_h1():
    target = _target_ok()
    target.h1_count = 3
    iv = validate_item(_source(), target)
    assert "multiple_h1" in iv.warnings


def test_validate_item_images_without_alt():
    target = _target_ok()
    target.images_without_alt = 2
    iv = validate_item(_source(), target)
    assert "images_without_alt" in iv.warnings


def test_validate_item_redirect_loop():
    target = _target_ok()
    target.redirect_chain = ["a", "b", "c", "d", "e", "f"]
    iv = validate_item(_source(), target)
    assert "redirect_loop" in iv.errors


# ── Tests diff_sitemaps ────────────────────────────────────────────────────────

def test_diff_sitemaps_all_present():
    src = ["https://old.com/a/", "https://old.com/b/"]
    dst = ["https://new.com/a/", "https://new.com/b/"]
    url_map = {"https://old.com/a/": "https://new.com/a/",
               "https://old.com/b/": "https://new.com/b/"}
    result = diff_sitemaps(src, dst, url_map)
    assert result["missing_count"] == 0


def test_diff_sitemaps_missing():
    src = ["https://old.com/a/", "https://old.com/b/", "https://old.com/c/"]
    dst = ["https://new.com/a/", "https://new.com/b/"]
    url_map = {
        "https://old.com/a/": "https://new.com/a/",
        "https://old.com/b/": "https://new.com/b/",
        "https://old.com/c/": "https://new.com/c/",
    }
    result = diff_sitemaps(src, dst, url_map)
    assert result["missing_count"] == 1
    assert "https://old.com/c/" in result["missing_from_destination"]


def test_diff_sitemaps_new_in_dest():
    src = ["https://old.com/a/"]
    dst = ["https://new.com/a/", "https://new.com/extra/"]
    url_map = {"https://old.com/a/": "https://new.com/a/"}
    result = diff_sitemaps(src, dst, url_map)
    assert result["new_count"] == 1
    assert "https://new.com/extra/" in result["new_in_destination"]


def test_diff_sitemaps_no_url_map():
    src = ["https://same.com/a/"]
    dst = ["https://same.com/a/"]
    result = diff_sitemaps(src, dst)
    assert result["missing_count"] == 0


# ── Tests SeoValidationReport ──────────────────────────────────────────────────

def test_report_summary_all_ok():
    report = SeoValidationReport(batch_id="test-batch")
    iv = validate_item(_source(), _target_ok())
    report.items.append(iv)
    s = report.summary()
    assert s["total_urls"] == 1
    assert s["with_errors"] == 0
    assert s["accessible"] == 1


def test_report_summary_with_error():
    report = SeoValidationReport(batch_id="test-batch")
    target = _target_ok()
    target.status_code = 500
    iv = validate_item(_source(), target)
    report.items.append(iv)
    s = report.summary()
    assert s["with_errors"] == 1
    assert s["accessible"] == 0


def test_report_to_csv(tmp_path):
    report = SeoValidationReport(batch_id="test-batch")
    report.items.append(validate_item(_source(), _target_ok()))
    csv_content = report.to_csv()
    assert "source_url" in csv_content
    assert "https://old.com/post/" in csv_content


def test_report_save(tmp_path):
    report = SeoValidationReport(batch_id="test-batch")
    report.items.append(validate_item(_source(), _target_ok()))
    paths = report.save(tmp_path)
    assert paths["report"].exists()
    assert paths["csv"].exists()
    assert paths["summary"].exists()
    data = json.loads(paths["report"].read_text())
    assert data["batch_id"] == "test-batch"
    assert len(data["items"]) == 1


# ── Tests crawl_url (mockat) ───────────────────────────────────────────────────

def _make_html_response(html: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.url = MagicMock()
    resp.url.__str__ = lambda self: "https://example.com/post/"
    resp.history = []
    resp.headers = {"content-type": "text/html; charset=utf-8"}
    resp.text = html
    return resp


def test_crawl_url_extracts_title():
    html = "<html><head><title>My Title</title></head><body><h1>Heading</h1></body></html>"
    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=_make_html_response(html))

    with patch("migration_agent.seo.crawler.httpx.Client", return_value=mock_client):
        result = crawl_url("https://example.com/post/")

    assert result.title == "My Title"
    assert result.h1 == "Heading"
    assert result.h1_count == 1
    assert result.status_code == 200


def test_crawl_url_extracts_og():
    html = """<html><head>
    <meta property="og:title" content="OG Title">
    <meta property="og:image" content="https://cdn.com/img.jpg">
    </head><body></body></html>"""
    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=_make_html_response(html))

    with patch("migration_agent.seo.crawler.httpx.Client", return_value=mock_client):
        result = crawl_url("https://example.com/post/")

    assert result.og_title == "OG Title"
    assert result.og_image == "https://cdn.com/img.jpg"


def test_crawl_url_4xx_returns_error():
    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    resp = _make_html_response("", status=404)
    mock_client.get = MagicMock(return_value=resp)

    with patch("migration_agent.seo.crawler.httpx.Client", return_value=mock_client):
        result = crawl_url("https://example.com/missing/")

    assert result.status_code == 404
    assert result.error == "HTTP_404"


def test_crawl_url_request_error():
    import httpx
    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(side_effect=httpx.RequestError("timeout"))

    with patch("migration_agent.seo.crawler.httpx.Client", return_value=mock_client):
        result = crawl_url("https://example.com/post/")

    assert "REQUEST_ERROR" in (result.error or "")


# ── Tests _domain ──────────────────────────────────────────────────────────────

def test_domain_extraction():
    assert _domain("https://example.com/path/") == "example.com"
    assert _domain("http://sub.domain.com/") == "sub.domain.com"
    assert _domain("not-a-url") == ""
