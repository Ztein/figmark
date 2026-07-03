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
import base64
import hashlib
import io
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import fitz
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from openai import APIError, APITimeoutError
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import __version__
from .cache import CacheStore, SharedDescriptionCache
from .config import load_config
from .describe import make_client
from .input_formats import EXTENSION_FORMATS, OFFICE_FORMATS, sniff_format
from .ocr import VisionOCRError
from .office import OfficeConversionError, convert_office_to_pdf
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
    # Where the cross-request cache lives (T-060). Defaults beside work_dir;
    # mount a persistent volume + set FIGMARK_CACHE_DIR to survive restarts.
    cache_dir: Path | None = None

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
            cache_dir=(
                Path(os.environ["FIGMARK_CACHE_DIR"])
                if os.environ.get("FIGMARK_CACHE_DIR")
                else None
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
    # True when served from the cross-request cache (T-060). The usage block
    # then echoes the ORIGINAL run's spend for information — it is not new spend.
    cached: bool = False


class VersionResponse(BaseModel):
    version: str
    model: str
    base_url: str


# Response formats for /v1/convert. `json` (default) and `both` return the full
# JSON object (which already carries markdown + metadata); `md` returns the raw
# Markdown body with the metadata echoed in X-Figmark-* headers.
ALLOWED_FORMATS = ("json", "md", "both")


def _convert_response_model(result, cached: bool = False) -> ConvertResponse:
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
        cached=cached,
    )


def _stamp_cache_header(formatted, injected_response, state: str) -> None:
    """Set X-Figmark-Cache on whichever response object will actually be sent.

    A returned Response instance (the md format) ignores the injected response's
    headers, so the header goes directly on it; for a model return the injected
    response carries the headers into the final JSON response.
    """
    if isinstance(formatted, Response):
        formatted.headers["X-Figmark-Cache"] = state
    else:
        injected_response.headers["X-Figmark-Cache"] = state


def format_convert_result(result, fmt: str, cached: bool = False):
    """Shape a ConversionResult per the requested format.

    Returns a ``ConvertResponse`` for ``json``/``both`` (the JSON already carries
    both markdown and metadata) or a ``text/markdown`` ``Response`` for ``md``
    (metadata echoed in ``X-Figmark-*`` headers). An unknown format fails loudly
    with 422 — no silent default (T-025).
    """
    if fmt not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown format {fmt!r}. Allowed: {', '.join(ALLOWED_FORMATS)}.",
        )
    if fmt != "md":
        return _convert_response_model(result, cached=cached)

    headers = {
        "X-Figmark-Page-Count": str(result.page_count),
        "X-Figmark-Figure-Count": str(result.figure_count),
        "X-Figmark-Skipped-Count": str(result.skipped_count),
        "X-Figmark-Language": result.language,
        "X-Figmark-Total-Tokens": str(result.usage.total_tokens),
        "X-Figmark-Api-Calls": str(result.usage.api_calls),
    }
    if result.estimated_cost is not None:
        headers["X-Figmark-Estimated-Cost"] = repr(result.estimated_cost)
        if result.currency:
            headers["X-Figmark-Currency"] = result.currency
    return Response(
        content=result.markdown,
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )


# Generic, client-safe details for an upstream LLM failure. The full error (status,
# provider correlation/request IDs, body) is logged server-side only — never echoed
# to the caller (T-048).
def _upstream_error_response(e: APIError) -> HTTPException:
    """Map an upstream LLM error to a clean gateway status with a generic detail.

    A bad key / no quota / unreachable endpoint is a *bad gateway* (502), not a
    figmark bug (500). Genuine figmark bugs are non-APIError and stay uncaught →
    Starlette's 500. Nothing from the upstream body reaches the client.
    """
    if isinstance(e, APITimeoutError):
        status, detail = 504, "LLM backend timed out"
    else:
        upstream_status = getattr(e, "status_code", None)
        if upstream_status == 429:
            status, detail = 503, "LLM backend is rate-limiting requests — retry later"
        else:
            status, detail = (
                502,
                "LLM backend rejected the request — check the API key, quota, and endpoint",
            )
    # Loud where the operator sees it; the message carries the upstream status and
    # exception type but is kept out of the client response.
    logger.error("upstream LLM error → HTTP %d (%s: %s)", status, type(e).__name__, e)
    return HTTPException(status_code=status, detail=detail)


