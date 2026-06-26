# T-048: Upstream LLM errors surface as HTTP 500 with the provider's raw error body

**Status:** Closed — implemented 2026-06-26. `convert_endpoint` now catches
`openai.APIError` next to the existing `TimeoutError` and maps it via
`_upstream_error_response`: `APITimeoutError` → **504**, upstream **429** → **503**,
everything else (auth/quota 401/402/403, upstream 5xx, connection errors) → **502
Bad Gateway**. The client gets a generic detail only; the full upstream error
(status, type, message, provider IDs) is logged server-side via `logger.error`.
Genuine figmark bugs are non-`APIError` and still surface as 500. Offline-covered
by `tests/test_api_upstream_errors.py` (a fake client raising the real openai
exceptions; asserts the mapped status, no `correlation_id`/`request_id` leak, and a
500 for a non-LLM bug).
**Priority:** Medium — wrong status class for an upstream/config fault, plus a
minor info leak of provider internals to the caller.

## Symptom

When the configured LLM key/endpoint rejects a call during `POST /v1/convert`,
the service returns **HTTP 500** with the provider's raw error JSON in the body —
including `code`, `message`, `correlation_id` and `request_id`. Observed
2026-06-25 deploying the service on the Mac Mini: an unfunded Berget key
(`402 WALLET_NOT_SETUP`) produced:

```
HTTP/1.1 500 Internal Server Error
openai.APIStatusError: Error code: 402 - {'error': {'code': 'WALLET_NOT_SETUP',
'message': 'No subscription found for this API key.', ... 'correlation_id': ...,
'request_id': ...}}
```

## Root cause

In [`api.py`](../../src/figmark/api.py) `convert_endpoint`, the `convert` call is
wrapped only for `TimeoutError` (→ 504). Any other exception — including
`openai.APIStatusError` and its subclasses raised from the pipeline's LLM calls —
propagates uncaught to Starlette's default 500 handler, which surfaces the upstream
error (body + IDs). The pipeline itself already *logs* this loudly ("Aborting — the
API key/endpoint looks misconfigured, which would fail every call"); the HTTP layer
just never translates it into a sane response.

## Impact

- **Wrong status class.** A 5xx-from-upstream / bad-key / no-quota condition is a
  *bad gateway*, not an internal server error — callers (and monitors) can't tell a
  config/credential problem from a genuine figmark bug.
- **Info leak.** The provider's `correlation_id` / `request_id` and endpoint
  behaviour are echoed to whoever called `/v1/convert`.
- **Poor operability.** No clean signal that the fix is "set up the LLM key/quota,"
  which is exactly the trap hit during the Mini deploy.

## Options

1. **Map upstream LLM errors to clean statuses.** Catch `openai.APIError`
   (and `APIStatusError`) around the `convert` call: auth/quota (401/402/403) →
   **502 Bad Gateway** (or 503) with a generic detail like *"LLM backend rejected
   the request — check api key / quota"*; upstream 429 → 503/429; keep 504 for
   timeouts. Log the full upstream error server-side; never echo it to the client.
2. **App-level exception handler** for `openai.APIStatusError` that does the same
   mapping in one place (cleaner if more endpoints start calling the model).
3. **Broad catch:** any uncaught exception in `convert` → 502 + generic message,
   detail logged server-side only. Simplest, but coarser (hides real figmark bugs
   behind 502 too) — combine with (1) so genuine bugs still 500.

In all cases: the response body must carry a generic message only — no upstream
JSON, `correlation_id`, or `request_id`.

## Acceptance criteria

- [ ] A conversion with an invalid/unfunded key returns a clean **502** (or 503),
  not 500, with a generic detail and **no** provider `correlation_id`/`request_id`
  or raw error JSON in the body.
- [ ] The full upstream error is still logged server-side (fail loud where the
  operator sees it, quiet where the caller does).
- [ ] A test asserts the mapped status and that the response body contains no
  upstream correlation/request IDs — using a fake client that raises
  `openai.APIStatusError` (offline) so CI covers it without a live key.
- [ ] Genuine figmark bugs (non-LLM exceptions) still surface as 500, not masked.
