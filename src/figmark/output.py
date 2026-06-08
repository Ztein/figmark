from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .diagrams import PLACEHOLDER as DIAGRAM_PLACEHOLDER
from .images import ExtractedImage
from .pdf_loader import Block, DiagramBlock, ImageBlock, TextBlock

# Inline template for raster images + page separator, used in the plain-text
# (raw) output. Rarely tuned, so it lives here rather than in config.yaml.
IMAGE_PLACEHOLDER = "[Image: {description}]"
PAGE_SEPARATOR = "\n\n--- Page {page} ---\n\n"


@dataclass
class PageData:
    page_num: int
    is_ocr: bool
    blocks: list[Block] = field(default_factory=list)
    ocr_text: str | None = None
    images: list[ExtractedImage] = field(default_factory=list)
    descriptions: dict[int, str] = field(default_factory=dict)  # xref -> description
    # region_index -> description
    diagram_descriptions: dict[int, str] = field(default_factory=dict)


def assemble(pages: list[PageData], cfg: Config) -> tuple[str, str]:
    """Assemble the plain-text outputs.

    Returns (raw_text, full_text):
    - raw_text: text only, no descriptions.
    - full_text: text with image/diagram descriptions inlined as placeholders.
    """
    raw_parts: list[str] = []
    full_parts: list[str] = []

    for page in pages:
        separator = PAGE_SEPARATOR.format(page=page.page_num)
        raw_parts.append(separator)
        full_parts.append(separator)

        if page.is_ocr:
            raw_parts.append(page.ocr_text or "")
            full_parts.append(page.ocr_text or "")
            sorted_images = sorted(
                page.images,
                key=lambda im: (im.bbox[1] if im.bbox else 0.0, im.bbox[0] if im.bbox else 0.0),
            )
            for img in sorted_images:
                desc = page.descriptions.get(img.xref, "")
                if desc:
                    full_parts.append("\n\n" + IMAGE_PLACEHOLDER.format(description=desc))
        else:
            page_raw: list[str] = []
            page_full: list[str] = []
            for block in page.blocks:
                if isinstance(block, TextBlock):
                    page_raw.append(block.text)
                    page_full.append(block.text)
                elif isinstance(block, ImageBlock):
                    desc = page.descriptions.get(block.xref, "")
                    if desc:
                        page_full.append(IMAGE_PLACEHOLDER.format(description=desc))
                elif isinstance(block, DiagramBlock):
                    desc = page.diagram_descriptions.get(block.region_index, "")
                    if desc:
                        page_full.append(DIAGRAM_PLACEHOLDER.format(description=desc))
            raw_parts.append("\n\n".join(page_raw))
            full_parts.append("\n\n".join(page_full))

    return "".join(raw_parts).strip() + "\n", "".join(full_parts).strip() + "\n"


def _blockquote(text: str) -> str:
    """Render a (possibly multi-paragraph) description as a Markdown blockquote."""
    out: list[str] = []
    for line in text.strip().splitlines():
        out.append(f"> {line}" if line.strip() else ">")
    return "\n".join(out)


def _figure(kind: str, page_num: int, rel_path: str, description: str) -> str:
    """Render one figure: the embedded image plus its description as a caption."""
    alt = f"{kind}, page {page_num}"
    return f"![{alt}]({rel_path})\n\n{_blockquote(description)}"


def to_markdown(pages: list[PageData]) -> str:
    """Assemble the primary Markdown output.

    Text flows as paragraphs; every described image and diagram is embedded with
    `![...](path)` followed by its AI description as a blockquote caption, in
    reading order. Page boundaries are kept as HTML comments for provenance.
    """
    parts: list[str] = []

    for page in pages:
        parts.append(f"<!-- page {page.page_num} -->")

        if page.is_ocr:
            if page.ocr_text and page.ocr_text.strip():
                parts.append(page.ocr_text.strip())
            sorted_images = sorted(
                page.images,
                key=lambda im: (im.bbox[1] if im.bbox else 0.0, im.bbox[0] if im.bbox else 0.0),
            )
            for img in sorted_images:
                desc = page.descriptions.get(img.xref, "")
                if desc:
                    parts.append(_figure("Image", page.page_num, f"images/{img.path.name}", desc))
        else:
            img_by_xref = {img.xref: img for img in page.images}
            for block in page.blocks:
                if isinstance(block, TextBlock):
                    if block.text.strip():
                        parts.append(block.text.strip())
                elif isinstance(block, ImageBlock):
                    desc = page.descriptions.get(block.xref, "")
                    if desc:
                        img = img_by_xref.get(block.xref)
                        rel = (
                            f"images/{img.path.name}"
                            if img is not None
                            else f"images/page-{page.page_num:03d}-img-xref-{block.xref}.png"
                        )
                        parts.append(_figure("Image", page.page_num, rel, desc))
                elif isinstance(block, DiagramBlock):
                    desc = page.diagram_descriptions.get(block.region_index, "")
                    if desc:
                        rel = (
                            f"diagrams/page-{page.page_num:03d}-diagram-"
                            f"{block.region_index:02d}.png"
                        )
                        parts.append(_figure("Diagram", page.page_num, rel, desc))

    return "\n\n".join(p for p in parts if p).strip() + "\n"
