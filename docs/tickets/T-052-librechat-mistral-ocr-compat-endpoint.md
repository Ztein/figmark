# T-052: LibreChat/Mistral-OCR clients can't point at figmark (no compatible endpoint)

**Status:** Open — **implemented (Option 1); pending live bench against a real
LibreChat instance** (being stood up separately). The endpoint + tests ship; the
`OCR_BASEURL` round-trip must still be verified end-to-end before we call it done.
**Priority:** Medium

## Symptom

LibreChat (and other tools that speak the Mistral OCR API) let an operator redirect
OCR to a self-hosted backend by setting `OCR_BASEURL` — but they then talk the
**Mistral OCR wire format**, not figmark's `/v1/convert`. figmark exposes a single
`POST /v1/convert` ([src/figmark/api.py](../../src/figmark/api.py)) that returns a
Markdown/JSON blob; LibreChat's default `mistral_ocr` strategy instead expects a
four-call `/files` + `/ocr` dance and a `{ "pages": [...] }` response. So today a
LibreChat operator cannot use figmark as their OCR backend at all, even though
figmark is the better engine for their documents.

The docs' `custom_ocr` strategy (a simpler generic contract) is marked **"not yet
implemented"** upstream, so mimicking the Mistral format is the only working path.

## Root cause

figmark was built API-first around its own contract, not around any third-party
OCR wire format. There is no compatibility surface, so Mistral-OCR clients have no
endpoint shape they recognise.

The gap is **shape, not capability**: figmark already produces per-page Markdown
(it preserves `<!-- page N -->` markers), figure/diagram descriptions, tables,
bearer auth, token accounting (T-029) and clean upstream-error mapping (T-048).
What's missing is a thin adapter that re-presents that output in the Mistral shape.

## The contract to satisfy

