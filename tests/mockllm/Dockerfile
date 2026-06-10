# Test-only mock OpenAI-compatible server image (NOT for production).
# Used by compose.test.yaml to stand in for the vision LLM in the offline stack.
FROM python:3.12-slim-bookworm

RUN pip install --no-cache-dir "fastapi>=0.119,<1.0" "uvicorn>=0.32,<1.0"

COPY app.py /app/app.py
WORKDIR /app
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
