"""Describe a raster image with the vision model.

Covers payload preparation (resize/encode under the API's size cap), prompt
composition (document summary + surrounding text + output language + the
significance skip gate), the chat completion call with retries, and on-disk
caching of the result. ``compose_prompt`` and ``language_instruction`` are shared
with the diagram and summary paths.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import mimetypes
import time
from pathlib import Path

from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from PIL import Image

from .config import Config
from .context import ContextText

logger = logging.getLogger("figmark.describe")

# Technical constants — tune here if you need to.
TIMEOUT_SECONDS = 60
MAX_RETRIES = 3
MAX_TOKENS = 600
# Some providers enforce a strict payload cap — empirically we see a 413 already
# at ~917 KB PNG (which expands to ~1.22 MB after base64). 500 KB raw → ~670 KB
# base64 gives a comfortable margin below the 413.
MAX_PAYLOAD_BYTES = 500_000
# Max dimension after resize. 1500 px is plenty for a description.
MAX_IMAGE_DIM = 1500
JPEG_QUALITY = 85

# Significance gate: when enabled, the model is told to answer with this exact
# marker for purely decorative images. The token is code-owned (parsed below),
# so it stays language-neutral even though the prompts around it are Swedish.
SKIP_MARKER = "[SKIP]"
SIGNIFICANCE_INSTRUCTION = (
    "Om bilden är rent dekorativ och inte tillför någon information till läsaren "
    "(till exempel en logotyp, en dekorativ linje, en bakgrund, en ikon eller en "
    f"bård), svara med exakt {SKIP_MARKER} och ingenting annat."
)


def is_skip(text: str | None) -> bool:
    """True if a description is the significance-gate skip marker (decorative image)."""
    return text is not None and text.strip().upper().startswith(SKIP_MARKER)


def cache_fingerprint(*parts: object) -> str:
    """Short, stable hash of the inputs that determine a description's content.

    Folded into the cache filename so that changing the model, prompt, output
    language, significance gate, or context settings produces a different key — a
    cache miss that regenerates — instead of silently reusing output produced under
    the old config. (T-034)
    """
    blob = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:10]


def language_instruction(output: str) -> str:
    """Clause that controls the model's output language.

    "auto" (or empty) tells the model to answer in the document's own language,
    using the document text/context already present in the prompt. Any other value
    forces that language explicitly. Written in English because it is a meta
    instruction about output — models follow it regardless of the target language.
    """
    out = (output or "").strip()
    if out.lower() in ("", "auto", "document"):
        return (
            "Write your answer in the same language as the document text and context "
            "provided in this prompt. Do not translate it into another language."
        )
    return f"Write your answer in {out}."


def make_client(cfg: Config) -> OpenAI:
    return OpenAI(
        api_key=cfg.api.api_key,
        base_url=cfg.api.base_url,
        timeout=TIMEOUT_SECONDS,
    )


def _prepare_image_for_api(path: Path) -> tuple[bytes, str]:
    """Return (bytes, mime). Resizes and converts to JPEG if the image is larger
    than the API's payload cap. A small image is left unchanged."""
    raw = path.read_bytes()
    if len(raw) <= MAX_PAYLOAD_BYTES:
        mime, _ = mimetypes.guess_type(path.name)
        return raw, mime or "image/png"

    img: Image.Image = Image.open(io.BytesIO(raw))
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
        f"    [resize] {path.name}: {len(raw) // 1024} KB → {len(buf.getvalue()) // 1024} KB "
        f"({img.size[0]}x{img.size[1]} JPEG q={quality})",
        flush=True,
    )
    return buf.getvalue(), "image/jpeg"


def _image_to_data_uri(path: Path) -> str:
    payload, mime = _prepare_image_for_api(path)
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def compose_prompt(
    task: str,
    *,
    doc_summary: str | None = None,
    context: ContextText | None = None,
    significance: bool = False,
    language: str | None = None,
) -> str:
    """Build the user text: optional document summary + text context, then the task.

    The scaffolding labels are English (matching the context labels); the task
    content itself stays in whatever language the prompt is written in. When
    `significance` is set, the skip instruction is appended to the task. When
    `language` is given, an output-language instruction is appended to the task.
    """
    task_text = task if not significance else f"{task}\n\n{SIGNIFICANCE_INSTRUCTION}"
    if language is not None:
        task_text = f"{task_text}\n\n{language_instruction(language)}"

    sections: list[str] = []
    if doc_summary and doc_summary.strip():
        sections.append(f"[Document type]\n{doc_summary.strip()}")
    if context is not None and not context.is_empty():
        sections.append(context.format_for_prompt())

    if not sections:
        return task_text
    sections.append(f"[Task]\n{task_text}")
    return "\n\n".join(sections)


def describe_image(
    client: OpenAI,
    image_path: Path,
    description_path: Path,
    cfg: Config,
    context: ContextText | None = None,
    doc_summary: str | None = None,
    language: str | None = None,
) -> str:
    if description_path.exists():
        cached = description_path.read_text(encoding="utf-8").strip()
        if cached:
            return cached

    data_uri = _image_to_data_uri(image_path)
    user_text = compose_prompt(
        cfg.description.prompt,
        doc_summary=doc_summary,
        context=context,
        significance=cfg.significance.enabled,
        language=language if language is not None else cfg.language.output,
    )

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
            choice = response.choices[0]
            text = (choice.message.content or "").strip()
            if not text:
                # An empty completion is a hard error, deliberately NOT retried:
                # with FAIL_FAST a retry just repeats the same failure, and an empty
                # body almost always means the model can't take image input or
                # rejected the prompt — not a transient blip. (T-033)
                raise RuntimeError(
                    f"The API returned empty content for {image_path.name} "
                    f"(model={cfg.api.model}). This usually means the model does "
                    f"not support image input or the prompt was rejected."
                )
            if getattr(choice, "finish_reason", None) == "length":
                # Truncated at the token cap — the description is likely cut
                # mid-sentence. Warn loudly (do not silently cache a partial as if
                # complete) but still keep what we got. (T-033)
                logger.warning(
                    "Description for %s was truncated at the %d-token cap "
                    "(finish_reason=length); it may be cut mid-sentence.",
                    image_path.name,
                    MAX_TOKENS,
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
                    f"{type(e).__name__}: {e}. Waiting {wait}s …",
                    flush=True,
                )
                time.sleep(wait)

    raise RuntimeError(
        f"Failed to describe {image_path.name} after "
        f"{MAX_RETRIES} attempts against {cfg.api.base_url} "
        f"(model={cfg.api.model}). Last error: {type(last_error).__name__}: {last_error}"
    )
