"""FastAPI service wrapping the conversion pipeline.

Exposes ``POST /v1/convert`` (PDF in → Markdown out) plus health/readiness/version
endpoints. The pipeline itself lives in ``pipeline.convert``; this layer adds
authentication, input validation, a concurrency gate, and timeouts. Ops/deployment
knobs come from the environment (``ServerSettings``) — the strict ``config.yaml``
contract is untouched. Secrets are read via the Docker ``*_FILE`` convention and
never logged.

Run with the ``figmark-server`` entry point (uvicorn, app factory).
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import fitz
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import load_config
from .describe import make_client
from .pipeline import convert

logger = logging.getLogger("figmark.api")

# Defaults for ops knobs (overridable via env). Sizes in bytes.
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_WORK_DIR = "/tmp/figmark"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 600.0
DEFAULT_MAX_CONCURRENT_JOBS = 1
_READ_CHUNK = 1024 * 1024


def _read_secret(value_env: str, file_env: str) -> str | None:
    """Read a secret, preferring the ``*_FILE`` path (Docker secrets) over the value."""
    file_path = os.environ.get(file_env)
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    value = os.environ.get(value_env)
    return value.strip() if value else None


@dataclass(frozen=True)
class ServerSettings:
    auth_token: str
    config_path: Path
    max_upload_bytes: int
    work_dir: Path
    request_timeout_seconds: float
    max_concurrent_jobs: int

    @classmethod
    def from_env(cls) -> ServerSettings:
        """Build settings from the environment; fail loudly on missing secrets."""
        token = _read_secret("FIGMARK_AUTH_TOKEN", "FIGMARK_AUTH_TOKEN_FILE")
        if not token:
            raise RuntimeError(
                "FIGMARK_AUTH_TOKEN (or FIGMARK_AUTH_TOKEN_FILE) is required to start "
                "the figmark server."
            )
        # Surface a file-mounted LLM key so the config loader finds it.
        # FIGMARK_API_KEY (or FIGMARK_API_KEY_FILE) is the only supported name —
        # no fallback to a differently-named variable.
        key = _read_secret("FIGMARK_API_KEY", "FIGMARK_API_KEY_FILE")
        if key:
            os.environ["FIGMARK_API_KEY"] = key
        return cls(
            auth_token=token,
            config_path=Path(os.environ.get("FIGMARK_CONFIG_PATH", "config.yaml")),
            max_upload_bytes=int(
                os.environ.get("FIGMARK_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
            ),
            work_dir=Path(os.environ.get("FIGMARK_WORK_DIR", DEFAULT_WORK_DIR)),
            request_timeout_seconds=float(
                os.environ.get("FIGMARK_REQUEST_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT_SECONDS)
            ),
            max_concurrent_jobs=int(
                os.environ.get("FIGMARK_MAX_CONCURRENT_JOBS", DEFAULT_MAX_CONCURRENT_JOBS)
            ),
        )


class UsageInfo(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    api_calls: int
    calls_missing_usage: int


class ConvertResponse(BaseModel):
    markdown: str
    page_count: int
    figure_count: int
    skipped_count: int
    language: str
    usage: UsageInfo
    # Monetary estimate, only when prices are configured; null otherwise (never 0).
    estimated_cost: float | None = None
    currency: str | None = None


class VersionResponse(BaseModel):
    version: str
    model: str
    base_url: str


def _available_ocr_languages() -> list[str]:
    """Languages Tesseract can use; empty list if it cannot be queried."""
    try:
        import pytesseract

        return list(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001 — readiness probe must never raise
        return []


def _require_auth(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Constant-time bearer-token check. Never logs the token."""
    expected = request.app.state.settings.auth_token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    provided = authorization[len("Bearer ") :]
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


