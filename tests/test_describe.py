"""Tests for the describe module — payload preparation.

Cache behaviour and prompt building are covered by the live pipeline tests in
test_pipeline.py. Here we test only the payload preparation, using synthesized
images so the test is fully self-contained (no external PDF, no API).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from figmark.config import load_config
from figmark.describe import MAX_PAYLOAD_BYTES, MAX_TOKENS, _prepare_image_for_api, describe_image

from .fakes import make_response


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


# --- T-033: a truncated description (finish_reason=length) warns loudly -------


class _TruncatingClient:
    """Returns a description the API cut off at the token cap."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, max_tokens, messages, **kwargs):
        return make_response("A partial description that was cut off", finish_reason="length")


def test_truncated_description_warns(env_with_key, project_root: Path, tmp_path: Path, caplog):
    cfg = load_config(project_root / "config.example.yaml")
    img_path = _write_random_png(tmp_path / "fig.png", 64)
    desc_path = tmp_path / "fig.txt"

    with caplog.at_level(logging.WARNING, logger="figmark.describe"):
        out = describe_image(_TruncatingClient(), img_path, desc_path, cfg)

    assert out == "A partial description that was cut off"  # still returned/cached
    assert "truncated" in caplog.text.lower()
    assert str(MAX_TOKENS) in caplog.text  # names the cap that was hit
