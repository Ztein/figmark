# Phase 1 — the simplest pipeline

Status 2026-10-06: measured. **At the decision point** (PRD: continue, shrink or
stop; where are the losses, which targets are reasonable).

## What was built

`figmark convert FILE... -o DIR` (`src/figmark/`, ~150 lines): Docling with its
default pipelines and its built-in picture description, pointed at any
OpenAI-compatible endpoint (`figmark.example.yaml`). It accepts every format
Docling reads; PDF, DOCX and PPTX were measured. Figures smaller than 5 % of
the page are left undescribed (Docling's default), and header/footer images are
not exported.

Readings compared, all scored by `eval/qa.py` (retrieval form, Gemma 4 31B
answerer, two runs each):

| Reading | What it is |
| --- | --- |
| floor | pdfium text layer, nothing interpreted |
| docling-plain | Docling, figures as `<!-- image -->` |
| docling | Docling + its default picture description ("Describe this image in a few sentences."), Gemma 4 31B |
| ceiling | floor retrieval + the figure (or page) image |

## Results — 230 questions on 7 documents

| Questions | n | floor | docling-plain | docling | ceiling |
| --- | --- | --- | --- | --- | --- |
| Figure | 174 | +0.11 | +0.07 | **+0.26** (22 % of the gap) | +0.83 |
| Table | 24 | +0.50 | +0.33 | +0.33 | +0.46 |
| Text | 32 | +0.80 | +0.81 | +0.75 | +0.97 |

Mean score per question (right +1, okänt 0, wrong −1). 95 % intervals are about
±0.1 for figures and ±0.2–0.3 for the small table and text groups.

Figure questions by kind (H0's reference description shown as a yardstick of
what a good description reaches):

| Kind | n | floor | docling | reference | ceiling |
| --- | --- | --- | --- | --- | --- |
| Line/bar chart (sv) | 119 | +0.01 | +0.22 | +0.61 | +0.81 |
| Flowchart | 34 | +0.41 | +0.31 | +0.94 | +0.94 |
| Scatter | 8 | +0.25 | +0.38 | +0.75 | +0.50 |
| Pie | 6 | +0.17 | +0.50 | +1.00 | +1.00 |
| Map | 7 | 0.00 | +0.43 | +1.00 | +1.00 |

### Hypotheses

- **H1 holds.** Text gap (ceiling − floor) 0.17, table gap ≈ 0, figure gap 0.73
  — text and tables are within half the figure gap. Docling is no better than
  the floor on text and tables in this measure.
- **H2 holds.** The floor reaches 13 % of the ceiling on figure questions
  (threshold: below 60 %). The figures carry most of what the floor misses.

## Where the losses are

1. **Figure descriptions are weak (the main loss).** Docling's default
   description closes 22 % of the gap; a good description closes ~80 %. Read
   side by side, the default description is in English for Swedish documents,
   describes shapes and colours ("a blue line … a red line"), hedges ("likely
   the policy rate"), gives almost no values and does not separate outcome from
   forecast. This is what phase 2's typed prompts are for.
2. **Docling drops the text inside figures.** A vector flowchart's labels are in
   the PDF text layer; the floor keeps them, Docling replaces the region with
   `<!-- image -->`. On flowcharts Docling with descriptions scores *below* the
   floor (+0.31 vs +0.41). In H0, the figure's own text alone lifted flowcharts
   from 0 to +0.30. Keep it.
3. **Small figures are never described.** 5 % of page area is Docling's default
   cut-off; 28 of 380 figures in the question documents were left undescribed
   (the Transformer paper's attention diagrams among them).
4. **Tables are read right but retrieved badly.** Docling's tables are correct
   (checked by hand), yet table questions score below the floor. Markdown tables
   padded with spaces are 70 % larger than needed, so a table spreads over many
   chunks and the header row ends up far from the values. Compact tables
   (padding removed) moved table questions +0.33 → +0.42 — within noise, but the
   direction is plausible. An output-format question for phase 2.
5. **Broken text layers pass unnoticed.** One Office file rendered to PDF has a
   font without a "d" mapping ("Energimyn ighetens"); Docling trusts the text
   layer. Phase 3's checks (PRD step 3: OCR where the text layer is broken).

## Text quality against native truth

Normalised edit distance against the source's own paragraphs, Office files in
test set v1, character-weighted (`eval/textquality.py`):

| Path | Distance | PRD target (digital PDF) |
| --- | --- | --- |
| Native DOCX/PPTX | 0.022 | — |
| Same files rendered to PDF | 0.079 | ≤ 0.02 |

The PDF path loses about 4× more; the largest single loss is the broken text
layer above (0.879 on that file).

## Robustness and throughput (test set v1)

All 49 documents converted without error (`eval/convert_set.py docling
--testset`, one process per document):

| Format | Documents | Pages | Figures | Described | Pages/min |
| --- | --- | --- | --- | --- | --- |
| PDF | 31 | 2 226 | 1 592 | 1 421 (89 %) | 23.7 |
| PPTX | 8 | 73 | 25 | 11 | — (seconds) |
| DOCX | 10 | — | 16 | 12 | — (seconds) |

- Robustness 49/49. One caveat: running many documents in a single process
  died silently on the fourth large PDF (no traceback; one document alone peaks
  at 8 GB resident). Each document now runs in its own process. The service in
  phase 4 needs the same isolation and a memory limit per job.
- PDF throughput: 23.7 pages/min on the Mac (Docling layout, tables and OCR on
  CPU/MPS) with figures described on a hosted endpoint at 8 in parallel. Not
  the Mac profile's figure time — that is measured in phase 2, locally.
- Native Office charts come through as data tables read from the chart XML
  (e.g. the CDC vaccine-effectiveness chart), without a description. Promising
  for H3 (phase 3).
- The figures left undescribed (11 %) are under Docling's 5 % size cut-off.

## Proposed decision

**Continue to phase 2, unchanged in scope.** The losses sit where the PRD put
them: figures. Proposed additions to phase 2, each with its own measurement:

1. Typed figure prompts in the document's language, with values per series and
   outcome vs forecast (H4) — the main lever, from 22 % towards ~80 %.
2. Keep the text layer inside figure regions next to the description.
3. Lower or remove the 5 % size cut-off, measured on recall (H10).
4. Compact Markdown tables.
5. Flowchart questions redone before (1) is judged on flowcharts (from phase 0).

6. **Figure cache — built (2026-10-06).** On the public corpus (120 PDF-heavy
   documents) repeats are rare: 0 within a document, about 1 % across documents
   once two reports that are in the corpus twice are discounted
   (`eval/duplicates.py`; `riksbank-ppr-202503` = `ppr-2025-03` and
   `riksbank-ppr-202512` = `ppr-2025-12`, to be removed in test set v2). A
   non-public field corpus of 177 PPTX/DOCX files gave the opposite answer:
   of 1 143 uses of images ≥ 30 kB in slides and body text, 26 % repeat an
   image earlier in the same file and 38 % one in an earlier file — decks built
   from one another and several versions of one deck. So figmark now caches
   descriptions (`src/figmark/cache.py`): keyed on the image's pixels, the
   prompt and the request parameters, stored locally, empty answers never
   stored, identical images in flight described once, hits and misses reported
   per document. Hit rate on the field is measured there, with Docling's own
   figures.

Proposed targets after phase 1: figure coverage ≥ 60 % for phase 2 (the
reference reaches ~80 % on the same questions), ≤ 10 s per figure on the Mac
profile.
