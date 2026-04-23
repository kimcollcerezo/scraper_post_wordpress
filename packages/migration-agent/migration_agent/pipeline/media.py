"""Media pipeline — ADR-0006.

Fases:
  1. Descarregar original
  2. Detectar MIME real
  3. Validar format i mida
  4. Calcular SHA-256 i deduplicar
  5. Determinar adaptation_strategy
  6. Generar variants (exact_fit / crop_safe / fit_with_background)
  7. Metadades completes
  8. Log estructurat
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import filetype
import httpx
from PIL import Image, ImageFilter

from migration_agent.logger import log
from migration_agent.models.intermediate import IntermediateItem, MediaRef


# ── Tipus d'adaptation strategy ────────────────────────────────────────────────

EXACT_FIT = "exact_fit"
CROP_SAFE = "crop_safe"
FIT_WITH_BACKGROUND = "fit_with_background"
REVIEW_REQUIRED = "review_required"

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "image/gif", "image/svg+xml",
}

# ── Dataclasses de resultat ────────────────────────────────────────────────────

@dataclass
class VariantResult:
    name: str
    width: int
    height: int
    path: Path
    adaptation_strategy: str
    background_type: str | None = None
    original_aspect_ratio: str | None = None
    target_aspect_ratio: str | None = None
    padding_applied: bool = False
    crop_loss_estimated: float = 0.0


@dataclass
class AssetResult:
    source_url: str
    original_path: Path | None = None
    hash: str | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    import_status: str = "pending"
    adaptation_strategy: str | None = None
    variants: list[VariantResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    deduplicated: bool = False
    existing_hash: str | None = None


# ── Funcions d'utilitat d'aspect ratio ────────────────────────────────────────

def _parse_ratio(ratio_str: str) -> float:
    """Converteix '4:3' o '1.91:1' a float."""
    parts = ratio_str.split(":")
    if len(parts) == 2:
        return float(parts[0]) / float(parts[1])
    return float(ratio_str)


def _ratio_str(w: int, h: int) -> str:
    """Retorna ratio com a string simplificat."""
    try:
        f = Fraction(w, h).limit_denominator(20)
        return f"{f.numerator}:{f.denominator}"
    except Exception:
        return f"{w}:{h}"


def _crop_loss(src_w: int, src_h: int, target_ratio: float) -> float:
    """Calcula fracció d'àrea perduda en crop centrat per assolir target_ratio."""
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        # Cal retallar amplada
        new_w = src_h * target_ratio
        kept = (new_w * src_h) / (src_w * src_h)
    else:
        # Cal retallar alçada
        new_h = src_w / target_ratio
        kept = (src_w * new_h) / (src_w * src_h)
    return 1.0 - kept


def _ratio_ok(src_w: int, src_h: int, target_ratio: float, tolerance: float = 0.05) -> bool:
    src_ratio = src_w / src_h
    return abs(src_ratio - target_ratio) / target_ratio < tolerance


# ── Descàrrega ─────────────────────────────────────────────────────────────────

