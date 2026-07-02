"""OCR for scanned pages.

Runs Tesseract first (free, local) and falls back to the vision model when
Tesseract's character count or mean confidence is too low. The fallback is
shouted loudly by the caller so it never hides in the logs.
"""

from __future__ import annotations

import base64
import io
import shutil
from dataclasses import dataclass

import fitz
import pytesseract
from openai import APIError
from PIL import Image

from .config import Config
from .describe import MAX_IMAGE_DIM, MAX_PAYLOAD_BYTES

# ============================================================================
# Technical constants — tune here if you need different behaviour.
# The language comes from config.yaml (ocr.language) since it varies per PDF.
# ============================================================================

# Tesseract threshold: below this character count → vision-OCR fallback
MIN_CHARS_PER_PAGE = 40
# Tesseract threshold: below this mean confidence → vision-OCR fallback
MIN_MEAN_CONFIDENCE = 60
# DPI for page rendering to Tesseract (local, can be high)
RENDER_DPI = 300
# DPI for page rendering to the vision-OCR fallback (lower, to stay under the payload cap)
VISION_DPI = 150
# JPEG quality (0-100) for the vision-OCR payload
VISION_JPEG_QUALITY = 80
# Cap on the response length from a vision-OCR call
OCR_MAX_TOKENS = 2000
# Prompt for the vision-OCR fallback (transcription, not description)
OCR_PROMPT = (
    "Transcribe all text visible in the image, exactly as written. "
    "Preserve line breaks and paragraph structure as far as possible. "
    "Output nothing but the transcribed text."
)


@dataclass
class OcrResult:
    text: str
    mean_confidence: float


class VisionOCRError(RuntimeError):
    """Vision-model OCR of a scanned page failed in a way the operator can act on.

    Carries the page number and a specific, figmark-authored reason — the page image
    is too large for the model, the model rejected it, or it returned nothing — so
    the failure surfaces as an actionable message instead of a generic backend fault
    (T-048) or an opaque 500. The message is safe to show a client: it names the page
    and payload size, never the provider's raw error body.
    """

    def __init__(self, page_num: int, detail: str) -> None:
        self.page_num = page_num
        self.detail = detail
        super().__init__(f"Vision-OCR failed on page {page_num}: {detail}")


_tesseract_checked = False


def _ensure_tesseract() -> None:
    global _tesseract_checked
    if _tesseract_checked:
        return
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Could not find 'tesseract' on PATH. Install it with:\n"
            "  brew install tesseract tesseract-lang"
        )
    _tesseract_checked = True


def render_page(page: fitz.Page, dpi: int) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def ocr_page(page: fitz.Page, cfg: Config) -> OcrResult:
    _ensure_tesseract()
    image = render_page(page, RENDER_DPI)
    data = pytesseract.image_to_data(
        image,
        lang=cfg.ocr.language,
        output_type=pytesseract.Output.DICT,
    )

    words: list[str] = []
    confidences: list[float] = []
    for text, conf in zip(data.get("text", []), data.get("conf", []), strict=False):
        if not text or not text.strip():
            continue
        try:
            conf_value = float(conf)
        except (TypeError, ValueError):
            continue
        if conf_value < 0:
            continue
        words.append(text)
        confidences.append(conf_value)

    text = _reconstruct_text(data)
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrResult(text=text, mean_confidence=mean_conf)


def _reconstruct_text(data: dict) -> str:
    lines: dict[tuple[int, int, int, int], list[str]] = {}
    for i, text in enumerate(data.get("text", [])):
        if not text or not text.strip():
            continue
        key = (
            data["block_num"][i],
            data["par_num"][i],
            data["line_num"][i],
            data["page_num"][i],
        )
        lines.setdefault(key, []).append(text)
    sorted_keys = sorted(lines.keys())
    return "\n".join(" ".join(lines[k]) for k in sorted_keys)


def should_fallback(result: OcrResult) -> bool:
    if len(result.text.strip()) < MIN_CHARS_PER_PAGE:
        return True
    if result.mean_confidence < MIN_MEAN_CONFIDENCE:
        return True
    return False


def _encode_page_under_cap(image: Image.Image, page_num: int) -> bytes:
    """JPEG-encode a rendered page under the vision API's payload cap.

    Mirrors ``describe._prepare_image_for_api`` (resize to ``MAX_IMAGE_DIM``, then
    step the quality down). Unlike a figure — where an over-cap payload is sent
    best-effort — a *page* that still won't fit is a loud, actionable failure: we do
    not ship an over-cap payload only to get an opaque 413 back from the provider.
    """
    if max(image.size) > MAX_IMAGE_DIM:
        image = image.copy()
        image.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))

    quality = VISION_JPEG_QUALITY
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    while len(buf.getvalue()) > MAX_PAYLOAD_BYTES and quality > 30:
        quality -= 15
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=quality, optimize=True)

    size = len(buf.getvalue())
    if size > MAX_PAYLOAD_BYTES:
        raise VisionOCRError(
            page_num,
            f"the rendered page is still {size // 1024} KB after maximum downscaling "
            f"({image.size[0]}x{image.size[1]} JPEG q={quality}), above the "
            f"{MAX_PAYLOAD_BYTES // 1024} KB the vision model accepts. Lower the OCR "
            f"render DPI, or use a model with a larger image-input limit.",
        )
    return buf.getvalue()


def ocr_page_with_vision(
    page: fitz.Page, client, cfg: Config, *, page_num: int | None = None
) -> str:
    """Transcribe a scanned page with the vision model. Fails loud on a too-large or
    rejected page (``VisionOCRError``), never a bare provider 413 or an empty string.
    """
    page_num = page_num if page_num is not None else page.number + 1
    # Lower DPI + JPEG to keep the payload under the vision API's limit; the cap is
    # then enforced (and shrunk into) rather than assumed.
    image = render_page(page, VISION_DPI)
    img_bytes = _encode_page_under_cap(image, page_num)
    print(
        f"    Vision payload: {len(img_bytes) / 1024:.0f} KB JPEG "
        f"({image.width}x{image.height} @ {VISION_DPI} DPI, q≤{VISION_JPEG_QUALITY})",
        flush=True,
    )
    data_uri = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode("ascii")

    try:
        response = client.chat.completions.create(
            model=cfg.api.model,
            max_tokens=OCR_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
        )
    except APIError as e:
        # A rejection here is most often the page image exceeding the model's limit,
        # or a model that does not accept image input. Re-raise with page context and
        # a provider-body-free message (T-048) so the caller can map it cleanly.
        status = getattr(e, "status_code", None)
        raise VisionOCRError(
            page_num,
            f"the vision model rejected the {len(img_bytes) // 1024} KB page image "
            f"({type(e).__name__}"
            f"{f', HTTP {status}' if status else ''}). The page may exceed the "
            f"model's image-size limit, or the model may not accept image input.",
        ) from e

    text = (response.choices[0].message.content or "").strip()
    if not text:
        # An empty completion on the OCR path means no text was recovered — a hard
        # failure, not a blank page (a blank page never reaches vision fallback).
        raise VisionOCRError(
            page_num,
            f"the vision model returned no text (model={cfg.api.model}). It likely "
            f"does not support image input, or rejected the page.",
        )
    return text
