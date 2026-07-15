# syntax=docker/dockerfile:1
#
# figmark service image — multi-stage, non-root, self-contained for air-gapped use.
# Everything (Python deps, Tesseract + eng/swe language data) is baked in; the only
# runtime dependency is the OpenAI-compatible vision endpoint (config api.base_url).
#
# Base is pinned by digest (python:3.14-slim-bookworm), kept current by Dependabot.
# Debian bookworm carries the Tesseract apt packages, and the PyMuPDF/Pillow wheels
# publish builds for this interpreter — verified at the pinned digest. For an even
# tighter Trivy posture a Chainguard Wolfi base is the documented alternative
# (see docs/deployment.md).

# ---- builder: install hash-pinned deps + the package into a venv ----
FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS builder

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
FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS runtime

ARG VERSION=0.0.0
ARG REVISION=unknown
LABEL org.opencontainers.image.title="figmark" \
      org.opencontainers.image.description="PDF to Markdown with AI figure descriptions (HTTP service)" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.source="https://github.com/Ztein/figmark" \
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
COPY config.example.yaml /app/config.yaml

# Non-root, fixed uid/gid; writes only to the tmpfs work dir at runtime.
RUN groupadd --system --gid 10001 figmark \
    && useradd --system --uid 10001 --gid figmark --no-create-home figmark
USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"]

ENTRYPOINT ["tini", "--"]
CMD ["figmark-server"]

# ---- runtime-office: the Office image variant (T-054) ----
# Adds a minimal headless LibreOffice (writer/calc/impress cores, no Java, no
# UI) on top of the slim runtime so docx/xlsx/pptx convert with full layout
# fidelity. Shipped as a SEPARATE opt-in tag — the slim image stays the default
# and does not inherit LibreOffice's CVE surface. Same non-root user,
# read-only-rootfs compatible; conversions run macro-locked in a throwaway
# profile with a hard timeout (src/figmark/office.py).
# hadolint ignore=DL3008
FROM runtime AS runtime-office
USER root
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui \
        libreoffice-calc-nogui \
        libreoffice-impress-nogui \
        fonts-dejavu-core \
        fonts-liberation \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
# soffice (dconf/XDG) wants a writable HOME; the non-root user has none, so
# point it into the tmpfs work dir. The conversion profile itself is already a
# throwaway under the work dir (office.py).
ENV HOME=/tmp/figmark
USER 10001

# Default target LAST on purpose: a bare `docker build .` must yield the slim
# image. Build the Office variant with `--target runtime-office`.
FROM runtime