def _download(
    url: str,
    allowed_domains: list[str] | None,
    timeout: int,
    max_bytes: int,
) -> bytes:
    """Descarrega asset. Valida domini i mida màxima."""
    parsed = urllib.parse.urlparse(url)
    if allowed_domains:
        if not any(parsed.netloc.endswith(d) for d in allowed_domains):
            raise ValueError(f"Domain not in allowlist: {parsed.netloc}")

    with httpx.Client(timeout=timeout, verify=True, follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            content_length = int(resp.headers.get("content-length", 0))
            if content_length > max_bytes:
                raise ValueError(f"Content-Length {content_length} exceeds max {max_bytes}")
            chunks = []
            total = 0
            for chunk in resp.iter_bytes(chunk_size=65536):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Download exceeded max bytes: {max_bytes}")
                chunks.append(chunk)
    return b"".join(chunks)


# ── Validació MIME ─────────────────────────────────────────────────────────────

def _detect_mime(data: bytes) -> str | None:
    kind = filetype.guess(data)
    if kind:
        return kind.mime
    # SVG fallback (filetype no el detecta bé)
    if data.lstrip()[:5] in (b"<?xml", b"<svg "):
        return "image/svg+xml"
    return None


# ── Deduplicació (in-memory per sessió) ───────────────────────────────────────

_seen_hashes: dict[str, str] = {}  # hash → source_url


def _compute_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _check_duplicate(h: str, url: str) -> bool:
    if h in _seen_hashes:
        return True
    _seen_hashes[h] = url
    return False


# ── Adaptation strategy ────────────────────────────────────────────────────────

def detect_adaptation_strategy(
    src_w: int,
    src_h: int,
    target_ratio: float,
    target_min_w: int,
    target_min_h: int,
    crop_loss_threshold: float,
    enable_background_fit: bool,
) -> tuple[str, float]:
    """Retorna (strategy, crop_loss_estimated)."""
    too_small = src_w < target_min_w or src_h < target_min_h
    loss = _crop_loss(src_w, src_h, target_ratio)

    if _ratio_ok(src_w, src_h, target_ratio) and not too_small:
        return EXACT_FIT, 0.0
    elif loss < crop_loss_threshold and not too_small:
        return CROP_SAFE, loss
    elif enable_background_fit:
        return FIT_WITH_BACKGROUND, loss
    else:
        return REVIEW_REQUIRED, loss


# ── Generació de variants ──────────────────────────────────────────────────────

def _apply_exact_fit(img: Image.Image, tw: int, th: int) -> Image.Image:
    """Escala mantenint ratio i centra en canvas target."""
    img_ratio = img.width / img.height
    target_ratio = tw / th
    if img_ratio > target_ratio:
        new_w = tw
        new_h = int(tw / img_ratio)
    else:
        new_h = th
        new_w = int(th * img_ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)


def _apply_crop_safe(img: Image.Image, tw: int, th: int) -> Image.Image:
    """Crop centrat per assolir ratio target."""
    target_ratio = tw / th
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize((tw, th), Image.LANCZOS)


def _apply_fit_with_background(
    img: Image.Image,
    tw: int,
    th: int,
    background: str,
    fallback_color: str,
) -> tuple[Image.Image, str]:
    """
    Genera canvas tw×th amb background + imatge centrada.
    Retorna (canvas, background_type_used).
    """
    # Escalar imatge mantenint ratio per cabre dins canvas
    img_ratio = img.width / img.height
    target_ratio = tw / th
    if img_ratio > target_ratio:
        fg_w = tw
        fg_h = int(tw / img_ratio)
    else:
        fg_h = th
        fg_w = int(th * img_ratio)
    fg_w = max(fg_w, 1)
    fg_h = max(fg_h, 1)
    fg = img.resize((fg_w, fg_h), Image.LANCZOS)

    # Crear canvas
    canvas = Image.new("RGB", (tw, th), color=_hex_to_rgb(fallback_color))
    bg_used = "project_color"

    if background == "blur":
        try:
            bg = img.resize((tw, th), Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=20))
            canvas.paste(bg, (0, 0))
            bg_used = "blur"
        except Exception:
            pass  # Fallback a color
    elif background == "color_dominant":
        try:
            dominant = _dominant_color(img)
            canvas = Image.new("RGB", (tw, th), color=dominant)
            bg_used = "color_dominant"
        except Exception:
            pass

    # Centrar foreground
    x = (tw - fg_w) // 2
    y = (th - fg_h) // 2
    if fg.mode in ("RGBA", "LA"):
        canvas.paste(fg, (x, y), fg)
    else:
        canvas.paste(fg, (x, y))

    return canvas, bg_used


def _dominant_color(img: Image.Image) -> tuple[int, int, int]:
    """Color dominant via reducció a paleta mínima."""
    small = img.convert("RGB").resize((50, 50), Image.LANCZOS)
    quantized = small.quantize(colors=1)
    palette = quantized.getpalette()
    if palette:
        return (palette[0], palette[1], palette[2])
    return (245, 245, 245)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _save_variant(canvas: Image.Image, dest: Path, quality: int = 85) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fmt = dest.suffix.lower().lstrip(".")
    if fmt in ("jpg", "jpeg"):
        canvas.convert("RGB").save(dest, format="JPEG", quality=quality, optimize=True)
    elif fmt == "webp":
        canvas.save(dest, format="WEBP", quality=quality)
    elif fmt == "png":
        canvas.save(dest, format="PNG", optimize=True)
    else:
        canvas.convert("RGB").save(dest, format="JPEG", quality=quality)


