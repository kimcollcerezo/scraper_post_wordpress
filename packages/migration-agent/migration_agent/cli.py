"""CLI principal — Despertare Migration Engine. ADR-0008."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from migration_agent.config.loader import (
    get_source_config,
    load_env,
    load_import_policy,
    resolve_env,
)
from migration_agent.logger import log
from migration_agent.pipeline.orchestrator import Pipeline


VALID_MODES = [
    "dry-run",
    "extract-only",
    "import-staging",
    "import-production",
    "validate",
    "resume",
    "rollback-plan",
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m migration_agent.cli",
        description="Despertare Migration Engine",
    )
    p.add_argument(
        "--mode",
        required=True,
        choices=VALID_MODES,
        help="Mode d'execució",
    )
    p.add_argument("--source", required=False, help="Nom de la font a config/sources.yml")
    p.add_argument("--limit", type=int, help="Màxim d'ítems a processar")
    p.add_argument("--ids", help="IDs específics separats per coma: 1,2,3")
    p.add_argument("--post-type", help="Tipus de post: post,page")
    p.add_argument("--status", help="Estat: publish,draft")
    p.add_argument("--published-after", help="Filtre per data de publicació ISO8601")
    p.add_argument("--modified-after", help="Filtre per data de modificació ISO8601")
    p.add_argument("--batch-id", help="Batch ID per a resume")
    p.add_argument("--force-extract", action="store_true", help="Sobreescriure snapshots existents")
    p.add_argument(
        "--confirm-production",
        action="store_true",
        help="Confirmació explícita per a import-production",
    )
    p.add_argument("--config-dir", help="Path alternatiu al directori config/")
    return p


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = build_parser()
    args = parser.parse_args(argv)

    mode = args.mode
    config_dir = Path(args.config_dir) if args.config_dir else None

    # Validació de producció
    if mode == "import-production":
        if os.getenv("ENV") != "production":
            log.error("production_env_required", detail="Set ENV=production in .env")
            return 1
        if not args.confirm_production:
            log.error(
                "production_confirmation_required",
                detail="Use --confirm-production to proceed",
            )
            return 1

    # Modes que no requereixen source
    if mode in ("rollback-plan",) and not args.source and not args.batch_id:
        log.error("missing_argument", detail="--batch-id required for rollback-plan")
        return 1

    if not args.source and mode not in ("rollback-plan",):
        log.error("missing_argument", detail="--source is required")
        return 1

    source_name = args.source or ""

    try:
        source_config = get_source_config(source_name, config_dir)
    except (FileNotFoundError, ValueError) as exc:
        log.error("config_error", detail=str(exc))
        return 1

    # Construir adapter
    try:
        adapter = _build_adapter(source_name, source_config)
    except EnvironmentError as exc:
        log.error("env_error", detail=str(exc))
        return 1

    ids = [int(i.strip()) for i in args.ids.split(",")] if args.ids else None
    post_types = [t.strip() for t in args.post_type.split(",")] if args.post_type else None
    statuses = [s.strip() for s in args.status.split(",")] if args.status else None

    pipeline = Pipeline(
        adapter=adapter,
        source_name=source_name,
        mode=mode,
        config_dir=config_dir,
        force_extract=args.force_extract,
        limit=args.limit,
        ids=ids,
        post_types=post_types,
        statuses=statuses,
        published_after=args.published_after,
        modified_after=args.modified_after,
        batch_id=args.batch_id,
    )

    try:
        report = pipeline.run()
    except RuntimeError as exc:
        log.error("pipeline_error", detail=str(exc))
        return 1

    # Output resum a stdout
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))  # noqa: T201
    return 0


def _build_adapter(source_name: str, source_config: dict) -> object:
    adapter_type = source_config.get("type", "wordpress")
    if adapter_type == "wordpress":
        from migration_agent.adapters.wordpress import WordPressAdapter
        return WordPressAdapter(source_name, source_config)
    raise ValueError(f"Unknown adapter type: {adapter_type}")


if __name__ == "__main__":
    sys.exit(main())
