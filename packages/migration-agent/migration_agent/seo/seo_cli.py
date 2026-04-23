"""CLI de validació SEO — ADR-0012.

Modes:
  pre-migration   Crawl de les URLs de l'origen i guarda snapshot
  post-migration  Crawl de les URLs destí i compara amb pre-migration
  redirects       Valida els redirects legacy → target
  sitemap         Compara sitemaps origen vs destí
  full            Executa post-migration + redirects + sitemap

Ús:
  python -m migration_agent.seo.seo_cli --mode pre-migration --source-url https://old.com
  python -m migration_agent.seo.seo_cli --mode post-migration --batch-id <uuid> \
      --source-crawl artifacts/seo/pre-migration-crawl.json \
      --target-base-url https://new.com
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from migration_agent.logger import log
from migration_agent.seo.crawler import CrawlResult, crawl_url
from migration_agent.seo.validator import (
    SeoValidationReport,
    diff_sitemaps,
    fetch_sitemap_urls,
    validate_item,
    validate_redirect,
)


def _artifacts_seo() -> Path:
    here = Path(__file__).resolve()
    return here.parents[5] / "artifacts" / "seo"


# ── Pre-migration crawl ────────────────────────────────────────────────────────

def cmd_pre_migration(args: argparse.Namespace) -> int:
    source_url = args.source_url.rstrip("/")
    sitemap_url = args.sitemap or f"{source_url}/sitemap.xml"

    log.info("seo_pre_migration_start", source_url=source_url)

    urls = fetch_sitemap_urls(sitemap_url)
    if not urls:
        log.warn("seo_sitemap_empty", sitemap_url=sitemap_url)
        if args.urls:
            urls = [u.strip() for u in Path(args.urls).read_text().splitlines() if u.strip()]
        if not urls:
            print(f"ERROR: No URLs found from sitemap {sitemap_url}. Use --urls FILE.", file=sys.stderr)
            return 1

    print(f"Crawling {len(urls)} URLs from {source_url}...")
    results = []
    for i, url in enumerate(urls, 1):
        r = crawl_url(url, internal_domain=_domain(source_url))
        results.append(r.to_dict())
        if i % 10 == 0:
            print(f"  {i}/{len(urls)}")

    out = _artifacts_seo()
    out.mkdir(parents=True, exist_ok=True)
    path = out / "pre-migration-crawl.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {path}")
    return 0


# ── Post-migration crawl + validation ─────────────────────────────────────────

def cmd_post_migration(args: argparse.Namespace) -> int:
    batch_id = args.batch_id
    source_crawl_path = Path(args.source_crawl)
    target_base_url = (args.target_base_url or "").rstrip("/")

    if not source_crawl_path.exists():
        print(f"ERROR: source crawl not found: {source_crawl_path}", file=sys.stderr)
        return 1

    source_data: list[dict] = json.loads(source_crawl_path.read_text())
    print(f"Loaded {len(source_data)} source URLs. Crawling destination...")

    report = SeoValidationReport(batch_id=batch_id)
    url_map: dict[str, str] = {}

    for sd in source_data:
        source_result = _dict_to_crawl_result(sd)
        target_url = _remap_url(source_result.url, target_base_url)
        url_map[source_result.url] = target_url

        target_result = crawl_url(target_url, internal_domain=_domain(target_base_url))
        iv = validate_item(source_result, target_result)
        report.items.append(iv)

    # Save post-migration crawl
    post_path = _artifacts_seo() / f"post-migration-crawl-{batch_id}.json"
    post_path.parent.mkdir(parents=True, exist_ok=True)
    post_path.write_text(
        json.dumps([_dict_to_crawl_result(sd).to_dict() for sd in source_data],
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    paths = report.save(_artifacts_seo())
    _print_summary(report)
    return 0 if report.summary()["with_errors"] == 0 else 1


# ── Redirect validation ────────────────────────────────────────────────────────

def cmd_redirects(args: argparse.Namespace) -> int:
    batch_id = args.batch_id
    redirects_file = Path(args.redirects_map)

    if not redirects_file.exists():
        print(f"ERROR: redirects map not found: {redirects_file}", file=sys.stderr)
        return 1

    redirects_data: list[dict] = json.loads(redirects_file.read_text())
    print(f"Validating {len(redirects_data)} redirects...")

    report = SeoValidationReport(batch_id=batch_id)
    for entry in redirects_data:
        rv = validate_redirect(
            legacy_url=entry["from"],
            expected_target=entry["to"],
        )
        report.redirects.append(rv)
        status = "✓" if rv.check == "ok" else "✗"
        print(f"  {status} {entry['from']} → {rv.check}")

    paths = report.save(_artifacts_seo())
    ok = sum(1 for r in report.redirects if r.check == "ok")
    print(f"\nRedirects OK: {ok}/{len(report.redirects)}")
    return 0 if ok == len(report.redirects) else 1


# ── Sitemap diff ───────────────────────────────────────────────────────────────

def cmd_sitemap(args: argparse.Namespace) -> int:
    source_sitemap = args.source_sitemap
    dest_sitemap = args.dest_sitemap

    print(f"Fetching source sitemap: {source_sitemap}")
    source_urls = fetch_sitemap_urls(source_sitemap)
    print(f"  {len(source_urls)} URLs found")

    print(f"Fetching destination sitemap: {dest_sitemap}")
    dest_urls = fetch_sitemap_urls(dest_sitemap)
    print(f"  {len(dest_urls)} URLs found")

    diff = diff_sitemaps(source_urls, dest_urls)

    out = _artifacts_seo() / "sitemap-diff.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nMissing from destination: {diff['missing_count']}")
    print(f"New in destination: {diff['new_count']}")
    print(f"Saved: {out}")
    return 0 if diff["missing_count"] == 0 else 1


# ── Helpers ────────────────────────────────────────────────────────────────────

def _domain(url: str) -> str:
    import re
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else ""


def _remap_url(source_url: str, target_base: str) -> str:
    """Substitueix el domini origen pel destí, mantenint el path."""
    import re
    path = re.sub(r"^https?://[^/]+", "", source_url)
    return f"{target_base}{path}"


def _dict_to_crawl_result(d: dict) -> CrawlResult:
    r = CrawlResult(url=d["url"])
    for k, v in d.items():
        if hasattr(r, k):
            setattr(r, k, v)
    return r


def _print_summary(report: SeoValidationReport) -> None:
    s = report.summary()
    print(f"\n── SEO Validation Summary ──")
    print(f"  Total URLs:      {s['total_urls']}")
    print(f"  Accessible:      {s['accessible']}")
    print(f"  With errors:     {s['with_errors']}")
    print(f"  With warnings:   {s['with_warnings']}")
    print(f"  H1 present:      {s['h1_ok']}")
    print(f"  OG image:        {s['og_image_ok']}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="SEO Validation — ADR-0012")
    sub = parser.add_subparsers(dest="mode", required=True)

    # pre-migration
    p_pre = sub.add_parser("pre-migration")
    p_pre.add_argument("--source-url", required=True)
    p_pre.add_argument("--sitemap", default=None)
    p_pre.add_argument("--urls", default=None, help="Fitxer TXT amb URLs (un per línia)")

    # post-migration
    p_post = sub.add_parser("post-migration")
    p_post.add_argument("--batch-id", required=True)
    p_post.add_argument("--source-crawl", required=True,
                        help="Path a pre-migration-crawl.json")
    p_post.add_argument("--target-base-url", required=True,
                        help="Base URL del destí (ex: https://new.despertare.com)")

    # redirects
    p_redir = sub.add_parser("redirects")
    p_redir.add_argument("--batch-id", required=True)
    p_redir.add_argument("--redirects-map", required=True,
                         help="JSON amb [{from:..., to:...}]")

    # sitemap
    p_sit = sub.add_parser("sitemap")
    p_sit.add_argument("--source-sitemap", required=True)
    p_sit.add_argument("--dest-sitemap", required=True)

    args = parser.parse_args()

    dispatch = {
        "pre-migration": cmd_pre_migration,
        "post-migration": cmd_post_migration,
        "redirects": cmd_redirects,
        "sitemap": cmd_sitemap,
    }
    return dispatch[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
