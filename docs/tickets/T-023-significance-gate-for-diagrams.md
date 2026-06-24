# T-023: Apply the significance gate to vector-diagram regions

**Status:** Closed — implemented 2026-06-24 (PR #33). `describe_diagram` now applies
`significance=cfg.significance.enabled`; `[SKIP]` diagrams are dropped from the
Markdown and not annotated. (Eval re-run on ECB bulletins is a live-API follow-up.)
**Priority:** Low — 2 % of diagram regions in the eval corpus; output is ugly, not wrong

## Symptom

In the central-bank evaluation (docs/eval-report-2026-06-11.md), 12 of 713
vector-diagram regions (2 %) were not charts but logos/decorations — mostly the
ECB logotype, which is vector art and clusters like a chart. The model honestly
answers "this is a logo, not a chart", and that text lands in the markdown as a
figure caption.

## Root cause

The significance gate ([SKIP] for decorative images) is deliberately applied
only to raster images; diagram regions were assumed to always be real charts
("clustering already ensures a region is a real chart"). The eval disproved the
assumption: vector logos pass the cluster filters.

## What to do

Enable the skip instruction in `describe_diagram`'s prompt composition
(`significance=cfg.significance.enabled` instead of `False`), and make the
output layer drop [SKIP]-marked diagram descriptions the same way it drops
skipped images (verify `_shown`/annotation handling covers
`diagram_descriptions`). Re-run the ECB bulletins from the eval corpus to
confirm the logos disappear and no real chart is lost.

## Acceptance criteria

- [ ] ECB bulletin logos are skipped, not described
- [ ] No regression in described-figure counts for chart-heavy docs (BIS QR,
      CNB chartbook within ±1 of the 2026-06-11 eval)
- [ ] Offline tests cover a [SKIP] diagram description end to end
