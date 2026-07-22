# T-081: the skip/keep decision rides on a free-text "[SKIP]" string the model can fail to emit

**Status:** Open — **partially landed (#145); keystone; unblocks T-080.**
**Priority:** High — the fragile contract leaks junk into output and blocks the
capture-100 % work.

## Symptom

The significance gate asks the model to answer *exactly* `[SKIP]` for a
decorative image; `describe.is_skip()` parses that string from free text. When
the model instead writes prose — observed on a govuk docx region: *"The provided
image is not a diagram… it is text-based content"* — the junk lands in the
Markdown instead of being skipped, and a describe call is wasted.

This surfaced under T-080: capturing more regions means the model must reliably
say "this is not a figure", and a string contract is not reliable.

## Root cause

A semantic decision (is this worth describing? what is it?) is encoded as a
free-text string the model must format perfectly. Models don't, reliably.

## Impact

- Junk descriptions leak into output; wasted API calls.
- Blocks T-080: "let the model decide" is only clean when the model's decision
  is machine-readable.

## Options

1. **Structured output via `response_format: json_schema` (chosen).** A typed
   result the model must conform to:
   ```python
   class FigureResult(BaseModel):
       is_figure: bool        # False → skip (replaces the "[SKIP]" string)
       kind: Literal["chart", "table", "photo", "diagram", "decoration", "text"]
       description: str
   ```
   **Verified 2026-07-09:** Berget/gemma-4-31B honours strict `json_schema`
   (returned exactly the schema). `pydantic` is already a dependency.
2. Tool/function-calling — also works on Berget; more moving parts than (1).
3. Keep the string; add lenient parsing — treats the symptom, still fragile.

**Graceful fallback (air-gap requirement).** An endpoint without structured-output
support must still work: JSON-in-prompt → `pydantic` validation → last resort the
legacy `[SKIP]` string. figmark can't assume one endpoint.

**Bonus.** `kind` is the model's own classification — the building block for
removing the vector→diagram / raster→image *prompt* routing entirely (the code
would no longer decide which prompt to use). Deferred to the quality track
(T-082), but the field lands now.

## Progress

**Landed (#145, 2026-07-22).** The raster path only:

- `describe.call_vision()` tries `response_format: json_schema` (strict) first,
  validates the reply with `FigureResult` (pydantic), and returns `SKIP_MARKER`
  when `is_figure` is false — no marker string reaches the output.
- Fallback is per-endpoint and sticky: a `BadRequestError` records
  `base_url|model` in `_structured_unsupported` and every later call for that
  endpoint goes straight to the legacy free-text prompt (which still carries the
  `[SKIP]` instruction). Covered by `tests/test_structured_describe.py`.
- Truncation, the empty-completion hard error, retries and caching are unchanged.

**Remaining:**

1. **The diagram path still bypasses it.** `diagrams.py` calls the client
   directly, so an over-captured *vector* region cannot skip cleanly — which is
   precisely what T-080 needs. Route it through `call_vision` too.
2. **Cache fingerprint does not cover the response format** (open AC). Both
   `image_fp` and `diagram_fp` in `pipeline.py` hash the prompt, model, language
   and significance flag — but not whether the structured schema was used. The
   structured path drops the `[SKIP]` instruction from the prompt, so the same
   fingerprint now maps to two different prompts, and a cache written before
   #145 is silently reused. Add the format to both fingerprints (T-034
   semantics: a switch must be a clean miss).

## Acceptance criteria

- The describe path returns a validated `FigureResult`; `is_figure=False` skips
  cleanly (no marker string in output).
- Graceful fallback path covered by a test against the mock client.
- The config/cache fingerprint includes the response format so a switch is a
  clean cache miss (T-034 semantics).
- Offline suite green; the govuk docx over-captured regions skip with no junk.
