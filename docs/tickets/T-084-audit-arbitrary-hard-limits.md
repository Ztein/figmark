# T-084: audit for hard limits set without a validated reason (sizes, mimetypes, timeouts)

**Status:** Open
**Priority:** Medium — the image cap (T-083) turned out to be a guess; the same
smell almost certainly recurs across the codebase, and an arbitrary limit
silently degrades (drops content, rejects input, cuts a description) with no
evidence it is correct.

## Symptom

`MAX_IMAGE_DIM = 1500` was frozen by feel, not validated against the model
(T-083). figmark has many similar module-level constants and allowlists that
gate real behaviour but were each set once and never checked:

- **Sizes / caps:** `MAX_PAYLOAD_BYTES`, `MAX_IMAGE_DIM`, `MAX_TOKENS`
  (describe/diagrams), `OCR_MAX_TOKENS`, `RENDER_DPI`, the diagram size/drawing
  floors, `SPREADSHEET_PAGE_WARN_THRESHOLD`.
- **Timeouts / retries:** the office `timeout_seconds`, request timeouts, retry
  counts / backoff.
- **Mimetypes / allowlists:** the input-format sniffing set, the Mistral-OCR
  parameter allowlist, the significance/skip contract.

Any one of these can be quietly wrong.

## Root cause

Constants accreted as the pipeline grew. The project upholds "fail loud" and
"stay lean," but not explicitly "**every limit must have a validated or
justified reason**" — so numbers picked by feel never got revisited.

## Impact

- Silent quality loss (downscaling, truncation) or silent rejection (a mimetype
  or size that a real input trips) with no signal that the threshold, not the
  input, was the problem.
- Operators can't adapt limits to their model/endpoint/documents.

## Options

1. **Sweep the constants and classify each:** validated (keep, cite the bench),
   arbitrary-but-safe (justify + document), or arbitrary-and-risky (make
   configurable, or remove, or bench a real value).
2. **Adopt a principle + a lightweight guard:** a limit either cites its
   validation or is config-driven — no bare magic numbers gating behaviour.
   (See the CLAUDE.md principle added alongside this ticket.)

## Acceptance criteria

- A documented inventory of every hard limit / allowlist that gates behaviour,
  each with: the value, where it's used, and *why* (validated against what, or
  "arbitrary → made configurable / fixed / removed").
- The arbitrary-and-risky ones are config-driven or benched, not frozen guesses.
- New limits going forward carry a justification (principle enforced in review).
