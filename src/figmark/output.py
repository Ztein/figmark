"""Assemble the extracted text and figure descriptions into the outputs.

Produces the primary Markdown (``to_markdown`` — figures embedded with
``![...](path)`` and their descriptions as blockquote captions, in reading order)
and the plain-text raw/full text (``assemble``). Descriptions marked by the
significance gate as decorative are omitted from every output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .describe import is_skip
from .diagrams import PLACEHOLDER as DIAGRAM_PLACEHOLDER
from .images import ExtractedImage
from .pdf_loader import Block, DiagramBlock, ImageBlock, TableBlock, TextBlock
from .structure import as_list_item, body_font_size, heading_level, heading_levels


def _shown(description: str) -> str:
    """A description that should appear in the output, or "" if it's a skip marker."""
    return "" if is_skip(description) else description


def _markdown_table(rows: list[list[str]]) -> str:
    """Render a detected table as a GitHub-flavoured Markdown table.

    The first row is the header. Ragged rows are padded; ``|`` is escaped. Returns
    "" for an empty grid.
    """
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)

    def fmt(row: list[str]) -> str:
        cells = list(row) + [""] * (ncols - len(row))
        return "| " + " | ".join((c or "").replace("|", "\\|") for c in cells) + " |"

    lines = [fmt(rows[0]), "| " + " | ".join(["---"] * ncols) + " |"]
    lines += [fmt(r) for r in rows[1:]]
    return "\n".join(lines)


# Inline template for raster images + page separator, used in the plain-text
# (raw) output. Rarely tuned, so it lives here rather than in config.yaml.
IMAGE_PLACEHOLDER = "[Image: {description}]"
PAGE_SEPARATOR = "\n\n--- Page {page} ---\n\n"


@dataclass
class PageData:
    page_num: int
    is_ocr: bool
    page_height: float = 0.0  # PDF page height in pt; 0.0 when unknown
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
                desc = _shown(page.descriptions.get(img.xref, ""))
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
                    desc = _shown(page.descriptions.get(block.xref, ""))
                    if desc:
                        page_full.append(IMAGE_PLACEHOLDER.format(description=desc))
                elif isinstance(block, DiagramBlock):
                    desc = _shown(page.diagram_descriptions.get(block.region_index, ""))
                    if desc:
                        page_full.append(DIAGRAM_PLACEHOLDER.format(description=desc))
                elif isinstance(block, TableBlock):
                    # A table is content, not an AI description — keep it in both
                    # the raw and full text so the data is not lost.
                    table_md = _markdown_table(block.rows)
                    if table_md:
                        page_raw.append(table_md)
                        page_full.append(table_md)
            raw_parts.append("\n\n".join(page_raw))
            full_parts.append("\n\n".join(page_full))

    return "".join(raw_parts).strip() + "\n", "".join(full_parts).strip() + "\n"


def build_figure_manifest(pages: list[PageData]) -> list[dict]:
    """A machine-readable index of every extracted figure (T-041).

    One entry per raster image and vector diagram, in page order:
    ``{id, page, kind, bbox, path, description, skipped}``. ``path`` is relative to
    the output directory (resolves to the file the Markdown also embeds).
    Significance-skipped figures are kept with ``skipped: true`` and an empty
    description, so nothing silently disappears from the index.
    """
    figures: list[dict] = []
    for page in pages:
        for img in page.images:
            desc = page.descriptions.get(img.xref, "")
            if not desc.strip():
                continue  # extracted but never described (e.g. an extraction error)
            figures.append(
                {
                    "id": img.path.stem,
                    "page": page.page_num,
                    "kind": "image",
                    "bbox": list(img.bbox) if img.bbox else None,
                    "path": f"images/{img.path.name}",
                    "description": _shown(desc),
                    "skipped": is_skip(desc),
                }
            )
        for block in page.blocks:
            if not isinstance(block, DiagramBlock):
                continue
            desc = page.diagram_descriptions.get(block.region_index, "")
            if not desc.strip():
                continue
            name = f"page-{page.page_num:03d}-diagram-{block.region_index:02d}.png"
            figures.append(
                {
                    "id": name[:-4],
                    "page": page.page_num,
                    "kind": "diagram",
                    "bbox": list(block.bbox),
                    "path": f"diagrams/{name}",
                    "description": _shown(desc),
                    "skipped": is_skip(desc),
                }
            )
    return figures


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


def _render_text_block(block: TextBlock, body, size_level, bold_body_level) -> str:
    """Render a text block as a Markdown heading, list item, or paragraph (T-042)."""
    level = heading_level(block, body, size_level, bold_body_level)
    if level:
        return "#" * level + " " + " ".join(block.text.split())
    item = as_list_item(block.text)
    if item:
        return item
    return block.text.strip()


def to_markdown(pages: list[PageData]) -> str:
    """Assemble the primary Markdown output.

    Text flows as paragraphs; every described image and diagram is embedded with
    `![...](path)` followed by its AI description as a blockquote caption, in
    reading order. Page boundaries are kept as HTML comments for provenance.
    """
    parts: list[str] = []

    # Document-level typography baseline, computed once for heading inference (T-042).
    body = body_font_size(pages)
    size_level, bold_body_level = heading_levels(pages, body)

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
                desc = _shown(page.descriptions.get(img.xref, ""))
                if desc:
                    parts.append(_figure("Image", page.page_num, f"images/{img.path.name}", desc))
        else:
            img_by_xref = {img.xref: img for img in page.images}
            for block in page.blocks:
                if isinstance(block, TextBlock):
                    if block.text.strip():
                        parts.append(_render_text_block(block, body, size_level, bold_body_level))
                elif isinstance(block, ImageBlock):
                    desc = _shown(page.descriptions.get(block.xref, ""))
                    if desc:
                        matched = img_by_xref.get(block.xref)
                        rel = (
                            f"images/{matched.path.name}"
                            if matched is not None
                            else f"images/page-{page.page_num:03d}-img-xref-{block.xref}.png"
                        )
                        parts.append(_figure("Image", page.page_num, rel, desc))
                elif isinstance(block, DiagramBlock):
                    desc = _shown(page.diagram_descriptions.get(block.region_index, ""))
                    if desc:
                        rel = (
                            f"diagrams/page-{page.page_num:03d}-diagram-"
                            f"{block.region_index:02d}.png"
                        )
                        parts.append(_figure("Diagram", page.page_num, rel, desc))
                elif isinstance(block, TableBlock):
                    table_md = _markdown_table(block.rows)
                    if table_md:
                        parts.append(table_md)

    return "\n\n".join(p for p in parts if p).strip() + "\n"
