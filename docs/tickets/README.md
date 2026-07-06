# Tickets

Open bugs and improvements for figmark, numbered `T-NNN`.

| ID | Status | Priority | Title |
|---|---|---|---|
| [T-001](T-001-vector-diagrams-missed.md) | **Closed** | HIGH | Vector charts missed entirely — pipeline only saw raster images |
| [T-002](T-002-misleading-filtered-image-log.md) | **Closed** | Low | Log says "N image blocks" but doesn't explain why 0 are saved |
| [T-003](T-003-parallel-image-description.md) | **Closed** | Medium | Parallel processing of image/diagram descriptions with a rich CLI |
| [T-004](T-004-tagged-pdf-pdfua.md) | Open (Phase 1) | Medium | Tagged PDF / PDF/UA — structure-tree foundation (`--tagged-pdf`, Figure /Alt); conformance is Phase 2 |
| [T-005](T-005-pdf-annotations.md) | **Closed** | Medium | Embed descriptions as text annotations in the PDF (MVP accessibility) |
| [T-006](T-006-text-context-around-images.md) | **Closed** | Medium | Send text context around the image (100 words before/after) to the description |
| [T-007](T-007-description-language-follows-document.md) | **Closed** | Medium | Description language is hardcoded to Swedish — should follow the document |
| [T-008](T-008-diagram-internal-text-leaks-into-body.md) | **Closed** | Low | Vector-diagram internal text leaks into the body text (drop ≥80%-contained text) |
| [T-009](T-009-starlette-badhost-cve.md) | **Closed** | HIGH | Starlette BadHost CVE in the lockfile — fixed before first push |
| [T-010](T-010-provider-agnostic-llm-key.md) | **Closed** | Medium | Purge provider-specific references — figmark is provider-neutral |
| [T-011](T-011-codeql-sast.md) | **Closed** | Medium | Enable CodeQL (SAST) |
| [T-012](T-012-dependabot.md) | **Closed** | Medium | Enable Dependabot updates |
| [T-013](T-013-pip-audit-hard-gate.md) | **Closed** | Medium | Make pip-audit a blocking CI gate (was advisory) |
| [T-014](T-014-secret-scanning-push-protection.md) | **Closed** | Medium | Verify GitHub secret scanning + push protection on the repo |
| [T-015](T-015-sha-pin-actions.md) | **Closed** | Low | SHA-pin GitHub Actions |
| [T-016](T-016-cosign-image-signing.md) | **Closed** | Low | Sign the release image and attest the SBOM (cosign) |
| [T-017](T-017-compose-defaults-to-ghcr.md) | **Closed** | Medium | compose should run the published GHCR image — clone-free quickstart |
| [T-018](T-018-first-public-release.md) | **Closed** | Medium | Cut the first public release (v0.2.0) |
| [T-019](T-019-repo-cosmetics.md) | **Closed** | Low | Disable unused repo tabs (Wiki, Projects) |
| [T-020](T-020-remove-berget-fallback.md) | **Closed** | Medium | Remove the deprecated BERGET_API_KEY fallback and last Berget-specific references |
| [T-021](T-021-offpage-drawings-crash.md) | **Closed** | HIGH | Off-page drawing clusters crash diagram rendering (found by the eval corpus) |
| [T-022](T-022-diagram-payload-cap.md) | **Closed** | HIGH | Diagram payloads were sent uncapped — large charts rejected by the API |
| [T-023](T-023-significance-gate-for-diagrams.md) | **Closed** | Low | Apply the significance gate to vector-diagram regions (2 % logo-as-diagram in eval) |
| [T-024](T-024-audit-silent-fallbacks-and-hidden-defaults.md) | **Closed** | Medium | Audit for further principle violations — silent fallbacks and hidden defaults |
| [T-025](T-025-selectable-output-format.md) | **Closed** | Low | Let the client choose the response format (JSON, Markdown, or both) on /v1/convert |
| [T-026](T-026-tables-flattened-to-text.md) | **Closed** | High | Tables are flattened to loose text lines — delivered via T-030/T-031 |
| [T-027](T-027-per-page-scan-decision.md) | **Closed** | High | A scanned/image-only page inside a text PDF is never OCR'd (document-level scan decision) |
| [T-028](T-028-evaluate-garbled-text-prevalence.md) | **Closed** | Low | Measure how often PDFs have garbled (present-but-broken) text before building OCR handling |
| [T-029](T-029-report-conversion-cost.md) | **Closed** | Medium | Report token usage (and an optional cost estimate) for a conversion |
| [T-030](T-030-labelled-table-bench.md) | **Closed** | High | Labelled table bench — scored: PyMuPDF+filter 100%/99%, beats pdfplumber → ship PyMuPDF-only |
| [T-031](T-031-conservative-table-extraction.md) | **Closed** | High | Conservative table extraction → Markdown via a TableBlock (PyMuPDF-only) |
| [T-032](T-032-loud-warnings-silenced-under-quiet.md) | **Closed** | High | Loud pipeline warnings silenced in container/API mode (quiet=True → _noop) |
| [T-033](T-033-truncated-descriptions-undetected.md) | **Closed** | Medium | Truncated descriptions never detected (finish_reason ignored); empty response not retried |
| [T-034](T-034-cache-ignores-config.md) | **Closed** | Medium | Description cache ignores config — stale output after a model/prompt/language change |
| [T-035](T-035-diagram-detection-recall-unmeasured.md) | **Closed** | High | Diagram recall measured — 100% diagram (4/4) + 100% figure (9/9) on 2 genres; nothing dropped |
| [T-036](T-036-naive-multicolumn-reading-order.md) | **Closed** | Medium | Reading order naive for multi-column pages (interleaves columns; affects T-031) |
| [T-037](T-037-quadratic-drawing-clustering.md) | **Closed** | Low | O(n²) drawing clustering — hotspot on draw-heavy pages |
| [T-038](T-038-document-pdf-prompt-injection.md) | **Closed** | Low | Threat model omits PDF-text prompt injection (document in SECURITY.md) |
| [T-039](T-039-dockerfile-base-comment-drift.md) | **Closed** | Low | Dockerfile base comment drifted (says 3.12, pins 3.14); verify wheel stability |
| [T-040](T-040-diagram-recall-fix.md) | **Closed** (invalid) | High | Improve diagram recall — withdrawn: the "misses" were raster figures, recall is 100% |
| [T-041](T-041-figure-manifest.md) | **Closed** | Medium | Extracted figures aren't machine-addressable for follow-up questions (figures.json) |
| [T-042](T-042-document-structure-headings-lists.md) | **Closed** | High | Output is a flat wall of paragraphs — headings/lists inferred from typography (100% on bench) |
| [T-043](T-043-strip-running-headers-footers.md) | **Closed** | Medium | Running headers, footers and page numbers leak into the body text |
| [T-044](T-044-hyperlinks-and-footnotes.md) | Open (Phase 1) | Medium | Hyperlinks preserved as Markdown links; footnote handling deferred to Phase 2 |
| [T-045](T-045-eval-corpus-german-case-is-english.md) | **Closed** | Medium | Eval corpus's only "German" doc was actually English (dead .de.pdf URL) — replaced with a real German OeNB report |
| [T-046](T-046-multiarch-arm64-image.md) | **Closed** | Medium | Published image is amd64-only — no native arm64 for Apple Silicon (Mac Mini) |
| T-047 | — | — | Reserved — operational/deployment item, tracked outside this repo |
| [T-048](T-048-upstream-llm-error-leaks-as-500.md) | **Closed** | Medium | Upstream LLM errors surface as HTTP 500 with the provider's raw error body (should be a clean 502) |
| T-049 | — | — | Reserved — operational/deployment item, tracked outside this repo |
| [T-050](T-050-borderless-forecast-tables-flattened.md) | Open | Medium | Borderless forecast tables are flattened, scrambling column↔value attribution |
| [T-051](T-051-fast-text-mode-min-api-calls.md) | **Closed** | Low | A figure-less text PDF still spends baseline API calls (no fast text mode) |
| [T-052](T-052-librechat-mistral-ocr-compat-endpoint.md) | Open (live bench pending) | Medium | LibreChat/Mistral-OCR clients can't point at figmark (no compatible endpoint) |
| [T-053](T-053-vision-ocr-failure-is-opaque.md) | **Closed** | Medium | A scanned page the vision model can't OCR fails with an opaque, misleading error |
| [T-054](T-054-configurable-input-document-formats.md) | **Closed** | Medium | figmark accepts only PDF — no way to configure other document formats (Word/Excel/PPT/EPUB) |
| [T-055](T-055-lo-vector-charts-missed-by-diagram-detection.md) | **Closed** | High | Vector charts in LibreOffice-produced PDFs are missed by diagram detection |
| [T-056](T-056-spreadsheet-input-flattening-and-page-explosion.md) | **Closed** | Medium | Spreadsheet input — borderless sheets flatten, big sheets explode into hundreds of pages |
| [T-057](T-057-ocr-endpoint-silently-ignores-request-parameters.md) | **Closed** | High | /v1/ocr silently ignores Mistral-OCR request parameters it doesn't support |
| [T-058](T-058-ocr-markdown-image-links-dead-no-image-base64.md) | **Closed** | High | /v1/ocr markdown references images that are unreachable — no include_image_base64, no id-matched images[] |
| [T-059](T-059-ocr-contract-gaps-pages-filechunk.md) | **Closed** | Medium | /v1/ocr contract gaps — no pages selection, no file_id document reference |
| [T-060](T-060-no-cross-request-cache-document-level.md) | **Closed** | High | The HTTP surface re-converts identical documents from scratch — no cross-request cache |
| [T-061](T-061-description-cache-not-shared-across-requests.md) | **Closed** | Medium | Figure descriptions are not reused when the same image appears in new requests or other documents |
| [T-062](T-062-cache-management-shares-the-conversion-token.md) | **Closed** | Low | Cache management shares the conversion bearer token — no privilege separation, no per-consumer partitioning |
| [T-063](T-063-cross-document-description-reuse-not-toggleable.md) | **Closed** | Low | Cross-document description reuse cannot be turned off (context bleed between documents) |
| [T-064](T-064-cache-savings-invisible-no-hit-miss-telemetry.md) | **Closed** | Low | The cache's savings are invisible in operation — no hit/miss telemetry |
| [T-065](T-065-interpret-office-natively-without-pdf-render.md) | Open | Medium | Office support depends entirely on a LibreOffice PDF render — no way to interpret OOXML directly |
| [T-066](T-066-cli-degrades-silently-on-non-pdf-input.md) | Open | Medium | The CLI accepts a non-PDF (e.g. an Office file) and emits a near-empty result instead of failing loud |
| [T-067](T-067-audit-for-more-silent-degradation-paths.md) | Open | Medium | Audit for further silent-degradation paths — where else does bad input or a degraded run produce a confident-looking result? |
| [T-068](T-068-speed-up-image-analysis-throughput.md) | Open | Medium | Image/figure analysis is slow end-to-end — measure the bottlenecks and decide how to speed it up |
| [T-069](T-069-request-queue-bounded-concurrency-backpressure.md) | Open | Medium | The service has no request queue — it rejects the moment all worker slots are busy, instead of queueing with bounded backpressure |
| [T-070](T-070-mistral-ocr-annotations-unsupported.md) | **Icebox** | Low | Mistral OCR Annotations (bbox / document structured extraction) are unsupported |
| [T-071](T-071-standalone-image-input.md) | Open | Medium | figmark can't take a standalone image as input — a raster image is rejected, though its whole engine is figure interpretation + OCR |
| [T-072](T-072-cache-failure-fails-requests-and-boot.md) | **Closed** | High | A cache failure fails the customer's request — and a corrupt cache file prevents the service from starting |
| [T-073](T-073-concurrent-same-document-uploads-all-convert.md) | Open | High | Concurrent uploads of the same document each run a full conversion — the cache does not coalesce in-flight requests |
| [T-074](T-074-cache-ops-cost-5ms-and-block-event-loop.md) | **Closed** | Medium | Every cache operation costs ~5 ms and runs blocking SQLite on the event loop |
| [T-075](T-075-truncated-descriptions-shared-as-complete.md) | Open | Low | A truncated figure description is stored in the shared cross-request cache as if complete |
| [T-076](T-076-cache-operational-envelope-unenforced.md) | Open | Medium | The cache's operational envelope is unenforced — no schema version, disk use beyond the cap, world-readable directory, undocumented scaling assumptions |

## Statuses

- **Open** — an active bug or improvement we intend to do; the default.
- **Parked** — cannot proceed yet because it is *blocked* on something external
  (a missing corpus, an upstream fix, a live signal). Un-parks when the blocker
  clears. Not a judgement on the idea — a dependency.
- **Icebox** — a *good idea we are deliberately not scheduling now*, by choice,
  not because it's blocked. It is written down so the reasoning is preserved and
  it can be picked up if priorities change; the ticket names the trigger that
  would move it back to Open.
- **Closed** — done (closed on merge) or withdrawn (with the reason recorded).

## How a ticket is written

- A title that describes the symptom, not the solution
- **Symptom**: what was observed, with a concrete repro
- **Root cause**: what the real problem is
- **Impact**: who notices it and how
- **Options**: numbered solution paths with trade-offs — not a pre-chosen solution
- **Acceptance criteria**: how we know the ticket is done