def create_app(*, settings: ServerSettings | None = None, cfg=None, client=None) -> FastAPI:
    """Build the FastAPI app. Loads config once; fails loudly on bad config/secrets."""
    settings = settings or ServerSettings.from_env()
    cfg = cfg if cfg is not None else load_config(settings.config_path)
    client = client if client is not None else make_client(cfg)
    settings.work_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="figmark", version=__version__)
    app.state.settings = settings
    app.state.cfg = cfg
    app.state.client = client
    app.state.job_semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_jobs))

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        tesseract = shutil.which("tesseract") is not None
        language_ok = cfg.ocr.language in _available_ocr_languages()
        checks = {"tesseract": tesseract, "ocr_language": language_ok}
        ready = tesseract and language_ok
        return JSONResponse({"ready": ready, "checks": checks}, status_code=200 if ready else 503)

    @app.get("/version", response_model=VersionResponse)
    def version() -> VersionResponse:
        return VersionResponse(version=__version__, model=cfg.api.model, base_url=cfg.api.base_url)

    @app.post(
        "/v1/convert",
        response_model=ConvertResponse,
        dependencies=[Depends(_require_auth)],
    )
    async def convert_endpoint(
        request: Request,
        file: UploadFile = File(...),
        annotate: bool = Form(default=False),
    ) -> ConvertResponse:
        name = (file.filename or "upload").lower()
        ctype = (file.content_type or "").lower()
        if not (name.endswith(".pdf") or ctype == "application/pdf"):
            raise HTTPException(status_code=415, detail="Only PDF uploads are supported")

        work = Path(tempfile.mkdtemp(dir=settings.work_dir))
        pdf_path = work / "input.pdf"
        try:
            # Stream to disk, enforcing the size cap before buffering the whole body.
            size = 0
            header = b""
            with pdf_path.open("wb") as out:
                while chunk := await file.read(_READ_CHUNK):
                    if not header:
                        header = chunk[:5]
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(status_code=413, detail="Upload exceeds the size limit")
                    out.write(chunk)
            if not header.startswith(b"%PDF"):
                raise HTTPException(status_code=422, detail="Not a valid PDF (missing %PDF header)")
            try:
                doc = fitz.open(pdf_path)
                if doc.needs_pass:
                    doc.close()
                    raise HTTPException(
                        status_code=422, detail="Password-protected PDFs unsupported"
                    )
                _ = doc.page_count
                doc.close()
            except HTTPException:
                raise
            except Exception as e:  # noqa: BLE001
                raise HTTPException(
                    status_code=422, detail="File could not be parsed as a PDF"
                ) from e

            sem = request.app.state.job_semaphore
            if sem.locked():
                raise HTTPException(status_code=429, detail="Server busy — too many conversions")
            async with sem:
                try:
                    result = await asyncio.wait_for(
                        run_in_threadpool(
                            convert,
                            pdf_path,
                            cfg,
                            work / "out",
                            annotate=annotate,
                            client=request.app.state.client,
                            quiet=True,
                        ),
                        timeout=settings.request_timeout_seconds,
                    )
                except TimeoutError as e:
                    raise HTTPException(status_code=504, detail="Conversion timed out") from e

            logger.info(
                "convert ok pages=%d figures=%d skipped=%d language=%s",
                result.page_count,
                result.figure_count,
                result.skipped_count,
                result.language,
            )
            return ConvertResponse(
                markdown=result.markdown,
                page_count=result.page_count,
                figure_count=result.figure_count,
                skipped_count=result.skipped_count,
                language=result.language,
                usage=UsageInfo(
                    prompt_tokens=result.usage.prompt_tokens,
                    completion_tokens=result.usage.completion_tokens,
                    total_tokens=result.usage.total_tokens,
                    api_calls=result.usage.api_calls,
                    calls_missing_usage=result.usage.calls_missing_usage,
                ),
                estimated_cost=result.estimated_cost,
                currency=result.currency,
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    return app


def main() -> int:
    """Console entry point: start uvicorn with the app factory (fails loudly early)."""
    import uvicorn

    logging.basicConfig(
        level=os.environ.get("FIGMARK_LOG_LEVEL", "INFO"),
        format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )
    ServerSettings.from_env()  # validate secrets/config before binding the port
    uvicorn.run(
        "figmark.api:create_app",
        factory=True,
        host=os.environ.get("FIGMARK_HOST", "0.0.0.0"),  # noqa: S104 — container service
        port=int(os.environ.get("FIGMARK_PORT", "8000")),
        log_level=os.environ.get("FIGMARK_LOG_LEVEL", "info").lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
