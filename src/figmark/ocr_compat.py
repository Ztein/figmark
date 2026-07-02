"""LibreChat / Mistral-OCR-compatible API surface (T-052).

LibreChat (and other tools that speak the Mistral OCR wire format) redirect OCR to
a self-hosted backend by pointing ``OCR_BASEURL`` at it — then talk Mistral's shape,
not figmark's ``/v1/convert``. This module re-presents the existing pipeline in that
shape so figmark can be a drop-in OCR backend, without touching the conversion code.

The default LibreChat strategy makes four calls (verified against LibreChat ``main``,
``packages/api/src/files/mistral/crud.ts``):

1. ``POST /v1/files`` (multipart, ``purpose=ocr``) → ``{"id": ...}``
2. ``GET  /v1/files/{id}/url?expiry=24``           → ``{"url": ...}`` (signed URL)
3. ``POST /v1/ocr``  with ``{document: {type, document_url|image_url}}`` → pages
4. ``DELETE /v1/files/{id}``                        → cleanup

The only response fields LibreChat consumes are ``pages[].markdown`` and
``pages[].images[].image_base64``; it ignores everything else and does not currently
use the OCR images at all — so we return ``images: []`` and stay fully functional.

Scope (see T-052): PDF-first. We resolve a document to bytes from *our own* signed
file URLs (the default flow) or an inline ``data:`` URL (LibreChat's Azure variant).
Arbitrary external URLs are rejected — that keeps the air-gapped image free of an
outbound fetch (and its SSRF surface). Non-PDF inputs get a clean 415.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import re
import secrets
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile

from . import __version__
from .api import _require_auth, _validate_pdf_document, gate_document_format, run_conversion

logger = logging.getLogger("figmark.ocr")

_READ_CHUNK = 1024 * 1024
_FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CONTENT_URL_RE = re.compile(r"/v1/files/(?P<id>[0-9a-f]{32})/content")
# figmark's per-page provenance marker, emitted by output.to_markdown().
_PAGE_MARKER_RE = re.compile(r"<!-- page (\d+) -->")


class FileStore:
    """A tiny on-disk store for uploaded OCR files, keyed by an opaque id.

    Mirrors the Mistral ``/files`` lifecycle (upload → reference → delete). Bytes and
    the original filename live under ``root``; ids are random hex so they are both
    filesystem-safe and unguessable.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes, *, filename: str) -> str:
        file_id = secrets.token_hex(16)
        (self.root / file_id).write_bytes(data)
        (self.root / f"{file_id}.name").write_text(filename, encoding="utf-8")
        return file_id

    def path(self, file_id: str) -> Path | None:
        if not _FILE_ID_RE.match(file_id):
            return None
        p = self.root / file_id
        return p if p.is_file() else None

    def filename(self, file_id: str) -> str:
        f = self.root / f"{file_id}.name"
        return f.read_text(encoding="utf-8") if f.is_file() else "upload.pdf"

    def delete(self, file_id: str) -> bool:
        if not _FILE_ID_RE.match(file_id):
            return False
        p = self.root / file_id
        existed = p.is_file()
        p.unlink(missing_ok=True)
        (self.root / f"{file_id}.name").unlink(missing_ok=True)
        return existed


def _sign(secret: str, file_id: str) -> str:
    """HMAC a file id with the server token so a signed URL can't be forged."""
    return hmac.new(secret.encode(), file_id.encode(), hashlib.sha256).hexdigest()


def split_pages(markdown: str) -> list[dict]:
    """Split figmark's single Markdown body into Mistral-shaped per-page objects.

    Uses the ``<!-- page N -->`` markers the pipeline already emits for provenance;
    the marker itself is dropped from the per-page text. If no marker is present
    (shouldn't happen for real output), the whole body is returned as one page.
    """
    matches = list(_PAGE_MARKER_RE.finditer(markdown))
    if not matches:
        return [{"index": 0, "markdown": markdown.strip(), "images": []}]
    pages: list[dict] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        pages.append(
            {
                "index": int(m.group(1)) - 1,  # Mistral indexes pages from 0
                "markdown": markdown[start:end].strip(),
                "images": [],
            }
        )
    return pages


