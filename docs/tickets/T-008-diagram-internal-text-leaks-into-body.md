# T-008: Vector-diagram internal text leaks into the body text

**Status:** Open — **needs a decision first** (see note below)
**Priority:** Low — cosmetic; affects only vector diagrams with embedded text
**Discovered:** 2026-06-09 reviewing `output/paper/paper.md` (U-Net Fig. 1, page 2)

> **Note — it is not obvious this is the right or necessary thing to fix.**
> The diagram is already described well, and an AI reader can tell the leaked
> fragments are label spillover and ignore them. The cost of a fix (suppressing
> text that overlaps a diagram region) carries a real risk of *removing legitimate
> body text* by mistake. "Do nothing" (Option 4) is a genuinely reasonable
> outcome. This ticket exists to capture the observation and force a deliberate
> decision, not because a fix is clearly warranted.

## Symptom

For a vector diagram that contains its own text labels, the labels are extracted
as ordinary text blocks and dumped — fragmented and out of order — between the
rendered figure and the continuing body text. In `paper.md`, page 2 (U-Net
Fig. 1) renders as:

```
![Diagram, page 2](diagrams/page-002-diagram-01.png)

> [a clear, complete description of the architecture]

2
64
1
64
128
…
input image
output segmentation map
196²
392 x 392
conv 3x3, ReLU
copy and crop
max pool 2x2
up-conv 2x2
conv 1x1
Fig. 1. U-net architecture (example for 32x32 pixels …)
```

The block of loose tokens (`64`, `128`, `196²`, `conv 3x3, ReLU`, …) is the
diagram's internal labels. They are redundant with the rendered image and the
description, fragmented, and easy to mistake for body content.

## Root cause

When a region is classified as a diagram it is rendered to PNG and described, but
the text blocks whose bounding boxes fall **inside that region** are not removed
from the page's text flow. So the same content is represented twice: once as the
image + description, and once as raw extracted label text. Raster images do not
have this problem — they carry no extractable text. It is specific to the vector
diagram path ([src/figmark/diagrams.py](../../src/figmark/diagrams.py) +
[src/figmark/output.py](../../src/figmark/output.py)).

## Impact

- The Markdown around a diagram is noisy and ugly for human readers.
- The loose numbers/labels can be misread as body text.
- For an AI consumer the impact is small — the description already carries the
  information and the spillover is recognisably noise.
- Confined to documents whose diagrams embed text (matplotlib/vector charts with
  axis labels, legends, annotations).

## Options

### Option 1: Suppress text blocks inside a diagram region
When a diagram region is finalised, drop the `TextBlock`s whose bbox is contained
in (or mostly overlaps) the region bbox from the body text.

- ✅ Removes the noise at the source
- ❌ **Risk of false removal**: the region bbox is expanded to capture axis titles
  and source lines (by design), so it can overlap nearby real body text — which
  would then silently vanish from the output. This is the main reason to be wary.
- ❌ Needs a containment threshold that is tuned and tested

### Option 2: Keep the text, but move/segregate it
Instead of deleting, collect the in-region text and attach it to the figure (e.g.
fold it into the description prompt as "labels visible in the figure", or render
it under the figure as a small `<details>`/caption rather than inline body text).

- ✅ Loses no information; no risk of deleting body text
- ✅ The labels could actually *improve* the description (Option 2a: feed them to
  the model as extra context)
- ❌ More plumbing; still has to decide what counts as "in the figure"

### Option 3: Heuristic de-noising of fragment runs
Detect runs of very short, isolated text blocks (single numbers, `196²`, 1–3
word legend items) adjacent to a diagram and collapse/hide them.

- ✅ Doesn't depend on exact bbox containment
- ❌ Fragile; risks eating real short lines (table cells, headings)

### Option 4: Do nothing
Accept the spillover. The description already conveys the figure; the noise is
tolerable, especially for machine consumers.

- ✅ Zero risk, zero work
- ✅ Honest about the low impact
- ❌ Human-facing Markdown stays a bit messy around text-heavy diagrams

## Recommendation

**Decide between Option 4 (do nothing) and Option 2 (segregate, don't delete).**
If anything is done, prefer Option 2 over Option 1 — never silently delete text
that might be real body content. Option 2a (feed the labels to the description
model) is the only variant that turns the leak into a net positive. But none of
this is clearly necessary; closing as "won't fix" is an acceptable resolution.

## Acceptance criteria

- [ ] A decision is recorded: fix (which option) or won't-fix, with the rationale.
- [ ] *If fixed:* no legitimate body text is removed from a regression document
      (e.g. the U-Net paper body text on page 2 is still fully present).
- [ ] *If fixed:* the U-Net Fig. 1 label spillover (`64`, `196²`, `conv 3x3,
      ReLU`, …) no longer appears as loose body text in `paper.md`.
- [ ] *If fixed:* raster-image pages are unchanged (no regression where there was
      no problem).
