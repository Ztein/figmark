# H0 — does the yardstick tell good output from bad?

PRD, *Validera måttstocken först*. Written down **before** the first H0 run
(2026-09-24); the run is judged against this, not the other way round.

## Set-up

- Figures: every figure in `eval/questions/` that has a reference description in
  `reference/` — 21 figures of five kinds (13 line/bar charts in Swedish;
  flowcharts, a map, a pie chart and a scatter plot, mostly in English).
- Reference descriptions: written by a model from another family than the figure
  interpreter (claude-opus-5-5), from the figure image and its page only,
  **without seeing the questions**, in the PRD's per-type format.
- Variants, each inserted into the floor text where the figure stands
  (`eval/h0.py build`):

  | Variant | What it is |
  | --- | --- |
  | `reference` | The reference description |
  | `wrong_numbers` | Same text, every value moved 30–60 % (years kept) |
  | `swapped` | Structure broken: flowchart edges reversed, chart series names rotated |
  | `ocr_only` | Only the text inside the figure box (text layer, else Tesseract) |
  | `none` | Nothing added — the floor |

  Plus the ceiling: the same retrieval with the figure image attached.
- Scoring: `eval/qa.py`, retrieval form, right +1, "okänt" 0, wrong −1; every
  variant run twice.

## Expected order

1. `reference` > `none`
2. `reference` > `wrong_numbers`
3. `reference` > `swapped`
4. `reference` > `ocr_only`
5. `wrong_numbers` < `ocr_only` — confident wrong values must cost, not pay
6. `ocr_only` ≥ `none` (may be equal: for vector figures the floor already
   holds the figure's text)

## Questions the floor already answers

A question the floor answers right in both runs does not need the figure (the
body text states it), so it cannot tell figure outputs apart. Such questions are
reported separately as *answerable without the figure*; the pass criteria apply
to the rest. (Added after the first floor run, before any H0 variant was scored:
the floor answered all seven questions on the Bank of Canada tariff figure.)

## Pass criteria

- Every strict inequality above holds on the mean score, and its 95 % bootstrap
  interval over questions excludes zero.
- The spread between the two runs of a variant is smaller than every difference
  in 1–5.
- Reported per figure kind as well; a kind where 1 fails is named as a weakness
  of the questions for that kind, not averaged away.

If H0 fails, questions or the measure change before anything else is measured.
