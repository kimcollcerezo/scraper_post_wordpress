"""Media URL rewriting — ADR-0006.

Reescriu les URLs d'imatges dins els blocs de contingut d'un IntermediateItem
un cop els assets han estat registrats a la Import API i disposen de storage_url.

Mapping: old_url → new_url (storage_url retornat per la Import API).

Les URLs no reescrites queden com a MEDIA_REWRITE_PENDING i es registren.
"""

from __future__ import annotations

from typing import Any

from migration_agent.logger import log
from migration_agent.models.intermediate import IntermediateItem


def build_url_map(item: IntermediateItem) -> dict[str, str]:
    """Construeix el mapping old_url → new_url a partir dels MediaRef de l'ítem."""
    url_map: dict[str, str] = {}

    if item.hero and item.hero.source_url and item.hero.new_url:
        url_map[item.hero.source_url] = item.hero.new_url

    for media_ref in item.media:
        if media_ref.source_url and media_ref.new_url:
            url_map[media_ref.source_url] = media_ref.new_url

    return url_map


def rewrite_blocks(
    item: IntermediateItem,
    url_map: dict[str, str],
) -> tuple[int, list[str]]:
    """
    Reescriu URLs als blocs de contingut.

    Retorna (rewritten_count, pending_urls).
    - rewritten_count: nombre d'URLs reescrites
    - pending_urls: URLs trobades als blocs que NO estan al url_map
    """
    rewritten = 0
    pending: list[str] = []

    for block in item.content.blocks:
        block_type = block.type
        data = block.data

        if block_type in ("image", "hero"):
            url = data.get("url") or data.get("src")
            if url:
                if url in url_map:
                    data["url"] = url_map[url]
                    data.pop("src", None)
                    rewritten += 1
                else:
                    pending.append(url)

        elif block_type == "gallery":
            images = data.get("images", [])
            for img in images:
                url = img.get("url") or img.get("src")
                if url:
                    if url in url_map:
                        img["url"] = url_map[url]
                        img.pop("src", None)
                        rewritten += 1
                    else:
                        pending.append(url)

        elif block_type in ("raw_html", "html"):
            html = data.get("html", "")
            new_html, n, pend = _rewrite_html_urls(html, url_map)
            if n > 0:
                data["html"] = new_html
                rewritten += n
            pending.extend(pend)

        elif block_type == "embed":
            url = data.get("url")
            if url and url in url_map:
                data["url"] = url_map[url]
                rewritten += 1

    return rewritten, pending


def _rewrite_html_urls(
    html: str, url_map: dict[str, str]
) -> tuple[str, int, list[str]]:
    """
    Reescriu URLs dins HTML raw (src= i href=) sense parsejar DOM.
    Usa substitució string simple per evitar dependència de BeautifulSoup aquí.
    Retorna (new_html, rewritten_count, pending_urls).
    """
    rewritten = 0
    pending: list[str] = []
    result = html

    for old_url, new_url in url_map.items():
        if old_url in result:
            result = result.replace(old_url, new_url)
            rewritten += 1

    # Detectar URLs d'imatge no reescrites (src=" que no estan al map)
    import re
    for m in re.finditer(r'src=["\']([^"\']+)["\']', html):
        url = m.group(1)
        if url not in url_map and url.startswith("http"):
            pending.append(url)

    return result, rewritten, pending


def rewrite_item_urls(item: IntermediateItem) -> dict[str, Any]:
    """
    Punt d'entrada principal. Reescriu tots els blocs de l'ítem.

    Retorna metadades del rewriting:
    {
        "rewritten": int,
        "pending": list[str],
        "pending_count": int,
    }
    """
    url_map = build_url_map(item)

    if not url_map:
        return {"rewritten": 0, "pending": [], "pending_count": 0}

    rewritten, pending = rewrite_blocks(item, url_map)

    # Deduplicar pending
    pending = list(dict.fromkeys(pending))

    if pending:
        item.add_warning("MEDIA_REWRITE_PENDING")
        log.warn(
            "media_rewrite_pending",
            source_id=str(item.source.id),
            pending_count=len(pending),
            pending_urls=pending[:5],  # log primer 5 per no saturar
        )

    if rewritten > 0:
        log.info(
            "media_urls_rewritten",
            source_id=str(item.source.id),
            rewritten=rewritten,
        )

    return {
        "rewritten": rewritten,
        "pending": pending,
        "pending_count": len(pending),
    }
