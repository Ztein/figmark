from __future__ import annotations

import base64
import io
import shutil
from dataclasses import dataclass

import fitz
import pytesseract
from PIL import Image

from .config import Config

# ============================================================================
# Tekniska konstanter — tuna här om du behöver olika beteende.
# Språket kommer från config.yaml (ocr.language) eftersom det varierar med PDF:en.
# ============================================================================

# Tesseract-tröskel: under detta antal tecken → Gemma-fallback
MIN_CHARS_PER_PAGE = 40
# Tesseract-tröskel: under detta confidence-medel → Gemma-fallback
MIN_MEAN_CONFIDENCE = 60
# DPI för sid-rendering till Tesseract (lokalt, kan vara högt)
RENDER_DPI = 300
# DPI för sid-rendering till Gemma-OCR-fallback (lägre för payload-tak)
VISION_DPI = 150
# JPEG-kvalitet (0-100) för Gemma-OCR-payload
VISION_JPEG_QUALITY = 80
# Tak för svarsläng från Gemma-OCR-anrop
OCR_MAX_TOKENS = 2000
# Prompt för Gemma-OCR-fallback (transkribering, inte syntolkning)
OCR_PROMPT = (
    "Transkribera all text som syns i bilden, exakt som den står. "
    "Bevara radbrytningar och styckesindelning så långt som möjligt. "
    "Skriv inget annat än den transkriberade texten."
)


@dataclass
class OcrResult:
    text: str
    mean_confidence: float


_tesseract_checked = False


def _ensure_tesseract() -> None:
    global _tesseract_checked
    if _tesseract_checked:
        return
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Hittar inte 'tesseract' på PATH. Installera med:\n"
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
    for text, conf in zip(data.get("text", []), data.get("conf", [])):
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


def ocr_page_with_vision(page: fitz.Page, client, cfg: Config) -> str:
    # Lägre DPI + JPEG för att hålla payload under vision-API:ts gräns.
    image = render_page(page, VISION_DPI)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=VISION_JPEG_QUALITY, optimize=True)
    img_bytes = buf.getvalue()
    print(
        f"    Vision-payload: {len(img_bytes)/1024:.0f} KB JPEG "
        f"({image.width}x{image.height} @ {VISION_DPI} DPI, q={VISION_JPEG_QUALITY})",
        flush=True,
    )
    data_uri = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode("ascii")

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
    return (response.choices[0].message.content or "").strip()
