# T-077: Hand-maintained docs drift from code — no guard catches a stale index, module map, or metadata

**Status:** Closed — **guard shipped 2026-07-07.** `scripts/check_doc_drift.py`
enforces (a) index↔file presence, (b) Status/Priority agreement, (c) contiguous
numbering, (d) module-map completeness, and runs in the offline suite
(`tests/test_doc_drift.py`, which also proves it catches injected drift — not a
no-op). Title policy is **Option B**: curated index titles stay, title-equality
is not checked. Shipping it immediately caught two malformed tickets (T-040 and
T-056 lacked a `**Priority:**` line), now fixed.
**Priority:** Medium — cosmetic individually, but as a public project gaining
readers the cumulative drift undercuts the "handover-grade docs" bar. This is
the systemic follow-up to the Tier 2 doc-accuracy sweep (which fixed the
instances by hand); the point here is to stop them recurring.

## Symptom

Several documentation surfaces are maintained by hand with no automated check
that they still match the code or each other. Drift found in the 2026-07-07
professionalism audit:

- **Ticket index vs ticket files** (`docs/tickets/README.md`): ~33 rows whose
  `Title` column differs from the ticket file's own `# T-NNN:` heading. Most are
  intentional (the index annotates *closed* tickets with their outcome — bench
  scores, withdrawal reasons — while the file keeps the original symptom title),
  but a handful are genuine wording drift, and nothing distinguishes the two.
- **Module map** (`docs/architecture.md`): shipped 0.3.0 with four modules
  (`input_formats.py`, `office.py`, `cache.py`, `ocr_compat.py`) missing from
  the table for weeks.
- **`ocr_compat.py` docstring**: claimed "Non-PDF inputs get a clean 415" long
  after the `/v1/ocr` surface started honouring the `input.formats` allowlist.
- **`pyproject.toml`** `description`/`keywords`: said PDF-only after EPUB/Office
  shipped.

None of these break a build or a test, so they rot silently until a human reads
the exact line.

## Root cause

The index table, the module map, and package metadata are free-text that a
human must remember to update in lockstep with a code or ticket change. There is
no generator and no CI assertion, so the only thing keeping them correct is
discipline — which is exactly the failure mode the "fail loud / no silent
degradation" principle rejects everywhere else in the codebase.

## Impact

- A newcomer browsing `docs/tickets/README.md` sees a title, opens the file, and
  finds a different one — small trust hit, repeated 33 times.
- The module map under-describes the system for anyone learning the codebase.
- Drift compounds with scale (74 tickets today, more later) and with more
  external eyes on a now-public repo.

## Options

1. **Generator + CI check for the ticket index.** A script rebuilds (or
   verifies) `docs/tickets/README.md`'s table from the ticket files; CI fails on
   a diff (same pattern as the `requirements.lock` regen-and-`git diff` gate).
   Requires deciding the **title policy** (see below).
2. **CI assertions only, no generation.** Lighter: assert the invariants that
   unambiguously matter — every `T-*.md` has an index row and vice-versa,
   `Status`/`Priority` columns match the file's `**Status:**`/`**Priority:**`,
   numbering is monotonic with documented reserved gaps (T-047/T-049), and every
   `src/figmark/*.py` module appears in the architecture module map. Leave the
   curated `Title` column alone.
3. **Do nothing structural**; rely on the Tier 2 one-time fix + review vigilance.
   Cheapest now, guarantees recurrence.

### Sub-decision — ticket-index title policy — **DECIDED: (B), 2026-07-07**

The index intentionally carries curated outcome annotations, which are worth more
to a reader than a machine-generated symptom title. So **(B)** is chosen: the
guard checks presence + status + numbering + module-map completeness (the Option 2
set) and leaves the `Title` column to review. The strict-mirror alternative (A)
is recorded below for context but not pursued.

- **(A) Strict mirror:** index `Title` == file `# T-NNN:` heading, machine-
  generated. Simple and fully checkable, but **flattens the curated outcome
  annotations** (e.g. T-030's "scored: PyMuPDF+filter 100%/99% → ship
  PyMuPDF-only" would revert to the bare symptom "Build the labelled table
  bench"). Loses information a reader currently benefits from.
- **(B) Curated titles stay:** the index `Title` is allowed to append an outcome
  to a closed ticket's symptom. Then the guard must **not** check title-equality;
  it checks presence + status + numbering + module-map completeness (Option 2's
  set). Preserves the richer index; drift on titles is caught by review, not CI.

## Acceptance criteria

- [x] A documented decision on the title policy (A vs B). **Done: (B), 2026-07-07.**
- [x] CI fails on: (a) a ticket file with no index row or an index row with no
  file; (b) an index `Status`/`Priority` that disagrees with the ticket file;
  (c) a `src/figmark/*.py` module absent from the architecture module map; plus
  (d) a contiguous-numbering check. Title-equality is **not** checked, per policy B.
- [x] The check runs in the existing offline CI leg via `tests/test_doc_drift.py`
  (no new required services) and names the exact drifting file/row — fail loud.
- [x] Documented how to run the check locally (`docs/tickets/README.md`).
