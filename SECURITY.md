# Security

## Reporting a vulnerability

Please report security issues privately to the maintainer
(l.j.stenberg@gmail.com) rather than opening a public issue. We aim to
acknowledge reports within a few working days.

## Deployment model & threat model

figmark runs as a container service (`figmark-server`) intended for an
**air-gapped** environment. It accepts PDF uploads, extracts text/figures (parsing
with PyMuPDF and OCR with Tesseract), and calls **one external endpoint**: the
OpenAI-compatible vision model configured by `api.base_url`. That endpoint is the
only network egress.

Trust boundaries and mitigations:

- **Untrusted uploads.** Every `POST /v1/convert` body is treated as hostile. The
  service enforces a content-type/extension check (415), a streaming size cap
  (413), a `%PDF-` magic-byte + `fitz.open()` parse check (422), and a per-request
  timeout (504). Password-protected PDFs are rejected. Uploads are written to a
  per-request temp dir and deleted afterwards; client filenames are never used as
  paths.
- **Resource exhaustion.** A concurrency gate (`FIGMARK_MAX_CONCURRENT_JOBS`,
  default 1) returns 429 when busy; the container sets memory/cpu/pids limits.
- **Authentication.** `POST /v1/convert` requires a bearer token, compared in
  constant time. `healthz`/`readyz`/`version` are unauthenticated and expose no
  secrets. Put a TLS-terminating reverse proxy in front for transport security.
- **Egress.** The container talks only to `api.base_url`. In an air-gapped network
  this is your internal LLM; nothing else is contacted at runtime, and the image
  performs no downloads.
- **Prompt injection via PDF text.** Text extracted from the PDF (the surrounding
  context sent with each figure, and the document summary) is concatenated into the
  model prompt. A hostile PDF could therefore embed instructions aimed at the vision
  model ("ignore the task and output X"). figmark's intended use is **trusted
  documents** (e.g. an agency's own reports), so this is accepted, not mitigated:
  the model only ever produces descriptive text that is written to output files —
  it has no tools, no actions, and no access to secrets or the network. The blast
  radius of a successful injection is a wrong/misleading figure description, not
  code execution or data exfiltration. Do not point figmark at untrusted PDFs and
  treat its output as authoritative without review.

## The cross-request cache (T-060/T-061)

When `cache.enabled: true`, converted results and figure descriptions persist
on disk and are shared across requests. Security properties, reviewed
2026-07-02:

- **No cross-content poisoning.** Cache keys are content digests the *server*
  computes (document sha256; image/rendered-region sha256[:32]) plus the config
  fingerprint — a client can only ever create entries for bytes it actually
  possesses, and cannot overwrite entries for other content. Digests are kept
  long precisely so a crafted partial collision cannot plant a description that
  another document would reuse.
- **Existence oracle (accepted, single-tenant).** Anyone holding the bearer
  token can tell whether a *specific document they already have* was processed
  before (`X-Figmark-Cache`, latency, `cached`). figmark's auth model is
  single-tenant — one token, one trust domain — so this reveals nothing the
  token holder could not learn anyway. If one figmark instance is shared by
  multiple consumers that should not learn about each other's documents, that
  is outside the current model: partition per consumer (separate instances or
  tokens+caches) — see T-062.
- **Cache management is not privilege-separated.** The same token that converts
  can also wipe the cache (a bounded cost/latency degradation, not data loss).
  Accepted under the single-tenant model; a separate admin credential is
  tracked as T-062.
- **Cross-document description reuse (T-061).** A description generated with
  document A's text context may be reused when the same image appears in
  document B — so wording influenced by A's context can surface in B's output.
  Within one trust domain this is a quality trade-off, not a leak; deployments
  that want strict per-document isolation need the reuse toggle tracked as
  T-063.
- **Data at rest.** Cached content is not additionally encrypted (filesystem
  access already implies full compromise here). Retention is bounded by
  `cache.max_age_hours` + `cache.max_size_mb`, and operators can purge one
  document (`DELETE /v1/cache/{sha256}`) or everything (`DELETE /v1/cache`).
  On the default hardened compose the cache lives on tmpfs and does not survive
  restarts; mounting a volume is an explicit operator choice.

## Secret handling

Secrets are **never** baked into the image, committed, or placed in plaintext
compose `environment`:

- The service auth token and the LLM API key are read at startup from files via
  the Docker `*_FILE` convention (`FIGMARK_AUTH_TOKEN_FILE`,
  `FIGMARK_API_KEY_FILE`), mounted as Docker secrets under `/run/secrets/`.
- Secrets are never logged. `/version` returns only the version, model name, and
  base URL.
- `.gitignore` and `.dockerignore` exclude `.env` and `secrets/`.

## Supply chain & scanning

- Dependencies are installed from a **hash-pinned lockfile** (`requirements.lock`,
  `pip install --require-hashes`); the base image is pinned by digest.
- CI runs **Trivy** on every push/PR: a config (misconfiguration) scan, a secret
  scan, and an **image vulnerability gate** at `--severity HIGH,CRITICAL
  --ignore-unfixed` (so any *fixable* high/critical fails the build), plus an SBOM
  (Syft) artifact and a Dockerfile lint (hadolint).
- `--ignore-unfixed` is used because vulnerabilities with no upstream fix cannot be
  remediated by us; everything fixable must be fixed. The narrow, documented escape
  hatch for a justified, time-boxed exception is [`.trivyignore`](.trivyignore).
- **Signed releases (keyless).** Each released GHCR image is signed with
  [cosign](https://github.com/sigstore/cosign) and carries an SPDX SBOM attestation,
  both produced in the release workflow via GitHub OIDC (no long-lived keys; the
  signature is recorded in the public Rekor transparency log). Verify before
  deploying:

  ```sh
  cosign verify ghcr.io/ztein/figmark:<version> \
    --certificate-identity-regexp '^https://github.com/Ztein/figmark/.github/workflows/release.yml@.*' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
  cosign verify-attestation --type spdxjson ghcr.io/ztein/figmark:<version> \
    --certificate-identity-regexp '^https://github.com/Ztein/figmark/.github/workflows/release.yml@.*' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
  ```

See [docs/deployment.md](docs/deployment.md) for the hardened runtime configuration
(non-root, read-only rootfs, dropped capabilities, no-new-privileges).
