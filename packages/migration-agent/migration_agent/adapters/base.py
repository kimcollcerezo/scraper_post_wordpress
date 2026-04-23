"""Interfície base SourceAdapter — ADR-0005."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class SourceCapabilities:
    has_gutenberg: bool = False
    has_elementor: bool = False
    has_classic_editor: bool = False
    has_yoast: bool = False
    has_rankmath: bool = False
    has_acf: bool = False
    has_wpml: bool = False
    has_polylang: bool = False
    rest_api_version: str | None = None


@dataclass
class PaginationResult:
    items: list[dict[str, Any]]
    total: int
    total_pages: int
    current_page: int
    has_more: bool


@dataclass
class HealthStatus:
    ok: bool
    message: str
    details: dict[str, Any] | None = None


class SourceAdapter(ABC):
    """Contracte mínim per a qualsevol adapter de font CMS."""

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """Verifica que la font és accessible."""
        ...

    @abstractmethod
    def detect_capabilities(self) -> SourceCapabilities:
        """Detecta plugins i capacitats disponibles."""
        ...

    @abstractmethod
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
        """Extreu ítems de la font. Retorna dicts en format raw de la font."""
        ...

    @abstractmethod
    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalitza un ítem raw cap al format pre-intermedi estàndard."""
        ...
