# Test-only mock OpenAI-compatible server image (NOT for production).
# Used by compose.test.yaml to stand in for the vision LLM in the offline stack.
# Same digest-pinned base as the main Dockerfile.
FROM python:3.12-slim-bookworm@sha256:93ab4b7fa528b25124c97bcc755415e60eb671a86b4dbe0328df2fe2d1c1193d

RUN pip install --no-cache-dir "fastapi>=0.119,<1.0" "uvicorn>=0.32,<1.0"

COPY app.py /app/app.py
WORKDIR /app
RUN groupadd --system --gid 10001 mock \
    && useradd --system --uid 10001 --gid mock --no-create-home mock
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
