"""Tests de càrrega de config."""

from __future__ import annotations

import pytest
import yaml
from pathlib import Path


def test_load_sources_example_is_valid_yaml(tmp_path):
    """El fitxer sources.example.yml és YAML vàlid."""
    here = Path(__file__).resolve()
    # tests/ → migration-agent/ → packages/ → project root
    example = here.parents[3] / "config" / "sources.example.yml"
    assert example.exists(), "config/sources.example.yml no existeix"
    data = yaml.safe_load(example.read_text())
    assert "sources" in data


def test_load_import_policy_defaults(tmp_path):
    """Si no existeix import-policy.yml, retorna política per defecte."""
    from migration_agent.config.loader import load_import_policy
    policy = load_import_policy(config_dir=tmp_path)
    assert policy["on_duplicate"]["post"] == "skip"
    assert policy["import"]["default_status"] == "draft"
    assert policy["transform"]["raw_html_warning_threshold"] == 0.20


def test_get_source_config_missing_source(tmp_path):
    """Llença ValueError si la font no existeix."""
    sources_yml = tmp_path / "sources.yml"
    sources_yml.write_text("sources:\n  other-source:\n    type: wordpress\n    base_url: https://x.com\n")
    from migration_agent.config.loader import get_source_config
    with pytest.raises(ValueError, match="not found"):
        get_source_config("non-existent", config_dir=tmp_path)


def test_get_source_config_found(tmp_path):
    """Retorna config correcta per a la font indicada."""
    sources_yml = tmp_path / "sources.yml"
    sources_yml.write_text(
        "sources:\n  wp-test:\n    type: wordpress\n    base_url: https://test.com\n"
    )
    from migration_agent.config.loader import get_source_config
    cfg = get_source_config("wp-test", config_dir=tmp_path)
    assert cfg["base_url"] == "https://test.com"
