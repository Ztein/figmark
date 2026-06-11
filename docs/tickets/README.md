# Tickets

Open bugs and improvements for figmark, numbered `T-NNN`.

| ID | Status | Priority | Title |
|---|---|---|---|
| [T-001](T-001-vector-diagrams-missed.md) | **Closed** | HIGH | Vector charts missed entirely — pipeline only saw raster images |
| [T-002](T-002-misleading-filtered-image-log.md) | Open | Low | Log says "N image blocks" but doesn't explain why 0 are saved |
| [T-003](T-003-parallel-image-description.md) | **Closed** | Medium | Parallel processing of image/diagram descriptions with a rich CLI |
| [T-004](T-004-tagged-pdf-pdfua.md) | Open | Medium | Tagged PDF / PDF/UA via pikepdf — real accessibility via the structure tree |
| [T-005](T-005-pdf-annotations.md) | **Closed** | Medium | Embed descriptions as text annotations in the PDF (MVP accessibility) |
| [T-006](T-006-text-context-around-images.md) | **Closed** | Medium | Send text context around the image (100 words before/after) to the description |
| [T-007](T-007-description-language-follows-document.md) | **Closed** | Medium | Description language is hardcoded to Swedish — should follow the document |
| [T-008](T-008-diagram-internal-text-leaks-into-body.md) | Open | Low | Vector-diagram internal text leaks into the body text (needs a decision first) |
| [T-009](T-009-starlette-badhost-cve.md) | **Closed** | HIGH | Starlette BadHost CVE in the lockfile — fixed before first push |
| [T-010](T-010-provider-agnostic-llm-key.md) | **Closed** | Medium | Purge provider-specific references — figmark is provider-neutral |
| [T-011](T-011-codeql-sast.md) | **Closed** | Medium | Enable CodeQL (SAST) |
| [T-012](T-012-dependabot.md) | **Closed** | Medium | Enable Dependabot updates |
| [T-013](T-013-pip-audit-hard-gate.md) | **Closed** | Medium | Make pip-audit a blocking CI gate (was advisory) |
| [T-014](T-014-secret-scanning-push-protection.md) | **Closed** | Medium | Verify GitHub secret scanning + push protection on the repo |
| [T-015](T-015-sha-pin-actions.md) | **Closed** | Low | SHA-pin GitHub Actions |
| [T-016](T-016-cosign-image-signing.md) | Open | Low | Sign the release image and attest the SBOM (cosign) |
| [T-017](T-017-compose-defaults-to-ghcr.md) | **Closed** | Medium | compose should run the published GHCR image — clone-free quickstart |
| [T-018](T-018-first-public-release.md) | Open | Medium | Cut the first public release (v0.2.0) |
| [T-019](T-019-repo-cosmetics.md) | Open | Low | Disable unused repo tabs (Wiki, Projects) |

## How a ticket is written

- A title that describes the symptom, not the solution
- **Symptom**: what was observed, with a concrete repro
- **Root cause**: what the real problem is
- **Impact**: who notices it and how
- **Options**: numbered solution paths with trade-offs — not a pre-chosen solution
- **Acceptance criteria**: how we know the ticket is done