def _sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\-.]", "_", name)
    return name[:120]


# ── Pipeline principal per asset ───────────────────────────────────────────────

def process_asset(
    media_ref: MediaRef,
    media_policy: dict[str, Any],
    source_config: dict[str, Any],
    storage_dir: Path,
    role: str = "inline",
    batch_id: str = "",
) -> AssetResult:
    """
    Processa un MediaRef complet:
    descàrrega → MIME → dedup → adaptation → variants
    """
    result = AssetResult(source_url=media_ref.source_url)
    url = media_ref.source_url

    if not url:
        result.import_status = "failed"
        result.errors.append("MEDIA_DOWNLOAD_FAILED")
        return result

    # Config
    allowed_domains = source_config.get("allowed_media_domains")
    timeout = source_config.get("timeout_seconds", 20)
    max_bytes = media_policy.get("max_bytes_default", 10 * 1024 * 1024)
    formats_allowed = set(media_policy.get("formats_allowed", ["jpg", "jpeg", "png", "webp", "gif", "svg"]))
    adaptation_cfg = media_policy.get("adaptation", {})
    enable_bg_fit = adaptation_cfg.get("enable_background_fit", True)
    default_bg = adaptation_cfg.get("default_background", "blur")
    crop_threshold = adaptation_cfg.get("crop_loss_threshold", 0.30)
    fallback_color = adaptation_cfg.get("fallback_background_color", "#f5f5f5")

    # Descàrrega
    try:
        data = _download(url, allowed_domains, timeout, max_bytes)
    except Exception as exc:
        log.warn("media_download_failed", source_url=url, batch_id=batch_id, detail=str(exc))
        result.import_status = "failed"
        result.errors.append("MEDIA_DOWNLOAD_FAILED")
        return result

    # MIME real
    mime = _detect_mime(data)
    result.mime_type = mime
    result.size_bytes = len(data)

    if not mime or mime not in ALLOWED_MIME_TYPES:
        log.warn("media_policy_violation", source_url=url, mime=mime, batch_id=batch_id)
        result.import_status = "failed"
        result.errors.append("MEDIA_POLICY_VIOLATION")
        return result

    # Deduplicació
    h = _compute_hash(data)
    result.hash = h
    if _check_duplicate(h, url):
        result.deduplicated = True
        result.existing_hash = h
        result.import_status = "deduplicated"
        log.info("asset_deduplicated", source_url=url, hash=h, batch_id=batch_id)
        return result

    # SVG: no processem amb Pillow
    if mime == "image/svg+xml":
        fname = _sanitize_filename(Path(urllib.parse.urlparse(url).path).name or "asset.svg")
        orig_path = storage_dir / "originals" / fname
        orig_path.parent.mkdir(parents=True, exist_ok=True)
        orig_path.write_bytes(data)
        result.original_path = orig_path
        result.adaptation_strategy = EXACT_FIT
        result.import_status = "imported"
        log.info("asset_imported", source_url=url, strategy=EXACT_FIT, batch_id=batch_id)
        return result

    # Obrir imatge
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        result.width = img.width
        result.height = img.height
    except Exception as exc:
        result.import_status = "failed"
        result.errors.append("MEDIA_POLICY_VIOLATION")
        log.warn("media_open_failed", source_url=url, detail=str(exc), batch_id=batch_id)
        return result

    # Desar original immutable
    fname_base = _sanitize_filename(
        Path(urllib.parse.urlparse(url).path).stem or "asset"
    )
    ext = mime.split("/")[-1].replace("jpeg", "jpg")
    orig_path = storage_dir / "originals" / f"{fname_base}.{ext}"
    orig_path.parent.mkdir(parents=True, exist_ok=True)
    orig_path.write_bytes(data)
    result.original_path = orig_path

    # Determinar variants a generar per role
    role_policy = _policy_for_role(role, media_policy)
    if not role_policy:
        # Sense política específica → desar original i marcar importat
        result.adaptation_strategy = EXACT_FIT
        result.import_status = "imported"
        return result

    target_ratio_str = role_policy.get("aspect_ratio", "16:9")
    target_ratio = _parse_ratio(target_ratio_str)
    min_w = role_policy.get("min_width", 0)
    min_h = role_policy.get("min_height", 0)

    strategy, crop_loss = detect_adaptation_strategy(
        img.width, img.height, target_ratio, min_w, min_h, crop_threshold, enable_bg_fit
    )
    result.adaptation_strategy = strategy

    original_ratio_str = _ratio_str(img.width, img.height)

    log.info(
        "media_adapted",
        strategy=strategy,
        source_url=url,
        original_ratio=original_ratio_str,
        target_ratio=target_ratio_str,
        crop_loss_estimated=round(crop_loss, 3),
        batch_id=batch_id,
    )

    if strategy == REVIEW_REQUIRED:
        result.warnings.append("MEDIA_REVIEW_REQUIRED")
        result.import_status = "imported_with_warnings"
        return result

    # Generar variants
    variants_cfg = role_policy.get("variants", [])
    for variant_cfg in variants_cfg:
        vname = variant_cfg["name"]
        vw = variant_cfg["width"]
        vh = variant_cfg["height"]
        vext = ext if ext in ("jpg", "png", "webp") else "jpg"
        variant_path = storage_dir / "variants" / role / f"{fname_base}_{vname}.{vext}"

        try:
            if strategy == EXACT_FIT:
                canvas = _apply_exact_fit(img.copy(), vw, vh)
                bg_type = None
                padding = False
            elif strategy == CROP_SAFE:
                canvas = _apply_crop_safe(img.copy(), vw, vh)
                bg_type = None
                padding = False
            else:  # FIT_WITH_BACKGROUND
                canvas, bg_type = _apply_fit_with_background(
                    img.copy(), vw, vh, default_bg, fallback_color
                )
                padding = True
                if strategy == FIT_WITH_BACKGROUND:
                    result.warnings.append("MEDIA_ADAPTED_WITH_BACKGROUND")

            _save_variant(canvas, variant_path)

            vresult = VariantResult(
                name=vname,
                width=vw,
                height=vh,
                path=variant_path,
                adaptation_strategy=strategy,
                background_type=bg_type,
                original_aspect_ratio=original_ratio_str,
                target_aspect_ratio=target_ratio_str,
                padding_applied=padding,
                crop_loss_estimated=round(crop_loss, 3),
            )
            result.variants.append(vresult)

            log.info(
                "asset_variant_generated",
                variant=vname,
                width=vw,
                height=vh,
                strategy=strategy,
                background_type=bg_type,
                source_url=url,
                batch_id=batch_id,
            )

        except Exception as exc:
            log.warn(
                "asset_variant_failed",
                variant=vname,
                source_url=url,
                detail=str(exc),
                batch_id=batch_id,
            )
            result.warnings.append("MEDIA_REVIEW_REQUIRED")

    result.import_status = (
        "imported_with_warnings" if result.warnings else "imported"
    )
    log.info(
        "asset_imported",
        source_url=url,
        strategy=strategy,
        variants=len(result.variants),
        warnings=result.warnings,
        batch_id=batch_id,
    )
    return result


