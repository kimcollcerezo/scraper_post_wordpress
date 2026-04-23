"""Config loader — carrega sources.yml, import-policy.yml, media-policy.yml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def _project_root() -> Path:
    """Retorna el root del projecte (on viu el .env i config/)."""
    # Desde packages/migration-agent/ pujar 2 nivells
    here = Path(__file__).resolve()
    return here.parents[4]


def load_env(env_file: Path | None = None) -> None:
    """Carrega .env sense sobreescriure variables ja existents."""
    root = _project_root()
    path = env_file or root / ".env"
    load_dotenv(path, override=False)


def load_yaml(path: Path) -> dict[str, Any]:
    """Carrega un fitxer YAML i retorna dict. Falla explícitament si no existeix."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_sources(config_dir: Path | None = None) -> dict[str, Any]:
    root = _project_root()
    path = (config_dir or root / "config") / "sources.yml"
    return load_yaml(path)


def load_import_policy(config_dir: Path | None = None) -> dict[str, Any]:
    root = _project_root()
    path = (config_dir or root / "config") / "import-policy.yml"
    try:
        return load_yaml(path)
    except FileNotFoundError:
        return _default_import_policy()


def load_media_policy(config_dir: Path | None = None) -> dict[str, Any]:
    root = _project_root()
    path = (config_dir or root / "config") / "media-policy.yml"
    try:
        return load_yaml(path)
    except FileNotFoundError:
        return {}


def load_mappings(config_dir: Path | None = None) -> dict[str, Any]:
    root = _project_root()
    mappings_dir = (config_dir or root / "config") / "mappings"
    result: dict[str, Any] = {}
    for name in ("authors", "taxonomies", "slugs", "locales"):
        path = mappings_dir / f"{name}.yml"
        try:
            result[name] = load_yaml(path)
        except FileNotFoundError:
            result[name] = {}
    return result


def get_source_config(source_name: str, config_dir: Path | None = None) -> dict[str, Any]:
    sources = load_sources(config_dir)
    all_sources = sources.get("sources", {})
    if source_name not in all_sources:
        raise ValueError(
            f"Source '{source_name}' not found in sources.yml. "
            f"Available: {list(all_sources.keys())}"
        )
    return all_sources[source_name]


def _default_import_policy() -> dict[str, Any]:
    return {
        "on_duplicate": {"post": "skip", "page": "skip", "media": "skip"},
        "transform": {
            "raw_html_warning_threshold": 0.20,
            "raw_html_block_threshold": 0.50,
        },
        "import": {"default_status": "draft", "allow_ready_with_warnings": True},
        "author": {"on_missing": "pending"},
        "taxonomy": {"on_missing": "pending"},
    }


def resolve_env(value: str) -> str:
    """Resol un valor que pot ser un nom de variable d'entorn."""
    val = os.getenv(value)
    if val is None:
        raise EnvironmentError(f"Environment variable not set: {value}")
    return val
