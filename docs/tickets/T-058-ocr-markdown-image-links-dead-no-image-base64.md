# T-058: /v1/ocr markdown references images that are unreachable — no `include_image_base64`, no id-matched `images[]`

**Status:** Closed — **Option 1 shipped (2026-07-03):** `pages[].images[]` is
populated from the figure manifest (T-041). Markdown refs are rewritten to bare
figure ids matching `images[].id` (cookbook-style `![id](id)`); `images[]`
carries bbox coordinates in PDF points, consistent with the new
`pages[].dimensions` (`dpi: 72`); `image_base64` is a data-URI when
`include_image_base64: true`; `image_limit`/`image_min_size` are honoured (a
filtered figure's ref is stripped, its description caption stays — never a dead
link). The figure bytes ride in the document-cache payload, so cache hits serve
images too; the cache key was version-bumped (`doc2-`) so pre-T-058 entries miss
cleanly instead of resurfacing image-less.
**Priority:** High — this is the product goal (maximum information value for an
LLM consumer) leaking away on the main integration surface: the figure
*descriptions* arrive, but the figures themselves are dead links.

## Symptom

figmark's Markdown embeds extracted figures as
`![Image, page 1](images/page-001-img-05.jpeg)` followed by the description.
Over `/v1/ocr` those relative paths resolve to nothing — the API never serves
the extracted image files. Mistral's contract instead puts placeholder refs in
the markdown (`![img-0.jpeg](img-0.jpeg)`) whose names match `pages[].images[].id`,
and populates `images[].image_base64` when `include_image_base64: true` — so a
compliant client can re-inline every figure from the response alone.

figmark returns `images: []` unconditionally, so:

- a RAG pipeline ingesting the response can index the *description* but can
  never show or re-process the figure itself;
- the markdown carries link noise pointing at files the client cannot fetch;
- `pages[].dimensions` (dpi/height/width) is also absent, so bbox consumers
  have nothing to scale against.

## Root cause

`split_pages()` in [ocr_compat.py](../../src/figmark/ocr_compat.py) slices the
pipeline's Markdown per page but discards the figure artifacts the pipeline
already produced (extracted image files, bboxes from `figures.json`, T-041).
The response was scoped to what LibreChat consumes (markdown only, T-052).

## Impact

- The response is not self-contained: figmark's differentiator (interpreted
  figures) arrives as text, but the underlying figures are lost to the caller.
- Divergence from the Mistral contract for any client that correlates
  `images[].id` with markdown refs (Mistral cookbooks do exactly this).

## Options

1. **Populate `images[]` from the figure manifest** (T-041 already indexes id,
   page, bbox, path): rewrite markdown image refs to Mistral-style ids, return
   `id` + bbox coordinates always, and `image_base64` when
   `include_image_base64: true`; honour `image_limit`/`image_min_size`. Also
   emit `pages[].dimensions` from the page geometry. Fully contract-shaped and
   makes the response self-contained.
2. **Serve the images over signed URLs instead of base64** (like
   `/v1/files/{id}/content`). Smaller responses, but off-contract — Mistral
   clients expect base64 — and adds retention/lifecycle questions the stateless
   response avoids.
3. **Strip the dead links from the OCR markdown** (keep descriptions only).
   Honest minimum if Option 1 is deferred, and trivially cheap — but gives up
   the information value instead of delivering it.

Option 1 is the recommended end state; Option 3 is an acceptable stopgap only
if it ships together with T-057's loud rejection of `include_image_base64`.

## Acceptance criteria

- [x] Markdown image refs in the OCR response match `pages[].images[].id`
      (no unreachable relative paths).
- [x] `include_image_base64: true` returns base64 image data; `image_limit` /
      `image_min_size` are honoured (and removed from T-057's reject list).
- [x] `pages[].images[]` carries bbox coordinates and `pages[].dimensions` is
      populated, matching the Mistral schema.
- [x] The offline suite covers a figure-bearing document round-tripping with
      and without `include_image_base64` (`tests/test_api_ocr_compat.py`).
