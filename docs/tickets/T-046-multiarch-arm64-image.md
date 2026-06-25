# T-046: The published image is amd64-only — no native ARM for Apple Silicon hosts

**Status:** Open
**Priority:** Medium — blocks a clean native deploy on the Mac Mini (T-047); the
image *runs* there today, just emulated.

## Symptom

`ghcr.io/ztein/figmark:<version>` / `:edge` is a single-architecture
**linux/amd64** image. On an Apple Silicon host (the Mac Mini, via colima/docker —
an arm64 VM) it runs only under qemu/Rosetta emulation, or fails to schedule on a
strict-arm runtime.

## Root cause

[release.yml](../../.github/workflows/release.yml) builds with plain
`docker build` → `docker tag` → `docker push` on a GitHub `ubuntu` (amd64) runner.
There is no `docker buildx --platform linux/amd64,linux/arm64`, so only the
runner's native arch is produced and pushed. The Dockerfile itself is
arch-neutral (SHA-pinned `python:3.14-slim-bookworm`, apt + pip wheels), so the
limitation is purely in the build/publish step.

## Impact

- On the Mac Mini, the container runs emulated: slower OCR/rendering (PyMuPDF,
  Pillow, Tesseract are CPU-bound) and a class of qemu edge cases on native deps.
- Anyone on arm64 (Apple Silicon dev machines, ARM cloud) gets the same.
- Directly gates T-047 (hosting on the Mini) from being a clean, native deploy.

## Options

1. **buildx multi-arch in release.yml.** Add `docker/setup-qemu-action` +
   `docker/setup-buildx-action` and build `--platform linux/amd64,linux/arm64`,
   pushing a single multi-arch manifest. Simplest change; arm64 layers build under
   QEMU on the amd64 runner (slower CI, but correct). Must keep the existing
   cosign signing + Trivy gate working against the manifest list.
2. **Native arm64 runner.** Build the arm64 leg on an ARM runner (GitHub
   `ubuntu-24.04-arm`, or self-hosted on the Mini) and amd64 on the x86 runner,
   then `docker manifest create` to join them. Faster, more moving parts.
3. **Build locally on the Mini.** Skip multi-arch publishing; `docker build` the
   arm64 image on the Mini at deploy time. Unblocks T-047 immediately but loses
   the signed, scanned, reproducible GHCR artifact — a regression against the
   T-016 supply-chain posture. Stopgap only.

## Acceptance criteria

- [ ] `docker manifest inspect ghcr.io/ztein/figmark:<version>` lists both
  `linux/amd64` and `linux/arm64`.
- [ ] `docker pull` on the Mac Mini (colima/arm64) gets the arm64 layer and
  `readyz` passes with no emulation warnings.
- [ ] cosign signature + SBOM attestation and the Trivy gate still pass against
  the multi-arch manifest.
- [ ] `docs/deployment.md` notes multi-arch support.
