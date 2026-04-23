"""Import API client — ADR-0009.

Client HTTP per als endpoints de la Import API de Despertare:
  POST /api/admin/import/authors
  POST /api/admin/import/taxonomies
  POST /api/admin/import/media
  POST /api/admin/import/content
  POST /api/admin/import/redirects
  GET  /api/admin/import/status/{batch_id}

Autenticació: Authorization: Bearer <DESPERTARE_IMPORT_TOKEN>
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from migration_agent.logger import log
from migration_agent.models.intermediate import (
    AuthorRef,
    IntermediateItem,
    MediaRef,
    TaxonomyTerm,
)
from migration_agent.pipeline.media import AssetResult

# ── Errors contractats ADR-0009 ────────────────────────────────────────────────

IMPORT_API_ERRORS = {
    "INVALID_PAYLOAD",
    "MISSING_REQUIRED_FIELD",
    "INVALID_SLUG",
    "SLUG_COLLISION",
    "DUPLICATE_ITEM",
    "UNSUPPORTED_LOCALE",
    "AUTHOR_NOT_FOUND",
    "MEDIA_NOT_FOUND",
    "MEDIA_POLICY_VIOLATION",
    "PERMISSION_DENIED",
    "INVALID_TOKEN",
    "CONTENT_INVARIANT_VIOLATION",
    "BATCH_NOT_FOUND",
}


# ── Dataclasses de resultat ────────────────────────────────────────────────────

@dataclass
class ImportContentResult:
    source_id: str
    result: str = "failed"  # created | updated | skipped | failed
    content_item_id: str | None = None
    content_localization_id: str | None = None
    content_version_id: str | None = None
    target_url: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportMediaResult:
    source_url: str
    result: str = "failed"  # imported | deduplicated | failed
    media_asset_id: str | None = None
    storage_url: str | None = None
    variants: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportAuthorResult:
    source_id: str
    result: str = "failed"  # created | merged | skipped | failed
    author_id: str | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportTaxonomyResult:
    source_id: str
    taxonomy: str
    result: str = "failed"  # created | merged | skipped | failed
    taxonomy_term_id: str | None = None
    errors: list[str] = field(default_factory=list)


# ── Client ─────────────────────────────────────────────────────────────────────

class ImportApiClient:
    """Client per a la Import API de Despertare (ADR-0009)."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    @classmethod
    def from_env(cls) -> "ImportApiClient":
        base_url = os.environ.get("DESPERTARE_IMPORT_API_URL", "")
        token = os.environ.get("DESPERTARE_IMPORT_TOKEN", "")
        if not base_url:
            raise RuntimeError("DESPERTARE_IMPORT_API_URL not set")
        if not token:
            raise RuntimeError("DESPERTARE_IMPORT_TOKEN not set")
        return cls(base_url=base_url, token=token)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ImportApiClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ── Media ──────────────────────────────────────────────────────────────────

    def import_media(
        self,
        media_ref: MediaRef,
        asset_result: AssetResult,
        batch_id: str,
    ) -> ImportMediaResult:
        """Registra un asset a la Import API."""
        payload: dict[str, Any] = {
            "batch_id": batch_id,
            "source_url": media_ref.source_url,
            "filename": media_ref.filename or _filename_from_url(media_ref.source_url),
            "mime_type": asset_result.mime_type or media_ref.mime_type or "application/octet-stream",
            "size_bytes": asset_result.size_bytes or 0,
            "width": asset_result.width,
            "height": asset_result.height,
            "alt": media_ref.alt,
            "caption": media_ref.caption,
            "hash": asset_result.hash or "",
            "role": media_ref.role,
            "source_url_accessible": True,
            "binary": None,
        }

        # Si tenim el fitxer local i la URL no és accessible externament, enviem en base64
        if asset_result.original_path and asset_result.original_path.exists():
            raw = asset_result.original_path.read_bytes()
            payload["binary"] = base64.b64encode(raw).decode("ascii")
            payload["source_url_accessible"] = False

        resp = self._post("/api/admin/import/media", payload)
        out = ImportMediaResult(source_url=media_ref.source_url)

        if resp is None:
            out.errors.append("IMPORT_API_UNREACHABLE")
            return out

        if resp.status_code == 200:
            data = resp.json()
            out.result = data.get("result", "imported")
            out.media_asset_id = data.get("media_asset_id")
            out.storage_url = data.get("storage_url")
            out.variants = data.get("variants", {})
        elif resp.status_code == 422:
            error_code = resp.json().get("error", "MEDIA_POLICY_VIOLATION")
            out.errors.append(error_code)
        else:
            out.errors.append(self._extract_error(resp))

        return out

    # ── Authors ────────────────────────────────────────────────────────────────

    def import_author(self, author: AuthorRef, batch_id: str) -> ImportAuthorResult:
        payload: dict[str, Any] = {
            "batch_id": batch_id,
            "source_id": str(author.source_id or ""),
            "name": author.name or "",
            "slug": author.slug or "",
            "email": author.email,
            "bio": author.bio,
            "avatar_url": author.avatar_url,
            "on_duplicate": "merge",
        }
        resp = self._post("/api/admin/import/authors", payload)
        out = ImportAuthorResult(source_id=str(author.source_id or ""))

        if resp is None:
            out.errors.append("IMPORT_API_UNREACHABLE")
            return out

        if resp.status_code == 200:
            data = resp.json()
            out.result = data.get("result", "created")
            out.author_id = data.get("author_id")
        else:
            out.errors.append(self._extract_error(resp))

        return out

    # ── Taxonomies ─────────────────────────────────────────────────────────────

    def import_taxonomy_term(
        self, term: TaxonomyTerm, taxonomy: str, batch_id: str
    ) -> ImportTaxonomyResult:
        payload: dict[str, Any] = {
            "batch_id": batch_id,
            "taxonomy": taxonomy,
            "source_id": str(term.source_id),
            "name": term.name,
            "slug": term.slug,
            "on_duplicate": "merge",
        }
        resp = self._post("/api/admin/import/taxonomies", payload)
        out = ImportTaxonomyResult(source_id=str(term.source_id), taxonomy=taxonomy)

        if resp is None:
            out.errors.append("IMPORT_API_UNREACHABLE")
            return out

        if resp.status_code == 200:
            data = resp.json()
            out.result = data.get("result", "created")
            out.taxonomy_term_id = data.get("taxonomy_term_id")
        else:
            out.errors.append(self._extract_error(resp))

        return out

    # ── Content ────────────────────────────────────────────────────────────────

    def import_content(
        self,
        item: IntermediateItem,
        on_duplicate: str = "skip",
        import_as_status: str = "draft",
    ) -> ImportContentResult:
        payload = _build_content_payload(item, on_duplicate, import_as_status)
        resp = self._post("/api/admin/import/content", payload)
        out = ImportContentResult(source_id=str(item.source.id))

        if resp is None:
            out.errors.append("IMPORT_API_UNREACHABLE")
            return out

        if resp.status_code == 200:
            data = resp.json()
            out.result = data.get("result", "created")
            out.content_item_id = data.get("content_item_id")
            out.content_localization_id = data.get("content_localization_id")
            out.content_version_id = data.get("content_version_id")
            out.target_url = data.get("target_url")
            out.warnings = data.get("warnings", [])
        elif resp.status_code == 409:
            data = resp.json()
            if on_duplicate == "skip":
                out.result = "skipped"
            else:
                out.errors.append(data.get("error", "DUPLICATE_ITEM"))
        else:
            out.errors.append(self._extract_error(resp))

        return out

    # ── Redirects ──────────────────────────────────────────────────────────────

    def import_redirects(
        self, redirects: list[dict[str, str]], batch_id: str
    ) -> dict[str, Any]:
        payload = {"batch_id": batch_id, "redirects": redirects}
        resp = self._post("/api/admin/import/redirects", payload)
        if resp is None:
            return {"created": 0, "skipped": 0, "conflicts": [], "error": "IMPORT_API_UNREACHABLE"}
        if resp.status_code == 200:
            return resp.json()
        return {"created": 0, "skipped": 0, "conflicts": [], "error": self._extract_error(resp)}

    # ── Status ─────────────────────────────────────────────────────────────────

    def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        try:
            resp = self._client.get(
                f"{self._base_url}/api/admin/import/status/{batch_id}",
                timeout=self._timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"status": "error", "error": self._extract_error(resp)}
        except httpx.RequestError as exc:
            log.error("import_api_request_error", detail=str(exc))
            return {"status": "error", "error": "IMPORT_API_UNREACHABLE"}

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response | None:
        url = f"{self._base_url}{path}"
        try:
            resp = self._client.post(url, json=payload)
            log.info(
                "import_api_call",
                path=path,
                status=resp.status_code,
            )
            return resp
        except httpx.RequestError as exc:
            log.error("import_api_request_error", path=path, detail=str(exc))
            return None

    @staticmethod
    def _extract_error(resp: httpx.Response) -> str:
        try:
            body = resp.json()
            return body.get("error", f"HTTP_{resp.status_code}")
        except Exception:
            return f"HTTP_{resp.status_code}"


