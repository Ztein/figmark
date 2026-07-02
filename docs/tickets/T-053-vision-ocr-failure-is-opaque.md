# T-053: A scanned page the vision model can't OCR fails with an opaque, misleading error

**Status:** Closed
**Priority:** Medium

## Symptom

When a scanned page is escalated to the vision-OCR fallback and the model rejects
it — most often because the rendered page image is too large — the failure surfaced
badly:

- Over the HTTP API, the upstream `APIError` was caught by the generic T-048 mapping
  and returned as `502 "LLM backend rejected the request — check the API key, quota,
  and endpoint"`. That points the operator at the key/quota when the real cause is a
  too-large page image — a wrong and time-wasting diagnosis.
- On the CLI it propagated as a bare provider error/stack with no page context.
- An empty completion on the OCR path returned `""` silently (a page's text just
  vanished), unlike the figure path which already treats an empty completion as a
  hard error (T-033).

## Root cause

`ocr.ocr_page_with_vision` was the one vision call path that never adopted the
hardening the figure/diagram paths already had:

- **No payload cap.** `describe._prepare_image_for_api` resizes/re-encodes a figure
  under `MAX_PAYLOAD_BYTES` (500 KB) before sending (T-022); the OCR path rendered a
  page at 150 DPI and sent whatever size resulted. A large or high-detail page can
  exceed the provider's limit and get an opaque 413/400.
- **No error translation.** The raw `APIError` carried no page context, so the API
  layer could only map it as a generic upstream fault, and the CLI had nothing
  actionable to print.
- **No empty-response guard** (the T-033 treatment was never applied here).

## Impact

Operators of a scanned-heavy instance (or the LibreChat/Mistral-OCR backend, T-052)
got a `502` that blamed the API key for what was actually a too-large page — the
opposite of "fail loud" with an actionable message.

## Options (chosen: 1 + 2 + 3)

1. **Enforce the payload cap on the OCR path**, reusing the figure-path constants
   (`MAX_PAYLOAD_BYTES`, `MAX_IMAGE_DIM`): resize to the max dimension, then step the
   JPEG quality down. Prevents most "too large" failures proactively.
2. **A dedicated `VisionOCRError`** carrying the page number and a specific,
   provider-body-free reason. Raised when the page still won't fit after maximum
   downscaling, when the model rejects it (wrapping the `APIError`), or when it
   returns nothing.
3. **Map it cleanly at the API layer** to `422` with the page-specific detail — an
   input-document property, not a backend outage (`502`) or a figmark bug (`500`).

Rejected: raising the DPI cap blindly (would just move the failure), or silently
skipping the page (violates the fail-loud principle, T-024).

## Acceptance criteria

- [x] The OCR page image is shrunk under `MAX_PAYLOAD_BYTES` before the vision call;
      a page that still won't fit raises `VisionOCRError` naming the page, the size,
      and the remedy (lower DPI / larger-limit model).
- [x] A provider rejection is re-raised as `VisionOCRError` with page context and
      **no** provider body (T-048); an empty completion is a hard error, not `""`.
- [x] `/v1/convert` and `/v1/ocr` map `VisionOCRError` to `422` with the actionable
      detail (shared `run_conversion` path). Covered by
      `tests/test_ocr_vision_errors.py`.
- [x] README documents the `422` scanned-page failure behaviour.
