# T-034: Description cache ignores config — stale output after a config change

**Status:** Open
**Priority:** Medium — a correctness trap disguised as a feature
**Source:** External code review (2026-06-24), verified against the code.

## Symptom

Descriptions are cached per figure stem: `descriptions/<stem>.txt` and
`diagram_descriptions/<stem>.txt`
([pipeline.py:364](../../src/figmark/pipeline.py),
[:387](../../src/figmark/pipeline.py); read-back in
[describe.py:153](../../src/figmark/describe.py) and
[diagrams.py:277](../../src/figmark/diagrams.py)). The cache key is the figure's
identity only. Change `language.output`, the prompt, the model, or `context.*` and
the old description is reused silently — the documentation tells you to delete the
cache directory by hand.

## Root cause

Cache key = figure identity, not (figure **+ the config that produced the text**).

## Impact

Output that does not match the current config, with no signal. Sharpest for
`language.output`: switch `sv → en` and you get the stale Swedish description back.
A correctness risk presented as a caching feature.

## Options

1. **Fold a short hash of `(model, prompt, language, significance, context settings)`
   into the cache filename** (or a sidecar). A config change → different key → miss
   → regenerate; identical config still hits.
2. Write a meta sidecar (the config fingerprint) next to each cached file and
   compare on read.
3. Documentation only (status quo) — rejected; it is a footgun.

Recommendation: **Option 1**, applied to both the image and diagram caches.

## Acceptance criteria

- [ ] Changing any of model / prompt / language / significance / context yields a
      cache miss and regenerates the description.
- [ ] Identical config still hits the cache (no needless API calls).
- [ ] Both the image and diagram caches are covered.
- [ ] Tested: same input + changed config → regeneration; same input + same config →
      hit.
