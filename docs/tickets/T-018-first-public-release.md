# T-018: Cut the first public release (v0.2.0)

**Status:** Open
**Priority:** Medium — users need a stable version to pin; the air-gap bundle
has never actually been produced

## Symptom

No git tag, no GitHub Release, no `:latest`/`:X.Y.Z` in GHCR — only `:edge`.
The code still says `__version__ = "0.1.0"` while the CHANGELOG keeps everything
under Unreleased (0.1.0 is marked internal/never published). The release
workflow (Trivy-gated image → GHCR `:<ver>` + `:latest` → tarball bundle +
SHA256SUMS as release assets) exists but has never run.

Blocker: the PyPI `publish` job requires Trusted Publishing to be configured on
pypi.org — an account-level, one-time manual step. Tagging today would turn that
job red.

## What should be built

- Bump `__version__` to 0.2.0; move Unreleased → `[0.2.0]` in the CHANGELOG.
- Gate the PyPI job behind a repository variable (e.g. `vars.PYPI_PUBLISH ==
  'true'`), unset by default → the job skips cleanly until the maintainer
  configures PyPI Trusted Publishing. Document the flip in the workflow.
- Tag `v0.2.0` → the release workflow produces: GHCR `:0.2.0` + `:latest`,
  the air-gap tarball bundle, checksums, attached to the GitHub Release.
- Verify: release assets present; `docker pull ghcr.io/ztein/figmark:0.2.0`
  and `:latest` work anonymously.

Depends on T-010 (provider purge) and T-017 (compose/GHCR) landing first, so
the first pinnable release is the clean, provider-neutral one.

## Acceptance criteria

- [ ] `v0.2.0` tag + GitHub Release with tarball, SHA256SUMS, compose, config
      example, runbook attached
- [ ] GHCR has `:0.2.0` and `:latest`; anonymous pull verified
- [ ] PyPI job skipped (not failed) on the release run
- [ ] CHANGELOG and `__version__` agree with the tag
