"""Input-format detection and the configurable allowlist (T-054).

The gate trusts bytes, not filenames: magic numbers first, then container
inspection (OOXML, EPUB and XPS are all ZIP archives). An unrecognised or
mismatching input fails loud instead of being mis-parsed. The gate is
transport-neutral (T-066): the HTTP handlers map ``InputFormatError`` to
415/422 and the CLI to a non-zero exit — the same input is accepted or
refused identically on both surfaces, never silently under-extracted.

Two tiers of support:

- ``NATIVE_FORMATS`` open directly in PyMuPDF — no extra dependency, air-gap-safe.
- ``OFFICE_FORMATS`` need the LibreOffice conversion path (separate image
  variant; see T-054's security requirements) and are rejected at config load
  until that path is present.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

# Formats fitz.open() handles natively. MOBI/FB2/CBZ are included because they
# ride the same reflow/render machinery as EPUB; PDF and XPS are fixed-layout.
NATIVE_FORMATS = frozenset({"pdf", "epub", "xps", "fb2", "cbz", "mobi"})
# OOXML formats that need LibreOffice → PDF before the pipeline can keep layout.
OFFICE_FORMATS = frozenset({"docx", "xlsx", "pptx"})
SUPPORTED_FORMATS = NATIVE_FORMATS | OFFICE_FORMATS

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc/.xls/.ppt container

# What each sniffable extension claims to be — used to fail loud on a
# name/content mismatch. Extensions outside this map are simply not trusted.
EXTENSION_FORMATS = {f".{fmt}": fmt for fmt in SUPPORTED_FORMATS} | {
    ".doc": "ole",
    ".xls": "ole",
    ".ppt": "ole",
}

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")


class InputFormatError(Exception):
    """A refused input document — unsupported type or a name/content mismatch.

    ``kind`` lets each transport map the refusal faithfully:
    ``"unsupported"`` → HTTP 415 / CLI exit≠0, ``"mismatch"`` → HTTP 422 /
    CLI exit≠0. The message always names what was seen and what is supported.
    """

    def __init__(self, message: str, *, kind: str):
        super().__init__(message)
        self.kind = kind


def reject_claimed_format(claimed: str | None, allowed: list[str]) -> None:
    """Fail fast when a *claimed* format (extension) is outside the allowlist.

    ``claimed=None`` means no recognisable claim — sniffing decides later.
    """
    supported = ", ".join(allowed)
    if claimed == "ole":
        raise InputFormatError(
            "Legacy binary Office files (.doc/.xls/.ppt) are not supported — "
            f"save as OOXML or PDF. Supported formats: {supported}.",
            kind="unsupported",
        )
    if claimed is not None and claimed not in allowed:
        raise InputFormatError(
            f"Format '{claimed}' is not enabled here. Supported formats: {supported}.",
            kind="unsupported",
        )


def claimed_format(filename: str, allowed: list[str]) -> str | None:
    """The format a file *name* claims, gated against the allowlist.

    Returns ``None`` for a name with no extension (content sniffing alone
    decides); raises for an extension that is unrecognised, legacy-Office, or
    outside the allowlist — before any expensive work happens.
    """
    suffix = Path(filename.lower()).suffix
    if not suffix:
        return None
    claimed = EXTENSION_FORMATS.get(suffix)
    if claimed is None:
        raise InputFormatError(
            f"Unsupported file type '{suffix}'. Supported formats: {', '.join(allowed)}.",
            kind="unsupported",
        )
    reject_claimed_format(claimed, allowed)
    return claimed


def gate_document_format(path: Path, claimed: str | None, allowed: list[str]) -> str:
    """Sniff the on-disk file's real format and enforce the allowlist (T-054).

    Returns the detected format name. The content decides: an extension/content
    mismatch is a loud refusal, never mis-handled; a real-but-disallowed format
    is refused with a message naming both the detected format and the supported
    set.
    """
    fmt = sniff_format(path)
    supported = ", ".join(allowed)
    if fmt == "ole":
        reject_claimed_format("ole", allowed)
    if fmt is None:
        if claimed is None:
            # No filename claim to contradict (e.g. /v1/ocr) — this is simply an
            # unsupported media type, not a mismatch.
            raise InputFormatError(
                "Could not identify the document as any supported format. "
                f"Supported formats: {supported}.",
                kind="unsupported",
            )
        raise InputFormatError(
            f"File name claims '{claimed}' but the content is not identifiable "
            f"as any supported format. Supported formats: {supported}.",
            kind="mismatch",
        )
    if claimed is not None and fmt != claimed:
        raise InputFormatError(
            f"File name claims '{claimed}' but the content is '{fmt}' — "
            "extension/content mismatch.",
            kind="mismatch",
        )
    if fmt not in allowed:
        raise InputFormatError(
            f"Detected format '{fmt}' is not enabled here. Supported formats: {supported}.",
            kind="unsupported",
        )
    return fmt


def _sniff_zip(path: Path) -> str | None:
    """Classify a ZIP container: EPUB, OOXML flavour, XPS, or comic archive."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            name_set = set(names)
            if "mimetype" in name_set:
                try:
                    if b"application/epub+zip" in z.read("mimetype"):
                        return "epub"
                except (KeyError, zipfile.BadZipFile):
                    return None
            if any(n.startswith("word/") for n in names):
                return "docx"
            if any(n.startswith("xl/") for n in names):
                return "xlsx"
            if any(n.startswith("ppt/") for n in names):
                return "pptx"
            if any(n.endswith((".fdseq", ".fpage")) for n in names):
                return "xps"
            files = [n for n in names if not n.endswith("/")]
            if files and all(n.lower().endswith(_IMAGE_SUFFIXES) for n in files):
                return "cbz"
    except (zipfile.BadZipFile, OSError):
        return None
    return None


