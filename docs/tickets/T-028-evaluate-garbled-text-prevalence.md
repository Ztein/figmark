# T-028: Measure how often PDFs have garbled (present-but-broken) text before building OCR handling

**Status:** Open
**Priority:** Low — evaluation/spike; decides whether T-027's quality axis is worth building
**Relates to:** [T-027](T-027-per-page-scan-decision.md) (the per-page decision this would extend)

## Symptom / motivation

figmark trusts the PDF's embedded text layer. When that layer is *present but
broken* — a missing/garbled ToUnicode CMap, a subsetted or CID font with no proper
Unicode mapping — `get_text()` returns mojibake: Private Use Area characters
(U+E000–U+F8FF), replacement characters (U+FFFD), or systematically wrong letters.

This slips through every guard we have:

- [`is_scanned`](src/figmark/pdf_loader.py) counts character *quantity*, not
  *quality*; a garbled page has plenty of characters, so it is classified
  "text-encoded" and never OCR'd.
- Unlike Tesseract, native extraction returns **no confidence signal**, so the
  output looks 100 % successful while being unreadable.

We could add a *quality axis* to the per-page classifier (T-027): detect garbled
text and fall back to render→OCR. That is a **reasonable** fallback (same goal, a
legitimately equivalent path, on a real signal, announced loudly). **But** it
carries real false-positive risk — number-heavy tables, math, non-Latin scripts
can look "garbled" to a naive detector, and needlessly OCR-ing a correct page
costs money and can *degrade* good text. OCR is neither free nor lossless.

So before building anything, **measure how often this actually happens** on
realistic inputs. The cost of detection only pays off if the problem is real at
some prevalence.

## This is a spike, not an implementation

The deliverable is a **measurement + a recorded decision**, not a feature.

## Approach

1. **Assemble a realistic corpus.** The `eval/` set plus a broader, deliberately
   varied sample of what figmark will really meet: Riksbank reports across several
   years *and* some third-party / older / externally-produced PDFs — the latter
   are the likely offenders, since the bank's own export pipeline tends to emit
   clean text layers.
2. **Compute cheap garble signals per page** (measurement only, not shipped): PUA
   ratio (U+E000–U+F8FF), U+FFFD ratio, control/non-printable ratio, and a
   no-spaces / implausible-symbol-density check. Flag pages above conservative
   thresholds.
3. **Verify a sample by hand** — flagged and unflagged — to estimate precision
   (are flagged pages truly garbled?) and recall (any garbled pages missed?).
4. **Report prevalence:** share of documents and of pages affected, with the
   thresholds used.

## Decision (record the outcome in the PR)

- **If meaningfully prevalent** → file a follow-up implementation ticket: add the
  quality axis to T-027's per-page classifier (render→OCR on a garble signal),
  starting with the highest-precision signals (PUA + U+FFFD) to keep false
  positives near zero.
- **If rare** → do **not** build detection. Instead:
  - document the known limitation in the README ("figmark trusts the PDF's text
    layer; PDFs with broken font encodings / missing ToUnicode may produce garbled
    output — re-export or pre-OCR such files"), and
  - optionally add a *cheap* per-document loud warning when the garble signal is
    high, so a user is never silently handed mojibake (fail-loudly, at low cost).

## Acceptance criteria

- [ ] A representative corpus is assembled and described (sources, document/page
      counts).
- [ ] Per-page garble metrics are computed and the prevalence reported (documents
      and pages affected, thresholds stated).
- [ ] A hand-verified sample gives a rough precision/recall for the cheap signals.
- [ ] A decision is recorded: **implement** (→ follow-up ticket extending T-027,
      linked) or **document-as-limitation** (→ README note added in this PR, plus
      optional loud warning).
- [ ] No detection code is shipped to `src/` under this ticket beyond a throwaway
      measurement script (kept out of the runtime path, or under the eval tooling).
