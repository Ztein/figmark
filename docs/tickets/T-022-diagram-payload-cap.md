# T-022: Diagram payloads were sent uncapped — large charts rejected by the API

**Status:** Closed — fixed 2026-06-11, found by the central-bank evaluation corpus
**Priority:** HIGH — hard failure on real-world documents

## Symptom

bis-ar-2024 (BIS Annual Economic Report 2024) failed with
`BadRequestError` on "page 115 diagram 1". The rendered region was a 1 MB PNG
(~1.37 MB after base64) — past the endpoint's payload limit.

## Root cause

`describe_image` prepares payloads via `_prepare_image_for_api` (resize +
JPEG re-encode under `MAX_PAYLOAD_BYTES`), but `describe_diagram` base64'd the
raw rendered PNG with no size guard. Any sufficiently large/complex chart
region rendered at 200 DPI could exceed the cap.

## Resolution

`describe_diagram` now routes through the same `_prepare_image_for_api`.
Regression test feeds a >cap noise PNG through `describe_diagram` with a
recording fake client and asserts the encoded payload stays under the cap.
Verified live: bis-ar-2024 now converts fully (150 pages, 121 figures).

## Acceptance criteria

- [x] Regression test red before, green after
- [x] bis-ar-2024 converts end-to-end against the real API
