# T-051: A figure-less text PDF still spends baseline API calls (no fast text mode)

**Status:** Closed — **implemented as Option 1 (2026-07-02).** When detection
finds zero image and zero diagram blocks, the document-summary call and the auto
language-detection call are skipped (language detection still runs when
`--tagged` is requested, since the tagged PDF sets the document `/Lang`). The
skip is logged — `logger.info` in quiet/API mode, stdout interactively — never
silent (T-024). A 0-figure text document now reports `api_calls: 0` instead of 2;
the saving is the full baseline (2 calls/document), which at corpus scale was the
entire reported cost. Tests: `tests/test_fast_text_path.py`.
**Priority:** Low

## Symptom

Converting a 1-page, 0-figure text PDF over `/v1/convert` reports `api_calls: 2`
even though there is nothing to describe. A 54-page text-only Beige Book reports 5
calls. The baseline spend is the document-summary call plus the language step, not
figure work. Reported during a downstream consumer's corpus-ingestion testing.

## Root cause

The pipeline always runs its context-building steps (document summary, language
handling) regardless of whether any figure/diagram will actually consume them. For
a purely textual document with no figures, that context is never used, so the calls
are pure overhead.

## Impact

- Not a bug — output is correct. But for a consumer ingesting a **large corpus** of
  text-heavy reports, the per-document baseline multiplies into real inference cost
  and latency that adds no value.

## Options

1. **Skip figure-context calls when there are no figures/diagrams.** If detection
   finds zero image and zero diagram blocks, the document summary (whose only job is
   to contextualise figure descriptions) and any figure-language step can be
   skipped. Smallest change; must stay *loud* (log that summary was skipped because
   there were no figures — no silent behaviour change).
2. **An explicit `text_only` / fast mode** on the request that bypasses all
   vision-oriented steps. More control for the consumer, but a new surface to
   document and test.
3. **Do nothing.** The cost is small per document; only matters at corpus scale.

## Acceptance criteria

- [ ] Decide whether the saving is worth the conditional complexity (bench the
      actual call/cost delta on a text-only corpus first).
- [ ] If implemented: a 0-figure text document makes the minimum necessary calls,
      and any skipped step is **logged**, not silently dropped (cf. T-024).
