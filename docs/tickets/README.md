# Tickets

Open bugs and improvements for figmark, numbered `T-NNN`.

> Note: the individual ticket files below are historical design notes from the
> project's pre-open-source development and are still written in Swedish. They
> are kept for context; new tickets should be written in English.

| ID | Status | Priority | Title |
|---|---|---|---|
| [T-001](T-001-vector-diagrams-missed.md) | **Closed** | HIGH | Vector charts missed entirely — pipeline only saw raster images |
| [T-002](T-002-misleading-filtered-image-log.md) | Open | Low | Log says "N image blocks" but doesn't explain why 0 are saved |
| [T-003](T-003-parallel-image-description.md) | **Closed** | Medium | Parallel processing of image/diagram descriptions with a rich CLI |
| [T-004](T-004-tagged-pdf-pdfua.md) | Open | Medium | Tagged PDF / PDF/UA via pikepdf — real accessibility via the structure tree |
| [T-005](T-005-pdf-annotations.md) | **Closed** | Medium | Embed descriptions as text annotations in the PDF (MVP accessibility) |
| [T-006](T-006-text-context-around-images.md) | **Closed** | Medium | Send text context around the image (100 words before/after) to the description |

## How a ticket is written

- A title that describes the symptom, not the solution
- **Symptom**: what was observed, with a concrete repro
- **Root cause**: what the real problem is
- **Impact**: who notices it and how
- **Options**: numbered solution paths with trade-offs — not a pre-chosen solution
- **Acceptance criteria**: how we know the ticket is done
