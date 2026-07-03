# T-057: /v1/ocr silently ignores Mistral-OCR request parameters it doesn't support

**Status:** Closed — **Option 1 shipped (2026-07-03):** `reject_unsupported_params`
in `ocr_compat.py` rejects every documented-but-unimplemented Mistral OCR
parameter (and unknown keys) with a 422 naming the field and the supported set.
One deliberate nuance: `include_image_base64: false` is *accepted* — it asks for
no image data, which the response satisfies, and it is what LibreChat's default
request carries; only `true` is rejected (until T-058). A null value carries no
request and passes. `document.type: "file"` gets a targeted 422 pointing at the
signed-URL flow (until T-059). README documents the supported set and that
`model` is echoed but never selects a model.
**Priority:** High — the endpoint returns *wrong-looking-right* results: a client
asks for something specific, gets a 200 with different semantics, and nothing
tells it. That is exactly the silent-degradation class the project bans (T-024).

## Symptom

`POST /v1/ocr` (the Mistral-OCR-compatible surface, T-052) accepts the full
Mistral request body but only reads `model` and `document`. Every other
documented parameter is ignored without a word (checked against the
[Mistral OCR endpoint spec](https://docs.mistral.ai/api/endpoint/ocr),
2026-07-02):

- `pages: [0, 2]` → the response contains **all** pages, not the requested two.
- `include_image_base64: true` → `pages[].images` is always `[]`; the client
  asked for image data and silently gets none.
- `image_limit`, `image_min_size`, `bbox_annotation_format`,
  `document_annotation_format`, `document_annotation_prompt`, `table_format`,
  `extract_header`, `extract_footer`, `include_blocks`,
  `confidence_scores_granularity` — all accepted, all ignored.

## Root cause

[ocr_compat.py](../../src/figmark/ocr_compat.py) reads `body.get("model")` and
`body.get("document")` and never inspects the rest of the body. There is no
allowlist of understood parameters, so unsupported ones cannot be detected.

## Impact

- A Mistral-OCR client that relies on `pages` gets a silently different (and
  potentially much larger/costlier) response than it asked for.
- A client that sets `include_image_base64: true` and then tries to re-inline
  figures finds none — with no error to explain why (see T-058 for making the
  images actually available).
- Violates the repo's fail-loud principle on a public API surface.

## Options

1. **Reject unknown/unsupported parameters with a 422 naming the field** (and,
   for the supported subset, pointing at what *is* supported). Parameters move
   off the reject list as they get implemented (T-058 for the image fields,
   T-059 for `pages`/`file_id`/`dimensions`). Simple, honest, unblocks nothing.
2. **Implement the parameters instead of rejecting them.** The right end state
   for the high-value ones, but that work is scoped in T-058/T-059 — rejection
   is the correct behaviour *until* each lands.
3. **Log-only warning.** Keeps clients working but the caller never sees it —
   server logs are not part of the wire contract. Rejected: this is the silent
   path with extra steps.

Option 1 now, shrinking as T-058/T-059 land, is the recommended shape.
Note: `model` is read but its value is ignored (figmark always runs its own
pipeline) — that is fine to keep, but document it in the README's OCR section.

## Acceptance criteria

- [x] A request carrying any documented-but-unsupported Mistral OCR parameter
      gets a 422 that names the parameter and the supported set — no silent
      behaviour differences. (`tests/test_api_ocr_compat.py`)
- [ ] Parameters implemented later (T-058/T-059) are removed from the reject
      list in the same PR that implements them, with tests covering both sides.
      *(Lands with T-058/T-059 — tracked there.)*
- [x] The README's LibreChat/Mistral-OCR section documents exactly which
      parameters the surface supports.
