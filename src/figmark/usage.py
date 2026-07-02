"""Token-usage accounting for a conversion.

Every OpenAI-compatible chat completion returns a ``usage`` object. We wrap the
client (:class:`TrackingClient`) so each call records its usage into a thread-safe
:class:`UsageTracker` — descriptions run in parallel, so the accumulation is
locked. Money is *derived* (tokens × price) and only computed when the config
supplies prices: there is no hardcoded provider pricing, and a missing price (or
missing usage on a response) yields ``None``/an explicit note, never a misleading
zero.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    calls_missing_usage: int = 0


@dataclass(frozen=True)
class Cost:
    amount: float
    currency: str


class UsageTracker:
    """Accumulates token usage across every API call in one conversion (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prompt = 0
        self._completion = 0
        self._total = 0
        self._calls = 0
        self._missing = 0

    def record(self, response: object) -> None:
        """Record one completion's usage. Tolerates a response without ``usage``."""
        usage = getattr(response, "usage", None)
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = getattr(usage, "total_tokens", None)
        total = int(total) if total else prompt + completion
        with self._lock:
            self._calls += 1
            if usage is None:
                self._missing += 1
                return
            self._prompt += prompt
            self._completion += completion
            self._total += total

    def snapshot(self) -> Usage:
        with self._lock:
            return Usage(
                prompt_tokens=self._prompt,
                completion_tokens=self._completion,
                total_tokens=self._total,
                api_calls=self._calls,
                calls_missing_usage=self._missing,
            )


class _Completions:
    def __init__(self, inner: Any, tracker: UsageTracker) -> None:
        self._inner = inner
        self._tracker = tracker

    def create(self, *args, **kwargs):
        response = self._inner.create(*args, **kwargs)
        self._tracker.record(response)
        return response


class _Chat:
    def __init__(self, inner: Any, tracker: UsageTracker) -> None:
        self.completions = _Completions(inner.completions, tracker)


class TrackingClient:
    """A transparent proxy around an OpenAI client that records usage per call.

    Only ``client.chat.completions.create`` is intercepted — the one call figmark
    makes. Every other attribute passes straight through to the wrapped client.
    """

    def __init__(self, inner: Any, tracker: UsageTracker) -> None:
        self._inner = inner
        self.chat = _Chat(inner.chat, tracker)

    def __getattr__(self, name: str):
        # Only reached for attributes not set on the proxy itself.
        return getattr(self._inner, name)


def estimate_cost(usage: Usage, api_cfg: object) -> Cost | None:
    """Estimate the monetary cost from token counts × configured per-token prices.

    Returns ``None`` when prices are not configured — never a misleading zero.
    Prices are per single token (matching the ``/v1/models`` pricing unit),
    provider-neutral, and never hardcoded.
    """
    in_price = getattr(api_cfg, "input_token_price", None)
    out_price = getattr(api_cfg, "output_token_price", None)
    if in_price is None or out_price is None:
        return None
    amount = usage.prompt_tokens * in_price + usage.completion_tokens * out_price
    currency = (getattr(api_cfg, "currency", None) or "").strip()
    return Cost(amount=amount, currency=currency)


def format_usage(usage: Usage, cost: Cost | None) -> str:
    """One-line human summary of usage (and cost, if known)."""
    summary = (
        f"API usage: {usage.api_calls} call(s), {usage.total_tokens:,} tokens "
        f"({usage.prompt_tokens:,} in / {usage.completion_tokens:,} out)"
    )
    if cost is not None:
        money = f"{cost.amount:.4f} {cost.currency}".strip()
        summary += f" — est. cost ≈ {money}"
    else:
        summary += " — est. cost: n/a (set api.input_token_price + api.output_token_price)"
    if usage.calls_missing_usage:
        summary += f" — WARNING: {usage.calls_missing_usage} call(s) returned no usage"
    return summary