def _policy_for_role(role: str, policy: dict[str, Any]) -> dict[str, Any] | None:
    mapping = {
        "hero": "hero",
        "og_image": "og_image",
        "card": "thumbnail",
        "inline": None,
        "gallery": None,
        "attachment": None,
    }
    key = mapping.get(role)
    if key is None:
        return None
    return policy.get(key)


# ── Entry point per IntermediateItem ──────────────────────────────────────────

def process_item_media(
    item: IntermediateItem,
    media_policy: dict[str, Any],
    source_config: dict[str, Any],
    storage_dir: Path,
    batch_id: str = "",
) -> dict[str, list[AssetResult]]:
    """Processa tots els assets d'un IntermediateItem."""
    results: dict[str, list[AssetResult]] = {"hero": [], "media": []}

    if item.hero and item.hero.source_url:
        r = process_asset(
            item.hero, media_policy, source_config, storage_dir,
            role="hero", batch_id=batch_id,
        )
        results["hero"].append(r)
        if r.warnings:
            for w in r.warnings:
                item.add_warning(w)

    for media_ref in item.media:
        r = process_asset(
            media_ref, media_policy, source_config, storage_dir,
            role=media_ref.role, batch_id=batch_id,
        )
        results["media"].append(r)
        if r.warnings:
            for w in r.warnings:
                item.add_warning(w)

    return results