def _validate_pdf_document(pdf_path: Path) -> None:
    """Fail loudly (422) if the on-disk file isn't openable and unencrypted.

    Shared by ``/v1/convert`` and the Mistral-OCR-compatible ``/v1/ocr`` route so
    both reject the same inputs the same way. Works for every PyMuPDF-native
    format (the loader is picked from the file extension).
    """
    try:
        doc = fitz.open(pdf_path)
        if doc.needs_pass:
            doc.close()
            raise HTTPException(status_code=422, detail="Password-protected documents unsupported")
        _ = doc.page_count
        doc.close()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=422,
            detail=f"File could not be parsed as {pdf_path.suffix.lstrip('.') or 'a document'}",
        ) from e


def _reject_claimed_format(claimed: str | None, allowed: list[str]) -> None:
    """Fail fast (415) when a *claimed* format (extension) is outside the allowlist.

    ``claimed=None`` means no recognisable claim — sniffing decides later.
    """
    supported = ", ".join(allowed)
    if claimed == "ole":
        raise HTTPException(
            status_code=415,
            detail=(
                "Legacy binary Office files (.doc/.xls/.ppt) are not supported — "
                f"save as OOXML or PDF. Supported formats: {supported}."
            ),
        )
    if claimed is not None and claimed not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Format '{claimed}' is not enabled here. Supported formats: {supported}.",
        )


def gate_document_format(path: Path, claimed: str | None, allowed: list[str]) -> str:
    """Sniff the on-disk file's real format and enforce the allowlist (T-054).

    Returns the detected format name. The content decides: an extension/content
    mismatch is a loud 422, never mis-handled; a real-but-disallowed format is a
    415 that names both the detected format and the supported set.
    """
    fmt = sniff_format(path)
    supported = ", ".join(allowed)
    if fmt == "ole":
        _reject_claimed_format("ole", allowed)
    if fmt is None:
        if claimed is None:
            # No filename claim to contradict (e.g. /v1/ocr) — this is simply an
            # unsupported media type, not a mismatch.
            raise HTTPException(
                status_code=415,
                detail=(
                    "Could not identify the document as any supported format. "
                    f"Supported formats: {supported}."
                ),
            )
        raise HTTPException(
            status_code=422,
            detail=(
                f"File name claims '{claimed}' but the content is not identifiable "
                f"as any supported format. Supported formats: {supported}."
            ),
        )
    if claimed is not None and fmt != claimed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"File name claims '{claimed}' but the content is '{fmt}' — "
                "extension/content mismatch."
            ),
        )
    if fmt not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Detected format '{fmt}' is not enabled here. Supported formats: {supported}.",
        )
    return fmt


