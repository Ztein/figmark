# Deployment (air-gapped, docker compose)

figmark ships as a self-contained container image plus a hardened
`compose.yaml`. Everything it needs at runtime (Python deps, Tesseract + eng/swe
language data) is baked in; the only thing it talks to is your internal
OpenAI-compatible vision endpoint, set via `api.base_url`.

## What you ship into the air-gapped host

From a connected machine, take the release bundle (attached to the GitHub
Release, produced by CI):

- `figmark-<version>.tar.gz` — the scanned image (`docker save`)
- `SHA256SUMS` — checksums
- `compose.yaml` — the hardened deployment
- `config.yaml` — a starting config to edit
- `docs/deployment.md` — this runbook

## Steps

```bash
# 1. Verify and load the image
sha256sum -c SHA256SUMS
docker load < figmark-<version>.tar.gz

# 2. Create the secrets (never committed; compose reads them from files)
mkdir -p secrets
printf '%s' '<a-strong-random-token>' > secrets/auth_token
printf '%s' '<your-llm-api-key>'      > secrets/berget_api_key
chmod 600 secrets/*

# 3. Point figmark at your internal LLM
#    edit config.yaml -> api.base_url: "https://<your-internal-llm>/v1"
#                        api.model:    "<the model name>"

# 4. Start it
FIGMARK_VERSION=<version> docker compose up -d

# 5. Check readiness (tesseract + language pack + config loaded)
curl -s http://127.0.0.1:8000/readyz        # {"ready":true,...}

# 6. Convert a PDF
curl -s -X POST http://127.0.0.1:8000/v1/convert \
  -H "Authorization: Bearer <a-strong-random-token>" \
  -F "file=@document.pdf;type=application/pdf"
```

The response is JSON: `{markdown, page_count, figure_count, skipped_count,
language}`.

## Endpoints

| Method/path | Auth | Purpose |
|---|---|---|
| `POST /v1/convert` | bearer | PDF (multipart `file`) → Markdown |
| `GET /healthz` | none | liveness |
| `GET /readyz` | none | readiness (tesseract + language + config) |
| `GET /version` | none | version/model/base_url (no secrets) |

## Configuration

- **Service/ops knobs (environment):** `FIGMARK_AUTH_TOKEN_FILE`,
  `BERGET_API_KEY_FILE`, `FIGMARK_CONFIG_PATH`, `FIGMARK_MAX_UPLOAD_BYTES`,
  `FIGMARK_MAX_CONCURRENT_JOBS`, `FIGMARK_REQUEST_TIMEOUT_SECONDS`,
  `FIGMARK_WORK_DIR`, `FIGMARK_HOST`, `FIGMARK_PORT`.
- **Pipeline knobs (`config.yaml`, mounted read-only):** `api.*`, `ocr.language`,
  `language.output`, the prompts, `concurrency.*`, `context.*`,
  `significance.*`, `document_summary.*`. See the top-level
  [README](../README.md) and [architecture](architecture.md).

The container runs non-root, with a read-only root filesystem (a tmpfs for its
work dir), `no-new-privileges`, all Linux capabilities dropped, and memory/cpu/pids
limits — all set in `compose.yaml`. Bind a TLS-terminating reverse proxy in front
for transport security; the service port is bound to localhost by default.

## Try it fully offline (no LLM needed)

The repository includes an offline stack that stands a mock OpenAI-compatible
server in for the vision model — useful to validate the deployment with no
internet and no real model:

```bash
mkdir -p secrets && printf x > secrets/auth_token && printf x > secrets/berget_api_key
docker compose -f compose.yaml -f compose.test.yaml up --build -d
curl -s http://127.0.0.1:8000/readyz
curl -s -X POST http://127.0.0.1:8000/v1/convert \
  -H "Authorization: Bearer test-token" -F "file=@document.pdf;type=application/pdf"
docker compose -f compose.yaml -f compose.test.yaml down -v
```

## Upgrading / OCR languages

Add more Tesseract languages by extending the `apt-get install` line in the
[Dockerfile](../Dockerfile) (e.g. `tesseract-ocr-deu`) and rebuilding, then set
`ocr.language` accordingly. For an even tighter vulnerability posture, the
Dockerfile notes a Chainguard Wolfi base as an alternative to Debian slim.
