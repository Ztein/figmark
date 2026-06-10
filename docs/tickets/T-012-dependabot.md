# T-012: Enable Dependabot updates

**Status:** Closed — implemented 2026-06-10
**Priority:** Medium — pinned dependencies rot without automation

## Motivation

Everything is deliberately pinned (hash-locked Python deps, digest-pinned base
images, version-tagged actions). Pins are only safe with automation that proposes
updates — otherwise the project drifts into stale, vulnerable versions silently.

## Resolution

Added [.github/dependabot.yml](../../.github/dependabot.yml): weekly grouped pip
updates, docker updates for both the main and the mockllm Dockerfile, and
github-actions updates. Every Dependabot PR runs the full CI + security gates,
so an update that breaks the Trivy/pip-audit gates is caught in the PR.

## Acceptance criteria

- [x] Dependabot config covers pip + both Dockerfiles + actions
- [ ] First Dependabot PRs arrive and pass gates (verify after first push)
