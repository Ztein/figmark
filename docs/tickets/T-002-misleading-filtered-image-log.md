# T-002: Log says "N image blocks" but doesn't explain why 0 are saved

**Status:** Open
**Priority:** Low — cosmetic, but confusing during diagnosis

## Symptom

When running against `penningpolitisk-rapport-mars-2026.pdf` the log shows:

```
Page 44/72
  → 8 text blocks, 4 image blocks (references)
  → 0 image(s) saved

Page 60/72
  → 9 text blocks, 9 image blocks (references)
  → 0 image(s) saved
```

"4 image blocks detected, 0 saved" makes it sound like a bug. The user noticed this during diagnosis and reported it as a possible candidate for T-001.

## Root cause

The image blocks are 10×10 px decorative icons (probably rasterized bullet markers or footnote markers). [src/figmark/images.py](../../src/figmark/images.py) filters out everything below `cfg.images.min_width` / `min_height` (default 50). The filter is correct — we don't want to describe 10×10 icons. But the log says nothing about the filtering having happened.

## Impact

- Misleading during diagnosis — looks like a bug even though it's expected behavior
- Makes it hard to tell "filtered out" apart from "extraction failed"

## Options

### Option 1: Add a filtering count to the log
```
Page 44/72
  → 8 text blocks, 4 image blocks (references)
  → 0 image(s) saved (4 filtered: all < 50x50)
```

Requires `extract_images_from_page` to return both `kept` and `skipped` lists, or at least a counter.

### Option 2: Log only at debug level
Drop the detailed per-page log and show only the final summary. Gives cleaner default output but worse diagnostics.

### Option 3: Structured log output (JSON via flag)
For scripting/automation. Overkill for this ticket.

## Recommendation

**Option 1.** Small code change, big explanatory value.

## Acceptance criteria

- [ ] When filtering happens, the reason + count are shown in the log
- [ ] The Pentland PDF (no filtered images) shows the same log as today
- [ ] No change in exit codes or output artifacts
