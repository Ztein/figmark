"""CLI entry point.

A thin adapter over ``pipeline.convert``: parse args, load config, build the
client, run the conversion, and print a summary. The pipeline itself lives in
``pipeline.py`` so the CLI and the API server share one code path. See
``docs/architecture.md`` for the full flow.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .config import load_config
from .describe import make_client
from .input_formats import (
    OFFICE_FORMATS,
    InputFormatError,
    claimed_format,
    gate_document_format,
)
from .office import OfficeConversionError, convert_office_to_pdf
from .pipeline import convert, log
from .usage import Cost, format_usage


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="figmark",
        description="Turn a document into Markdown with AI-generated figure descriptions.",
    )
    parser.add_argument(
        "pdf",
        type=Path,
        help="Path to the input document (PDF, or any format enabled in config input.formats)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to the config file (default: config.yaml)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Output directory (default: output/)",
    )
    parser.add_argument(
        "--annotate-pdf",
        action="store_true",
        help="Also produce an annotated copy of the PDF with the descriptions as text annotations.",
    )
    parser.add_argument(
        "--tagged-pdf",
        action="store_true",
        help="Also produce a tagged copy (<pdf>_tagged.pdf) with a Figure structure "
        "tree carrying the descriptions as /Alt (accessibility foundation).",
    )
    return parser.parse_args(argv)


def _prepare_input(doc_path: Path, cfg, work_dir: Path) -> Path:
    """Gate the input exactly like the HTTP surface (T-066), converting Office
    formats to PDF on the way.

    The same file is either handled with full parity or refused loudly with
    the same message on both surfaces — never opened as a degraded near-empty
    "document" that completes with a confident empty result.
    """
    allowed = cfg.input.formats
    fmt = gate_document_format(doc_path, claimed_format(doc_path.name, allowed), allowed)
    if fmt in OFFICE_FORMATS:
        # The allowlist guarantees cfg.input.office is set when an Office
        # format got this far (enforced at config load, T-054).
        office = cfg.input.office
        log(f"Converting {fmt} to PDF (LibreOffice) …")
        return convert_office_to_pdf(
            doc_path, work_dir, soffice=office.soffice_path, timeout=office.timeout_seconds
        )
    return doc_path


def run(
    pdf_path: Path,
    config_path: Path,
    output_root: Path,
    annotate: bool = False,
    tagged: bool = False,
) -> int:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Document not found: {pdf_path}")

    cfg = load_config(config_path)
    client = make_client(cfg)
    with tempfile.TemporaryDirectory(prefix="figmark-input-") as work:
        doc_path = _prepare_input(pdf_path, cfg, Path(work))
        result = convert(
            doc_path, cfg, output_root, annotate=annotate, tagged=tagged, client=client
        )

    log("\nDone.")
    log(f"  Markdown:     {result.markdown_path}")
    log(f"  Raw text:     {result.raw_text_path}")
    log(f"  Figures JSON: {result.figures_manifest_path}")
    log(f"  Images:       {result.images_dir}")
    log(f"  Descriptions: {result.output_dir / 'descriptions'}")
    if (result.output_dir / "diagrams").exists():
        log(f"  Diagrams:     {result.output_dir / 'diagrams'}")
        log(f"  Diagram text: {result.output_dir / 'diagram_descriptions'}")
    if result.annotated_pdf_path:
        log(f"  Alt-text PDF: {result.annotated_pdf_path}")
    if result.tagged_pdf_path:
        log(f"  Tagged PDF:   {result.tagged_pdf_path}")

    cost = (
        Cost(result.estimated_cost, result.currency or "")
        if result.estimated_cost is not None
        else None
    )
    log("  " + format_usage(result.usage, cost))

    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(
            args.pdf, args.config, args.output, annotate=args.annotate_pdf, tagged=args.tagged_pdf
        )
    except (InputFormatError, OfficeConversionError) as e:
        # The loud floor (T-066): a refused input is a clear message and a
        # non-zero exit — never a confident, near-empty result.
        print(f"figmark: error: {e}", file=sys.stderr)
        if isinstance(e, InputFormatError):
            print(
                "figmark: hint: input formats are enabled in config.yaml (input.formats); "
                "Office formats additionally need LibreOffice (see docs/deployment.md).",
                file=sys.stderr,
            )
        return 2


if __name__ == "__main__":
    sys.exit(main())
