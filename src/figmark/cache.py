"""Cache of figure descriptions, so an image seen before is not described again.

Slide decks built from one another reuse the same pictures; describing each copy
costs ~15 s on a laptop. The key is the image's pixels plus everything that
shapes the answer — prompt and request parameters (model, temperature, token
limit, ...). A new model or prompt therefore misses, never returns a stale
description. The endpoint URL and headers are not in the key: the same model
behind another URL gives the same answer, and headers carry the API key.

Stored in one local SQLite file (default ~/.cache/figmark/descriptions.sqlite);
nothing leaves the machine. Empty answers are never stored.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

from PIL import Image

DEFAULT_PATH = Path.home() / ".cache" / "figmark" / "descriptions.sqlite"


class DescriptionCache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "create table if not exists d (key text primary key, text text, model text, created real)"
        )
        self.lock = threading.Lock()
        self.inflight: dict[str, threading.Event] = {}  # key → set when its description is stored
        self.hits = self.misses = 0

    @staticmethod
    def key(image: Image.Image, prompt: str, params: dict) -> str:
        img = image.convert("RGBA")
        h = hashlib.sha256()
        h.update(f"{img.size}".encode())
        h.update(img.tobytes())
        h.update(prompt.encode())
        h.update(json.dumps(params, sort_keys=True, default=str).encode())
        return h.hexdigest()

    def get(self, key: str) -> str | None:
        """The stored description, or None — then the caller must describe the
        image and `put` the result. If the same image is being described right
        now (identical pictures in one batch), wait for that instead."""
        while True:
            with self.lock:
                row = self.db.execute("select text from d where key = ?", (key,)).fetchone()
                if row:
                    self.hits += 1
                    return row[0]
                pending = self.inflight.get(key)
                if pending is None:
                    self.inflight[key] = threading.Event()
                    self.misses += 1
                    return None
            pending.wait()
            with self.lock:  # the first caller failed or got an empty answer: try ourselves
                if not self.db.execute("select 1 from d where key = ?", (key,)).fetchone() and key not in self.inflight:
                    self.inflight[key] = threading.Event()
                    self.misses += 1
                    return None

    def put(self, key: str, text: str | None, model: str | None) -> None:
        """Store a description (never an empty one) and release anyone waiting."""
        with self.lock:
            if text and text.strip():
                self.db.execute("insert or replace into d values (?, ?, ?, ?)", (key, text, model, time.time()))
                self.db.commit()
            event = self.inflight.pop(key, None)
        if event:
            event.set()

    def size(self) -> int:
        with self.lock:
            return self.db.execute("select count(*) from d").fetchone()[0]


def install(cache: DescriptionCache) -> None:
    """Route Docling's API picture description through the cache.

    Docling calls `api_image_request` once per picture; wrapping that one
    function keeps the request, the answer and Docling's own bookkeeping
    unchanged — a hit returns the text a call would have returned.
    """
    from docling.datamodel.base_models import ApiImageRequestResult, VlmStopReason
    from docling.models.stages.picture_description import picture_description_api_model as m

    original = getattr(m.api_image_request, "__wrapped__", m.api_image_request)

    def cached(image, prompt, url, timeout=20, headers=None, **params):
        key = cache.key(image, prompt, params)
        text = cache.get(key)
        if text is not None:
            return ApiImageRequestResult(text=text, num_tokens=None, stop_reason=VlmStopReason.UNSPECIFIED)
        result = None
        try:
            result = original(image, prompt, url, timeout, headers, **params)
            return result
        finally:  # also on an exception, so waiters are never left hanging
            cache.put(key, result.text if result else None, params.get("model"))

    cached.__wrapped__ = original
    m.api_image_request = cached
