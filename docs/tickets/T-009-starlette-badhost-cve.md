# T-009: Starlette BadHost CVE in the lockfile — must be fixed before first push

**Status:** Closed — fixed 2026-06-10, before the first public push
**Priority:** HIGH — known, fixable vulnerability in a security-profiled project

## Symptom

`pip-audit -r requirements.lock` reported **PYSEC-2026-161 / CVE-2026-48710 /
GHSA-86qp-5c8j-p5mr** ("BadHost: Missing Host header validation poisons
`request.url.path`, bypassing path-based security checks") in `starlette 0.52.1`.
Fixed in starlette **1.0.1**.

Trivy's image gate did **not** catch it — Trivy's DB had not yet ingested the
advisory (DB lag). This is exactly why a second, independent vulnerability source
matters (see T-013).

## Root cause

Our pin was `starlette>=0.49.1,<1.0` (added to patch the previous CVE-2025-62727),
which **blocked the 1.0.1 fix**. FastAPI's own floor (`>=0.46.0`) is no protection
— it has now left two known CVEs unpatched.

Exploitability in figmark was low (no path-based security middleware; auth is a
per-route dependency), but shipping a known-fixable CVE on day one is unacceptable
for a project whose pitch includes hard security scanning.

## Resolution

- Raised the pin to `starlette>=1.0.1,<2.0` in [pyproject.toml](../../pyproject.toml);
  the lockfile resolved to starlette 1.2.1 with FastAPI 0.136.
- Compatibility proven by the full offline suite (105 tests) and the Docker-gated
  image/compose end-to-end tests.
- `pip-audit` is clean; the Trivy image/config/secret gates pass.
- Follow-up hardening: T-013 makes pip-audit a blocking CI gate.

## Acceptance criteria

- [x] `pip-audit -r requirements.lock --strict` exits 0
- [x] Full offline suite green on the new starlette major
- [x] Image rebuilt; Trivy gates still pass
- [x] Landed before the first public push
