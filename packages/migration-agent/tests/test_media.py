"""Tests de media pipeline i adaptation strategies."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

from migration_agent.pipeline.media import (
    CROP_SAFE,
    EXACT_FIT,
    FIT_WITH_BACKGROUND,
    REVIEW_REQUIRED,
    _apply_crop_safe,
    _apply_exact_fit,
    _apply_fit_with_background,
    _compute_hash,
    _crop_loss,
    _detect_mime,
    _dominant_color,
    _hex_to_rgb,
    _parse_ratio,
    _policy_for_role,
    _ratio_ok,
    _ratio_str,
    detect_adaptation_strategy,
    process_asset,
    AssetResult,
)
from migration_agent.models.intermediate import MediaRef


# ── Fixtures d'imatge ──────────────────────────────────────────────────────────

def _make_image_bytes(w: int, h: int, color=(200, 100, 50)) -> bytes:
    img = Image.new("RGB", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_png_bytes(w: int, h: int) -> bytes:
    img = Image.new("RGB", (w, h), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Tests d'utilitat d'aspect ratio ───────────────────────────────────────────

def test_parse_ratio_colon():
    assert abs(_parse_ratio("4:3") - 4/3) < 0.001

def test_parse_ratio_decimal():
    assert abs(_parse_ratio("1.91:1") - 1.91) < 0.001

def test_ratio_ok_exact():
    assert _ratio_ok(1200, 900, 4/3) is True

def test_ratio_ok_within_tolerance():
    assert _ratio_ok(1210, 900, 4/3) is True

def test_ratio_ok_outside_tolerance():
    assert _ratio_ok(1920, 900, 4/3) is False

def test_ratio_str():
    assert _ratio_str(1200, 900) == "4:3"
    assert _ratio_str(1920, 1080) == "16:9"

def test_crop_loss_horizontal():
    # Imatge 3:2, target 4:3 → cal retallar amplada
    loss = _crop_loss(1200, 800, 4/3)
    assert 0 < loss < 0.30

def test_crop_loss_vertical():
    # Imatge molt vertical, target horitzontal
    loss = _crop_loss(400, 1200, 4/3)
    assert loss > 0.50  # Pèrdua gran

def test_hex_to_rgb():
    assert _hex_to_rgb("#f5f5f5") == (245, 245, 245)
    assert _hex_to_rgb("#fff") == (255, 255, 255)


# ── Tests detect_adaptation_strategy ──────────────────────────────────────────

def test_strategy_exact_fit():
    strategy, loss = detect_adaptation_strategy(
        1200, 900, 4/3, 1200, 900, 0.30, True
    )
    assert strategy == EXACT_FIT
    assert loss == 0.0

def test_strategy_crop_safe():
    # 3:2 cap a 4:3 → crop petit
    strategy, loss = detect_adaptation_strategy(
        1200, 800, 4/3, 800, 600, 0.30, True
    )
    assert strategy == CROP_SAFE
    assert loss < 0.30

def test_strategy_fit_with_background_vertical():
    # Imatge molt vertical → crop perdria molt
    strategy, loss = detect_adaptation_strategy(
        400, 1200, 4/3, 800, 600, 0.30, True
    )
    assert strategy == FIT_WITH_BACKGROUND
    assert loss > 0.30

def test_strategy_review_required_when_bg_disabled():
    strategy, _ = detect_adaptation_strategy(
        400, 1200, 4/3, 800, 600, 0.30, enable_background_fit=False
    )
    assert strategy == REVIEW_REQUIRED

def test_strategy_too_small():
    # Imatge petita amb ratio ok → fit_with_background (massa petita)
    strategy, _ = detect_adaptation_strategy(
        400, 300, 4/3, 1200, 900, 0.30, True
    )
    assert strategy == FIT_WITH_BACKGROUND


# ── Tests de generació de variants ────────────────────────────────────────────

def test_apply_exact_fit_dimensions():
    img = Image.new("RGB", (1200, 900))
    result = _apply_exact_fit(img, 600, 450)
    assert result.width == 600
    assert result.height == 450

def test_apply_exact_fit_preserves_ratio():
    img = Image.new("RGB", (1600, 900))  # 16:9
    result = _apply_exact_fit(img, 1200, 900)  # target 4:3
    # Ha de caber dins 1200x900
    assert result.width <= 1200
    assert result.height <= 900

def test_apply_crop_safe_dimensions():
    img = Image.new("RGB", (1200, 800))  # 3:2
    result = _apply_crop_safe(img, 1200, 900)  # target 4:3
    assert result.width == 1200
    assert result.height == 900

def test_apply_fit_with_background_blur_dimensions():
    img = Image.new("RGB", (400, 1200), color=(200, 100, 50))
    canvas, bg_type = _apply_fit_with_background(img, 1200, 900, "blur", "#f5f5f5")
    assert canvas.width == 1200
    assert canvas.height == 900
    assert bg_type == "blur"

def test_apply_fit_with_background_color_dominant():
    img = Image.new("RGB", (400, 1200), color=(200, 100, 50))
    canvas, bg_type = _apply_fit_with_background(img, 1200, 900, "color_dominant", "#f5f5f5")
    assert canvas.width == 1200
    assert canvas.height == 900
    assert bg_type == "color_dominant"

def test_apply_fit_with_background_project_color():
    img = Image.new("RGB", (400, 1200), color=(200, 100, 50))
    canvas, bg_type = _apply_fit_with_background(img, 1200, 900, "project_color", "#aabbcc")
    assert canvas.width == 1200
    assert canvas.height == 900
    assert bg_type == "project_color"


# ── Tests MIME i hash ──────────────────────────────────────────────────────────

def test_detect_mime_jpeg():
    data = _make_image_bytes(100, 100)
    mime = _detect_mime(data)
    assert mime == "image/jpeg"

def test_detect_mime_png():
    data = _make_png_bytes(100, 100)
    mime = _detect_mime(data)
    assert mime == "image/png"

def test_detect_mime_svg():
    data = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    mime = _detect_mime(data)
    assert mime == "image/svg+xml"

def test_compute_hash_deterministic():
    data = b"hello world"
    h1 = _compute_hash(data)
    h2 = _compute_hash(data)
    assert h1 == h2
    assert h1.startswith("sha256:")

def test_compute_hash_different_data():
    assert _compute_hash(b"a") != _compute_hash(b"b")


# ── Tests process_asset (amb mock de descàrrega) ──────────────────────────────

def _make_media_ref(url: str) -> MediaRef:
    return MediaRef(source_url=url, role="hero")


def _base_policy():
    return {
        "hero": {
            "aspect_ratio": "4:3",
            "min_width": 800,
            "min_height": 600,
            "variants": [{"name": "hero", "width": 800, "height": 600}],
        },
        "formats_allowed": ["jpg", "jpeg", "png", "webp", "gif", "svg"],
        "max_bytes_default": 10 * 1024 * 1024,
        "adaptation": {
            "enable_background_fit": True,
            "default_background": "blur",
            "crop_loss_threshold": 0.30,
            "fallback_background_color": "#f5f5f5",
        },
    }


def _base_source_config():
    return {"allowed_media_domains": None, "timeout_seconds": 10}


def test_process_asset_exact_fit(tmp_path):
    data = _make_image_bytes(1200, 900)  # 4:3 exacte
    media_ref = _make_media_ref("https://example.com/img.jpg")
    with patch("migration_agent.pipeline.media._download", return_value=data):
        with patch("migration_agent.pipeline.media._seen_hashes", {}):
            result = process_asset(
                media_ref, _base_policy(), _base_source_config(), tmp_path, role="hero"
            )
    assert result.import_status == "imported"
    assert result.adaptation_strategy == EXACT_FIT
    assert len(result.variants) == 1
    assert "MEDIA_ADAPTED_WITH_BACKGROUND" not in result.warnings


def test_process_asset_fit_with_background(tmp_path):
    data = _make_image_bytes(400, 1200)  # molt vertical
    media_ref = _make_media_ref("https://example.com/vertical.jpg")
    with patch("migration_agent.pipeline.media._download", return_value=data):
        with patch("migration_agent.pipeline.media._seen_hashes", {}):
            result = process_asset(
                media_ref, _base_policy(), _base_source_config(), tmp_path, role="hero"
            )
    assert result.adaptation_strategy == FIT_WITH_BACKGROUND
    assert "MEDIA_ADAPTED_WITH_BACKGROUND" in result.warnings
    assert len(result.variants) == 1
    variant = result.variants[0]
    assert variant.padding_applied is True
    assert variant.original_aspect_ratio is not None


def test_process_asset_download_failed(tmp_path):
    media_ref = _make_media_ref("https://example.com/missing.jpg")
    with patch("migration_agent.pipeline.media._download", side_effect=Exception("timeout")):
        result = process_asset(
            media_ref, _base_policy(), _base_source_config(), tmp_path
        )
    assert result.import_status == "failed"
    assert "MEDIA_DOWNLOAD_FAILED" in result.errors


def test_process_asset_invalid_mime(tmp_path):
    media_ref = _make_media_ref("https://example.com/script.php")
    with patch("migration_agent.pipeline.media._download", return_value=b"<?php echo 1; ?>"):
        with patch("migration_agent.pipeline.media._seen_hashes", {}):
            result = process_asset(
                media_ref, _base_policy(), _base_source_config(), tmp_path
            )
    assert result.import_status == "failed"
    assert "MEDIA_POLICY_VIOLATION" in result.errors


def test_process_asset_deduplication(tmp_path):
    data = _make_image_bytes(1200, 900)
    h = _compute_hash(data)
    media_ref = _make_media_ref("https://example.com/img.jpg")
    fake_seen = {h: "https://example.com/img.jpg"}
    with patch("migration_agent.pipeline.media._download", return_value=data):
        with patch("migration_agent.pipeline.media._seen_hashes", fake_seen):
            result = process_asset(
                media_ref, _base_policy(), _base_source_config(), tmp_path, role="hero"
            )
    assert result.deduplicated is True
    assert result.import_status == "deduplicated"


def test_process_asset_no_source_url(tmp_path):
    media_ref = MediaRef(source_url="", role="hero")
    result = process_asset(media_ref, _base_policy(), _base_source_config(), tmp_path)
    assert result.import_status == "failed"
    assert "MEDIA_DOWNLOAD_FAILED" in result.errors


# ── Tests _policy_for_role amb content_types ───────────────────────────────────

def _policy_with_content_types() -> dict:
    return {
        "formats_allowed": ["jpg", "jpeg", "png", "webp", "gif", "svg"],
        "max_bytes_default": 10 * 1024 * 1024,
        "adaptation": {
            "enable_background_fit": True,
            "default_background": "blur",
            "crop_loss_threshold": 0.30,
            "fallback_background_color": "#f5f5f5",
        },
        "content_types": {
            "post": {
                "hero": {
                    "aspect_ratio": "4:3",
                    "min_width": 1200,
                    "min_height": 900,
                    "variants": [{"name": "hero", "width": 1200, "height": 900}],
                },
                "content_image": {
                    "variants": [{"name": "full", "width": 1200, "height": 0}],
                },
            },
            "page": {
                "hero": {
                    "aspect_ratio": "16:9",
                    "min_width": 1920,
                    "min_height": 1080,
                    "variants": [{"name": "hero_full", "width": 1920, "height": 1080}],
                },
                "content_image": {
                    "variants": [{"name": "full", "width": 1440, "height": 0}],
                },
            },
        },
        "hero": {
            "aspect_ratio": "4:3",
            "min_width": 800,
            "min_height": 600,
            "variants": [{"name": "hero_generic", "width": 800, "height": 600}],
        },
    }


def test_policy_for_role_post_hero():
    policy = _policy_with_content_types()
    p = _policy_for_role("hero", policy, content_type="post")
    assert p is not None
    assert p["aspect_ratio"] == "4:3"
    assert p["variants"][0]["name"] == "hero"


def test_policy_for_role_page_hero():
    policy = _policy_with_content_types()
    p = _policy_for_role("hero", policy, content_type="page")
    assert p is not None
    assert p["aspect_ratio"] == "16:9"
    assert p["variants"][0]["name"] == "hero_full"


def test_policy_for_role_post_content_image():
    policy = _policy_with_content_types()
    p = _policy_for_role("content_image", policy, content_type="post")
    assert p is not None
    assert p["variants"][0]["width"] == 1200


def test_policy_for_role_page_content_image():
    policy = _policy_with_content_types()
    p = _policy_for_role("content_image", policy, content_type="page")
    assert p is not None
    assert p["variants"][0]["width"] == 1440


def test_policy_for_role_inline_maps_to_content_image():
    policy = _policy_with_content_types()
    p = _policy_for_role("inline", policy, content_type="post")
    assert p is not None
    assert p["variants"][0]["name"] == "full"


def test_policy_for_role_unknown_type_fallback_to_generic():
    """Tipus desconegut (custom post type) cau al rol genèric de l'arrel."""
    policy = _policy_with_content_types()
    p = _policy_for_role("hero", policy, content_type="custom_cpt")
    assert p is not None
    assert p["variants"][0]["name"] == "hero_generic"


def test_policy_for_role_no_content_type_fallback():
    """Sense content_type, s'usa el rol genèric."""
    policy = _policy_with_content_types()
    p = _policy_for_role("hero", policy, content_type="")
    assert p is not None
    assert p["variants"][0]["name"] == "hero_generic"


def test_policy_for_role_attachment_returns_none():
    policy = _policy_with_content_types()
    assert _policy_for_role("attachment", policy, content_type="post") is None


def test_process_asset_uses_content_type(tmp_path):
    """process_asset amb content_type='page' usa la política de page."""
    data = _make_image_bytes(1920, 1080)  # 16:9 perfecte per page.hero
    policy = _policy_with_content_types()
    media_ref = MediaRef(source_url="https://example.com/img.jpg", role="hero")
    with patch("migration_agent.pipeline.media._download", return_value=data):
        with patch("migration_agent.pipeline.media._seen_hashes", {}):
            result = process_asset(
                media_ref, policy, _base_source_config(), tmp_path,
                role="hero", content_type="page",
            )
    assert result.import_status == "imported"
    assert len(result.variants) == 1
    assert result.variants[0].name == "hero_full"
