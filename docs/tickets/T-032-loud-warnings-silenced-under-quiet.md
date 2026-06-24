# T-032: Loud pipeline warnings are silenced in container/API mode

**Status:** Open
**Priority:** High — fail-loud breaks in exactly the deployment it was designed for
**Source:** External code review (2026-06-24), verified against the code.

## Symptom

The API server calls the pipeline with `quiet=True`
([api.py:307](../../src/figmark/api.py)). That sets `emit_loud = _noop`
([pipeline.py:203](../../src/figmark/pipeline.py)), so every `loud()` banner is
suppressed: OCR rescue in a text-encoded document
([pipeline.py:240](../../src/figmark/pipeline.py)), Tesseract→vision fallback
([pipeline.py:261](../../src/figmark/pipeline.py)), and a broken/mojibake text
layer ([pipeline.py:278](../../src/figmark/pipeline.py)). None of these reach the
API's structured JSON logger ([api.py:45](../../src/figmark/api.py)). So in the
air-gapped container deployment the project is hardened for, the warnings that
signal **degraded-but-not-failed** output vanish.

## Root cause

Pipeline diagnostics use `print()`-based `log()`/`loud()` gated by `quiet`, instead
of the `logging` module. The API has a JSON logger but the core pipeline never
writes to it. Note: *fatal* failures (language detection / document summary
`APIError`, [pipeline.py:319](../../src/figmark/pipeline.py),
[:336](../../src/figmark/pipeline.py)) still surface because they `raise`. This
ticket is specifically the **non-fatal warnings that only print** — the most
insidious to lose, since they mark silently degraded output.

## Impact

An operator running the server sees clean output with no indication that a page
was OCR-rescued, fell back to the vision model, or had an unusable text layer —
the exact opposite of the fail-loud principle, in the mode that matters most.

## Options

1. **Replace `log()`/`loud()` in the pipeline with a module logger**
   (`logging.getLogger("figmark.pipeline")`). The CLI attaches a pretty
   console handler in `main.run`; the API's JSON handler captures the same
   records. `quiet` then controls only the human-pretty console, not whether
   warnings are recorded.
2. Keep `loud()` for the TTY but *also* emit `logger.warning()` unconditionally
   for the loud events.

Recommendation: **Option 1** — one diagnostics path; warnings survive `quiet`.

## Acceptance criteria

- [ ] Loud-level events (OCR rescue, Tesseract fallback, garbled text layer) appear
      in the API's structured log when `quiet=True`.
- [ ] CLI output is unchanged (still human-readable banners on a TTY).
- [ ] A test forces a fallback under `quiet=True` and asserts a warning record is
      emitted.
