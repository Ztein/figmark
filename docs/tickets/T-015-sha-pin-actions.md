# T-015: SHA-pin GitHub Actions

**Status:** Closed — implemented 2026-06-10
**Priority:** Low — supply-chain hardening; tags are mutable, SHAs are not

## Resolution

Every `uses:` in all five workflows is pinned to a full commit SHA with the
version as a trailing comment, at the latest Node 24-compatible releases
(checkout v6.0.3, setup-python v6.2.0, upload-artifact v7.0.1,
download-artifact v8.0.1, hadolint v3.3.0, sbom-action v0.24.0,
gh-release v3.0.0, codeql-action v4.36.2, pypi-publish v1.14.0,
trivy-action v0.36.0) — which also cleared the runner's Node.js 20
deprecation warnings. Dependabot's `github-actions` ecosystem keeps the SHAs
fresh automatically.

## Motivation

Workflows reference actions by tag (`actions/checkout@v4`,
`aquasecurity/trivy-action@0.28.0`, …). Tags are mutable: a compromised or
re-pointed tag executes attacker code with our CI's permissions. The strict
standard (and what OpenSSF Scorecard checks) is pinning to a full commit SHA with
the tag as a comment:

```yaml
uses: actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955 # v4.3.0
```

## What to do

- Pin every `uses:` in `ci.yml`, `security.yml`, `release.yml`, `codeql.yml` to a
  full commit SHA (+ trailing version comment).
- Dependabot's `github-actions` ecosystem (T-012) keeps SHA pins updated, so this
  does not rot.

## Acceptance criteria

- [ ] No mutable tag references remain in any workflow
- [ ] Dependabot PRs bump the SHAs
