# T-061: Figure descriptions are not reused when the same image appears in new requests or other documents

**Status:** Closed — **implemented (2026-07-02).** `SharedDescriptionCache`
rides the T-060 store: images share by content digest, diagrams by the digest
of their rendered pixels (position-independent), `[SKIP]` verdicts are cached
too. Entries are attributed to the document that first created them, so purging
a document (T-060's `DELETE /v1/cache/{sha256}`) also purges its descriptions.
Same size/TTL/LRU/clear policies; the CLI is unchanged (per-document cache
only). Cross-document context trade-off: reuse is ON (the description of a
figure is overwhelmingly image-driven; partial fidelity beats re-spend — the
product goal), documented in the security analysis; a per-deployment toggle was
considered and deferred until someone needs it. Found & fixed while testing: a
pipeline refactor had left the diagram-job loop outside the per-page loop, so
diagram regions had silently stopped being described — restored, with a CI
regression test (`test_diagram_regions_are_scheduled_for_description`).
Tests: `tests/test_shared_description_cache.py`.
**Priority:** Medium — the document-level cache (T-060) only helps when the
*whole document* is identical. The same figure recurring in different documents
(an organisation's logo, a shared chart, a report template's header art, a new
revision of yesterday's report) is re-described — re-spent — every time.

## Symptom

Two different documents containing the same embedded image each pay a
vision-model call for it. Likewise, re-uploading a *revised* document (one page
changed) misses T-060's document-level cache entirely and re-describes every
unchanged figure.

Within a single conversion this is already solved: descriptions are cached on
disk keyed by image **content digest** + config fingerprint, and duplicate
instances share one call (T-054 work, 2026-07-02). But that cache directory
lives — and dies — with the request's temp dir.

## Root cause

Same as T-060: the description cache was designed for persistent CLI output
directories; the API gives the pipeline throwaway storage per request.

## Decided design (2026-07-02)

A **shared description cache** across requests and documents, riding on T-060's
cache infrastructure (same store, same policies):

- **Key:** image content digest + config fingerprint (already exactly how the
  per-run cache files are named — `img-<digest>-<fingerprint>.txt`). Content
  digest means the *same pixels* reuse the description regardless of which
  document, page, or xref they arrive under.
- **Policies inherited from T-060:** counts toward the same configurable max
  size, same max-age TTL, same LRU last-accessed re-stamping on every hit, and
  is included in the full-cache clear.
- Diagram descriptions should join the same scheme, which requires keying them
  by rendered-region content digest instead of today's page-position stem —
  otherwise only raster figures benefit.

## Options

1. **Point the pipeline's `descriptions_dir` at the shared store** (per-request
   symlink/path indirection). Minimal pipeline change; the store must then
   handle the pipeline's read/write file pattern and stamp LRU on reads.
2. **A cache interface in `describe.py`** (get/put by key) with the file layout
   as an implementation detail. Cleaner boundary, slightly more refactor.

## Notes / constraints

- **Context-dependence caveat:** descriptions are generated with surrounding
  text + a document summary as context (T-006). The config fingerprint already
  covers the *settings*, not the *content* of that context — reusing a
  description across documents means accepting the first document's context in
  later ones. That trade-off is deliberate (the description of a chart is
  overwhelmingly image-driven, and partial fidelity beats re-spend — see the
  product goal), but it must be documented, and the ticket work should consider
  whether cross-document reuse should be a config toggle.
- Same data-at-rest note as T-060: cached descriptions persist server-side;
  TTL/size/clear are the operator's controls.

## Acceptance criteria

- [ ] The same image content in two *different* documents (or two uploads of a
      revised document) produces one vision-model call in total; the second
      occurrence is a cache hit that re-stamps the entry's last-accessed time.
- [ ] Diagram regions participate via content-digest keys (or a recorded
      decision why raster-only is acceptable).
- [ ] Entries obey T-060's size cap, TTL, and full-clear; description entries
      are evicted LRU like everything else.
- [ ] The cross-document context trade-off is documented (and a config toggle
      considered, with the decision recorded).
- [ ] Offline tests cover cross-request reuse, cross-document reuse, and
      eviction/expiry of description entries.
