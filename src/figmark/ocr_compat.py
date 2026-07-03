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
``pages[].images[].image_base64``. Beyond that minimum, the response is contract-
shaped (T-058): markdown figure refs are Mistral-style ids matching
``pages[].images[].id``, ``images[]`` carries bbox coordinates (and base64 data when
``include_image_base64`` is set), and ``pages[].dimensions`` is populated — so a
compliant client can re-inline every figure from the response alone.

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

import fitz
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile

from . import __version__
from .api import (
    _require_auth,
    _validate_pdf_document,
    cache_payload_to_result,
    document_cache_key,
    gate_document_format,
    prepare_office_document,
    result_to_cache_payload,
    run_conversion,
)

logger = logging.getLogger("figmark.ocr")

_READ_CHUNK = 1024 * 1024
_FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CONTENT_URL_RE = re.compile(r"/v1/files/(?P<id>[0-9a-f]{32})/content")
# figmark's per-page provenance marker, emitted by output.to_markdown().
_PAGE_MARKER_RE = re.compile(r"<!-- page (\d+) -->")

# T-057: every documented Mistral OCR request parameter is either implemented or
# rejected with a 422 naming it — never accepted-and-ignored. A parameter moves
# to _IMPLEMENTED_PARAMS in the same PR that implements it (T-058 did the image
# fields; T-059: pages). `model` is read but its value does not select a model —
# figmark always runs its own pipeline (documented in the README).
_IMPLEMENTED_PARAMS = {
    "model",
    "document",
    "pages",
    "include_image_base64",
    "image_limit",
    "image_min_size",
}
# Documented parameters we do not implement yet: rejected when set to anything
# non-null.
_NOT_YET_IMPLEMENTED = {
    "bbox_annotation_format",
    "document_annotation_format",
    "document_annotation_prompt",
    "table_format",
    "extract_header",
    "extract_footer",
    "include_blocks",
    "confidence_scores_granularity",
}
_SUPPORTED_SUMMARY = "model, document, pages, include_image_base64, image_limit, image_min_size"


def reject_unsupported_params(body: dict) -> None:
    """Fail loud (422) on any request parameter whose semantics we would not honour.

    Silently ignoring a documented parameter returns wrong-looking-right results —
    the silent-degradation class this project bans (T-024).
    """
    for key, value in body.items():
        if key in _IMPLEMENTED_PARAMS:
            continue
        if key in _NOT_YET_IMPLEMENTED:
            if value is not None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"'{key}' is not supported by this figmark backend; it "
                        "would be silently ignored, so the request is rejected "
                        f"instead. Supported parameters: {_SUPPORTED_SUMMARY}."
                    ),
                )
            continue
        raise HTTPException(
            status_code=422,
            detail=(f"Unknown parameter '{key}'. Supported parameters: {_SUPPORTED_SUMMARY}."),
        )


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


# A figmark markdown figure embed: ![<alt>](images/<name>) or ![...](diagrams/<name>).
_MD_FIG_REF_RE = re.compile(r"!\[[^\]]*\]\((?:images|diagrams)/(?P<name>[^)]+)\)")


_PAGE_RANGE_RE = re.compile(r"(\d+)-(\d+)")


def _parse_pages_param(body: dict) -> list[int] | None:
    """Parse the Mistral ``pages`` selection (T-059).

    Accepts a list mixing 0-based indices and inclusive ``"a-b"`` range strings
    (a bare range string is accepted too). Order is preserved — the response
    carries the pages in the requested order with their original indices.
    """
    value = body.get("pages")
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    bad = HTTPException(
        status_code=422,
        detail="'pages' must be a non-empty list of 0-based page indices and/or 'a-b' ranges",
    )
    if not isinstance(value, list) or not value:
        raise bad
    pages: list[int] = []
    for item in value:
        if isinstance(item, int) and not isinstance(item, bool):
            if item < 0:
                raise bad
            pages.append(item)
        elif isinstance(item, str) and (m := _PAGE_RANGE_RE.fullmatch(item)):
            first, last = int(m.group(1)), int(m.group(2))
            if last < first:
                raise bad
            pages.extend(range(first, last + 1))
        else:
            raise bad
    return pages


