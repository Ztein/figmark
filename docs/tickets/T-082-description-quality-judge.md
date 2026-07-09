# T-082: no way to measure figure-description quality, only whether a figure was captured

**Status:** Open — the quality track (Step 2), after T-080/T-081.
**Priority:** Medium — coverage without a quality signal can regress silently
(a captured figure described badly still counts as covered).

## Symptom

The coverage bench (`scripts/coverage_bench`) measures *recall* — did we get the
figure at all. It says nothing about whether the description is **correct,
relevant, and at the right level of detail** for what the image is. Two concrete
gaps seen in the sample:

- A captured BoC stacked-bar chart was described by *colour* ("the orange segment
  is negative") instead of *concept* ("Exports contributed negatively"), though
  the legend was in the image.
- The prompt A/B "measured" quality by **word count** (+78 %) — which would rank
  a better, shorter, insight-first description as *worse*.

## Root cause

Description quality is open-ended and phrasing-invariant; a deterministic script
can't judge relevance or correctness. And there is no reproducibility control —
the model runs at the endpoint's default temperature, so quality varies run to
run and "better or worse?" is unanswerable.

## Impact

- Cannot tell whether a prompt/model/extraction change improved or degraded the
  actual output — the product's core value is unmeasured.

## Options (layered — cheap first)

1. **Reproducibility (Phase 0, prerequisite):** `temperature: 0` (+ seed if the
   endpoint supports it) so a baseline is stable.
2. **Curated gold set + fact-presence checks.** ~15–20 hand-picked figures across
   types (line, bar, stacked, combo, raster chart, process image, table, photo,
   decoration) with the *must-have facts* a good description contains (e.g. "names
   all 5 country series", "states Sweden lowest", "~800 bn peak"). A checker
   verifies presence — robust to phrasing. Seed: the govuk "Future of social care
   inspection" process image (verified capture already).
3. **LLM-as-judge (the real quality signal).** A strong model scores
   description-vs-source on a rubric: correct, relevant, and **right detail level
   for `kind`** (short for a genre photo, thorough for a process/diagram/chart).
   Costs budget + has its own variance → run before releases / on big changes.

## Coupled work (enabled by T-081's `kind`)

Unify the prompt: drop the vector→diagram / raster→image routing (the code
deciding "which prompt"), use one adaptive prompt keyed on the model's `kind`.
Measure the change with the judge, not word count. Direction from the session:
insight-first over exhaustive enumeration; enrich the request with document
metadata (publication, publisher, date, nearby headings — `doc.metadata` is
currently unused). See [[feedback-description-quality-direction]].

## Acceptance criteria

- A documented, reproducible quality score (gold-set fact coverage + judge
  rubric) that a change can be run against to show better/worse.
- The prompt A/B (Swedish vs English + metadata context) re-run under the judge,
  not word count, with numbers recorded.
