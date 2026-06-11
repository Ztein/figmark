# T-017: compose should run the published GHCR image — clone-free quickstart

**Status:** Closed — implemented 2026-06-11
**Priority:** Medium — onboarding friction for the container path

## Resolution

`compose.yaml` now runs `ghcr.io/ztein/figmark:${FIGMARK_VERSION:-edge}` with no
build section — clone-free. `compose.test.yaml` carries the local build under the
non-clobbering tag `figmark-test:local`; the offline e2e suite passes against it.
`release.yml` saves the tarball under the GHCR name so `docker load` matches what
compose references; the bundle ships `config.example.yaml`. Runbook updated for
both the pull and the air-gap flow. (Bundle load-flow verified at the v0.2.0
release, T-018.)

## Symptom

`compose.yaml` references the local image name `figmark:${FIGMARK_VERSION:-0.1.0}`
plus a `build:` context. A user who has *not* cloned the repository cannot
`docker compose up` — compose tries to build from a context that doesn't exist.
Meanwhile the image is already published to GHCR (`ghcr.io/ztein/figmark:edge`),
verified publicly pullable. The two halves don't meet.

The air-gap bundle has the same mismatch: `release.yml` runs
`docker save figmark:<ver>` (the local name), so after `docker load` the image
name still doesn't match what a GHCR-based compose file would reference.

## What should be built

- `compose.yaml` defaults to the published image:
  `image: ghcr.io/ztein/figmark:${FIGMARK_VERSION:-edge}` — no `build:` in the
  production file. Connected hosts pull; air-gapped hosts `docker load` the
  bundle and set `FIGMARK_VERSION=<ver>`.
- The dev/test override (`compose.test.yaml`) carries the `build:` so the
  offline e2e stack still builds and tests the *local* source, under a
  non-clobbering test tag.
- `release.yml` saves the tarball under the GHCR name
  (`ghcr.io/<owner>/figmark:<ver>`) so `docker load` restores exactly the name
  compose expects.
- `docs/deployment.md` runbook updated for both flows (pull vs load).

## Acceptance criteria

- [ ] With only `compose.yaml` + secrets + a config file (no clone):
      `docker compose up -d` pulls from GHCR and serves `/readyz`
- [ ] The offline e2e test stack still builds local source and passes
- [ ] After `docker load` of the release tarball, `FIGMARK_VERSION=<ver>
      docker compose up -d` works without internet
