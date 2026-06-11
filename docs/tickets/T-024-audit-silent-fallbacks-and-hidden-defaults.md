# T-024: Audit for further principle violations — silent fallbacks and hidden defaults

**Status:** Open
**Priority:** Medium — guards the project's core "fail loudly" principle

## Symptom / motivation

T-020 removed one dangerous silent fallback (the `BERGET_API_KEY` shim). That
prompted a wider question: where else does the code paper over a missing input,
a misconfiguration, or a failed call instead of failing loudly?

The principle (`CONTRIBUTING.md`, `README.md`, `docs/architecture.md`):

> **Fail loudly. No silent fallbacks.**

The nuance that makes this an audit rather than a blanket "remove all fallbacks":
**some fallbacks are legitimate and part of the design; most are not.**

- **Reasonable fallback** — a genuinely equivalent alternative strategy for the
  *same* goal, taken on a real signal, and announced loudly. Example: a page is
  not extractable as text with pdfplumber/PyMuPDF → fall back to OCR with
  Tesseract (and, below a confidence threshold, to the vision model). This is
  `ocr.py`'s `should_fallback` path and it is shouted loudly. **Keep.**
- **Unreasonable fallback** — papering over a user/config error by guessing at an
  input the user never gave, hoping something else works. Example (now removed):
  "the user didn't set `FIGMARK_API_KEY`, so quietly try a key left over under an
  old, deprecated variable name." These hide the real misconfiguration and
  **must raise**.

**Decision heuristic for every fallback found:** does it recover the *same*
operation via a legitimately equivalent path (reasonable — keep, but make it
loud), or does it mask a missing input / failed call by guessing (unreasonable —
raise)? When in doubt, raise.

## Inventory (audit 2026-06-11)

Concrete suspects found by reading `src/figmark/*.py`. Each needs a triage
decision (fix / accept-with-rationale).

### Likely violations

- **F1 — `images.py:65` silently drops an image.** `try: base =
  doc.extract_image(xref) except Exception: continue`. An image that fails to
  extract just vanishes — no log, no count, no marker. That is a silent
  fallback, and it compounds T-002 (the "N image blocks but 0 saved" log is
  already misleading). Fix: log loudly at WARNING+ with the xref and reason, and
  surface it in the skipped/diagnostics count — or re-raise if extraction
  failure is never expected.

- **F2 — `pipeline.py:288` and `:301` swallow *all* exceptions on best-effort
  LLM steps.** Language detection and the document summary catch `Exception` and
  continue with an `emit_loud(...)` message. It is loud, but it cannot tell apart
  "the model returned nothing useful" (fine to degrade) from "the API call
  itself failed — 401 from a bad key, timeout, connection refused" (a real
  error that a description call *would* abort on). A misconfigured key would
  surface here first as a benign "summary failed — continuing", masking the
  fault. Fix: let transport/auth errors propagate (abort, same as a description
  call), and only soft-degrade on a genuinely empty/again-loud result.

### Minor / diagnostics

- **F3 — `config.py` missing section → `{}`.** `raw.get("api") or {}` (and the
  same for every section). A wholly missing section degrades to an empty dict,
  after which `_require` reports a single *field* as missing rather than the
  whole section. Not a silent fallback (it still fails loudly), but the message
  could name the missing section. Low priority — decide whether to add an
  explicit "section present" check.

## Explicitly checked and found COMPLIANT (do not re-litigate)

- **`ocr.py` text → Tesseract → vision OCR fallback (`should_fallback`).** The
  canonical *reasonable* fallback; shouted loudly. Keep as-is.
- **`parallel.py` worker pool.** On a worker exception it cancels siblings
  (`FAIL_FAST`) and re-raises a `RuntimeError`. Compliant.
- **`api.py` `/v1/convert` broad excepts.** They map errors to HTTP status codes
  (422 unparseable PDF, 504 timeout, 429 busy, 413 too large) and re-raise
  `HTTPException` — surfacing errors as responses, not swallowing them. Compliant.
- **`config.py` disabled-branch defaults.** `sample_words`/`prompt` default to
  `0`/`""` only when `document_summary.enabled` / `diagrams.enabled` is false, in
  which case the values are never read. Harmless.
- **Operational env defaults** (`FIGMARK_HOST=0.0.0.0`, `FIGMARK_PORT=8000`,
  `FIGMARK_LOG_LEVEL`, `FIGMARK_WORK_DIR`, `DEFAULT_MAX_UPLOAD_BYTES`,
  `DEFAULT_REQUEST_TIMEOUT_SECONDS`, `DEFAULT_MAX_CONCURRENT_JOBS`). Sensible ops
  knobs with safe defaults — a different category from the strict `config.yaml`
  pipeline contract, which already enforces "no hidden defaults". Acceptable.
- **Module-level technical constants** (render DPI, clustering thresholds,
  `MAX_TOKENS`, `MAX_RETRIES`, image-size filters). Intentional design per
  `docs/architecture.md` and the `config.example.yaml` note. Acceptable —
  hardcoded *by policy*, in the documented place.

## Options

1. **Triage and fix F1 + F2; accept F3 with a clearer message; codify the rule.**
   Recommended.
2. Fix only F1/F2, leave the documentation rule implicit. Weaker — the next
   contributor re-derives the reasonable/unreasonable line from scratch.

## Acceptance criteria

- [ ] F1: a failed image extraction is logged loudly and counted, not silently
      dropped (or re-raised) — and the count is reflected in the response.
- [ ] F2: best-effort LLM steps propagate transport/auth failures (abort) and
      only soft-degrade on an empty result, still loudly.
- [ ] F3: triaged — either an explicit missing-section check, or a one-line
      note here recording the conscious decision to leave it.
- [ ] No `except Exception` in `src/` swallows an error without re-raising or a
      WARNING+ log / `emit_loud`.
- [ ] `CONTRIBUTING.md` design principles gain a short
      "fallbacks: reasonable vs must-raise" note, using the two canonical
      examples (OCR fallback = keep; missing-key fallback = raise).