# ── Helpers de payload ─────────────────────────────────────────────────────────

def _filename_from_url(url: str) -> str:
    return url.split("/")[-1].split("?")[0] or "asset"


def _build_content_payload(
    item: IntermediateItem,
    on_duplicate: str,
    import_as_status: str,
) -> dict[str, Any]:
    return {
        "batch_id": item.import_batch_id,
        "source": {
            "system": item.source.system,
            "site_url": item.source.site_url,
            "id": item.source.id,
            "type": item.source.type,
            "status": item.source.status,
            "url": item.source.url,
            "locale": item.source.locale,
        },
        "routing": {
            "slug": item.routing.slug,
            "path": item.routing.path,
            "legacy_url": item.routing.legacy_url,
            "desired_url": item.routing.desired_url,
        },
        "content": {
            "title": item.content.title,
            "excerpt": item.content.excerpt,
            "blocks": [b.model_dump() for b in item.content.blocks],
        },
        "hero": (
            {
                "source_url": item.hero.source_url,
                "media_asset_id": item.hero.media_asset_id,
                "alt": item.hero.alt,
                "caption": item.hero.caption,
                "role": item.hero.role,
            }
            if item.hero
            else None
        ),
        "author": (
            {
                "source_id": item.author.source_id,
                "name": item.author.name,
                "slug": item.author.slug,
                "email": item.author.email,
            }
            if item.author
            else None
        ),
        "taxonomies": {
            "categories": [
                {"source_id": t.source_id, "name": t.name, "slug": t.slug}
                for t in item.taxonomies.categories
            ],
            "tags": [
                {"source_id": t.source_id, "name": t.name, "slug": t.slug}
                for t in item.taxonomies.tags
            ],
        },
        "seo": {
            "title": item.seo.title,
            "description": item.seo.description,
            "canonical": item.seo.canonical,
            "robots": item.seo.robots,
            "og_title": item.seo.og_title,
            "og_description": item.seo.og_description,
            "og_image": item.seo.og_image,
        },
        "dates": {
            "created_at": item.dates.created_at,
            "published_at": item.dates.published_at,
            "modified_at": item.dates.modified_at,
        },
        "on_duplicate": on_duplicate,
        "import_as_status": import_as_status,
    }
