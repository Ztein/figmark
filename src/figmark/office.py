"""Office (docx/xlsx/pptx) → PDF via LibreOffice headless (T-054).

figmark's value is preserving layout, tables and embedded figures so the vision
model can describe them — so Office documents are converted to PDF at full
fidelity and then ride the normal pipeline. Lightweight text extractors were
rejected for exactly this reason (see the ticket's Decision).

Process-level sandboxing (the Office image variant adds the rest — no network,
non-root, read-only rootfs):

- Every conversion gets a **fresh throwaway profile** (``-env:UserInstallation``)
  pre-seeded with macro security "very high" — document macros never run, and no
  state leaks between conversions.
- A **hard timeout**: a hung or runaway ``soffice`` is killed and surfaces as a
  loud ``OfficeConversionError``, never a hang.
- Output is confined to the caller's directory.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import fitz

logger = logging.getLogger("figmark.office")

DEFAULT_TIMEOUT_SECONDS = 120.0

# Spreadsheets have no intrinsic page count — LibreOffice paginates a used range
# into print pages, so a long time series (e.g. a 9000-row FX sheet) explodes
# into hundreds of PDF pages of loose, flattened numbers (T-056). We can't fix
# the flatten without a spreadsheet-native extractor (deferred, see the ticket),
# but we refuse to do it *silently*: above this page count a spreadsheet
# conversion shouts a loud warning naming the file and the likely cause.
SPREADSHEET_PAGE_WARN_THRESHOLD = 50
_SPREADSHEET_SUFFIXES = frozenset({".xlsx", ".xls", ".ods", ".csv"})

# Pre-seeded into the throwaway profile: macro security level 3 = "very high"
# (only signed macros from trusted locations — and we trust none). LibreOffice
# reads this before opening the document, so it holds even for formats that
# embed auto-exec macros.
MACRO_SECURITY_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry"
           xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <item oor:path="/org.openoffice.Office.Common/Security/Scripting">
    <prop oor:name="MacroSecurityLevel" oor:op="fuse">
      <value>3</value>
    </prop>
    <prop oor:name="DisableMacrosExecution" oor:op="fuse">
      <value>true</value>
    </prop>
  </item>
</oor:items>
"""


class OfficeConversionError(RuntimeError):
    """A LibreOffice conversion failed, timed out, or produced no output."""


def find_soffice(configured: str | None = None) -> str | None:
    """Resolve the LibreOffice binary: the configured path first, then $PATH."""
    if configured:
        p = Path(configured)
        return str(p) if p.exists() else None
    return shutil.which("soffice")


def convert_office_to_pdf(
    source: Path,
    out_dir: Path,
    *,
    soffice: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Path:
    """Convert an Office document to ``out_dir/<stem>.pdf``. Fails loud, never hangs.

    ``soffice`` defaults to whatever ``find_soffice`` resolves. The conversion
    runs with a fresh, macro-locked profile under ``out_dir/lo-profile``.
    """
    binary = soffice or find_soffice()
    if binary is None:
        raise OfficeConversionError(
            "LibreOffice (soffice) not found — Office input requires the Office "
            "image variant or a local LibreOffice install (T-054)."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    profile = out_dir / "lo-profile"
    (profile / "user").mkdir(parents=True, exist_ok=True)
    (profile / "user" / "registrymodifications.xcu").write_text(
        MACRO_SECURITY_XCU, encoding="utf-8"
    )

    cmd = [
        binary,
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--nodefault",
        "--nologo",
        f"-env:UserInstallation=file://{profile.resolve()}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir),
        str(source),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        # subprocess.run kills the child on timeout — surface it loudly.
        raise OfficeConversionError(
            f"LibreOffice conversion of {source.name} timed out after {timeout:.0f}s "
            "and was killed."
        ) from e

    result = out_dir / f"{source.stem}.pdf"
    if proc.returncode != 0 or not result.exists():
        stderr = (proc.stderr or "").strip()[-500:]
        logger.error("soffice failed for %s (exit %d): %s", source.name, proc.returncode, stderr)
        raise OfficeConversionError(
            f"LibreOffice could not convert {source.name} to PDF (exit {proc.returncode})."
        )
    _warn_on_spreadsheet_page_explosion(source, result)
    return result


def _warn_on_spreadsheet_page_explosion(source: Path, pdf: Path) -> None:
    """Shout (never swallow) when a spreadsheet paginated into a huge PDF (T-056).

    The numbers survive but their table structure is flattened across print
    pages; a downstream LLM copes far better with a heads-up in the logs than
    with a silent 380-page wall of loose values.
    """
    if source.suffix.lower() not in _SPREADSHEET_SUFFIXES:
        return
    try:
        with fitz.open(pdf) as doc:
            pages = len(doc)
    except Exception:  # noqa: BLE001 — a page-count probe must never fail the conversion
        return
    if pages > SPREADSHEET_PAGE_WARN_THRESHOLD:
        logger.warning(
            "SPREADSHEET PAGE EXPLOSION: %s produced a %d-page PDF (threshold %d). "
            "LibreOffice paginates large sheets into print pages, so table "
            "structure is flattened into loose values across those pages. The data "
            "is present but its column<->value attribution is degraded (T-056).",
            source.name,
            pages,
            SPREADSHEET_PAGE_WARN_THRESHOLD,
        )