def _resolve_document_bytes(request: Request, document: dict) -> bytes:
    """Resolve a Mistral ``document`` object to the raw file bytes.

    Supports our own signed file URLs (the default LibreChat flow) and inline
    ``data:`` URLs (the Azure variant). Anything else fails loudly — we do not fetch
    arbitrary external URLs from inside the air-gapped image.
    """
    if not isinstance(document, dict):
        raise HTTPException(status_code=422, detail="'document' object is required")
    url = document.get("document_url") or document.get("image_url")
    if not isinstance(url, str) or not url:
        raise HTTPException(
            status_code=422,
            detail="document.document_url (or image_url) is required",
        )

    if url.startswith("data:"):
        try:
            b64 = url.split(",", 1)[1]
            return base64.b64decode(b64, validate=True)
        except (IndexError, binascii.Error) as e:
            raise HTTPException(status_code=422, detail="Malformed data: URL") from e

    m = _CONTENT_URL_RE.search(url)
    if m:
        file_id = m.group("id")
        sig = parse_qs(urlparse(url).query).get("sig", [""])[0]
        expected = _sign(request.app.state.settings.auth_token, file_id)
        if not sig or not secrets.compare_digest(sig, expected):
            raise HTTPException(status_code=403, detail="Invalid file URL signature")
        path = request.app.state.ocr_file_store.path(file_id)
        if path is None:
            raise HTTPException(
                status_code=404, detail="Referenced file not found or already deleted"
            )
        return path.read_bytes()

    raise HTTPException(
        status_code=400,
        detail=(
            "Unsupported document URL. A self-hosted figmark resolves only its own "
            "uploaded-file URLs (from /v1/files/{id}/url) or inline data: URLs."
        ),
    )


def add_mistral_ocr_routes(app: FastAPI) -> None:
    """Register the Mistral-OCR-compatible routes and attach the file store."""
    settings = app.state.settings
    app.state.ocr_file_store = FileStore(settings.work_dir / "ocr_files")

    @app.post("/v1/files", dependencies=[Depends(_require_auth)])
    async def upload_file(
        request: Request,
        file: UploadFile = File(...),
        purpose: str = Form(default="ocr"),
    ) -> dict:
        # Stream to memory under the same size cap /v1/convert enforces.
        data = b""
        while chunk := await file.read(_READ_CHUNK):
            data += chunk
            if len(data) > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="Upload exceeds the size limit")
        filename = file.filename or "upload.pdf"
        file_id = request.app.state.ocr_file_store.put(data, filename=filename)
        return {
            "id": file_id,
            "object": "file",
            "bytes": len(data),
            "filename": filename,
            "purpose": purpose,
        }

    @app.get("/v1/files/{file_id}/url", dependencies=[Depends(_require_auth)])
    async def get_file_url(request: Request, file_id: str, expiry: int = 24) -> dict:
        if request.app.state.ocr_file_store.path(file_id) is None:
            raise HTTPException(status_code=404, detail="File not found")
        sig = _sign(settings.auth_token, file_id)
        base = str(request.base_url).rstrip("/")
        return {"url": f"{base}/v1/files/{file_id}/content?sig={sig}"}

    @app.get("/v1/files/{file_id}/content")
    async def get_file_content(request: Request, file_id: str, sig: str = "") -> Response:
        # Authenticated by the HMAC signature, not the bearer token — this is the
        # pre-signed URL handed out by /url. (The default LibreChat flow never
        # fetches it; /v1/ocr resolves the file by id directly. Kept so the URL is
        # genuinely valid.)
        expected = _sign(settings.auth_token, file_id)
        if not sig or not secrets.compare_digest(sig, expected):
            raise HTTPException(status_code=403, detail="Invalid signature")
        path = request.app.state.ocr_file_store.path(file_id)
        if path is None:
            raise HTTPException(status_code=404, detail="File not found")
        return Response(content=path.read_bytes(), media_type="application/pdf")

    @app.delete("/v1/files/{file_id}", dependencies=[Depends(_require_auth)])
    async def delete_file(request: Request, file_id: str) -> dict:
        deleted = request.app.state.ocr_file_store.delete(file_id)
        return {"id": file_id, "object": "file", "deleted": deleted}

    @app.post("/v1/ocr", dependencies=[Depends(_require_auth)])
    async def ocr(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="Request body must be JSON") from e
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="Request body must be a JSON object")

        model = body.get("model") or f"figmark-{__version__}"
        data = _resolve_document_bytes(request, body.get("document"))

        work = Path(tempfile.mkdtemp(dir=settings.work_dir))
        upload_path = work / "upload.bin"
        try:
            upload_path.write_bytes(data)
            # There is no trustworthy filename on this surface — the sniffed
            # content alone decides, against the same allowlist as /v1/convert
            # (T-054). Raster image input (image_url) is still a T-052 deferred
            # item and fails loud here.
            fmt = gate_document_format(upload_path, None, request.app.state.cfg.input.formats)
            doc_path = upload_path.rename(work / f"input.{fmt}")
            _validate_pdf_document(doc_path)
            result = await run_conversion(request.app, doc_path, work / "out")
            pages = split_pages(result.markdown)
            logger.info("ocr ok pages=%d figures=%d", result.page_count, result.figure_count)
            return {
                "pages": pages,
                "model": model,
                "usage_info": {
                    "pages_processed": result.page_count,
                    "doc_size_bytes": len(data),
                },
            }
        finally:
            shutil.rmtree(work, ignore_errors=True)
