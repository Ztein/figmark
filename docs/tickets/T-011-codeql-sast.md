# T-011: Enable CodeQL (SAST)

**Status:** Closed — implemented 2026-06-10
**Priority:** Medium — security gate the scanners don't cover

## Motivation

Trivy/pip-audit scan *dependencies and config*; nothing scanned *our own code*
for vulnerability patterns (injection, path traversal, etc.). CodeQL is free for
public repositories.

## Resolution

Added [.github/workflows/codeql.yml](../../.github/workflows/codeql.yml): Python,
`security-and-quality` query suite, on push/PR to main plus a weekly schedule.
Results appear under Security → Code scanning once the repo is public.

## Acceptance criteria

- [x] CodeQL workflow runs on push/PR + weekly
- [ ] First scan on GitHub is clean or triaged (verify after first push)
