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

## Secret handling

Secrets are **never** baked into the image, committed, or placed in plaintext
compose `environment`:

- The service auth token and the LLM API key are read at startup from files via
  the Docker `*_FILE` convention (`FIGMARK_AUTH_TOKEN_FILE`,
  `BERGET_API_KEY_FILE`), mounted as Docker secrets under `/run/secrets/`.
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

See [docs/deployment.md](docs/deployment.md) for the hardened runtime configuration
(non-root, read-only rootfs, dropped capabilities, no-new-privileges).