def sniff_format(path: Path) -> str | None:
    """Return the canonical format of the file's actual content.

    ``"ole"`` marks a legacy binary Office file (own targeted rejection);
    ``None`` means unrecognised. Never raises on malformed input.
    """
    try:
        with path.open("rb") as f:
            header = f.read(68)
    except OSError:
        return None
    if header.startswith(b"%PDF"):
        return "pdf"
    if header.startswith(b"PK\x03\x04"):
        return _sniff_zip(path)
    if header.startswith(_OLE_MAGIC):
        return "ole"
    if len(header) >= 68 and header[60:68] in (b"BOOKMOBI", b"TEXtREAd"):
        return "mobi"
    if b"<FictionBook" in header or (
        header.startswith(b"<?xml") and b"<FictionBook" in _head(path)
    ):
        return "fb2"
    return None


def _head(path: Path, n: int = 2048) -> bytes:
    try:
        with path.open("rb") as f:
            return f.read(n)
    except OSError:
        return b""


def validate_formats(formats: list[str], *, office_available: bool = False) -> list[str]:
    """Validate a configured allowlist; returns it deduplicated, order kept.

    Fails loud on an empty list, an unknown format, or an Office format when no
    Office conversion path is available in this deployment.
    """
    if not formats:
        raise RuntimeError(
            "input.formats is empty — at least one input format is required "
            f"(supported: {', '.join(sorted(SUPPORTED_FORMATS))})."
        )
    seen: list[str] = []
    for fmt in formats:
        name = str(fmt).strip().lower().lstrip(".")
        if name not in SUPPORTED_FORMATS:
            raise RuntimeError(
                f"input.formats contains unsupported format {fmt!r}. "
                f"Supported: {', '.join(sorted(SUPPORTED_FORMATS))}."
            )
        if name in OFFICE_FORMATS and not office_available:
            raise RuntimeError(
                f"input.formats contains {name!r}, which requires the LibreOffice "
                "conversion path — not available in this deployment. Use the "
                "Office image variant, or remove the Office formats (T-054)."
            )
        if name not in seen:
            seen.append(name)
    return seen
