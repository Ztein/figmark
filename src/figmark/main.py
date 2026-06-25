"""CLI entry point.

A thin adapter over ``pipeline.convert``: parse args, load config, build the
client, run the conversion, and print a summary. The pipeline itself lives in
``pipeline.py`` so the CLI and the API server share one code path. See
``docs/architecture.md`` for the full flow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .describe import make_client
from .pipeline import convert, log
from .usage import Cost, format_usage


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="figmark",
        description="Turn a PDF into Markdown with AI-generated figure descriptions.",
    )
    parser.add_argument("pdf", type=Path, help="Path to the PDF file")
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


def run(
    pdf_path: Path,
    config_path: Path,
    output_root: Path,
    annotate: bool = False,
    tagged: bool = False,
) -> int:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    cfg = load_config(config_path)
    client = make_client(cfg)
    result = convert(pdf_path, cfg, output_root, annotate=annotate, tagged=tagged, client=client)

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
    return run(
        args.pdf, args.config, args.output, annotate=args.annotate_pdf, tagged=args.tagged_pdf
    )


if __name__ == "__main__":
    sys.exit(main())
