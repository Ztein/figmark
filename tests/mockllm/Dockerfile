# Test-only mock OpenAI-compatible server image (NOT for production).
# Used by compose.test.yaml to stand in for the vision LLM in the offline stack.
# Same digest-pinned base as the main Dockerfile.
FROM python:3.14-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb

RUN pip install --no-cache-dir "fastapi>=0.119,<1.0" "uvicorn>=0.32,<1.0"

COPY app.py /app/app.py
WORKDIR /app
RUN groupadd --system --gid 10001 mock \
    && useradd --system --uid 10001 --gid mock --no-create-home mock
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