Verified against LibreChat `main`
([`packages/api/src/files/mistral/crud.ts`](https://github.com/danny-avila/LibreChat/blob/main/packages/api/src/files/mistral/crud.ts)).
All calls carry `Authorization: Bearer <OCR_API_KEY>`; base is `OCR_BASEURL`
(default `https://api.mistral.ai/v1`):

| # | Call | Body | Response read by client |
|---|---|---|---|
| 1 | `POST /files` (multipart) | `purpose=ocr` + file | `{ "id": "…" }` |
| 2 | `GET /files/{id}/url?expiry=24` | — | `{ "url": "…" }` (signed URL) |
| 3 | `POST /ocr` (JSON) | `{ model, document: { type: "document_url"\|"image_url", document_url: url }, include_image_base64, image_limit }` | see below |
| 4 | `DELETE /files/{id}` | — | (cleanup) |

The **only** response fields LibreChat consumes (`processOCRResult`):

```jsonc
{
  "pages": [ { "index": 0, "markdown": "…", "images": [ { "image_base64": "…" } ] } ],
  "model": "…", "usage_info": { … }
}
```

Everything else Mistral returns (dimensions, bounding boxes, tables, hyperlinks,
confidence) is ignored, and LibreChat does **not** currently use the OCR `images`
at all — so returning `images: []` is fully functional.

## Impact

- **Who:** any LibreChat/Mistral-OCR operator who wants a self-hosted, air-gappable
  OCR backend. Without this they must use Mistral's cloud (data leaves the network)
  or a lesser local `document_parser`.
- **Why figmark specifically:** for **born-digital, figure/diagram-heavy** corpora,
  figmark *describes* figures and diagrams with a vision model instead of OCR'ing
  them into broken text — something Mistral OCR does not do. For that document
  profile figmark is not parity, it is a better result, plus it keeps data local.
- **Honest limitation (must be stated, not hidden):** figmark's raster OCR is
  Tesseract (document-level scan decision, T-027), not a VLM. figmark-as-OCR is
  strongest on born-digital / figure-heavy documents and **weaker than Mistral's
  model on messy scans and handwriting.** Scope and market it accordingly; do not
  claim VLM-grade scan fidelity.

## Options

1. **Thin Mistral-compat router over `/v1/convert` (recommended).** Add the four
   routes as an adapter that reuses the existing pipeline unchanged:
   - `POST /ocr`: resolve `document.document_url` (or `image_url`) to bytes, run the
     existing conversion, split the Markdown on the `<!-- page N -->` markers into
     `pages[].markdown`, map `usage_info` from the existing token accounting, return
     `images: []` initially.
   - `POST /files` / `GET /files/{id}/url` / `DELETE /files/{id}`: a small stateful
     temp-store keyed by `id`; the signed URL points back at figmark itself and is
     consumed by our own `/ocr`. No new heavy dependency → the air-gapped image
     constraint holds.
   - PDF-first; return HTTP 415 for `image_url` inputs until image handling is added.
   - Auth: reuse the existing constant-time bearer check.
   Smallest change; no touch to `describe`/`ocr`/`table` code.
2. **Also accept inline base64 on `/ocr`** (as LibreChat's Azure variant sends),
   letting a client skip the `/files` dance. Cheap add-on to option 1; do it if the
   temp-store proves awkward.
3. **Wait for LibreChat's `custom_ocr`.** A simpler generic contract may land
   upstream and avoid emulating four Mistral endpoints — but it is unimplemented
   with no committed shape, so this blocks indefinitely. Rejected as the primary
   path; revisit if it ships.

## Acceptance criteria

- [ ] **Live bench (pending):** point a real LibreChat instance at figmark via
      `OCR_BASEURL` and confirm the four-call flow round-trips (upload → signed URL →
      `/ocr` → delete) on a representative figure-heavy PDF. Record the
      request/response. *This is the one criterion the offline suite can't cover;
      the LibreChat instance is being stood up separately.*
- [x] `POST /ocr` returns a valid `{ "pages": [...] }` with per-page `markdown`
      derived from the existing pipeline (split on the `<!-- page N -->` markers);
      `usage_info` carries `pages_processed` + `doc_size_bytes`. Covered by
      `tests/test_api_ocr_compat.py::test_full_mistral_flow_roundtrips`.
- [x] Auth parity: a wrong/absent bearer token is rejected exactly as `/v1/convert`
      (`test_ocr_and_files_require_auth`); signed file URLs are HMAC'd against the
      server token (`test_tampered_signature_is_403`).
- [x] The scan-fidelity limitation is documented in the README (figmark-as-OCR is
      for born-digital / figure-heavy docs; not VLM-grade on messy scans; PDF-first,
      non-PDF → 415) — fail loud about the boundary, per our principles.
- [x] Contract source is pinned: the shape was verified against LibreChat `main`
      (`packages/api/src/files/mistral/crud.ts`), noted above. Re-check when bumping
      the paired LibreChat version, since Mistral OCR is evolving (OCR 3 shipped).

## Implementation notes (2026-07-01)

Shipped **Option 1** — a thin Mistral-compat router, no change to the conversion
code:

- New module [`src/figmark/ocr_compat.py`](../../src/figmark/ocr_compat.py):
  `POST /v1/files`, `GET /v1/files/{id}/url`, `GET /v1/files/{id}/content`,
  `DELETE /v1/files/{id}`, `POST /v1/ocr`, plus a tiny on-disk `FileStore`.
- `api.py` refactor: the concurrency-gate + timeout + upstream-error mapping
  (T-048) and PDF validation were extracted into shared `run_conversion` /
  `_validate_pdf_document` helpers, so `/v1/convert` and `/v1/ocr` behave
  identically. No behaviour change to `/v1/convert`.
- **Air-gap preserved:** document bytes are resolved only from figmark's *own*
  signed file URLs (the default LibreChat flow) or inline `data:` URLs (the Azure
  variant). Arbitrary external URLs are rejected (`400`) — no outbound fetch, no
  SSRF surface. No new runtime dependency.
- **Deferred:** populating `pages[].images[].image_base64` when
  `include_image_base64: true` (LibreChat ignores OCR images today, so `images: []`
  is fully functional); non-PDF `image_url` inputs (currently `415`).
