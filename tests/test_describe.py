"""Tests for the describe module — payload preparation.

Cache behaviour and prompt building are covered by the live pipeline tests in
test_pipeline.py. Here we test only the payload preparation, using synthesized
images so the test is fully self-contained (no external PDF, no API).
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image

from figmark.describe import MAX_PAYLOAD_BYTES, _prepare_image_for_api


def _write_random_png(path: Path, size: int) -> Path:
    """Write an incompressible (random-noise) PNG of the given square size."""
    data = os.urandom(size * size * 3)
    Image.frombytes("RGB", (size, size), data).save(path, format="PNG")
    return path


def test_small_image_passes_through_unchanged(tmp_path: Path):
    """A small image (< the payload cap) must be sent as-is, no recompression."""
    img_path = _write_random_png(tmp_path / "small.png", 64)
    assert img_path.stat().st_size <= MAX_PAYLOAD_BYTES

    raw = img_path.read_bytes()
    payload, mime = _prepare_image_for_api(img_path)
    assert payload == raw, "A small image should not be recompressed"
    assert mime.startswith("image/")


def test_large_image_gets_resized_under_cap(tmp_path: Path):
    """A large image (> the payload cap) must be downscaled and JPEG-encoded."""
    img_path = _write_random_png(tmp_path / "large.png", 2000)
    assert img_path.stat().st_size > MAX_PAYLOAD_BYTES, (
        f"Test image is no longer 'too large': {img_path.stat().st_size} B"
    )

    payload, mime = _prepare_image_for_api(img_path)
    assert len(payload) <= MAX_PAYLOAD_BYTES
    assert mime == "image/jpeg"  # converted to JPEG on resize
