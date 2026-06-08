from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .annotate import AnnotationItem, annotate_pdf
from .config import load_config
from .context import ContextText, get_text_context_around
from .describe import describe_image, make_client
from .diagrams import (
    DiagramRegion,
    describe_diagram,
    find_diagram_regions,
    render_and_save_region,
)
from .images import extract_images_from_page
from .ocr import (
    MIN_CHARS_PER_PAGE,
    MIN_MEAN_CONFIDENCE,
    ocr_page,
    ocr_page_with_vision,
    should_fallback,
)
from .output import PageData, assemble
from .parallel import Job, run_jobs
from .pdf_loader import (
    SCANNED_MIN_AVG_CHARS_PER_PAGE,
    DiagramBlock,
    ImageBlock,
    is_scanned,
    iter_page_blocks,
    iter_pages,
    open_pdf,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parsa PDF till text med AI-syntolkningar av bilder."
    )
    parser.add_argument("pdf", type=Path, help="Sökväg till PDF-filen")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Sökväg till config-fil (default: config.yaml)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Output-katalog (default: output/)",
    )
    parser.add_argument(
        "--annotate-pdf",
        action="store_true",
        help="Producera även en annoterad kopia av PDF:en med syntolkningarna som text-annotations.",
    )
    return parser.parse_args(argv)


def log(msg: str) -> None:
    print(msg, flush=True)


def loud(msg: str) -> None:
    """Skrik ut viktiga beslut/fallbacks så de inte gömmer sig i loggar."""
    bar = "!" * 78
    print(f"\n{bar}\n!!! {msg}\n{bar}\n", flush=True)


def _collect_annotation_items(pages: list[PageData]) -> list[AnnotationItem]:
    """Bygg AnnotationItem-lista från syntolkade bilder + diagram i page_data."""
    items: list[AnnotationItem] = []
    for page_data in pages:
        for img in page_data.images:
            if img.bbox is None:
                continue
            desc = page_data.descriptions.get(img.xref)
            if desc:
                items.append(
                    AnnotationItem(
                        page_num=page_data.page_num,
                        bbox=img.bbox,
                        text=desc,
                        kind="Bild",
                    )
                )
        for block in page_data.blocks:
            if isinstance(block, DiagramBlock):
                desc = page_data.diagram_descriptions.get(block.region_index)
                if desc:
                    items.append(
                        AnnotationItem(
                            page_num=page_data.page_num,
                            bbox=block.bbox,
                            text=desc,
                            kind="Diagram",
                        )
                    )
    return items


