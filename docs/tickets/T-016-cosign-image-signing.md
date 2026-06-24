# T-016: Sign the release image and attest the SBOM (cosign)

**Status:** Closed — implemented 2026-06-24 (PR #38). The release workflow signs the
GHCR image by digest with keyless cosign (GitHub OIDC → Rekor) and attests an SPDX
SBOM (Syft). `id-token: write` added to the `image-bundle` job; actions SHA-pinned
(`cosign-installer` v4.1.2, `sbom-action` v0.24.0). Verification commands documented
in SECURITY.md. Exercised only on the next tagged release.
**Priority:** Low — provenance for the air-gapped delivery chain

## Motivation

The air-gapped bundle ships a `docker save` tarball + SHA256SUMS. Checksums prove
integrity but not *origin* — anyone can regenerate checksums for a tampered
tarball. Keyless cosign signing (GitHub OIDC) plus an SBOM attestation lets the
air-gapped recipient verify that the image was built by this repository's release
workflow, before loading it.

## What to do

- In `release.yml` (image-bundle job): `cosign sign` the image (keyless, OIDC)
  and `cosign attest` the Syft SBOM; export the signature/attestation files into
  the bundle alongside SHA256SUMS.
- Document the verification step in `docs/deployment.md`
  (`cosign verify --certificate-identity ...` against the bundle, which works
  offline with the bundled signature material).

## Acceptance criteria

- [ ] Release bundle includes signature + attestation
- [ ] `docs/deployment.md` shows the offline verification command
- [ ] A tampered tarball fails verification (tested once)
