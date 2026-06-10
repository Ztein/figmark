# T-013: Make pip-audit a blocking CI gate (was advisory)

**Status:** Closed — implemented 2026-06-10
**Priority:** Medium — proven necessary by T-009

## Symptom

`security.yml` ran pip-audit with `|| true` — advisory only, on the theory that
the Trivy image scan was the real gate. T-009 disproved that theory: pip-audit
(OSV/PyPA data) flagged CVE-2026-48710 in starlette **before Trivy's DB had
ingested it**. A silenced scanner that is sometimes first is worse than useless —
it documents that we saw nothing.

## Resolution

The pip-audit step in [.github/workflows/security.yml](../../.github/workflows/security.yml)
now runs `pip-audit -r requirements.lock --disable-pip --strict` with no
`|| true` — any known vulnerability in the lockfile fails CI. Two independent
vulnerability sources now gate: Trivy (image) and pip-audit (lockfile/OSV).

## Acceptance criteria

- [x] pip-audit failure fails the workflow
- [x] Currently clean (post T-009)
