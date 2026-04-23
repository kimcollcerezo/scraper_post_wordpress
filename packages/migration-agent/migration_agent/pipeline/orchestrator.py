"""Pipeline orchestrator — ADR-0004 / ADR-0008."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from migration_agent.adapters.base import SourceAdapter
from migration_agent.config.loader import load_import_policy
from migration_agent.logger import log
from migration_agent.models.batch import BatchReport
from migration_agent.models.intermediate import IntermediateItem
from migration_agent.pipeline.snapshot import build_intermediate, save_snapshot
from migration_agent.pipeline.transform import transform
from migration_agent.pipeline.validate import validate


def _artifacts_dir() -> Path:
    here = Path(__file__).resolve()
    return here.parents[5] / "artifacts" / "import-batches"


class Pipeline:
    """Orquestra les fases Extract → Snapshot → Transform → Validate → Import."""

    def __init__(
        self,
        *,
        adapter: SourceAdapter,
        source_name: str,
        mode: str,
        config_dir: Path | None = None,
        force_extract: bool = False,
        limit: int | None = None,
        ids: list[int] | None = None,
        post_types: list[str] | None = None,
        statuses: list[str] | None = None,
        published_after: str | None = None,
        modified_after: str | None = None,
        batch_id: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.source_name = source_name
        self.mode = mode
        self.force_extract = force_extract
        self.limit = limit
        self.ids = ids
        self.post_types = post_types
        self.statuses = statuses
        self.published_after = published_after
        self.modified_after = modified_after
        self.batch_id = batch_id or str(uuid.uuid4())
        self.policy = load_import_policy(config_dir)
        self._started_at = datetime.now(timezone.utc).isoformat()

    def run(self) -> BatchReport:
        log.info("batch_started", batch_id=self.batch_id, mode=self.mode, source=self.source_name)

        # Health check
        health = self.adapter.health_check()
        if not health.ok:
            raise RuntimeError(f"Source health check failed: {health.message}")

        report = BatchReport(
            batch_id=self.batch_id,
            mode=self.mode,
            source_name=self.source_name,
            source_system="wordpress",
            source_site_url="",
            started_at=self._started_at,
        )

        items: list[IntermediateItem] = []
        errors_jsonl: list[dict[str, Any]] = []
        warnings_jsonl: list[dict[str, Any]] = []

        # Fase 1+2 — Extract + Snapshot
        for raw in self.adapter.extract(
            post_types=self.post_types,
            statuses=self.statuses,
            limit=self.limit,
            ids=self.ids,
            published_after=self.published_after,
            modified_after=self.modified_after,
        ):
            report.total_detected += 1
            try:
                normalized = self.adapter.normalize(raw)
                if not report.source_site_url:
                    report.source_site_url = normalized.get("source_site_url", "")

                item = build_intermediate(normalized, self.batch_id)
                save_snapshot(item, force=self.force_extract)

                log.info(
                    "item_extracted",
                    batch_id=self.batch_id,
                    source_system=item.source.system,
                    source_id=str(item.source.id),
                )

                # Fase 3 — Transform
                item = transform(item, self.policy)

                # Fase 4 — Validate
                item = validate(item, self.policy)

                items.append(item)
                report.assets_detected += len(item.media) + (1 if item.hero else 0)

                status = item.import_state.import_status
                if status == "ready":
                    report.total_importable += 1
                elif status == "ready_with_warnings":
                    report.total_importable += 1
                    report.total_with_warnings += 1
                elif status == "pending_review":
                    report.total_pending_review += 1
                elif status == "blocked":
                    report.total_blocked += 1
                    report.items_blocked.append({
                        "source_id": str(item.source.id),
                        "errors": item.import_state.errors,
                    })

                for w in item.import_state.warnings:
                    report.increment_warning(w)
                for e in item.import_state.errors:
                    report.increment_error(e)

                if item.import_state.warnings:
                    warnings_jsonl.append({
                        "batch_id": self.batch_id,
                        "source_id": str(item.source.id),
                        "warnings": item.import_state.warnings,
                    })
                if item.import_state.errors:
                    errors_jsonl.append({
                        "batch_id": self.batch_id,
                        "source_id": str(item.source.id),
                        "errors": item.import_state.errors,
                    })

                # SEO tracking
                if not item.seo.canonical or item.seo.source == "derived":
                    report.seo_incomplete += 1

                log.info(
                    "item_validated",
                    batch_id=self.batch_id,
                    source_id=str(item.source.id),
                    status=status,
                    warnings=len(item.import_state.warnings),
                    errors=len(item.import_state.errors),
                )

            except Exception as exc:
                report.total_failed += 1
                source_id = str(raw.get("id", "unknown"))
                log.error(
                    "item_failed",
                    batch_id=self.batch_id,
                    source_id=source_id,
                    detail=str(exc),
                )
                errors_jsonl.append({
                    "batch_id": self.batch_id,
                    "source_id": source_id,
                    "errors": ["PIPELINE_EXCEPTION"],
                    "detail": str(exc),
                })

        # Fase 5 — Import (només si no és dry-run)
        if self.mode not in ("dry-run", "extract-only", "validate"):
            report = self._run_import(items, report)
        else:
            log.info("import_skipped", batch_id=self.batch_id, reason=f"mode={self.mode}")

        # Finalitzar report
        finished_at = datetime.now(timezone.utc).isoformat()
        report.finished_at = finished_at
        started = datetime.fromisoformat(self._started_at)
        finished = datetime.fromisoformat(finished_at)
        report.duration_seconds = (finished - started).total_seconds()

        log.info(
            "batch_completed",
            batch_id=self.batch_id,
            mode=self.mode,
            total_detected=report.total_detected,
            total_importable=report.total_importable,
            total_blocked=report.total_blocked,
            total_failed=report.total_failed,
            duration_seconds=report.duration_seconds,
        )

        self._save_artifacts(report, items, errors_jsonl, warnings_jsonl)
        return report

    def _run_import(self, items: list[IntermediateItem], report: BatchReport) -> BatchReport:
        """Import real — no implementat en MVP Sprint 1."""
        log.warn(
            "import_not_implemented",
            batch_id=self.batch_id,
            detail="Import API integration pending Sprint 2",
        )
        return report

    def _save_artifacts(
        self,
        report: BatchReport,
        items: list[IntermediateItem],
        errors: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> None:
        batch_dir = _artifacts_dir() / self.batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)

        # manifest.json
        manifest = {
            "batch_id": self.batch_id,
            "mode": self.mode,
            "source": self.source_name,
            "started_at": self._started_at,
            "finished_at": report.finished_at,
        }
        (batch_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # report.json
        (batch_dir / "report.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # items.jsonl
        with (batch_dir / "items.jsonl").open("w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item.import_state.model_dump(), ensure_ascii=False) + "\n")

        # errors.jsonl
        with (batch_dir / "errors.jsonl").open("w", encoding="utf-8") as f:
            for err in errors:
                f.write(json.dumps(err, ensure_ascii=False) + "\n")

        # warnings.jsonl
        with (batch_dir / "warnings.jsonl").open("w", encoding="utf-8") as f:
            for w in warnings:
                f.write(json.dumps(w, ensure_ascii=False) + "\n")

        log.info(
            "artifacts_saved",
            batch_id=self.batch_id,
            path=str(batch_dir),
        )
