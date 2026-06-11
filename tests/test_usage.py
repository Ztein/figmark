"""Token-usage accounting and optional cost estimation (T-029)."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from figmark.config import load_config
from figmark.pipeline import convert
from figmark.usage import (
    Cost,
    TrackingClient,
    Usage,
    UsageTracker,
    estimate_cost,
    format_usage,
)

from .fakes import FakeClient, make_response, synthetic_pdf


def _usage(prompt, completion, total=None):
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total if total is not None else prompt + completion,
    )


# --- UsageTracker ---------------------------------------------------------


def test_tracker_sums_usage_across_calls():
    tracker = UsageTracker()
    tracker.record(SimpleNamespace(usage=_usage(10, 5)))
    tracker.record(SimpleNamespace(usage=_usage(20, 8)))
    snap = tracker.snapshot()
    assert snap.api_calls == 2
    assert snap.prompt_tokens == 30
    assert snap.completion_tokens == 13
    assert snap.total_tokens == 43
    assert snap.calls_missing_usage == 0


def test_tracker_counts_missing_usage_without_inventing_tokens():
    tracker = UsageTracker()
    tracker.record(SimpleNamespace())  # a response with no usage attribute
    snap = tracker.snapshot()
    assert snap.api_calls == 1
    assert snap.calls_missing_usage == 1
    assert snap.total_tokens == 0


def test_tracker_is_thread_safe():
    tracker = UsageTracker()

    def hammer():
        for _ in range(1000):
            tracker.record(SimpleNamespace(usage=_usage(1, 1)))

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snap = tracker.snapshot()
    assert snap.api_calls == 8000
    assert snap.prompt_tokens == 8000
    assert snap.completion_tokens == 8000


# --- TrackingClient -------------------------------------------------------


def test_tracking_client_records_and_passes_through():
    tracker = UsageTracker()
    inner = FakeClient("a description")
    client = TrackingClient(inner, tracker)

    resp = client.chat.completions.create(
        model="m", max_tokens=10, messages=[{"role": "user", "content": "Identify the language"}]
    )
    # The wrapped response is returned unchanged …
    assert resp.choices[0].message.content
    # … and its usage was recorded.
    assert tracker.snapshot().api_calls == 1
    assert tracker.snapshot().total_tokens == 15  # FakeClient default 10 + 5


# --- estimate_cost --------------------------------------------------------


def test_estimate_cost_is_none_without_prices():
    api = SimpleNamespace(input_token_price=None, output_token_price=None, currency=None)
    assert estimate_cost(Usage(prompt_tokens=100, completion_tokens=50), api) is None


def test_estimate_cost_uses_per_token_prices():
    api = SimpleNamespace(
        input_token_price=2.5e-7, output_token_price=5e-7, currency="EUR"
    )
    cost = estimate_cost(Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000), api)
    assert cost is not None
    assert cost.currency == "EUR"
    assert abs(cost.amount - (0.25 + 0.5)) < 1e-9


# --- format_usage ---------------------------------------------------------


def test_format_usage_marks_cost_unavailable_not_zero():
    usage = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15, api_calls=2)
    text = format_usage(usage, None)
    assert "n/a" in text
    assert "0.0000" not in text


def test_format_usage_shows_cost_and_missing_warning():
    usage = Usage(
        prompt_tokens=10, completion_tokens=5, total_tokens=15, api_calls=2, calls_missing_usage=1
    )
    text = format_usage(usage, Cost(amount=0.0012, currency="EUR"))
    assert "0.0012 EUR" in text
    assert "WARNING" in text and "1 call" in text


# --- end to end through convert ------------------------------------------


def test_convert_reports_usage(env_with_key, project_root: Path, tmp_path: Path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    result = convert(pdf, cfg, tmp_path / "output", client=FakeClient("desc"), quiet=True)

    # Language detection + summary + one image description = at least 3 calls.
    assert result.usage.api_calls >= 3
    assert result.usage.total_tokens > 0
    # No prices configured in the example config → cost is not invented.
    assert result.estimated_cost is None


def test_convert_estimates_cost_when_prices_configured(
    env_with_key, project_root: Path, tmp_path: Path
):
    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    cfg.api.input_token_price = 2.5e-7
    cfg.api.output_token_price = 5e-7
    cfg.api.currency = "EUR"

    result = convert(pdf, cfg, tmp_path / "output", client=FakeClient("desc"), quiet=True)

    expected = (
        result.usage.prompt_tokens * 2.5e-7 + result.usage.completion_tokens * 5e-7
    )
    assert result.estimated_cost is not None
    assert abs(result.estimated_cost - expected) < 1e-12
    assert result.currency == "EUR"
