"""T-081: the skip/keep decision comes from a validated is_figure boolean, and
the text path is a working fallback for endpoints without json_schema support."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from figmark.describe import SKIP_MARKER, _structured_unsupported, call_vision

from .fakes import FakeClient


def _cfg(base_url: str) -> SimpleNamespace:
    return SimpleNamespace(api=SimpleNamespace(model="m", base_url=base_url, temperature=0.0))


@pytest.fixture(autouse=True)
def _clear_unsupported():
    _structured_unsupported.clear()
    yield
    _structured_unsupported.clear()


def test_structured_skip_uses_is_figure_not_the_string():
    """A decorative image -> the mock returns is_figure=false -> clean skip,
    via the structured prompt (no fragile "[SKIP]" string parsing)."""
    client = FakeClient("[SKIP]")
    text, truncated = call_vision(client, _cfg("http://a"), "STRUCTURED", "FALLBACK", "data:x", 100)
    assert text == SKIP_MARKER
    assert not truncated
    assert client.describe_prompts[-1] == "STRUCTURED"


def test_structured_describe_returns_description():
    client = FakeClient("A bar chart of exports.")
    text, _ = call_vision(client, _cfg("http://b"), "STRUCTURED", "FALLBACK", "data:x", 100)
    assert text == "A bar chart of exports."
    assert client.describe_prompts[-1] == "STRUCTURED"


def test_falls_back_to_text_when_endpoint_lacks_structured_support():
    """An endpoint known to reject json_schema -> the legacy text prompt runs,
    and its "[SKIP]" reply is still honoured via is_skip() downstream."""
    _structured_unsupported.add("http://c|m")
    client = FakeClient("A line chart.")
    text, _ = call_vision(client, _cfg("http://c"), "STRUCTURED", "FALLBACK", "data:x", 100)
    assert text == "A line chart."
    assert client.describe_prompts[-1] == "FALLBACK"  # the text path, not structured
