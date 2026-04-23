"""SEO validator — ADR-0012.

Compara CrawlResult d'origen i destí i genera checks, warnings i errors.
Valida redirects i sitemaps.
"""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from migration_agent.logger import log
from migration_agent.seo.crawler import CrawlResult, crawl_url


# ── Check result ───────────────────────────────────────────────────────────────

@dataclass
class ItemValidation:
    source_url: str
    target_url: str
    status: str = "ok"          # ok | warning | error
    checks: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "target_url": self.target_url,
            "status": self.status,
            "checks": self.checks,
            "warnings": self.warnings,
            "errors": self.errors,
        }


@dataclass
class RedirectValidation:
    legacy_url: str
    expected_target: str
    redirect_status: int | None = None
    redirect_location: str | None = None
    target_status: int | None = None
    check: str = "missing_redirect"  # ok | missing_redirect | wrong_target | target_broken

    def to_dict(self) -> dict[str, Any]:
        return {
            "legacy_url": self.legacy_url,
            "expected_target": self.expected_target,
            "redirect_status": self.redirect_status,
            "redirect_location": self.redirect_location,
            "target_status": self.target_status,
            "check": self.check,
        }


# ── Item validation ────────────────────────────────────────────────────────────

def validate_item(source: CrawlResult, target: CrawlResult) -> ItemValidation:
    """Compara source i target i retorna ItemValidation."""
    iv = ItemValidation(
        source_url=source.url,
        target_url=target.url,
    )

    # Error: URL no accessible
    if target.status_code is None or target.status_code >= 400:
        iv.errors.append("url_not_accessible")
        iv.checks["url_accessible"] = False
    else:
        iv.checks["url_accessible"] = True

    # Error: noindex inesperat
    target_robots = (target.robots or "").lower()
    source_robots = (source.robots or "").lower()
    if "noindex" in target_robots and "noindex" not in source_robots:
        iv.errors.append("noindex_unexpected")

    # Error: canonical apunta a domini antic
    if target.canonical and source.url and _domain_of(source.url) in target.canonical:
        iv.errors.append("canonical_points_to_old_domain")

    # Error: redirect loop
    if len(target.redirect_chain) > 5:
        iv.errors.append("redirect_loop")

    # Warning: title
    if not target.title:
        iv.warnings.append("title_missing")
    elif len(target.title) > 60:
        iv.warnings.append("title_too_long")

    if target.title and source.title and target.title != source.title:
        iv.warnings.append("title_changed")

    iv.checks["title_preserved"] = target.title == source.title
    iv.checks["title_match"] = {"source": source.title, "target": target.title}

    # Warning: meta description
    if not target.meta_description:
        iv.warnings.append("meta_description_missing")
    elif len(target.meta_description) > 160:
        iv.warnings.append("meta_description_too_long")

    iv.checks["meta_description_preserved"] = target.meta_description == source.meta_description

    # Warning: canonical
    iv.checks["canonical_valid"] = bool(target.canonical)
    iv.checks["canonical_self_referencing"] = (
        target.canonical == target.final_url or target.canonical == target.url
        if target.canonical else False
    )
    if target.canonical and target.canonical not in (target.url, target.final_url):
        iv.warnings.append("canonical_different_from_target")

    # Warning: robots
    iv.checks["robots_preserved"] = target.robots == source.robots

    # Warning: OG image
    if not target.og_image:
        iv.warnings.append("og_image_missing")
    iv.checks["og_image_accessible"] = bool(target.og_image)

    # Warning: H1
    if target.h1_count == 0:
        iv.warnings.append("h1_missing")
    elif target.h1_count > 1:
        iv.warnings.append("multiple_h1")
    iv.checks["h1_present"] = target.h1_count >= 1

    # Warning: images without alt
    if target.images_without_alt > 0:
        iv.warnings.append("images_without_alt")

    # Final status
    if iv.errors:
        iv.status = "error"
    elif iv.warnings:
        iv.status = "warning"

    return iv


def _domain_of(url: str) -> str:
    import re
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else ""


# ── Redirect validation ────────────────────────────────────────────────────────

def validate_redirect(
    legacy_url: str,
    expected_target: str,
    timeout: float = 10.0,
) -> RedirectValidation:
    rv = RedirectValidation(legacy_url=legacy_url, expected_target=expected_target)

    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            resp = client.get(legacy_url)

        rv.redirect_status = resp.status_code

        if resp.status_code not in (301, 302):
            rv.check = "missing_redirect"
            return rv

        location = resp.headers.get("location", "")
        rv.redirect_location = location

        # Normalitzar per comparar (ignorar trailing slash)
        if location.rstrip("/") != expected_target.rstrip("/"):
            rv.check = "wrong_target"
            return rv

        # Verificar que el target respon 200
        target_resp = client.get(expected_target)
        rv.target_status = target_resp.status_code
        if target_resp.status_code == 200:
            rv.check = "ok"
        else:
            rv.check = "target_broken"

    except httpx.RequestError as exc:
        rv.check = "missing_redirect"
        log.warn("redirect_validation_error", url=legacy_url, detail=str(exc))

    return rv


# ── Sitemap diff ───────────────────────────────────────────────────────────────

