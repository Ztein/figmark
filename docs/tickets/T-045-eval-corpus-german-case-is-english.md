# T-045: The eval corpus's only non-English document is actually English

**Status:** Closed — fixed 2026-06-25. The fake `ecb-eb-202404-de` entry (an
English PDF under a German name) is replaced in
[manifest.yaml](../../examples/eval/manifest.yaml) by a genuinely German
central-bank report — OeNB *Konjunktur aktuell* (September 2023) — verified to
download and to be detected as **German** by `detect_language` against the real
API. The corpus now has real non-English coverage for T-007.
**Priority:** Medium — corpus integrity; no code defect, but it hid a blind spot.

## Symptom

`output/eval/ecb-eb-202404-de/document_language.txt` reads `English`, even though
the entry is labelled German (`language: de`,
`source: EZB Wirtschaftsbericht 4/2024 (German)`). Surfaced while spot-checking
language detection after the first live e2e run in 14 days (see
[#50](https://github.com/Ztein/figmark/pull/50)).

## Root cause

Not a detection bug — detection was **correct**. The file is English:

- `examples/eval/ecb-eb-202404-de.pdf` contains "ECB Economic Bulletin, Issue
  4/2024 … the Governing Council decided to lower the three key ECB interest
  rates" — no German anywhere.
- The manifest URL `…/eb202404.de.pdf` **serves the English PDF** (byte-identical,
  4,172,015 bytes). The ECB Economic Bulletin is published as a PDF only in
  English; the German edition exists only as web HTML (`eb202404.de.html`), so the
  assumed `.de.pdf` never carried German content.

`download_eval.py` faithfully downloaded what the URL served; the manifest's
assumption was wrong.

## Impact

The eval corpus *looked* multilingual but was not. `ecb-eb-202404` and
`ecb-eb-202404-de` were the **same English document under two names** — a wasted
eval slot masquerading as language diversity. T-007 (descriptions follow the
document's language; detect ≠ English → describe in that language) therefore had
**zero real coverage** in the corpus, while appearing to have it. Exactly the
"the corpus is lying to us" failure mode the bench-before-code discipline exists to
prevent.

## Options

1. **Replace with a genuinely German central-bank PDF** and content-verify the
   download (chosen). Candidate verified: OeNB *Konjunktur aktuell* — a direct,
   stable `.pdf`, unambiguously German, central-bank genre (close to the rest of
   the corpus).
2. **Drop the `-de` entry** — removes the false diversity but leaves T-007 with no
   non-English coverage at all. Worse.
3. **Add a content-language assertion to `download_eval.py`** — fetch, then check
   the extracted text actually matches the declared `language` before accepting the
   file, so a wrong/redirecting URL fails loud instead of silently storing the
   wrong document. Complements (1) and prevents recurrence.

## Acceptance criteria

- [x] The corpus contains at least one document whose text is genuinely
  non-English, with a stable direct-download URL.
- [x] `detect_language` returns the correct non-English name for it against the
  real API (verified: `German`).
- [ ] (Follow-up) `download_eval.py` verifies downloaded content-language against
  the manifest `language` field and fails loud on mismatch (Option 3).
