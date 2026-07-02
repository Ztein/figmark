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
| [T-046](T-046-multiarch-arm64-image.md) | Open | Medium | Published image is amd64-only — no native arm64 for Apple Silicon (Mac Mini) |
| T-047 | — | — | Reserved — operational/deployment item, tracked outside this repo |
| [T-048](T-048-upstream-llm-error-leaks-as-500.md) | **Closed** | Medium | Upstream LLM errors surface as HTTP 500 with the provider's raw error body (should be a clean 502) |
| T-049 | — | — | Reserved — operational/deployment item, tracked outside this repo |
| [T-050](T-050-borderless-forecast-tables-flattened.md) | Open | Medium | Borderless forecast tables are flattened, scrambling column↔value attribution |
| [T-051](T-051-fast-text-mode-min-api-calls.md) | Open | Low | A figure-less text PDF still spends baseline API calls (no fast text mode) |
| [T-052](T-052-librechat-mistral-ocr-compat-endpoint.md) | Open | Medium | LibreChat/Mistral-OCR clients can't point at figmark (no compatible endpoint) |
| [T-053](T-053-vision-ocr-failure-is-opaque.md) | **Closed** | Medium | A scanned page the vision model can't OCR fails with an opaque, misleading error |

## How a ticket is written

- A title that describes the symptom, not the solution
- **Symptom**: what was observed, with a concrete repro
- **Root cause**: what the real problem is
- **Impact**: who notices it and how
- **Options**: numbered solution paths with trade-offs — not a pre-chosen solution
- **Acceptance criteria**: how we know the ticket is done
