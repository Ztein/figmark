# T-083: the image payload cap (1500 px / 500 KB) is a hardcoded guess, not validated against the model

**Status:** Open
**Priority:** Medium — an arbitrary cap silently trades away detail (or risks
rejection) with no evidence it is the right number, and it can't adapt to the
endpoint you actually run.

## Symptom

`describe.py` downscales every image to fit two hardcoded constants:

```python
MAX_PAYLOAD_BYTES = 500_000
MAX_IMAGE_DIM = 1500  # "1500 px is plenty for a description"
```

Neither was derived from a model's real input limit — the comment literally says
"plenty," a guess. The value that matters is the model's **effective** vision
resolution (e.g. the SigLIP encoder in the Gemma family works at ~896², with
optional pan-and-scan tiling), which is model- and endpoint-specific. A cap set
too low needlessly discards detail; too high wastes bytes or gets rejected.

## Root cause

A technical constant that shapes output quality was picked once, by feel, and
frozen — instead of being validated against the model or exposed for the operator
to set for their endpoint.

## Impact

- On a model that could use higher resolution, we downscale and lose detail we
  didn't have to.
- On a stricter endpoint, a fixed cap may still be wrong (too large → rejected,
  too small → coarse).
- The operator can't tune it for their model without editing source.

## Evidence (2026-07-09, gemma-4-31B via Berget)

A whole 3-panel figure (each panel small after downscale) and a single panel at
full resolution both had the model read the same fine 6-character stacked axis
labels correctly — so 1500 px isn't obviously *wrong* here, but it is a guess
either way, and the "right" cap is whatever the running model validates to.

## Options

1. **Make it configurable** (e.g. `api.max_image_dim`, `api.max_payload_bytes`)
   with defaults that don't needlessly downscale — the operator sets what their
   endpoint supports.
2. **Probe the endpoint** at startup (or document a validation recipe) and pick
   the cap from what the model actually accepts/reads.
3. Both: configurable, with a documented "validate against your model" step.

Recommendation: (1) now (unblocks operators), (3) as the fuller answer. Pairs
with T-084 (audit the other unjustified limits).

## Acceptance criteria

- The image size/payload limit is config-driven, not a hidden constant, and
  documented as "set to what your model validates to — do not assume."
- The default does not downscale below what a mainstream vision model uses.
- No behaviour silently depends on an unexplained magic number here.
