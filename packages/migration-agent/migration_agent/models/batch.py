"""Batch report models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BatchReport:
    batch_id: str
    mode: str
    source_name: str
    source_system: str
    source_site_url: str
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None

    total_detected: int = 0
    total_importable: int = 0
    total_imported: int = 0
    total_skipped: int = 0
    total_with_warnings: int = 0
    total_pending_review: int = 0
    total_blocked: int = 0
    total_failed: int = 0

    assets_detected: int = 0
    assets_imported: int = 0
    assets_failed: int = 0

    slugs_preserved: int = 0
    slugs_conflicted: int = 0
    redirects_suggested: int = 0
    seo_incomplete: int = 0

    warnings: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    items_blocked: list[dict[str, Any]] = field(default_factory=list)

    def increment_warning(self, code: str) -> None:
        self.warnings[code] = self.warnings.get(code, 0) + 1

    def increment_error(self, code: str) -> None:
        self.errors[code] = self.errors.get(code, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "mode": self.mode,
            "source": {
                "name": self.source_name,
                "system": self.source_system,
                "site_url": self.source_site_url,
            },
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "summary": {
                "total_detected": self.total_detected,
                "total_importable": self.total_importable,
                "total_imported": self.total_imported,
                "total_skipped": self.total_skipped,
                "total_with_warnings": self.total_with_warnings,
                "total_pending_review": self.total_pending_review,
                "total_blocked": self.total_blocked,
                "total_failed": self.total_failed,
            },
            "assets": {
                "total_detected": self.assets_detected,
                "total_imported": self.assets_imported,
                "total_failed": self.assets_failed,
            },
            "seo": {
                "slugs_preserved": self.slugs_preserved,
                "slugs_conflicted": self.slugs_conflicted,
                "redirects_suggested": self.redirects_suggested,
                "seo_incomplete": self.seo_incomplete,
            },
            "warnings": self.warnings,
            "errors": self.errors,
            "items_blocked": self.items_blocked,
        }
