"""WordPress Source Adapter — ADR-0005.

MVP: REST API nativa de WordPress. Suporta Application Passwords.
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterator

import httpx

from migration_agent.adapters.base import (
    HealthStatus,
    PaginationResult,
    SourceAdapter,
    SourceCapabilities,
)
from migration_agent.config.loader import resolve_env
from migration_agent.logger import log


class WordPressAdapter(SourceAdapter):
    """Adapter per a WordPress via REST API."""

    def __init__(self, source_name: str, source_config: dict[str, Any]) -> None:
        self._name = source_name
        self._config = source_config
        self._base_url = source_config["base_url"].rstrip("/")
        self._api_base = f"{self._base_url}/wp-json/wp/v2"
        self._timeout = source_config.get("timeout_seconds", 20)
        self._max_retries = source_config.get("max_retries", 3)
        self._backoff_factor = source_config.get("backoff_factor", 2)
        self._rate_limit_rps = source_config.get("rate_limit_rps", 1)
        self._min_interval = 1.0 / self._rate_limit_rps
        self._last_request_at: float = 0.0
        self._client = self._build_client()

    def _build_client(self) -> httpx.Client:
        auth_config = self._config.get("auth", {})
        auth_type = auth_config.get("type", "none")

        headers = {"Accept": "application/json", "User-Agent": "DespertareMigrationEngine/1.0"}
        auth = None

        if auth_type == "application_password":
            username = resolve_env(auth_config["username_env"])
            password = resolve_env(auth_config["password_env"])
            auth = httpx.BasicAuth(username, password)
        elif auth_type == "token":
            token = resolve_env(auth_config["token_env"])
            headers["Authorization"] = f"Bearer {token}"

        return httpx.Client(
            headers=headers,
            auth=auth,
            timeout=self._timeout,
            follow_redirects=True,
            verify=True,
        )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            try:
                response = self._client.get(url, params=params)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                # No reintentar 401/403/404
                if exc.response.status_code in (401, 403, 404):
                    raise
                last_exc = exc
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc

            wait_s = self._backoff_factor**attempt
            log.warn(
                "request_retry",
                url=url,
                attempt=attempt,
                wait_seconds=wait_s,
                error=str(last_exc),
            )
            time.sleep(wait_s)

        raise RuntimeError(f"Max retries exceeded for {url}: {last_exc}") from last_exc

    def health_check(self) -> HealthStatus:
        try:
            resp = self._get(f"{self._api_base}/posts", params={"per_page": 1})
            return HealthStatus(ok=True, message="WordPress REST API accessible")
        except Exception as exc:
            return HealthStatus(ok=False, message=str(exc))

    def detect_capabilities(self) -> SourceCapabilities:
        caps = SourceCapabilities()
        try:
            resp = self._get(f"{self._base_url}/wp-json")
            data = resp.json()
            namespaces = data.get("namespaces", [])
            caps.has_gutenberg = "wp-block-editor/v1" in namespaces
            # Detecció bàsica per namespace
            caps.rest_api_version = data.get("version")
        except Exception:
            pass
        return caps

    def extract(
        self,
        *,
        post_types: list[str] | None = None,
        statuses: list[str] | None = None,
        limit: int | None = None,
        ids: list[int] | None = None,
        published_after: str | None = None,
        modified_after: str | None = None,
        include_drafts: bool = False,
    ) -> Iterator[dict[str, Any]]:
        types = post_types or ["post"]
        status_filter = ",".join(statuses or ["publish"])
        count = 0

        for post_type in types:
            endpoint = f"{self._api_base}/{post_type}s"
            page = 1
            per_page = self._config.get("extract", {}).get("per_page", 20)

            while True:
                if limit is not None and count >= limit:
                    return

                params: dict[str, Any] = {
                    "status": status_filter,
                    "page": page,
                    "per_page": min(per_page, (limit - count) if limit else per_page),
                    "_embed": 1,
                }

                if ids:
                    params["include"] = ",".join(str(i) for i in ids)
                if published_after:
                    params["after"] = published_after
                if modified_after:
                    params["modified_after"] = modified_after

                try:
                    resp = self._get(endpoint, params=params)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 400:
                        # Post type no accessible via /posts, prova /pages, etc.
                        break
                    raise

                items = resp.json()
                if not items:
                    break

                for raw in items:
                    if limit is not None and count >= limit:
                        return
                    yield raw
                    count += 1

                total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
                if page >= total_pages:
                    break
                page += 1

    def normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalitza un post WordPress raw a format pre-intermedi."""
        embedded = raw.get("_embedded", {})
        author_data = self._extract_author(embedded)
        featured_media = self._extract_featured_media(embedded)
        categories = self._extract_terms(embedded, "wp:term", "category")
        tags = self._extract_terms(embedded, "wp:term", "post_tag")
        seo = self._extract_seo(raw)
        content_raw = raw.get("content", {}).get("raw") or raw.get("content", {}).get("rendered", "")
        title_raw = raw.get("title", {}).get("raw") or raw.get("title", {}).get("rendered", "")

        return {
            "source_system": "wordpress",
            "source_site_url": self._base_url,
            "source_id": raw["id"],
            "source_type": raw.get("type", "post"),
            "source_status": raw.get("status", "publish"),
            "source_url": raw.get("link", ""),
            "parent_id": raw.get("parent") or None,
            "menu_order": raw.get("menu_order", 0),
            "template": raw.get("template") or None,
            "locale": None,  # MVP: sense WPML/Polylang
            "slug": raw.get("slug", ""),
            "title": self._strip_html(title_raw),
            "excerpt": self._strip_html(
                raw.get("excerpt", {}).get("rendered", "")
            ),
            "content_html": raw.get("content", {}).get("rendered", ""),
            "content_raw": content_raw,
            "author": author_data,
            "featured_media": featured_media,
            "categories": categories,
            "tags": tags,
            "seo": seo,
            "dates": {
                "created_at": raw.get("date_gmt"),
                "published_at": raw.get("date_gmt"),
                "modified_at": raw.get("modified_gmt"),
            },
            "custom_fields": raw.get("meta", {}),
        }

    def _extract_author(self, embedded: dict[str, Any]) -> dict[str, Any] | None:
        authors = embedded.get("author", [])
        if not authors:
            return None
        a = authors[0]
        return {
            "source_id": a.get("id"),
            "name": a.get("name"),
            "slug": a.get("slug"),
            "email": None,  # REST API no exposa email per defecte
            "bio": self._strip_html(a.get("description", "")),
            "avatar_url": a.get("avatar_urls", {}).get("96"),
        }

    def _extract_featured_media(self, embedded: dict[str, Any]) -> dict[str, Any] | None:
        media_list = embedded.get("wp:featuredmedia", [])
        if not media_list:
            return None
        m = media_list[0]
        sizes = m.get("media_details", {}).get("sizes", {})
        full = sizes.get("full", {})
        return {
            "source_url": m.get("source_url", ""),
            "alt": m.get("alt_text", ""),
            "caption": self._strip_html(m.get("caption", {}).get("rendered", "")),
            "title": m.get("title", {}).get("rendered", ""),
            "mime_type": m.get("mime_type"),
            "width": full.get("width") or m.get("media_details", {}).get("width"),
            "height": full.get("height") or m.get("media_details", {}).get("height"),
        }

    def _extract_terms(
        self, embedded: dict[str, Any], key: str, taxonomy: str
    ) -> list[dict[str, Any]]:
        result = []
        for group in embedded.get(key, []):
            for term in group:
                if term.get("taxonomy") == taxonomy:
                    result.append({
                        "source_id": term["id"],
                        "name": term["name"],
                        "slug": term["slug"],
                    })
        return result

    def _extract_seo(self, raw: dict[str, Any]) -> dict[str, Any]:
        # MVP: derivat de title + excerpt. Yoast/RankMath a implementar via plugin propi.
        yoast = raw.get("yoast_head_json", {})
        if yoast:
            return {
                "title": yoast.get("title"),
                "description": yoast.get("description"),
                "canonical": yoast.get("canonical"),
                "robots": str(yoast.get("robots", {})),
                "og_title": yoast.get("og_title"),
                "og_description": yoast.get("og_description"),
                "og_image": (yoast.get("og_image") or [{}])[0].get("url"),
                "twitter_card": yoast.get("twitter_card"),
                "source": "yoast",
            }
        return {
            "title": None,
            "description": None,
            "canonical": raw.get("link"),
            "robots": None,
            "og_title": None,
            "og_description": None,
            "og_image": None,
            "twitter_card": None,
            "source": "derived",
        }

    @staticmethod
    def _strip_html(html: str) -> str:
        if not html:
            return ""
        return re.sub(r"<[^>]+>", "", html).strip()
