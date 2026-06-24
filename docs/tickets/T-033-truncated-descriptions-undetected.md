# T-033: Truncated descriptions are never detected (finish_reason ignored)

**Status:** Open
**Priority:** Medium — silent quality loss for an accessibility tool; tiny fix
**Source:** External code review (2026-06-24), verified against the code.

## Symptom

Neither `describe_image` ([describe.py:170](../../src/figmark/describe.py),
`MAX_TOKENS=600`) nor `describe_diagram`
([diagrams.py:298](../../src/figmark/diagrams.py), `MAX_TOKENS=1200`) inspects
`response.choices[0].finish_reason`. A description that hits the token cap is cut
mid-sentence, written to disk, and cached as if it were complete. For a tool whose
promise is faithful alt text, a truncated description is a silent quality failure —
contrary to fail-loud. The risk is sharpest on the **image path** (600 tokens); the
eval already noted a 420-word description, which in Swedish runs close to that cap.

## Secondary: a transient empty response is never retried

The empty-content `RuntimeError` ([describe.py:185](../../src/figmark/describe.py))
is raised *inside* the `try`, but the `except` only catches
`(APITimeoutError, RateLimitError, APIError)`
([describe.py:193](../../src/figmark/describe.py)). So a transient empty completion
aborts immediately instead of retrying. This may be intentional (a persistently
empty response usually means an unsupported model), but the behaviour should be a
deliberate, documented choice.

## Root cause

The response is reduced to `.content`; the metadata that says "I ran out of room"
(`finish_reason == "length"`) is discarded.

## Impact

Complex figures and diagrams in dense reports can be cut without any signal, and the
truncated text is then cached and reused.

## Options

1. If `finish_reason == "length"`, emit a loud/log warning naming the figure (do
   **not** auto-raise the cap — cost/runaway risk). Pairs with [T-032](T-032-loud-warnings-silenced-under-quiet.md).
2. Same, plus a config knob to retry once at a higher cap.
3. For the empty-response case: either add it to the retry set or document why not.

Recommendation: **Option 1** for truncation (warn, in line with fail-loud); decide
the empty-response retry separately and write the decision down.

## Acceptance criteria

- [ ] A length-capped completion emits a loud warning identifying the figure/diagram.
- [ ] Covered for both the image and diagram paths.
- [ ] Tested with a stubbed `finish_reason == "length"` response.
- [ ] The empty-response retry behaviour is decided and documented.
