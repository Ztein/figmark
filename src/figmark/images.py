"""Extract embedded raster images (JPEG/PNG XObjects) from a page.

Filters out decorative icons below a minimum size and, in OCR mode, full-page
images (where the "image" is the scanned page of text rather than an
illustration). Vector charts are handled separately in ``diagrams.py``.
"""

from __future__ import annotations

import hashlib
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
    # Content hash (sha256, 32 hex chars = 128 bits) — keys the description
    # cache so the same embedded image is described once, whatever page or xref
    # it appears under. Kept long: with the shared cross-request cache (T-061) a
    # truncated digest would let a crafted collision poison another document's
    # description.
    digest: str = ""


@dataclass
class ImageExtraction:
    """The kept images plus why others were dropped, so the caller can explain a
    "0 saved" line rather than make it look like a bug. (T-002)"""

    images: list[ExtractedImage]
    skipped_small: int = 0  # below MIN_IMAGE_WIDTH/HEIGHT (decorative icons)
    skipped_full_page: int = 0  # full-page image skipped in OCR mode
    # In the page's resource dict but never drawn on the page. LibreOffice-made
    # PDFs list every document image on every page — extracting those would turn
    # a 6-image document into hundreds of phantom figures (T-054).
    skipped_not_drawn: int = 0


def extract_images_from_page(
    doc: fitz.Document,
    page: fitz.Page,
    page_num: int,
    out_dir: Path,
    skip_full_page: bool = False,
) -> ImageExtraction:
    """Extract images from a page.

    skip_full_page=True skips images covering >80% of the page area — used in
    OCR mode, where the whole page is typically an image of text rather than a
    separate illustration that needs describing. The returned ImageExtraction also
    reports how many images were filtered (and why).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[ExtractedImage] = []
    skipped_small = 0
    skipped_full_page = 0

    image_list = page.get_images(full=True)
    if not image_list:
        return ImageExtraction(results)

    rect_lookup: dict[int, list[tuple[float, float, float, float]]] = {}
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref")
        if xref:
            rect_lookup.setdefault(xref, []).append(tuple(info.get("bbox", (0, 0, 0, 0))))

    page_area = page.rect.width * page.rect.height
    skipped_not_drawn = sum(1 for t in image_list if t[0] not in rect_lookup)

    for index, img_tuple in enumerate(image_list, start=1):
        xref = img_tuple[0]
        if xref not in rect_lookup:
            # In /Resources but never drawn on this page (counted above).
            continue
        try:
            base = doc.extract_image(xref)
        except Exception as exc:  # noqa: BLE001 — surface loudly, never drop silently
            print(
                f"WARNING: could not extract image xref={xref} on page {page_num} "
                f"({type(exc).__name__}: {exc}) — skipping this image",
                flush=True,
            )
            continue
        if base is None:
            print(
                f"WARNING: image xref={xref} on page {page_num} returned no data "
                "— skipping this image",
                flush=True,
            )
            continue

        width = base.get("width", 0)
        height = base.get("height", 0)
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            skipped_small += 1
            continue

        bboxes = rect_lookup.get(xref, [])
        bbox = bboxes[0] if bboxes else None

        if skip_full_page and bbox and page_area > 0:
            bbox_area = max(0.0, (bbox[2] - bbox[0])) * max(0.0, (bbox[3] - bbox[1]))
            if bbox_area / page_area > FULL_PAGE_AREA_RATIO:
                skipped_full_page += 1
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
                digest=hashlib.sha256(img_bytes).hexdigest()[:32],
            )
        )

    return ImageExtraction(results, skipped_small, skipped_full_page, skipped_not_drawn)
