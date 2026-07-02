# Deployment (docker compose)

figmark ships as a self-contained container image (published to GHCR, also
exported as a tarball for air-gapped hosts) plus a hardened `compose.yaml`.
The GHCR image is multi-arch (`linux/amd64` + `linux/arm64`), so `docker pull`
gets a native image on both x86 and ARM hosts (e.g. Apple Silicon, ARM cloud) —
no emulation.
Everything it needs at runtime (Python deps, Tesseract + eng/swe language data)
is baked in; the only thing it talks to is your OpenAI-compatible vision
endpoint, set via `api.base_url`.

## Connected host (pull from GHCR)

```bash
cp config.example.yaml config.yaml    # edit api.base_url + api.model
mkdir -p secrets
printf '%s' '<a-strong-random-token>' > secrets/auth_token
printf '%s' '<your-llm-api-key>'      > secrets/figmark_api_key
chmod 600 secrets/*
docker compose up -d                   # pulls ghcr.io/ztein/figmark:edge
# pin a release instead: FIGMARK_VERSION=<version> docker compose up -d
```

## Air-gapped host (release bundle)

From a connected machine, take the release bundle (attached to the GitHub
Release, produced by CI):

- `figmark-<version>.tar.gz` — the scanned image for **amd64** hosts
  (`docker save`, named `ghcr.io/ztein/figmark:<version>` so it matches
  `compose.yaml`)
- `figmark-<version>-arm64.tar.gz` — the same image for **arm64** hosts
  (Apple Silicon, ARM cloud); load this one instead on ARM
- `SHA256SUMS` — checksums
- `compose.yaml` — the hardened deployment
- `config.example.yaml` — copy to `config.yaml` and edit
- `docs/deployment.md` — this runbook

```bash
# 1. Verify and load the image
sha256sum -c SHA256SUMS
docker load < figmark-<version>.tar.gz

# 2. Create the secrets (never committed; compose reads them from files)
mkdir -p secrets
printf '%s' '<a-strong-random-token>' > secrets/auth_token
printf '%s' '<your-llm-api-key>'      > secrets/figmark_api_key
chmod 600 secrets/*

# 3. Point figmark at your internal LLM
cp config.example.yaml config.yaml
#    edit config.yaml -> api.base_url: "https://<your-internal-llm>/v1"
#                        api.model:    "<the model name>"

# 4. Start it (the version selects the loaded image)
FIGMARK_VERSION=<version> docker compose up -d

# 5. Check readiness (tesseract + language pack + config loaded)
curl -s http://127.0.0.1:8000/readyz        # {"ready":true,...}

# 6. Convert a PDF
curl -s -X POST http://127.0.0.1:8000/v1/convert \
  -H "Authorization: Bearer <a-strong-random-token>" \
  -F "file=@document.pdf;type=application/pdf"
```

By default the response is JSON: `{markdown, page_count, figure_count,
skipped_count, language, usage, estimated_cost, currency}`. `usage` always reports
`{prompt_tokens, completion_tokens, total_tokens, api_calls, calls_missing_usage}`;
`estimated_cost` (with `currency`) is included only when `api.input_token_price`
and `api.output_token_price` are configured, and is `null` otherwise — never a
misleading `0`.

Pick the response shape with the `format` field (`json` (default) | `md` |
`both`; `both` is an alias for `json`, which already carries markdown + metadata):

```bash
# Raw Markdown body (text/markdown), metadata echoed in X-Figmark-* headers:
curl -s -X POST http://127.0.0.1:8000/v1/convert \
  -H "Authorization: Bearer <token>" \
  -F "file=@document.pdf;type=application/pdf" -F "format=md" -o document.md
```

An unknown `format` is rejected with `422` (no silent default).

## Endpoints

| Method/path | Auth | Purpose |
|---|---|---|
| `POST /v1/convert` | bearer | PDF (multipart `file`) → Markdown |
| `GET /healthz` | none | liveness |
| `GET /readyz` | none | readiness (tesseract + language + config) |
| `GET /version` | none | version/model/base_url (no secrets) |

## Configuration

- **Service/ops knobs (environment):** `FIGMARK_AUTH_TOKEN_FILE`,
  `FIGMARK_API_KEY_FILE`, `FIGMARK_CONFIG_PATH`, `FIGMARK_MAX_UPLOAD_BYTES`,
  `FIGMARK_MAX_CONCURRENT_JOBS`, `FIGMARK_REQUEST_TIMEOUT_SECONDS`,
  `FIGMARK_WORK_DIR`, `FIGMARK_CACHE_DIR`, `FIGMARK_HOST`, `FIGMARK_PORT`.
- **Pipeline knobs (`config.yaml`, mounted read-only):** `api.*`, `ocr.language`,
  `language.output`, the prompts, `concurrency.*`, `context.*`,
  `significance.*`, `document_summary.*`. See the top-level
  [README](../README.md) and [architecture](architecture.md).

The container runs non-root, with a read-only root filesystem (a tmpfs for its
work dir), `no-new-privileges`, all Linux capabilities dropped, and memory/cpu/pids
limits — all set in `compose.yaml`. Bind a TLS-terminating reverse proxy in front
for transport security; the service port is bound to localhost by default.

### The cross-request cache (data at rest)

When `cache.enabled: true` (see `config.example.yaml`), converted results are
kept on disk under `FIGMARK_CACHE_DIR` (default: inside the work dir), so a
re-uploaded identical document is served without re-running the pipeline or
re-spending vision-model calls. Be deliberate about two things:

- **Persistence.** With the default hardened compose, the work dir is a tmpfs —
  the cache then lives only for the container's uptime. To keep it across
  restarts, mount a volume and point `FIGMARK_CACHE_DIR` at it.
- **Data at rest.** The cache stores document-derived content (the Markdown,
  including figure descriptions). If the documents are sensitive, that content
  now persists server-side beyond the request. Your controls: the TTL
  (`cache.max_age_hours`, measured from last access), the size cap
  (`cache.max_size_mb`, LRU eviction), targeted removal
  (`DELETE /v1/cache/{document-sha256}`), and a full wipe (`DELETE /v1/cache`).
  All management calls require the same bearer token as conversion;
  `GET /v1/cache/stats` shows what the cache currently holds.

## Try it fully offline (no LLM needed)

The repository includes an offline stack that stands a mock OpenAI-compatible
server in for the vision model — useful to validate the deployment with no
internet and no real model:

```bash
mkdir -p secrets && printf x > secrets/auth_token && printf x > secrets/figmark_api_key
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