def config_cache_fingerprint(cfg) -> str:
    """Hash every config field that shapes a conversion result, plus the figmark
    version — a change to any of them must miss the cache (T-034 parity)."""
    material = repr(
        (
            __version__,
            cfg.api.model,
            cfg.description.prompt,
            cfg.diagrams.enabled,
            cfg.diagrams.prompt,
            cfg.tables.enabled,
            cfg.context.enabled,
            cfg.context.words_before,
            cfg.context.words_after,
            cfg.significance.enabled,
            cfg.document_summary.enabled,
            cfg.document_summary.sample_words,
            cfg.document_summary.prompt,
            cfg.language.output,
            cfg.ocr.language,
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def document_cache_key(doc_digest: str, cfg) -> str:
    # "doc2": payload shape v2 (T-058 added figures + page_sizes). The version
    # in the key makes pre-T-058 entries miss cleanly instead of resurfacing
    # without image data; orphans age out via TTL/eviction.
    return f"doc2-{doc_digest}-{config_cache_fingerprint(cfg)}"


_FIGURE_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}


def collect_figure_images(result) -> list[dict]:
    """Read the figure manifest (T-041) and the extracted image files into a
    serialisable list for the OCR surface (T-058).

    Each entry carries ``id`` (the artifact filename — the id the rewritten
    markdown refs use), page number, bbox in PDF points, pixel size, mime type
    and the raw base64 payload. Skipped (decorative) figures are never embedded
    in the markdown and are left out. A manifest entry whose file is missing is
    logged loudly and dropped — its markdown ref is stripped downstream, so no
    unreachable ref survives into a response.
    """
    from PIL import Image  # runtime dep already; imported here to keep api.py's surface lean

    try:
        manifest = json.loads(Path(result.figures_manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("figure manifest unreadable (%s) — no images in the OCR response", e)
        return []
    figures: list[dict] = []
    for entry in manifest:
        if entry.get("skipped"):
            continue
        path = Path(result.output_dir) / entry["path"]
        if not path.is_file():
            logger.warning(
                "figure file missing for manifest id=%s — dropped from images[]", entry["id"]
            )
            continue
        data = path.read_bytes()
        try:
            with Image.open(io.BytesIO(data)) as im:
                width_px, height_px = im.size
        except OSError:
            width_px = height_px = None
        figures.append(
            {
                "id": path.name,
                "page": entry["page"],
                "bbox": entry.get("bbox"),
                "width_px": width_px,
                "height_px": height_px,
                "mime": _FIGURE_MIME.get(
                    path.suffix.lower().lstrip("."), "application/octet-stream"
                ),
                "base64": base64.b64encode(data).decode("ascii"),
            }
        )
    return figures


def result_to_cache_payload(result) -> bytes:
    """Serialise the response-relevant slice of a ConversionResult (paths die
    with the request's temp dir and are deliberately not cached — the figure
    *bytes* are cached instead, so a cache hit can still serve images)."""
    return json.dumps(
        {
            "markdown": result.markdown,
            "page_count": result.page_count,
            "figure_count": result.figure_count,
            "skipped_count": result.skipped_count,
            "language": result.language,
            "usage": {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "total_tokens": result.usage.total_tokens,
                "api_calls": result.usage.api_calls,
                "calls_missing_usage": result.usage.calls_missing_usage,
            },
            "estimated_cost": result.estimated_cost,
            "currency": result.currency,
            "figures": collect_figure_images(result),
            "page_sizes": list(result.page_sizes),
        },
        ensure_ascii=False,
    ).encode("utf-8")


def cache_payload_to_result(payload: bytes) -> SimpleNamespace:
    """Rebuild an object attribute-compatible with ConversionResult for the
    response formatters."""
    data = json.loads(payload.decode("utf-8"))
    data["usage"] = SimpleNamespace(**data["usage"])
    data.setdefault("figures", [])
    data.setdefault("page_sizes", [])
    return SimpleNamespace(**data)


async def prepare_office_document(doc_path: Path, fmt: str, cfg) -> Path:
    """Convert an allowlisted Office upload to PDF before it enters the pipeline.

    Non-Office formats pass through untouched. The allowlist guarantees
    ``cfg.input.office`` is set when an Office format got this far (enforced at
    config load); conversion failures surface as a clean 422 — the document is
    the client's — with the full error logged server-side.
    """
    if fmt not in OFFICE_FORMATS:
        return doc_path
    office = cfg.input.office
    try:
        return await run_in_threadpool(
            convert_office_to_pdf,
            doc_path,
            doc_path.parent,
            soffice=office.soffice_path,
            timeout=office.timeout_seconds,
        )
    except OfficeConversionError as e:
        logger.error("office conversion failed: %s", e)
        raise HTTPException(
            status_code=422,
            detail=f"The {fmt} document could not be converted for processing.",
        ) from e


async def run_conversion(
    app: FastAPI,
    pdf_path: Path,
    out_dir: Path,
    *,
    annotate: bool = False,
    doc_digest: str | None = None,
):
    """Run the pipeline under the concurrency gate + timeout, mapping upstream LLM
    faults to clean gateway errors (T-048).

    The single place ``convert`` is invoked over HTTP — shared by ``/v1/convert``
    and the Mistral-OCR-compatible ``/v1/ocr`` route so the busy/timeout/upstream
    error behaviour stays identical.
    """
    settings = app.state.settings
    sem = app.state.job_semaphore
    if sem.locked():
        raise HTTPException(status_code=429, detail="Server busy — too many conversions")
    # Shared description cache (T-061): descriptions created for this document
    # are attributed to its digest, so purging the document purges them too.
    shared = None
    if app.state.cache_store is not None and doc_digest:
        shared = SharedDescriptionCache(app.state.cache_store, doc_digest)
    async with sem:
        try:
            return await asyncio.wait_for(
                run_in_threadpool(
                    convert,
                    pdf_path,
                    app.state.cfg,
                    out_dir,
                    annotate=annotate,
                    client=app.state.client,
                    quiet=True,
                    shared_cache=shared,
                ),
                timeout=settings.request_timeout_seconds,
            )
        except TimeoutError as e:
            raise HTTPException(status_code=504, detail="Conversion timed out") from e
        except VisionOCRError as e:
            # A scanned page couldn't be OCR'd (too large for the vision model, or
            # rejected/empty). This is a property of the uploaded document, not a
            # backend outage or a figmark bug — surface it as an actionable 422 with
            # the page-specific, provider-body-free detail rather than a generic 502.
            logger.error("vision-OCR failure → HTTP 422 (%s)", e)
            raise HTTPException(status_code=422, detail=str(e)) from e
        except APIError as e:
            # Upstream LLM fault (bad key/quota, rate limit, unreachable endpoint):
            # a bad gateway, not a figmark bug. Full error logged server-side (T-048).
            raise _upstream_error_response(e) from e


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
    # Cross-request cache (T-060). None when disabled — every consumer checks.
    if cfg.cache.enabled:
        cache_dir = settings.cache_dir or (settings.work_dir / "cache")
        app.state.cache_store = CacheStore(
            cache_dir,
            max_bytes=cfg.cache.max_size_mb * 1024 * 1024,
            max_age_hours=cfg.cache.max_age_hours,
        )
        logger.info(
            "document cache enabled at %s (max %d MB, max age %.0f h)",
            cache_dir,
            cfg.cache.max_size_mb,
            cfg.cache.max_age_hours,
        )
    else:
        app.state.cache_store = None

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        tesseract = shutil.which("tesseract") is not None
        language_ok = cfg.ocr.language in _available_ocr_languages()
        checks = {"tesseract": tesseract, "ocr_language": language_ok}
        if cfg.input.office is not None:
            # Office formats are configured — the resolved soffice must still exist.
            checks["libreoffice"] = Path(cfg.input.office.soffice_path).exists()
        ready = all(checks.values())
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
        response: Response,
        file: UploadFile = File(...),
        annotate: bool = Form(default=False),
        output_format: str = Form(default="json", alias="format"),
    ):
        # Validate the format up front so a bad value fails fast (and loudly),
        # before any expensive conversion work.
        if output_format not in ALLOWED_FORMATS:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown format {output_format!r}. Allowed: {', '.join(ALLOWED_FORMATS)}.",
            )
        # The filename's claim is checked up front (fail fast, before streaming);
        # the *content* has the final say via gate_document_format below (T-054).
        name = (file.filename or "upload").lower()
        suffix = Path(name).suffix
        allowed = cfg.input.formats
        if suffix:
            claimed = EXTENSION_FORMATS.get(suffix)
            if claimed is None:
                raise HTTPException(
                    status_code=415,
                    detail=(
                        f"Unsupported file type '{suffix}'. "
                        f"Supported formats: {', '.join(allowed)}."
                    ),
                )
            _reject_claimed_format(claimed, allowed)
        else:
            claimed = None

        work = Path(tempfile.mkdtemp(dir=settings.work_dir))
        upload_path = work / "upload.bin"
        try:
            # Stream to disk, enforcing the size cap before buffering the whole
            # body; the sha256 (the cache key's document half) rides along.
            size = 0
            hasher = hashlib.sha256()
            with upload_path.open("wb") as out:
                while chunk := await file.read(_READ_CHUNK):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(status_code=413, detail="Upload exceeds the size limit")
                    hasher.update(chunk)
                    out.write(chunk)
            fmt = gate_document_format(upload_path, claimed, allowed)
            doc_digest = hasher.hexdigest()

            store: CacheStore | None = request.app.state.cache_store
            if store is not None:
                hit = store.get(document_cache_key(doc_digest, cfg))
                if hit is not None:
                    logger.info("convert cache hit doc=%s…", doc_digest[:12])
                    cached_result = cache_payload_to_result(hit)
                    formatted = format_convert_result(cached_result, output_format, cached=True)
                    _stamp_cache_header(formatted, response, "hit")
                    return formatted

            # PyMuPDF picks its loader from the extension — name the file for
            # what its content actually is.
            doc_path = upload_path.rename(work / f"input.{fmt}")
            doc_path = await prepare_office_document(doc_path, fmt, cfg)
            _validate_pdf_document(doc_path)

            result = await run_conversion(
                request.app, doc_path, work / "out", annotate=annotate, doc_digest=doc_digest
            )

            if store is not None:
                store.put(
                    document_cache_key(doc_digest, cfg),
                    result_to_cache_payload(result),
                    doc_digest=doc_digest,
                    kind="document",
                )

            logger.info(
                "convert ok pages=%d figures=%d skipped=%d language=%s",
                result.page_count,
                result.figure_count,
                result.skipped_count,
                result.language,
            )
            formatted = format_convert_result(result, output_format)
            _stamp_cache_header(formatted, response, "miss" if store is not None else "off")
            return formatted
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # --- Cache management (T-060): stats, remove one document, clear all. ---
    def _require_store(request: Request) -> CacheStore:
        store = request.app.state.cache_store
        if store is None:
            raise HTTPException(status_code=404, detail="Caching is disabled on this server")
        return store

    @app.get("/v1/cache/stats", dependencies=[Depends(_require_auth)])
    def cache_stats(request: Request) -> dict:
        return _require_store(request).stats()

    @app.delete("/v1/cache/{doc_digest}", dependencies=[Depends(_require_auth)])
    def cache_delete_document(request: Request, doc_digest: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{64}", doc_digest):
            raise HTTPException(
                status_code=422,
                detail="doc_digest must be the document's sha256 (64 hex chars)",
            )
        deleted = _require_store(request).delete_document(doc_digest)
        logger.info("cache delete doc=%s… removed %d entries", doc_digest[:12], deleted)
        return {"doc_digest": doc_digest, "deleted": deleted}

    @app.delete("/v1/cache", dependencies=[Depends(_require_auth)])
    def cache_clear(request: Request) -> dict:
        deleted = _require_store(request).clear()
        logger.info("cache cleared: %d entries removed", deleted)
        return {"deleted": deleted}

    # LibreChat / Mistral-OCR-compatible surface (/v1/files + /v1/ocr), so clients
    # that speak that wire format can use figmark as a self-hosted OCR backend
    # (T-052). Registered here — local import avoids an import cycle with this module.
    from .ocr_compat import add_mistral_ocr_routes

    add_mistral_ocr_routes(app)

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
