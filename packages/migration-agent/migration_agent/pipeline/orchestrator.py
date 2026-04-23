"""Pipeline orchestrator — ADR-0004 / ADR-0008."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from migration_agent.adapters.base import SourceAdapter
from migration_agent.config.loader import load_import_policy, load_media_policy, load_sources
from migration_agent.logger import log
from migration_agent.models.batch import BatchReport
from migration_agent.models.intermediate import IntermediateItem
from migration_agent.pipeline.import_client import ImportApiClient
from migration_agent.pipeline.mappings import MappingResolver
from migration_agent.pipeline.media import CROP_SAFE, EXACT_FIT, FIT_WITH_BACKGROUND, AssetResult, process_item_media
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
        self._config_dir = config_dir
        self.policy = load_import_policy(config_dir)
        self._started_at = datetime.now(timezone.utc).isoformat()

        # Carregar MappingResolver (ADR-0010) — opcional si no existeix el directori
        _root = Path(__file__).resolve().parents[5]
        _mappings_dir = (config_dir or _root / "config") / "mappings"
        self._resolver = MappingResolver(_mappings_dir) if _mappings_dir.exists() else None

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

                # Fase 4 — Validate + mapping resolution (ADR-0010)
                item = validate(item, self.policy, resolver=self._resolver)

                # Fase 4b — Media normalization (dry-run inclòs: processa localment)
                assets_count = len(item.media) + (1 if item.hero else 0)
                report.assets_detected += assets_count
                if assets_count > 0:
                    media_policy = load_media_policy(self._config_dir)
                    all_sources = load_sources(self._config_dir)
                    source_cfg = (
                        all_sources.get("sources", {}).get(self.source_name)
                        or {"allowed_media_domains": None, "timeout_seconds": 20}
                    )
                    artifacts_base = _artifacts_dir() / self.batch_id / "media"
                    media_results_dict = process_item_media(
                        item, media_policy, source_cfg, artifacts_base, batch_id=self.batch_id
                    )
                    all_asset_results = (
                        media_results_dict.get("hero", []) + media_results_dict.get("media", [])
                    )
                    for ar in all_asset_results:
                        if ar.import_status == "imported":
                            report.assets_imported += 1
                        elif ar.import_status == "failed":
                            report.assets_failed += 1
                        if ar.adaptation_strategy == EXACT_FIT:
                            report.assets_exact_fit += 1
                        elif ar.adaptation_strategy == CROP_SAFE:
                            report.assets_crop_safe += 1
                        elif ar.adaptation_strategy == FIT_WITH_BACKGROUND:
                            report.assets_adapted_with_background += 1
                        elif ar.adaptation_strategy is not None:
                            report.assets_review_required += 1
                        for w in ar.warnings:
                            report.increment_warning(w)
                        for e in ar.errors:
                            report.increment_error(e)

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

        # Generar pending mappings file si n'hi ha (ADR-0010)
        if self._resolver is not None:
            self._resolver.write_pending(self.batch_id)

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
        """Import real via Import API de Despertare (ADR-0009).

        Seqüència per ítem:
          1. Authors
          2. Taxonomies (categories + tags)
          3. Media (hero + inline)
          4. Content
          5. Redirects (batch final)
        """
        policy = self.policy
        on_duplicate = policy.get("on_duplicate", "skip")
        import_as_status = policy.get("import_as_status", "draft")

        try:
            client = ImportApiClient.from_env()
        except RuntimeError as exc:
            log.error("import_api_client_init_failed", detail=str(exc), batch_id=self.batch_id)
            for item in items:
                item.set_status("failed")
                item.add_error("IMPORT_API_UNREACHABLE")
                report.total_failed += 1
            return report

        redirects: list[dict[str, str]] = []

        with client:
            for item in items:
                status = item.import_state.import_status
                if status in ("blocked", "failed"):
                    log.info(
                        "import_item_skipped",
                        batch_id=self.batch_id,
                        source_id=str(item.source.id),
                        reason=status,
                    )
                    report.total_skipped += 1
                    continue

                # 1. Author
                if item.author and item.author.name:
                    auth_result = client.import_author(item.author, self.batch_id)
                    if auth_result.author_id:
                        item.author.mapping_status = "complete"
                    elif auth_result.errors:
                        item.add_warning(f"AUTHOR_IMPORT_{auth_result.errors[0]}")

                # 2. Taxonomies
                for cat in item.taxonomies.categories:
                    r = client.import_taxonomy_term(cat, "category", self.batch_id)
                    if r.taxonomy_term_id:
                        cat.mapping_status = "complete"

                for tag in item.taxonomies.tags:
                    r = client.import_taxonomy_term(tag, "tag", self.batch_id)
                    if r.taxonomy_term_id:
                        tag.mapping_status = "complete"

                # 3. Media (hero)
                if item.hero and item.hero.source_url:
                    fake_asset = AssetResult(
                        source_url=item.hero.source_url,
                        mime_type=item.hero.mime_type,
                        width=item.hero.width,
                        height=item.hero.height,
                        hash=item.hero.hash,
                        import_status="imported",
                    )
                    media_r = client.import_media(item.hero, fake_asset, self.batch_id)
                    if media_r.media_asset_id:
                        item.hero.media_asset_id = media_r.media_asset_id
                        item.hero.new_url = media_r.storage_url
                        item.hero.import_status = media_r.result
                    elif media_r.errors:
                        item.add_warning(f"HERO_MEDIA_{media_r.errors[0]}")

                # 4. Content
                content_result = client.import_content(item, on_duplicate, import_as_status)

                if content_result.result in ("created", "updated"):
                    item.set_status("imported")
                    item.import_state.imported_at = datetime.now(timezone.utc).isoformat()
                    item.import_state.target_entity_id = content_result.content_item_id
                    item.import_state.target_url = content_result.target_url
                    report.total_imported += 1
                    report.assets_imported += 1 if item.hero else 0

                    # Redirect: legacy_url → target_url
                    if item.routing.legacy_url and content_result.target_url:
                        redirects.append({
                            "from": item.routing.legacy_url,
                            "to": content_result.target_url,
                            "type": "301",
                        })

                    for w in content_result.warnings:
                        item.add_warning(w)
                        report.increment_warning(w)

                    log.info(
                        "item_imported",
                        batch_id=self.batch_id,
                        source_id=str(item.source.id),
                        result=content_result.result,
                        content_item_id=content_result.content_item_id,
                        target_url=content_result.target_url,
                    )

                elif content_result.result == "skipped":
                    item.set_status("skipped")
                    report.total_skipped += 1
                    log.info(
                        "item_skipped",
                        batch_id=self.batch_id,
                        source_id=str(item.source.id),
                        reason="on_duplicate=skip",
                    )

                else:
                    item.set_status("failed")
                    for e in content_result.errors:
                        item.add_error(e)
                        report.increment_error(e)
                    report.total_failed += 1
                    log.error(
                        "item_import_failed",
                        batch_id=self.batch_id,
                        source_id=str(item.source.id),
                        errors=content_result.errors,
                    )

            # 5. Redirects — batch final
            if redirects:
                redir_result = client.import_redirects(redirects, self.batch_id)
                report.redirects_suggested = len(redirects)
                log.info(
                    "redirects_imported",
                    batch_id=self.batch_id,
                    created=redir_result.get("created", 0),
                    skipped=redir_result.get("skipped", 0),
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
