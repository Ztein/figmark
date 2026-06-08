from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .diagrams import PLACEHOLDER as DIAGRAM_PLACEHOLDER
from .images import ExtractedImage
from .pdf_loader import Block, DiagramBlock, ImageBlock, TextBlock

# Inklippningsmall för raster-bilder + sid-separator. Användarsynligt i full_text.txt,
# men sällan något man tunar — så det bor här istället för i config.yaml.
IMAGE_PLACEHOLDER = "[Bild: {description}]"
PAGE_SEPARATOR = "\n\n--- Sida {page} ---\n\n"


@dataclass
class PageData:
    page_num: int
    is_ocr: bool
    blocks: list[Block] = field(default_factory=list)
    ocr_text: str | None = None
    images: list[ExtractedImage] = field(default_factory=list)
    descriptions: dict[int, str] = field(default_factory=dict)  # xref -> description
    diagram_descriptions: dict[int, str] = field(default_factory=dict)  # region_index -> description


def assemble(pages: list[PageData], cfg: Config) -> tuple[str, str]:
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
