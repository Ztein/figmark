# T-067: Audit for further silent-degradation paths — where else does bad input or a degraded run produce a confident-looking result?

**Status:** Closed — **audit performed + Option 3 shipped 2026-07-06** (see
the audit record at the bottom: 7 instances found and fixed inline, the
remaining surfaces recorded clean, and the mechanical guard adopted as ruff
rules BLE001/S110/S112 on `src/figmark`).
**Priority:** Medium — the CLI Office gap (T-066) is proof that the last
fail-loud audit (T-024) did not cover every surface. One escaped instance means
the class isn't closed; a fresh, systematic sweep is warranted.

## Symptom

figmark's core principle is **fail loud, never silently degrade** (T-024). Two
instances have since slipped through anyway:

- the CLI accepts a non-PDF and emits a near-empty result with `exit 0` (T-066);
- `/v1/ocr` accepted documented request parameters and silently ignored them
  (T-057, now fixed).

Both are the same shape: an input or condition the code can't truly honour is
handled *as if it were fine*, producing output that looks right and is wrong.
There is no reason to assume these are the last two.

## Root cause

The T-024 audit was a point-in-time pass and predates several surfaces (the
Mistral-OCR compat layer, the Office path, the cross-request cache, the CLI's
current shape). New code adds new places a degraded path can be taken quietly:
a fallback `except` that returns a default, an "open it anyway" that tolerates
the wrong type, an optional feature that no-ops when misconfigured instead of
complaining.

## Scope of the audit

Systematically sweep for the pattern "**a wrong/degraded input or state yields
output instead of a loud failure**." Concrete places to check:

- **Every entry point's input gate.** CLI (T-066), `/v1/convert`, `/v1/ocr`,
  `/v1/files` — does each reject or loudly handle unsupported/mismatched/
  truncated input, or open-and-hope?
- **`except` blocks that swallow or default.** Grep for broad excepts and
  `return None`/`return []`/`return ""` on error paths — is the failure surfaced
  (logged loud / raised) or quietly absorbed? (`find_tables` already does this
  right, T-024; confirm the newer modules do too — `office.py`, `ocr_compat.py`,
  `cache.py`, `input_formats.py`.)
- **Optional features that no-op when misconfigured.** A config flag on but its
  dependency missing, a prompt/threshold unset — does it warn or silently do
  nothing? (Contrast T-051's *intended* skip, which is announced.)
- **Truncated / empty model output.** finish_reason handling (T-033) — is every
  describe/summary/language call covered, including the OCR and diagram paths?
- **Cache correctness.** Does a config/version change always miss cleanly (a
  stale hit is a silent wrong answer), across both the document and description
  keys? (T-034/T-058 changed the keys; re-verify.)
- **Quiet mode.** The container runs `quiet=True`; confirm loud warnings still
  reach the logs and are not `_noop`'d away (the exact T-032 regression).

## Impact

- Trust: figmark's whole pitch to downstream LLM pipelines is that its output is
  honest — "partial but not silently wrong." Each silent-degradation instance
  erodes that.
- Every escaped instance is a debugging trap for operators (a wrong result with
  no error to grep for).

## Options

1. **Manual structured audit** across the surfaces above, filing a `T-NNN` per
   real instance found (as T-024 did). Thorough; the template exists.
2. **Add lint/CI guards where mechanisable** — e.g. flag bare `except:` /
   `except Exception` without a re-raise or a loud log in the pipeline packages,
   so new silent-degradation paths are caught at review time, not in production.
3. **Both**: audit now, then add the guard so the class stays closed.

## Acceptance criteria

- [x] A recorded pass over the surfaces listed, with each genuine
      silent-degradation instance filed as its own ticket (or fixed inline if
      trivial), and an explicit "no further instances found in X" where the
      sweep came up clean.
- [x] A decision on a mechanical guard (Option 2) — adopted with a rule, or
      recorded as rejected with a reason.

## Audit record (2026-07-06)

Three parallel sweeps over `src/figmark/` (except-blocks; entry-point gates +
misconfigured-feature no-ops + quiet mode; model-output handling + cache-key
correctness), each finding verified by hand before action.

### Instances found — all fixed inline in the closing PR

1. `api.py` figures assembly: a figure file PIL could not decode was absorbed
   (`except OSError: → None` dims, no log). Now announced at WARNING.
2. `config.py` `_require`: a whitespace-only prompt passed the missing-field
   check and stripped to empty — an enabled feature ran with a degenerate
   task. Whitespace-only now counts as missing (loud RuntimeError).
3. `summarize.py` language detection: a `finish_reason=length` truncation
   inside the 8-token cap cached a cut-off sentence as the document language.
   Now announced + falls back to the document-language instruction; garbage is
   never cached.
4. `summarize.py` document summary: a token-capped summary was cached and
   silently reused. Now announced, used for the current run (T-033 semantics),
   never cached.
5. `pipeline.py` description fingerprints: `ocr.language` was missing — a CLI
   re-run with a changed OCR language reused stale descriptions on scanned
   documents (the HTTP surface's `config_cache_fingerprint` already included
   it). Added to `image_fp`/`diagram_fp`.
6. `pipeline.py` `_summary_fp`: `document_summary.sample_words` was missing —
   a changed sample size reused descriptions built on a differently-sourced
   summary. Added.
7. `pipeline.py` summary/language disk caches: `document_summary.txt` /
   `document_language.txt` were keyed by path alone — any config change reused
   the stale file. Both filenames now carry a fingerprint of what shaped them.

### Recorded clean (no further instances found)

- Except-blocks: `office.py`, `ocr_compat.py`, `cache.py`, `input_formats.py`,
  `images.py`, `diagrams.py`, `tables.py`, `ocr.py`, `pdf_loader.py`,
  `structure.py`, `output.py`, `boilerplate.py`, `annotate.py`, `tagged.py`,
  `context.py`, `parallel.py`, `usage.py`, `config.py`, `describe.py`,
  `main.py` — every degradation is announced or re-raised.
- Entry-point gates: `/v1/convert` + `/v1/ocr` honour or loudly reject every
  documented parameter (T-057/T-059 hold); cache management validates digests;
  Office conversion failures surface as 422; the CLI gate is T-066.
- Quiet mode: `emit_loud` routes warnings to the structured logs under
  `quiet=True` (T-032 holds).
- Model output: describe/diagram/OCR calls all fail loud on empty content;
  describe/diagram truncation is T-033/T-075.
- Feature flags: enabled-with-missing-dependency fails at config load.

### Mechanical guard — adopted

Ruff rules `BLE001` (blind except), `S110` (try-except-pass) and `S112`
(try-except-continue) are now enforced on `src/figmark` (tests/scripts/
examples exempt): a swallowed exception in the shipped package needs a loud
log plus a `noqa` naming the reason, or it does not pass CI.