def _slice_pdf_pages(doc_path: Path, requested: list[int]) -> Path:
    """Cut the requested 0-based pages into a sub-document (PyMuPDF ``select``)
    so the pipeline only pays for the pages that were asked for (T-059)."""
    doc = fitz.open(doc_path)
    try:
        out_of_range = sorted({p for p in requested if p >= len(doc)})
        if out_of_range:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"'pages' out of range: {out_of_range} — the document has "
                    f"{len(doc)} pages (0-based indices)"
                ),
            )
        doc.select(requested)
        out = doc_path.with_name(f"pages-{doc_path.name}")
        doc.save(out)
        return out
    finally:
        doc.close()


def _int_param(body: dict, key: str) -> int | None:
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HTTPException(status_code=422, detail=f"'{key}' must be a non-negative integer")
    return value


def _bool_param(body: dict, key: str) -> bool:
    value = body.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"'{key}' must be a boolean")
    return value


def build_ocr_pages(
    markdown: str,
    figures: list[dict],
    page_sizes: list,
    *,
    include_image_base64: bool,
    image_limit: int | None,
    image_min_size: int | None,
    index_map: list[int] | None = None,
) -> list[dict]:
    """Assemble the Mistral-shaped ``pages[]`` from the pipeline output (T-058).

    Markdown figure refs are rewritten from figmark's relative artifact paths to
    bare figure ids that match ``pages[].images[].id`` (the Mistral cookbook
    correlation), ``image_limit``/``image_min_size`` are honoured (a filtered
    figure's ref is stripped — its description caption stays), coordinates are
    PDF points, matching the ``dpi: 72`` in ``pages[].dimensions``.

    ``index_map`` translates a sub-document's page position back to the original
    document's 0-based index when the pipeline ran on a ``pages``-sliced document
    (T-059).
    """
    selected = [
        f
        for f in figures
        if not (
            image_min_size
            and (
                f.get("width_px") is None
                or f.get("height_px") is None
                or f["width_px"] < image_min_size
                or f["height_px"] < image_min_size
            )
        )
    ]
    if image_limit is not None:
        selected = selected[:image_limit]
    selected_ids = {f["id"] for f in selected}
    by_page: dict[int, list[dict]] = {}
    for f in selected:
        by_page.setdefault(f["page"], []).append(f)

    def _image_entry(f: dict) -> dict:
        bbox = f.get("bbox") or [None] * 4
        return {
            "id": f["id"],
            "top_left_x": None if bbox[0] is None else int(round(bbox[0])),
            "top_left_y": None if bbox[1] is None else int(round(bbox[1])),
            "bottom_right_x": None if bbox[2] is None else int(round(bbox[2])),
            "bottom_right_y": None if bbox[3] is None else int(round(bbox[3])),
            "image_base64": (
                f"data:{f['mime']};base64,{f['base64']}" if include_image_base64 else None
            ),
        }

    def _rewrite_ref(m: re.Match) -> str:
        name = m.group("name")
        # A ref whose figure was filtered out (or has no artifact) is stripped —
        # never an unreachable path in the response.
        return f"![{name}]({name})" if name in selected_ids else ""

    pages = split_pages(markdown)
    for page in pages:
        page["markdown"] = _MD_FIG_REF_RE.sub(_rewrite_ref, page["markdown"]).strip()
        page["images"] = [_image_entry(f) for f in by_page.get(page["index"] + 1, [])]
        if 0 <= page["index"] < len(page_sizes):
            width, height = page_sizes[page["index"]]
            page["dimensions"] = {
                "dpi": 72,  # coordinates are PDF points; 1 pt = 1 px at 72 dpi
                "height": int(round(height)),
                "width": int(round(width)),
            }
        else:
            page["dimensions"] = None
        if index_map is not None and 0 <= page["index"] < len(index_map):
            page["index"] = index_map[page["index"]]
    return pages


