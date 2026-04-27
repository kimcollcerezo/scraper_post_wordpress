"""Transform — Fase 3. HTML → blocs Despertare. ADR-0011."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from migration_agent.models.intermediate import Block, IntermediateItem

# Tags HTML inline permesos dins paragraph/quote
ALLOWED_INLINE_TAGS = {"strong", "em", "a", "br", "span", "code", "s", "u"}
BLOCKED_TAGS = {"script", "style", "object"}


def transform(item: IntermediateItem, policy: dict[str, Any] | None = None) -> IntermediateItem:
    """Transforma el contingut HTML a blocs Despertare. Modifica item in-place."""
    raw_html = item.content.html or ""
    if not raw_html.strip():
        item.content.blocks = []
        return item

    internal_domain = _domain_from_url(item.source.site_url)
    blocks = _html_to_blocks(raw_html, internal_domain=internal_domain)
    item.content.blocks = blocks

    # Calcular raw_html_ratio
    total = len(blocks)
    raw_count = sum(1 for b in blocks if b.type == "raw_html")

    if total > 0:
        ratio = raw_count / total
        warn_threshold = (policy or {}).get("transform", {}).get("raw_html_warning_threshold", 0.20)
        block_threshold = (policy or {}).get("transform", {}).get("raw_html_block_threshold", 0.50)

        if ratio > block_threshold:
            item.add_warning("HIGH_RAW_HTML_RATIO")
            item.set_status("pending_review")
        elif ratio > warn_threshold:
            item.add_warning("HIGH_RAW_HTML_RATIO")

    # Derivar SEO si no existeix
    _derive_seo(item)

    return item


def _html_to_blocks(html: str, internal_domain: str = "") -> list[Block]:
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body") or soup
    blocks: list[Block] = []

    for el in body.children:
        if not isinstance(el, Tag):
            continue
        block = _tag_to_block(el, internal_domain=internal_domain)
        if block:
            blocks.append(block)

    return blocks


def _tag_to_block(el: Tag, internal_domain: str = "") -> Block | None:
    tag = el.name.lower() if el.name else ""

    if tag in BLOCKED_TAGS:
        return None

    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return Block(type="heading", data={"level": int(tag[1]), "text": el.get_text(strip=True)})

    if tag == "p":
        inner = _serialize_inline(el, internal_domain=internal_domain)
        if not inner.strip():
            return None
        return Block(type="paragraph", data={"html": f"<p>{inner}</p>"})

    if tag == "blockquote":
        cite = el.find("cite")
        cite_text = cite.get_text(strip=True) if cite else None
        if cite:
            cite.decompose()
        inner = _serialize_inline(el, internal_domain=internal_domain)
        return Block(type="quote", data={"html": inner, "citation": cite_text})

    if tag in ("ul", "ol"):
        items = [li.get_text(strip=True) for li in el.find_all("li", recursive=False)]
        return Block(type="list", data={"ordered": tag == "ol", "items": items})

    if tag == "pre":
        code_el = el.find("code")
        content = code_el.get_text() if code_el else el.get_text()
        return Block(type="code", data={"content": content})

    if tag == "hr":
        return Block(type="separator", data={})

    if tag == "table":
        return Block(type="table", data={"html": str(el)})

    if tag == "figure":
        imgs = el.find_all("img")
        figcap = el.find("figcaption")
        caption = figcap.get_text(strip=True) if figcap else None
        if len(imgs) == 1:
            img = imgs[0]
            return Block(type="image", data={
                "src": img.get("src", ""),
                "alt": img.get("alt", ""),
                "caption": caption,
                "width": img.get("width"),
                "height": img.get("height"),
            })
        if len(imgs) > 1:
            return Block(type="gallery", data={
                "images": [{"src": i.get("src", ""), "alt": i.get("alt", "")} for i in imgs]
            })

    if tag == "img":
        return Block(type="image", data={
            "src": el.get("src", ""),
            "alt": el.get("alt", ""),
            "width": el.get("width"),
            "height": el.get("height"),
        })

    if tag == "iframe":
        src = el.get("src", "")
        provider = _detect_embed_provider(src)
        if provider:
            return Block(type="embed", data={"url": src, "provider": provider})
        # iframe no reconegut → raw_html amb warning
        return Block(
            type="raw_html",
            data={"html": str(el)},
            legacy=True,
            warning="RAW_HTML_BLOCK_USED",
        )

    if tag == "div":
        # Intent de parsing recursiu dels fills
        child_blocks: list[Block] = []
        for child in el.children:
            if isinstance(child, Tag):
                b = _tag_to_block(child, internal_domain=internal_domain)
                if b:
                    child_blocks.append(b)
        if child_blocks:
            return None  # els fills s'afegiran a nivell superior? No: retornem group
            # Per simplicitat MVP: si tots fills son nadius, retornem un grup
        return Block(
            type="raw_html",
            data={"html": str(el)},
            legacy=True,
            warning="RAW_HTML_BLOCK_USED",
        )

    # Fallback
    return Block(
        type="raw_html",
        data={"html": str(el)},
        legacy=True,
        warning="RAW_HTML_BLOCK_USED",
    )


def _serialize_inline(el: Tag, internal_domain: str = "") -> str:
    """Serialitza contingut inline mantenint tags permesos.

    Afegeix rel="nofollow" als <a> que apunten a dominis externs.
    """
    result = []
    for child in el.children:
        if isinstance(child, Tag):
            if child.name in ALLOWED_INLINE_TAGS:
                if child.name == "a":
                    result.append(_serialize_anchor(child, internal_domain))
                else:
                    result.append(str(child))
            else:
                result.append(child.get_text())
        else:
            result.append(str(child))
    return "".join(result)


def _serialize_anchor(a: Tag, internal_domain: str = "") -> str:
    """Serialitza un <a> afegint rel="nofollow" si l'enllaç és extern."""
    href = a.get("href", "") or ""
    is_external = (
        href.startswith("http")
        and bool(internal_domain)
        and internal_domain not in href
    )
    if is_external:
        existing_rel = a.get("rel", [])
        if isinstance(existing_rel, str):
            existing_rel = existing_rel.split()
        rels = list(existing_rel)
        if "nofollow" not in rels:
            rels.append("nofollow")
        a["rel"] = " ".join(rels)
    return str(a)


def _detect_embed_provider(url: str) -> str | None:
    if not url:
        return None
    providers = {
        "youtube.com": "youtube",
        "youtu.be": "youtube",
        "vimeo.com": "vimeo",
        "twitter.com": "twitter",
        "x.com": "twitter",
        "instagram.com": "instagram",
        "spotify.com": "spotify",
        "soundcloud.com": "soundcloud",
    }
    for domain, name in providers.items():
        if domain in url:
            return name
    return None


def _domain_from_url(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else ""


def _derive_seo(item: IntermediateItem) -> None:
    """Deriva valors SEO base si no existeixen."""
    seo = item.seo
    if not seo.title:
        seo.title = item.content.title
    if not seo.description and item.content.excerpt:
        seo.description = item.content.excerpt
    if not seo.og_title:
        seo.og_title = seo.title
    if not seo.og_description:
        seo.og_description = seo.description
    if not seo.og_image and item.hero:
        seo.og_image = item.hero.source_url

    if seo.source == "derived":
        item.add_warning("SEO_INCOMPLETE") if not seo.description else None
