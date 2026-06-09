"""Extract embedded raster images (JPEG/PNG XObjects) from a page.

Filters out decorative icons below a minimum size and, in OCR mode, full-page
images (where the "image" is the scanned page of text rather than an
illustration). Vector charts are handled separately in ``diagrams.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

# Technical constants — images smaller than this (px) are treated as
# decorative icons and skipped.
MIN_IMAGE_WIDTH = 50
MIN_IMAGE_HEIGHT = 50
# Images covering more than this fraction of the page are skipped in OCR mode
# (there the "image" is the whole page of text).
FULL_PAGE_AREA_RATIO = 0.80


@dataclass
class ExtractedImage:
    path: Path
    page_num: int
    index: int
    xref: int
    bbox: tuple[float, float, float, float] | None


def extract_images_from_page(
    doc: fitz.Document,
    page: fitz.Page,
    page_num: int,
    out_dir: Path,
    skip_full_page: bool = False,
) -> list[ExtractedImage]:
    """Extract images from a page.

    skip_full_page=True skips images covering >80% of the page area — used in
    OCR mode, where the whole page is typically an image of text rather than a
    separate illustration that needs describing.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[ExtractedImage] = []

    image_list = page.get_images(full=True)
    if not image_list:
        return results

    rect_lookup: dict[int, list[tuple[float, float, float, float]]] = {}
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref")
        if xref:
            rect_lookup.setdefault(xref, []).append(tuple(info.get("bbox", (0, 0, 0, 0))))

    page_area = page.rect.width * page.rect.height

    for index, img_tuple in enumerate(image_list, start=1):
        xref = img_tuple[0]
        try:
            base = doc.extract_image(xref)
        except Exception:
            continue
        if base is None:
            continue

        width = base.get("width", 0)
        height = base.get("height", 0)
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            continue

        bboxes = rect_lookup.get(xref, [])
        bbox = bboxes[0] if bboxes else None

        if skip_full_page and bbox and page_area > 0:
            bbox_area = max(0.0, (bbox[2] - bbox[0])) * max(0.0, (bbox[3] - bbox[1]))
            if bbox_area / page_area > FULL_PAGE_AREA_RATIO:
                continue

        ext = base.get("ext", "png")
        img_bytes = base["image"]

        filename = f"page-{page_num:03d}-img-{index:02d}.{ext}"
        path = out_dir / filename
        path.write_bytes(img_bytes)

        results.append(
            ExtractedImage(
                path=path,
                page_num=page_num,
                index=index,
                xref=xref,
                bbox=bbox,
            )
        )

    return results
