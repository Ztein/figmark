# T-066: The CLI accepts a non-PDF (e.g. an Office file) and emits a near-empty result instead of failing loud

**Status:** Closed — **Option 1 shipped 2026-07-06** (the input gate is now
transport-neutral in `input_formats.py` and shared by both surfaces: the CLI
sniffs, enforces the allowlist, converts Office input via LibreOffice exactly
like the service, and refuses unsupported/mismatching input with a clear
message + exit 2 — never a confident empty run).
**Priority:** Medium — a silent wrong answer on a public entry point is exactly
the failure class the project bans (fail loud, never silently degrade — T-024).
A user who runs `figmark deck.pptx` gets output that *looks* fine and is nearly
empty, with no signal that anything went wrong.

## Symptom

`figmark <file>` (the CLI, `main.run`) passes the path straight to `convert()`,
which opens it with PyMuPDF. Given an Office file, PyMuPDF does not convert it —
it opens it as a degraded near-empty "document" and the run completes with
`exit 0`:

```
$ figmark poi-bar-chart.pptx
Opening PDF: poi-bar-chart.pptx
Page count: 1
  → text: 12 chars, no full-page image (sparse, not scanned)
  → 0 image(s) saved
No figures or diagrams detected …
Done.  API usage: 0 call(s)
```

The same file through the HTTP surface converts correctly (LibreOffice → 1
diagram detected and described, T-054/T-055). The CLI produced an empty
Markdown, described nothing, and said nothing was wrong. Found 2026-07-03 while
running the office-eval corpus.

## Root cause

The input **format gate lives only in the HTTP handlers** — `/v1/convert` and
`/v1/ocr` sniff content and route Office formats through
`prepare_office_document` (T-054). The CLI's `main.run` has **no gate at all**:
no content sniff, no allowlist check, no Office conversion. It assumes its
argument is a PDF and lets PyMuPDF do whatever it does with whatever it is
handed. So any input PyMuPDF can *partially* open — an Office file, a mislabeled
file, a truncated PDF — yields output rather than a clear rejection.

## Impact

- **Office files via the CLI silently under-extract** — the whole T-054/T-055
  value (convert, detect charts, describe) is bypassed with no warning.
- **The two surfaces disagree.** The same document gives a rich result over HTTP
  and an empty one on the CLI — a correctness/consistency trap.
- More broadly, the CLI has no loud floor for "this input isn't what I can
  process," so future input types inherit the same silent-degradation risk.

## Options

1. **Share the input gate + Office conversion between CLI and HTTP.** Extract
   the sniff → allowlist-check → `prepare_office_document` logic into a shared
   helper both entry points call, so the CLI converts Office files exactly like
   the service and rejects unsupported input with the same loud 415-equivalent
   message. Best fidelity + consistency; the most code movement.
2. **CLI gate that fails loud but does not convert.** The CLI sniffs and, for a
   format it cannot handle itself (Office without the conversion wired in),
   exits non-zero with a clear message ("this is a .pptx — use the service, or
   pre-convert to PDF"). Cheaper; leaves the CLI less capable than HTTP, but
   honest.
3. **Detect the mismatch minimally.** At least assert the opened document looks
   like the requested type (e.g. the sniffed format is PDF, or page/text sanity
   checks pass) and fail loud otherwise. Narrowest fix; catches the silent-empty
   case without unifying the surfaces.

Option 1 is the product-consistent end state; Option 2 is an acceptable
loud-floor stopgap. Whatever ships, the litmus is: **no input produces a
confident empty result** — it is either handled or loudly refused.

## Acceptance criteria

- [x] `figmark <office-file>` either converts it (parity with the HTTP surface)
      or exits non-zero with a message naming the format and the remedy — never
      `exit 0` with an empty description set.
- [x] A content/extension mismatch or an unsupported type on the CLI fails loud,
      matching the HTTP surface's behaviour.
- [x] A test covers the CLI path for a non-PDF input (asserting the loud
      outcome, not a silent empty run).
