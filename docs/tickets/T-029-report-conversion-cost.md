# T-029: Report token usage (and an optional cost estimate) for a conversion

**Status:** Closed — implemented 2026-06-11 (PR #15): usage on the response + CLI, optional config-priced cost.
**Priority:** Medium — cost visibility; the data is already returned and thrown away

## Symptom / motivation

A conversion of a real report fans out into many vision calls (one per figure +
language detection + document summary + any vision-OCR pages), but the caller has
no idea how much it cost or how many tokens it used. The response is just
`{markdown, page_count, figure_count, skipped_count, language}`.

The information is **already on every API response and we discard it.** Each
OpenAI-compatible `chat.completions.create` returns a `usage` object
(`prompt_tokens`, `completion_tokens`, `total_tokens`); all five call sites
([describe.py](src/figmark/describe.py), [diagrams.py](src/figmark/diagrams.py),
[ocr.py](src/figmark/ocr.py), [summarize.py](src/figmark/summarize.py) ×2) ignore
`response.usage`.

## What the API does and does not give us

- **Token usage: yes, always.** Standard field on a (non-streaming) completion.
  We use non-streaming calls, so it is present. (If any call ever streams, it
  needs `stream_options={"include_usage": true}`.)
- **Monetary cost: no.** The completion never returns money. Cost = tokens ×
  price, and price comes from elsewhere. Berget happens to expose per-token
  prices via `GET /v1/models` (`pricing.input` / `pricing.output`, currency EUR);
  OpenAI does not return prices via API at all. So **cost is a derived value that
  needs a price source and is not universally available.**

## Design constraints (project principles)

- **Provider-neutral (cf. T-024):** do not hardcode any provider's prices. Token
  usage must work for every endpoint; cost is opt-in/derived.
- **Fail loudly:** if a price is not available, report usage and mark cost as
  unavailable — never show a fake `0` that reads as "free".

## Options

1. **Tokens only.** Add a `usage` object to the response (`prompt_tokens`,
   `completion_tokens`, `total_tokens`, `api_calls`), accumulated across all
   calls in the conversion. Always works, provider-neutral, simple. The caller
   multiplies by their own price. Cons: no money figure out of the box.
2. **Tokens + config-priced cost.** Option 1, plus optional config
   (`api.input_token_price`, `api.output_token_price`, `api.currency`); when set,
   add an `estimated_cost` (amount + currency). Explicit, provider-neutral,
   no network. Cons: the user must look up and enter prices.
3. **Tokens + auto-discovered cost.** Option 1, plus: on startup fetch
   `GET /v1/models` and, if the configured model exposes `pricing`, use it to
   compute `estimated_cost`. Zero-config on providers that publish prices (Berget);
   silently omits cost where they don't (OpenAI). Cons: an extra call + parsing a
   non-standard field; must degrade cleanly (loudly) when absent.

Recommendation to evaluate: **Option 1 as the floor** (always ship token usage),
with **Option 2** as the cost layer (explicit, no surprises), and Option 3 only if
zero-config cost on price-publishing providers proves worth the coupling.

## Scope

- Accumulate usage in `pipeline.convert` (thread-safe — descriptions run in
  parallel via `parallel.py`) and return it on `ConversionResult`.
- Surface it on the API `ConvertResponse` and print a one-line summary at the end
  of the CLI run (tokens, calls, and cost if available).
- A per-call-type breakdown (descriptions vs diagrams vs OCR vs summary) is a
  nice-to-have, not required.

## Acceptance criteria

- [ ] Every `create()` call's `usage` is captured and summed across the whole
      conversion (including parallel description workers — no lost updates).
- [ ] The response carries `prompt_tokens`, `completion_tokens`, `total_tokens`,
      and `api_calls`.
- [ ] When a price source is configured/available, an `estimated_cost`
      (amount + currency) is included; when not, cost is omitted or explicitly
      `null`/"unavailable" — never a misleading `0`.
- [ ] No provider's prices are hardcoded anywhere.
- [ ] The CLI prints a one-line cost/usage summary at the end of a run.
- [ ] A call whose response lacks `usage` is handled loudly (counted as unknown),
      not silently treated as zero tokens.
