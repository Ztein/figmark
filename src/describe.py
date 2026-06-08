from __future__ import annotations

import base64
import io
import mimetypes
import time
from pathlib import Path

from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from PIL import Image

from .config import Config
from .context import ContextText

# Tekniska konstanter — tuna här om du behöver.
TIMEOUT_SECONDS = 60
MAX_RETRIES = 3
MAX_TOKENS = 600
# Berget har strikt payload-tak — empiriskt får vi 413 redan vid ~917 KB PNG
# (efter base64-expansion blir det ~1.22 MB). 500 KB raw → ~670 KB base64
# ger oss god marginal mot 413.
MAX_PAYLOAD_BYTES = 500_000
# Max-dimension efter resize. 1500 px räcker gott för syntolkning.
MAX_IMAGE_DIM = 1500
JPEG_QUALITY = 85


def make_client(cfg: Config) -> OpenAI:
    return OpenAI(
        api_key=cfg.api.api_key,
        base_url=cfg.api.base_url,
        timeout=TIMEOUT_SECONDS,
    )


def _prepare_image_for_api(path: Path) -> tuple[bytes, str]:
    """Returnera (bytes, mime). Resizar och konverterar till JPEG om bilden är
    större än API:ts payload-tak. Liten bild lämnas oförändrad."""
    raw = path.read_bytes()
    if len(raw) <= MAX_PAYLOAD_BYTES:
        mime, _ = mimetypes.guess_type(path.name)
        return raw, mime or "image/png"

    img = Image.open(io.BytesIO(raw))
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > MAX_IMAGE_DIM:
        img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))

    quality = JPEG_QUALITY
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    while len(buf.getvalue()) > MAX_PAYLOAD_BYTES and quality > 30:
        quality -= 15
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)

    print(
        f"    [resize] {path.name}: {len(raw)//1024} KB → {len(buf.getvalue())//1024} KB "
        f"({img.size[0]}x{img.size[1]} JPEG q={quality})",
        flush=True,
    )
    return buf.getvalue(), "image/jpeg"


def _image_to_data_uri(path: Path) -> str:
    payload, mime = _prepare_image_for_api(path)
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _build_user_text(base_prompt: str, context: ContextText | None) -> str:
    """Lägg in eventuell text-kontext före uppgiften i prompten."""
    if context is None or context.is_empty():
        return base_prompt
    return f"{context.format_for_prompt()}\n\n[Uppgift]\n{base_prompt}"


def describe_image(
    client: OpenAI,
    image_path: Path,
    description_path: Path,
    cfg: Config,
    context: ContextText | None = None,
) -> str:
    if description_path.exists():
        cached = description_path.read_text(encoding="utf-8").strip()
        if cached:
            return cached

    data_uri = _image_to_data_uri(image_path)
    user_text = _build_user_text(cfg.description.prompt, context)

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=cfg.api.model,
                max_tokens=MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    }
                ],
            )
            text = (response.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError(
                    f"API returnerade tomt innehåll för {image_path.name} "
                    f"(modell={cfg.api.model}). Detta är troligen ett tecken på "
                    f"att modellen inte stöder bild-input eller att prompten avvisades."
                )
            description_path.parent.mkdir(parents=True, exist_ok=True)
            description_path.write_text(text, encoding="utf-8")
            return text
        except (APITimeoutError, RateLimitError, APIError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = 2 ** (attempt - 1)
                print(
                    f"    [retry {attempt}/{MAX_RETRIES}] {image_path.name}: "
                    f"{type(e).__name__}: {e}. Väntar {wait}s …",
                    flush=True,
                )
                time.sleep(wait)

    raise RuntimeError(
        f"Misslyckades med att beskriva {image_path.name} efter "
        f"{MAX_RETRIES} försök mot {cfg.api.base_url} "
        f"(modell={cfg.api.model}). Senaste fel: {type(last_error).__name__}: {last_error}"
    )
