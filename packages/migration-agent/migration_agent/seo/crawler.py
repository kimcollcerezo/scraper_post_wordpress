"""SEO crawler — ADR-0012.

Crawl d'una URL i extracció de metadades SEO:
  status_code, title, meta_description, canonical, robots,
  og_*, h1, structured_data, hreflang, redirect_chain,
  images_with_alt, images_without_alt, broken_images, internal_links.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from bs4 import BeautifulSoup

from migration_agent.logger import log


@dataclass
class CrawlResult:
    url: str
    status_code: int | None = None
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    robots: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image: str | None = None
    og_url: str | None = None
    og_type: str | None = None
    h1: str | None = None
    h1_count: int = 0
    structured_data: list[dict[str, Any]] = field(default_factory=list)
    hreflang: list[dict[str, str]] = field(default_factory=list)
    images_with_alt: int = 0
    images_without_alt: int = 0
    broken_images: int = 0
    internal_links: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "final_url": self.final_url,
            "redirect_chain": self.redirect_chain,
            "title": self.title,
            "meta_description": self.meta_description,
            "canonical": self.canonical,
            "robots": self.robots,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "og_image": self.og_image,
            "og_url": self.og_url,
            "og_type": self.og_type,
            "h1": self.h1,
            "h1_count": self.h1_count,
            "structured_data": self.structured_data,
            "hreflang": self.hreflang,
            "images_with_alt": self.images_with_alt,
            "images_without_alt": self.images_without_alt,
            "broken_images": self.broken_images,
            "internal_links": self.internal_links,
            "error": self.error,
        }


def crawl_url(
    url: str,
    *,
    timeout: float = 15.0,
    follow_redirects: bool = True,
    internal_domain: str | None = None,
) -> CrawlResult:
    """Crawla una URL i extreu metadades SEO."""
    result = CrawlResult(url=url)

    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=follow_redirects,
            headers={"User-Agent": "DespertareMigrationBot/1.0"},
        ) as client:
            resp = client.get(url)

        result.status_code = resp.status_code
        result.final_url = str(resp.url)

        # Redirect chain
        result.redirect_chain = [str(r.url) for r in resp.history]

        if resp.status_code >= 400:
            result.error = f"HTTP_{resp.status_code}"
            return result

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type:
            return result

        soup = BeautifulSoup(resp.text, "lxml")

        # Title
        title_tag = soup.find("title")
        result.title = title_tag.get_text(strip=True) if title_tag else None

        # Meta description
        desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        result.meta_description = desc.get("content") if desc else None  # type: ignore[union-attr]

        # Canonical
        can = soup.find("link", attrs={"rel": re.compile(r"canonical", re.I)})
        result.canonical = can.get("href") if can else None  # type: ignore[union-attr]

        # Robots
        rob = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
        result.robots = rob.get("content") if rob else None  # type: ignore[union-attr]

        # OG tags
        for prop, attr in [
            ("og:title", "og_title"),
            ("og:description", "og_description"),
            ("og:image", "og_image"),
            ("og:url", "og_url"),
            ("og:type", "og_type"),
        ]:
            tag = soup.find("meta", attrs={"property": prop})
            if tag:
                setattr(result, attr, tag.get("content"))  # type: ignore[union-attr]

        # H1
        h1_tags = soup.find_all("h1")
        result.h1_count = len(h1_tags)
        result.h1 = h1_tags[0].get_text(strip=True) if h1_tags else None

        # Structured data (JSON-LD)
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                result.structured_data.append(data)
            except Exception:
                pass

        # Hreflang
        for link in soup.find_all("link", attrs={"rel": "alternate", "hreflang": True}):
            result.hreflang.append({
                "hreflang": link.get("hreflang", ""),
                "href": link.get("href", ""),
            })

        # Images
        base_domain = _domain(result.final_url or url)
        for img in soup.find_all("img"):
            alt = img.get("alt")
            if alt is not None and alt.strip():
                result.images_with_alt += 1
            else:
                result.images_without_alt += 1

        # Internal links
        if internal_domain:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if internal_domain in href or href.startswith("/"):
                    result.internal_links += 1

    except httpx.RequestError as exc:
        result.error = f"REQUEST_ERROR: {exc}"
        log.warn("seo_crawl_error", url=url, detail=str(exc))

    return result


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else ""