def _resolve_document_bytes(request: Request, document: dict | None) -> bytes:
    """Resolve a Mistral ``document`` object to the raw file bytes.

    Supports our own signed file URLs (the default LibreChat flow) and inline
    ``data:`` URLs (the Azure variant). Anything else fails loudly — we do not fetch
    arbitrary external URLs from inside the air-gapped image.
    """
    if not isinstance(document, dict):
        raise HTTPException(status_code=422, detail="'document' object is required")
    if document.get("type") == "file" or "file_id" in document:
        # Direct file reference (T-059). No signature needed: possession of the
        # id came from an authenticated /v1/files upload, and /v1/ocr itself is
        # behind the bearer check.
        file_id = document.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            raise HTTPException(
                status_code=422, detail="document.file_id is required for type 'file'"
            )
        path = request.app.state.ocr_file_store.path(file_id)
        if path is None:
            raise HTTPException(
                status_code=404, detail="Referenced file not found or already deleted"
            )
        return path.read_bytes()
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
    async def ocr(request: Request, response: Response) -> dict:
        try:
            body = await request.json()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="Request body must be JSON") from e
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="Request body must be a JSON object")
        reject_unsupported_params(body)

        model = body.get("model") or f"figmark-{__version__}"
        include_image_base64 = _bool_param(body, "include_image_base64")
        image_limit = _int_param(body, "image_limit")
        image_min_size = _int_param(body, "image_min_size")
        requested_pages = _parse_pages_param(body)
        data = _resolve_document_bytes(request, body.get("document"))
        cfg = request.app.state.cfg

        def _ocr_response(norm, *, index_map=None, only_indices=None) -> dict:
            pages_out = build_ocr_pages(
                norm.markdown,
                norm.figures,
                norm.page_sizes,
                include_image_base64=include_image_base64,
                image_limit=image_limit,
                image_min_size=image_min_size,
                index_map=index_map,
            )
            if only_indices is not None:
                by_index = {p["index"]: p for p in pages_out}
                pages_out = [by_index[i] for i in only_indices]
            return {
                "pages": pages_out,
                "model": model,
                "usage_info": {
                    "pages_processed": len(pages_out),
                    "doc_size_bytes": len(data),
                },
            }

        # Shared with /v1/convert (T-060): same document + same config = same
        # cached result, whichever surface it arrived through. The payload
        # carries the figure bytes (T-058), so a hit serves images too. A
        # `pages` request is answered from a full-document entry when one
        # exists (the work is already done); a sliced run is cached under its
        # own selection-suffixed key.
        doc_digest = hashlib.sha256(data).hexdigest()
        full_key = document_cache_key(doc_digest, cfg)
        pages_key = (
            None
            if requested_pages is None
            else full_key + "-pages-" + ",".join(map(str, requested_pages))
        )
        store = request.app.state.cache_store
        if store is not None:
            hit = store.get(full_key)
            if hit is not None:
                norm = cache_payload_to_result(hit)
                if requested_pages is not None:
                    out_of_range = sorted({p for p in requested_pages if p >= norm.page_count})
                    if out_of_range:
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                f"'pages' out of range: {out_of_range} — the document "
                                f"has {norm.page_count} pages (0-based indices)"
                            ),
                        )
                logger.info("ocr cache hit doc=%s…", doc_digest[:12])
                response.headers["X-Figmark-Cache"] = "hit"
                return _ocr_response(norm, only_indices=requested_pages)
            if pages_key is not None:
                hit = store.get(pages_key)
                if hit is not None:
                    logger.info("ocr cache hit doc=%s… pages=%s", doc_digest[:12], requested_pages)
                    response.headers["X-Figmark-Cache"] = "hit"
                    return _ocr_response(cache_payload_to_result(hit), index_map=requested_pages)

        work = Path(tempfile.mkdtemp(dir=settings.work_dir))
        upload_path = work / "upload.bin"
        try:
            upload_path.write_bytes(data)
            # There is no trustworthy filename on this surface — the sniffed
            # content alone decides, against the same allowlist as /v1/convert
            # (T-054). Raster image input (image_url) is still a T-052 deferred
            # item and fails loud here.
            fmt = gate_document_format(upload_path, None, cfg.input.formats)
            doc_path = upload_path.rename(work / f"input.{fmt}")
            doc_path = await prepare_office_document(doc_path, fmt, cfg)
            _validate_pdf_document(doc_path)
            if requested_pages is not None:
                # Slice before the pipeline so unrequested pages cost nothing
                # (T-059). The description cache still keys on the full-document
                # digest, so figure reuse across selections keeps working.
                doc_path = _slice_pdf_pages(doc_path, requested_pages)
            result = await run_conversion(
                request.app, doc_path, work / "out", doc_digest=doc_digest
            )
            # Serialise while the temp output dir (and its figure files) still
            # exists; hit and miss then answer from the same normalised shape.
            payload = result_to_cache_payload(result)
            if store is not None:
                store.put(
                    pages_key if pages_key is not None else full_key,
                    payload,
                    doc_digest=doc_digest,
                    kind="document",
                )
            response.headers["X-Figmark-Cache"] = "miss" if store is not None else "off"
            logger.info("ocr ok pages=%d figures=%d", result.page_count, result.figure_count)
            return _ocr_response(cache_payload_to_result(payload), index_map=requested_pages)
        finally:
            shutil.rmtree(work, ignore_errors=True)