def fetch_sitemap_urls(sitemap_url: str, timeout: float = 15.0) -> list[str]:
    """Descarrega un sitemap XML i retorna la llista de URLs."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(sitemap_url)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        return [loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text]
    except Exception as exc:
        log.warn("sitemap_fetch_error", url=sitemap_url, detail=str(exc))
        return []


def diff_sitemaps(
    source_urls: list[str],
    destination_urls: list[str],
    url_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Compara llistes d'URLs de sitemaps.
    url_map: {legacy_url: target_url} per normalitzar comparació.
    """
    dest_set = set(destination_urls)

    missing: list[str] = []
    for src_url in source_urls:
        mapped = (url_map or {}).get(src_url, src_url)
        if mapped not in dest_set:
            missing.append(src_url)

    src_set = {(url_map or {}).get(u, u) for u in source_urls}
    new_in_dest = [u for u in destination_urls if u not in src_set]

    return {
        "source_count": len(source_urls),
        "destination_count": len(destination_urls),
        "missing_from_destination": missing,
        "missing_count": len(missing),
        "new_in_destination": new_in_dest,
        "new_count": len(new_in_dest),
    }


# ── Report builder ─────────────────────────────────────────────────────────────

@dataclass
class SeoValidationReport:
    batch_id: str
    validated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    items: list[ItemValidation] = field(default_factory=list)
    redirects: list[RedirectValidation] = field(default_factory=list)
    sitemap_diff: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        total = len(self.items)
        errors = sum(1 for i in self.items if i.status == "error")
        warnings = sum(1 for i in self.items if i.status == "warning")
        redirects_ok = sum(1 for r in self.redirects if r.check == "ok")
        redirects_missing = sum(1 for r in self.redirects if r.check == "missing_redirect")
        redirects_broken = sum(1 for r in self.redirects if r.check in ("wrong_target", "target_broken"))

        return {
            "total_urls": total,
            "accessible": sum(1 for i in self.items if i.checks.get("url_accessible")),
            "with_errors": errors,
            "with_warnings": warnings,
            "redirects_ok": redirects_ok,
            "redirects_missing": redirects_missing,
            "redirects_broken": redirects_broken,
            "og_image_ok": sum(1 for i in self.items if i.checks.get("og_image_accessible")),
            "og_image_missing": sum(1 for i in self.items if not i.checks.get("og_image_accessible")),
            "h1_ok": sum(1 for i in self.items if i.checks.get("h1_present")),
            "h1_missing": sum(1 for i in self.items if not i.checks.get("h1_present")),
            "sitemap_urls_origin": self.sitemap_diff.get("source_count", 0),
            "sitemap_urls_destination": self.sitemap_diff.get("destination_count", 0),
            "sitemap_missing": self.sitemap_diff.get("missing_count", 0),
        }

    def to_dict(self) -> dict[str, Any]:
        s = self.summary()
        all_errors = [
            {"source_url": i.source_url, "errors": i.errors}
            for i in self.items if i.errors
        ]
        all_warnings = [
            {"source_url": i.source_url, "warnings": i.warnings}
            for i in self.items if i.warnings
        ]
        return {
            "batch_id": self.batch_id,
            "validated_at": self.validated_at,
            "summary": s,
            "errors": all_errors,
            "warnings": all_warnings,
        }

    def to_csv(self) -> str:
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=[
            "source_url", "target_url", "status",
            "url_accessible", "title_preserved", "canonical_valid",
            "h1_present", "og_image_accessible", "warnings", "errors",
        ])
        writer.writeheader()
        for iv in self.items:
            writer.writerow({
                "source_url": iv.source_url,
                "target_url": iv.target_url,
                "status": iv.status,
                "url_accessible": iv.checks.get("url_accessible", ""),
                "title_preserved": iv.checks.get("title_preserved", ""),
                "canonical_valid": iv.checks.get("canonical_valid", ""),
                "h1_present": iv.checks.get("h1_present", ""),
                "og_image_accessible": iv.checks.get("og_image_accessible", ""),
                "warnings": "|".join(iv.warnings),
                "errors": "|".join(iv.errors),
            })
        return out.getvalue()

    def save(self, artifacts_dir: Path) -> dict[str, Path]:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}

        # seo-validation-report.json
        report_path = artifacts_dir / f"seo-validation-report-{self.batch_id}.json"
        full = {
            "batch_id": self.batch_id,
            "validated_at": self.validated_at,
            "summary": self.summary(),
            "items": [i.to_dict() for i in self.items],
            "redirects": [r.to_dict() for r in self.redirects],
            "sitemap_diff": self.sitemap_diff,
        }
        report_path.write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["report"] = report_path

        # seo-validation-report.csv
        csv_path = artifacts_dir / f"seo-validation-report-{self.batch_id}.csv"
        csv_path.write_text(self.to_csv(), encoding="utf-8")
        paths["csv"] = csv_path

        # seo-summary.json
        summary_path = artifacts_dir / f"seo-summary-{self.batch_id}.json"
        summary_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        paths["summary"] = summary_path

        log.info(
            "seo_report_saved",
            batch_id=self.batch_id,
            report=str(report_path),
            csv=str(csv_path),
        )
        return paths
