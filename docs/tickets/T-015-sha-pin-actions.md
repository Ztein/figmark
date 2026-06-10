# T-015: SHA-pin GitHub Actions

**Status:** Open
**Priority:** Low — supply-chain hardening; tags are mutable, SHAs are not

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
