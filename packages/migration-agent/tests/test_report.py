"""Tests de generació de BatchReport."""

from __future__ import annotations

from migration_agent.models.batch import BatchReport


def test_report_to_dict_structure():
    report = BatchReport(
        batch_id="abc-123",
        mode="dry-run",
        source_name="wp-test",
        source_system="wordpress",
        source_site_url="https://example.com",
        started_at="2026-04-23T10:00:00+00:00",
        finished_at="2026-04-23T10:01:00+00:00",
        duration_seconds=60.0,
        total_detected=10,
        total_importable=8,
        total_blocked=2,
    )
    d = report.to_dict()
    assert d["batch_id"] == "abc-123"
    assert d["mode"] == "dry-run"
    assert d["summary"]["total_detected"] == 10
    assert d["summary"]["total_importable"] == 8
    assert d["summary"]["total_blocked"] == 2


def test_report_increment_warning():
    report = BatchReport(
        batch_id="x", mode="dry-run", source_name="s",
        source_system="wordpress", source_site_url="https://x.com",
        started_at="2026-04-23T10:00:00+00:00",
    )
    report.increment_warning("SEO_INCOMPLETE")
    report.increment_warning("SEO_INCOMPLETE")
    report.increment_warning("AUTHOR_PENDING")
    assert report.warnings["SEO_INCOMPLETE"] == 2
    assert report.warnings["AUTHOR_PENDING"] == 1


def test_report_increment_error():
    report = BatchReport(
        batch_id="x", mode="dry-run", source_name="s",
        source_system="wordpress", source_site_url="https://x.com",
        started_at="2026-04-23T10:00:00+00:00",
    )
    report.increment_error("SLUG_COLLISION")
    assert report.errors["SLUG_COLLISION"] == 1
