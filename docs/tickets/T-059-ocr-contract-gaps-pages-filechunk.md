# T-059: /v1/ocr contract gaps — no `pages` selection, no `file_id` document reference

**Status:** Closed — **shipped 2026-07-03.** `pages` (list and `"a-b"` range
forms) slices the document at the pipeline boundary (PyMuPDF `select()`), so
unrequested pages cost nothing; response indices are the original 0-based ones
(Option 1). A full-document cache entry answers a subset request directly; a
sliced run is cached under a selection-suffixed key. Out-of-range/malformed
selections → 422 on both fresh and cached paths. `document: {type: "file",
file_id}` resolves against the existing `FileStore` (404 unknown, 422 missing
id). Both left T-057's reject list with tests on both sides; README updated.
**Priority:** Medium — pure contract completion; nothing returns wrong data once
T-057 rejects these loudly, but Mistral-OCR clients that use them cannot switch
to figmark until they exist.

## Symptom

Two documented Mistral OCR request shapes are unsupported (checked against the
[endpoint spec](https://docs.mistral.ai/api/endpoint/ocr), 2026-07-02):

1. **`pages` selection** (`"pages": [0, 2]` or a range string): figmark always
   processes and returns the whole document. For corpus-scale consumers, page
   selection is also a cost feature — a 300-page document where the client
   wants 3 pages burns the full pipeline.
2. **`document: {type: "file", file_id: ...}` (FileChunk)**: figmark only
   resolves `document_url`/`image_url`. A client that uploads via `/v1/files`
   and then references the id directly — instead of first fetching a signed
   URL — gets a 422/400. LibreChat happens to use the signed-URL flow, so it
   works today, but the direct-id flow is the simpler documented path.

Related, smaller: `model` is accepted but ignored (figmark always runs its own
pipeline) — keep, but document. Raster-image OCR via `image_url` remains a
separate deferred item (T-052) and is *not* in scope here.

## Root cause

The T-052 implementation was scoped to exactly the calls LibreChat's client
makes; the rest of the contract was deferred without a tracking ticket.

## Impact

- Mistral-OCR clients using `pages` or FileChunk cannot point at figmark.
- Full-document processing where a subset was wanted wastes pipeline time and
  vision-model spend (cf. the product goal: put API cost where it adds value).

## Options

1. **`pages`: slice at the pipeline boundary** — extract the requested pages
   into a sub-document (PyMuPDF `select()`), run the pipeline on that, and
   re-index the response to the requested page numbers. Cheapest correct cut;
   caches keyed on content still work.
2. **`pages`: post-filter** — run the full document, return the requested
   subset. Trivial but keeps the full cost; defeats the cost half of the
   feature. Acceptable first step only if labelled as such.
3. **FileChunk**: resolve `file_id` against the existing `FileStore` (same
   validation + signature-free path, since possession of the id came from an
   authenticated upload). Small, self-contained.

## Acceptance criteria

- [x] `pages` (list and range forms) returns exactly the requested pages, with
      correct 0-based `index` values, and skips pipeline work for unrequested
      pages (PyMuPDF `select()` before the pipeline).
- [x] `document: {type: "file", file_id}` works end-to-end after a `/v1/files`
      upload, with a clean 404 for unknown ids.
- [x] Both are removed from T-057's unsupported-parameter reject list, with
      tests for the supported behaviour.
- [x] The README OCR section's supported-parameter list is updated.
