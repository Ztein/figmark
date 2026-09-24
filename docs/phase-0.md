# Phase 0 — the yardstick

Status 2026-09-24: built and run. **Waiting for the decision point**: the
yardstick's approval and the thresholds for H1–H10 are Joel's call (PRD, *Faser*).

## What exists

| Piece | Where | Result |
| --- | --- | --- |
| Inventory | `eval/inventory.py`, `eval/inventory.csv` | 120 documents, 5 911 pages, 4 762 figures in the PDFs. Line charts 79 %, bar charts 9 %; flowcharts 37, maps 4, pie charts 2. 68 sv, 51 en, 1 de. **No scanned documents.** |
| Native truth | `eval/native_truth.py` | 20 Office charts with exact values from chart XML, 2 SmartArt graphics, paragraph text; Office → PDF via LibreOffice |
| Test set v1 | `eval/testset-v1.yaml` (frozen) | 49 documents, 1 633 figures; rules in `eval/testset.py` |
| Figure questions | `eval/questions/` | 174 categorical questions on 21 figures (13 Swedish charts, 5 flowcharts, map, pie, scatter) |
| Floor reading | `eval/floor.py` | pdfium text layer, nothing interpreted |
| Question runner | `eval/qa.py` | Retrieval form (e5-large, 800-character chunks, top 8), answerer Gemma 4 31B, right +1 / okänt 0 / wrong −1, ceiling = same retrieval plus the figure image |
| H0 | `eval/h0.py`, `eval/h0/` | Pre-registered in `eval/h0/README.md` before the run |

Models: answerer `gemma-4-31B-it`, embedder `multilingual-e5-large` — both run
locally; for speed they were served from a hosted endpoint. References for H0
were written by `claude-opus-5-5` (another family than the interpreter) from the
image alone, without seeing the questions.

## H0 result

145 questions that need the figure (29 more are answered by the floor alone and
are left out, as pre-registered). Two runs per variant.

| Variant | Mean score per question | Per run |
| --- | --- | --- |
| reference | +0.655 | +95, +95 |
| wrong_numbers | +0.090 | +13, +13 |
| swapped | +0.172 | +25, +25 |
| ocr_only | −0.010 | −1, −2 |
| none (= floor) | −0.079 | −11, −12 |
| ceiling (image) | +0.828 | +119, +121 |

| Pre-registered expectation | Difference | 95 % CI | Holds? |
| --- | --- | --- | --- |
| 1. reference > none | +0.734 | [+0.634, +0.828] | yes |
| 2. reference > wrong_numbers | +0.566 | [+0.414, +0.717] | yes |
| 3. reference > swapped | +0.483 | [+0.324, +0.638] | yes overall — **not for flowcharts** |
| 4. reference > ocr_only | +0.666 | [+0.538, +0.793] | yes |
| 5. wrong_numbers < ocr_only | +0.100 the other way | [−0.055, +0.252] | **no** |
| 6. ocr_only ≥ none | +0.069 | [−0.014, +0.148] | yes |
| Run-to-run spread < every difference | ≤ 1 question of 145 | | yes |

By figure kind (reference / wrong_numbers / swapped / ocr_only / none):

| Kind | Questions | Scores |
| --- | --- | --- |
| Charts (sv) | 107 | +0.57 / −0.08 / +0.04 / −0.07 / −0.11 |
| Flowcharts | 20 | +0.90 / +0.90 / +0.90 / +0.30 / 0.00 |
| Map | 7 | +1.00 / +0.71 / +0.57 / 0.00 / 0.00 |
| Pie | 5 | +1.00 / −0.20 / −0.60 / 0.00 / 0.00 |
| Scatter | 6 | +0.67 / −0.17 / +0.33 / 0.00 / 0.00 |

### Reading

- **Charts: the yardstick works.** Every degradation falls to about the floor,
  the reference sits well above, and the image ceiling above that.
- **Expectation 5 was wrongly specified.** `wrong_numbers` only corrupts values,
  so its yes/no and choice answers stay right. On the 66 number questions alone
  (a post-hoc cut, labelled as such) the penalty does what it should:
  wrong_numbers −0.38, ocr_only −0.08, none −0.06, reference +0.68.
- **Flowcharts: the yardstick cannot see reversed arrows.** With every edge
  reversed and the step list removed, the answerer still gets 18 of 20 right.
  The questions are answered from node labels, the summary sentence and world
  knowledge ("who starts a Swish payment" is the consumer whatever the arrows
  say; the Transformer figure is famous). The flowchart questions need items
  where direction is not common sense, and the swapped variant should also
  reverse the summary sentence.
- **Map, pie and scatter** have 5–7 questions each: the direction is right, but
  the numbers are too small to conclude anything.
- **The reference reaches 81 % coverage** ((ref − floor) / (ceiling − floor)). A
  careful description from a frontier model, 200–400 words, already falls
  short of the PRD's preliminary ≥ 85 % target.

### Resolution

The run-to-run spread on a hosted endpoint is at most one question in 145. The
PRD's concern about reloads cannot be observed there. The limit is the number of
questions: the 95 % interval on a paired difference is about ±0.08–0.10 score
per question, or **±10 coverage points with ~150 questions**. For ±5 points,
about 500–650 questions are needed.

## Proposed thresholds (for decision)

Proposals only. The PRD says they are set before any pipeline is measured.

| Id | Proposal | Note |
| --- | --- | --- |
| H0 | Approved for charts; **flowchart questions revised and H0 re-run for flowcharts before phase 2** | Charts are 88 % of all figures |
| H1 | Text gap ≤ ½ of the figure gap | Needs ~50 text questions, written in phase 1 |
| H2 | Floor below 60 % of the ceiling on figure questions (PRD) | Today −0.08 vs +0.83 |
| H3 | Native reading ≥ 10 points higher data-point hit rate on the 20 XML charts | Small N; a strong signal is needed |
| H4 | ≥ 10 coverage points, not 5 — or grow the set to ~600 questions first | 5 points is below today's resolution |
| H5 | Per figure ≤ 1 question difference (of ≥ 5) for ≥ 70 % of figures | |
| H6 | The flag catches ≥ 60 % of human-marked errors with ≤ 30 % false alarms | |
| H7 | Context package ≥ image only + 10 points, invented details up ≤ 1 point | |
| H8 | sv–en coverage gap ≤ 10 points | |
| H9 | Swapping the page parser moves final coverage ≤ 10 points | |
| H10 | Recall ≥ 98 % on ≥ 200 hand-counted figures | |
| Target | Figure understanding ≥ 75 % coverage for v1, 85 % as a stretch goal | The reference itself reaches 81 % |

## Open

- **Human review of the questions.** The 55 new questions were proposed by
  `claude-opus-5-5` and are marked pending review. The PRD requires a person to
  write or review every question before the set is frozen.
- **No scanned documents** in the corpus: the "textkvalitet, skannat" stratum
  is empty until some are added.
- **~150 questions give ±10 points.** More questions (≥ 5 per figure over
  ~100 figures) are needed before H4/H7/H9 can separate small effects.