def run(pdf_path: Path, config_path: Path, output_root: Path, annotate: bool = False) -> int:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Hittar inte PDF: {pdf_path}")

    cfg = load_config(config_path)
    client = make_client(cfg)

    out_dir = output_root / pdf_path.stem
    images_dir = out_dir / "images"
    descriptions_dir = out_dir / "descriptions"
    diagrams_dir = out_dir / "diagrams"
    diagram_descriptions_dir = out_dir / "diagram_descriptions"
    out_dir.mkdir(parents=True, exist_ok=True)
    descriptions_dir.mkdir(parents=True, exist_ok=True)

    log(f"Öppnar PDF: {pdf_path}")
    doc = open_pdf(pdf_path)
    log(f"Antal sidor: {len(doc)}")
    log(f"Modell: {cfg.api.model}  (base: {cfg.api.base_url})")

    avg_chars = sum(len(p.get_text("text").strip()) for p in doc) / max(1, len(doc))
    scanned = is_scanned(doc)
    log(
        f"Textdensitet: {avg_chars:.0f} tecken/sida i snitt "
        f"(tröskel: {SCANNED_MIN_AVG_CHARS_PER_PAGE})"
    )
    if scanned:
        loud(
            f"PDF KLASSIFICERAD SOM SKANNAD — kör OCR-läge (Tesseract först, "
            f"Gemma-fallback vid otillräcklig kvalitet)"
        )
    else:
        log("PDF klassificerad som textkodad — använder direkt textextraktion.")

    pages: list[PageData] = []
    # Spara fitz.Page-referenser så vi kan rendera diagram-regioner senare
    page_objects: dict[int, "object"] = {}
    page_regions: dict[int, list[DiagramRegion]] = {}

    for page_num, page in iter_pages(doc):
        log(f"\nSida {page_num}/{len(doc)}")
        page_data = PageData(page_num=page_num, is_ocr=scanned)
        page_objects[page_num] = page

        if scanned:
            log("  → Kör Tesseract …")
            result = ocr_page(page, cfg)
            log(
                f"    Tesseract: {len(result.text.strip())} tecken, "
                f"confidence {result.mean_confidence:.1f}"
            )
            if should_fallback(result):
                reasons = []
                if len(result.text.strip()) < MIN_CHARS_PER_PAGE:
                    reasons.append(
                        f"tecken {len(result.text.strip())} < tröskel {MIN_CHARS_PER_PAGE}"
                    )
                if result.mean_confidence < MIN_MEAN_CONFIDENCE:
                    reasons.append(
                        f"confidence {result.mean_confidence:.1f} < tröskel {MIN_MEAN_CONFIDENCE}"
                    )
                loud(
                    f"FALLBACK PÅ SIDA {page_num}: Tesseract otillräcklig "
                    f"({'; '.join(reasons)}) — anropar Gemma för OCR"
                )
                page_data.ocr_text = ocr_page_with_vision(page, client, cfg)
                log(f"    Gemma-OCR: {len(page_data.ocr_text.strip())} tecken")
            else:
                page_data.ocr_text = result.text
        else:
            page_data.blocks = iter_page_blocks(page)
            n_text = sum(1 for b in page_data.blocks if not isinstance(b, ImageBlock))
            n_img = sum(1 for b in page_data.blocks if isinstance(b, ImageBlock))
            log(f"  → {n_text} textblock, {n_img} bildblock (referenser)")

        page_data.images = extract_images_from_page(
            doc, page, page_num, images_dir, skip_full_page=scanned
        )
        log(f"  → {len(page_data.images)} bild(er) sparade")

        # Diagram-extraktion: bara för textkodade PDF:er (för skannade är "diagrammen"
        # redan en del av sidan och fångas i OCR-vägen)
        if cfg.diagrams.enabled and not scanned:
            regions = find_diagram_regions(page, page_num)
            if regions:
                for region in regions:
                    render_and_save_region(page, region, diagrams_dir)
                    page_data.blocks.append(
                        DiagramBlock(bbox=region.bbox, region_index=region.index)
                    )
                page_regions[page_num] = regions
                log(f"  → {len(regions)} diagram-region(er) identifierade")
                # Re-sortera blocks så diagrammen hamnar i läsordning ihop med text/bild
                page_data.blocks.sort(key=lambda b: (round(b.bbox[1] / 10), b.bbox[0]))

        pages.append(page_data)

    total_diagrams = sum(len(regions) for regions in page_regions.values())
    if total_diagrams:
        diagram_descriptions_dir.mkdir(parents=True, exist_ok=True)

    # Samla ihop ALLA syntolkningsjobb (bilder + diagram). Cache-träffar löses
    # här direkt så vi inte schemalägger onödiga workers; bara faktiska API-anrop
    # går till parallel.run_jobs.
    jobs: list[Job] = []
    cache_hits = 0
    total_pending = sum(len(p.images) for p in pages) + total_diagrams

    def _maybe_context(bbox) -> ContextText | None:
        if not cfg.context.enabled:
            return None
        if bbox is None:
            return None
        return get_text_context_around(
            pages,
            page_num=page_data.page_num,
            bbox=bbox,
            words_before=cfg.context.words_before,
            words_after=cfg.context.words_after,
        )

    for page_data in pages:
        for img in page_data.images:
            desc_path = descriptions_dir / f"{img.path.stem}.txt"
            cached = desc_path.exists() and desc_path.read_text(encoding="utf-8").strip()
            if cached:
                page_data.descriptions[img.xref] = cached
                cache_hits += 1
                continue
            label = f"sida {page_data.page_num:>3} bild  {img.index:>2}"
            ctx = _maybe_context(img.bbox)
            jobs.append(_make_image_job(label, client, img, desc_path, cfg, page_data, ctx))

        for region in page_regions.get(page_data.page_num, []):
            desc_path = diagram_descriptions_dir / f"{region.path.stem}.txt"
            cached = desc_path.exists() and desc_path.read_text(encoding="utf-8").strip()
            if cached:
                page_data.diagram_descriptions[region.index] = cached
                cache_hits += 1
                continue
            label = f"sida {page_data.page_num:>3} diagram {region.index:>2}"
            ctx = _maybe_context(region.bbox)
            jobs.append(_make_diagram_job(label, client, region, desc_path, cfg, page_data, ctx))

    if total_pending:
        if cache_hits:
            log(f"\nSyntolkning: {cache_hits} av {total_pending} hämtades från cache")
        if jobs:
            header = (
                f"Syntolkar {len(jobs)} via {cfg.api.model} "
                f"({cfg.concurrency.max_workers} parallella)"
            )
            run_jobs(jobs, cfg.concurrency.max_workers, header)
        else:
            log("\nAllt redan cache-hämtat — inga API-anrop behövdes.")

    log("\nSammanställer text …")
    raw_text, full_text = assemble(pages, cfg)

    raw_path = out_dir / "raw_text.txt"
    full_path = out_dir / "full_text.txt"
    raw_path.write_text(raw_text, encoding="utf-8")
    full_path.write_text(full_text, encoding="utf-8")

    annotated_pdf_path: Path | None = None
    if annotate:
        items = _collect_annotation_items(pages)
        annotated_pdf_path = out_dir / f"{pdf_path.stem}_alt_text.pdf"
        log(f"\nLägger in {len(items)} syntolkningar som alt-text → {annotated_pdf_path}")
        # Stäng källans doc först — vi måste öppna om filen rent
        doc.close()
        annotate_pdf(pdf_path, annotated_pdf_path, items)
    else:
        doc.close()

    log("\nKlart.")
    log(f"  Råtext:        {raw_path}")
    log(f"  Fulltext:      {full_path}")
    log(f"  Bilder:        {images_dir}")
    log(f"  Syntolkningar: {descriptions_dir}")
    if total_diagrams:
        log(f"  Diagram:       {diagrams_dir}")
        log(f"  Diagram-text:  {diagram_descriptions_dir}")
    if annotated_pdf_path:
        log(f"  Alt-text PDF:  {annotated_pdf_path}")

    return 0


def _make_image_job(label, client, img, desc_path, cfg, page_data, context) -> Job:
    """Stäng in variabler i en factory — closures-i-loop-fällan annars."""
    def run_describe() -> str:
        return describe_image(client, img.path, desc_path, cfg, context=context)

    def store(text: str) -> None:
        page_data.descriptions[img.xref] = text

    return Job(label=label, func=run_describe, on_done=store)


def _make_diagram_job(label, client, region, desc_path, cfg, page_data, context) -> Job:
    def run_describe() -> str:
        return describe_diagram(client, region, desc_path, cfg, context=context)

    def store(text: str) -> None:
        page_data.diagram_descriptions[region.index] = text

    return Job(label=label, func=run_describe, on_done=store)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args.pdf, args.config, args.output, annotate=args.annotate_pdf)


if __name__ == "__main__":
    sys.exit(main())
