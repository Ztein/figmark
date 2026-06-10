# syntax=docker/dockerfile:1
#
# figmark service image — multi-stage, non-root, self-contained for air-gapped use.
# Everything (Python deps, Tesseract + eng/swe language data) is baked in; the only
# runtime dependency is the OpenAI-compatible vision endpoint (config api.base_url).
#
# Base is pinned by digest. python:3.12-slim-bookworm is the reliable choice that
# carries Tesseract + language packs; for an even tighter Trivy posture a Chainguard
# Wolfi base is the documented alternative (see docs/deployment.md).

# ---- builder: install hash-pinned deps + the package into a venv ----
FROM python:3.12-slim-bookworm@sha256:93ab4b7fa528b25124c97bcc755415e60eb671a86b4dbe0328df2fe2d1c1193d AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /build
RUN python -m venv /opt/venv

# Install dependencies from the hash-pinned lockfile (reproducible, verified).
COPY requirements.lock ./
RUN pip install --require-hashes --no-deps -r requirements.lock

# Install the figmark package itself (no deps — they came from the lockfile).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .

# ---- runtime: minimal image with tesseract + the venv ----
FROM python:3.12-slim-bookworm@sha256:93ab4b7fa528b25124c97bcc755415e60eb671a86b4dbe0328df2fe2d1c1193d AS runtime

ARG VERSION=0.0.0
ARG REVISION=unknown
LABEL org.opencontainers.image.title="figmark" \
      org.opencontainers.image.description="PDF to Markdown with AI figure descriptions (HTTP service)" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.source="https://github.com/joelstenberg/figmark" \
      org.opencontainers.image.licenses="MIT"

# System runtime deps: Tesseract + English/Swedish data, and tini for clean PID 1.
# `apt-get upgrade` pulls the latest security patches over the (digest-pinned) base,
# so the Trivy gate stays green even when the base lags a CVE fix.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-swe \
        tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FIGMARK_WORK_DIR=/tmp/figmark \
    FIGMARK_CONFIG_PATH=/app/config.yaml \
    FIGMARK_HOST=0.0.0.0 \
    FIGMARK_PORT=8000

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
# A default config; deployments mount their own read-only over this.
COPY config.yaml /app/config.yaml

# Non-root, fixed uid/gid; writes only to the tmpfs work dir at runtime.
RUN groupadd --system --gid 10001 figmark \
    && useradd --system --uid 10001 --gid figmark --no-create-home figmark
USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"]

ENTRYPOINT ["tini", "--"]
CMD ["figmark-server"]
