# figmark — working agreement for Claude

figmark converts PDFs to Markdown for accessibility, describing figures and vector
diagrams with a vision model instead of dropping them. Lean and air-gap-friendly
(PyMuPDF + Tesseract + Pillow + an OpenAI-compatible client), with a "fail loud,
never silently degrade" principle.

## Git & PR workflow

- **Never commit directly to `main`** — it is the default branch and protected.
  Always branch first, then open a PR (`gh pr create --base main`).
- **Claude is authorized to approve and merge its own PRs.** Do not wait for a
  human reviewer. Squash-merge to match the repo's history:
  - Preferred: `gh pr merge <n> --squash --auto --delete-branch` — lands the PR
    automatically once CI is green, honouring branch protection.
  - If a self-authored PR is blocked *only* on the required-review rule (you
    cannot approve your own PR via the review UI), use
    `gh pr merge <n> --squash --admin --delete-branch` to merge immediately.
    Only bypass when checks are green or the change is docs/scripts-only.
- Commit messages end with the `Co-Authored-By: Claude Opus 4.8` trailer.

## Tickets

- One file per ticket: `docs/tickets/T-NNN-slug.md`, indexed in
  `docs/tickets/README.md` (keep the table row in sync: ID, Status, Priority,
  Title). Numbers are monotonic — the next ticket is the highest `T-NNN` + 1.
- Title describes the **symptom, not the solution**. Body sections:
  **Status**, **Priority**, **Symptom**, **Root cause**, **Impact**,
  **Options** (numbered trade-offs, not a pre-picked answer), **Acceptance
  criteria**. Statuses seen here: Open / Parked / **Closed** (closed on merge).

## Principles to uphold in code

- **Fail loud.** No silent fallbacks or hidden defaults; a degraded path is
  logged/warned, not swallowed (see T-024).
- **Bench before code** for any detection/extraction change. Build a small
  labelled bench, write the decision threshold down, record the numbers in the PR
  (the table work in T-026/T-030 is the template).
- **Stay lean.** Adding a runtime dependency needs an explicit, justified reason
  in the relevant ticket; the air-gapped Docker image is a hard constraint.
