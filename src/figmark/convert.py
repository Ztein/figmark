"""Convert a document to Markdown with Docling, describing figures with a VLM.

Phase 1 candidate (PRD): Docling's default pipelines and its built-in picture
description, pointed at an OpenAI-compatible endpoint. Every input format
Docling reads is accepted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    ConvertPipelineOptions,
    PdfPipelineOptions,
    PictureDescriptionApiOptions,
)
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
    PowerpointFormatOption,
    WordFormatOption,
)

from .config import Config, FigureModel


@dataclass
class Result:
    markdown: str
    pages: int
    figures: int  # pictures in the body, i.e. in the Markdown
    described: int  # the rest fall under Docling's minimum size (5 % of the page) or failed
    seconds: float


def _describe(fig: FigureModel) -> PictureDescriptionApiOptions:
    opts = PictureDescriptionApiOptions(
        url=fig.base_url.rstrip("/") + "/chat/completions",
        params={"model": fig.model, "temperature": 0, **fig.params},
        headers={"Authorization": f"Bearer {fig.api_key}"} if fig.api_key else {},
        concurrency=fig.concurrency,
        timeout=fig.timeout,
    )
    if fig.prompt:
        opts.prompt = fig.prompt
    return opts


def converter(cfg: Config) -> DocumentConverter:
    describe = cfg.figures is not None
    pdf = PdfPipelineOptions(generate_picture_images=describe, images_scale=2.0)
    office = ConvertPipelineOptions()
    for opts in (pdf, office):
        opts.do_picture_description = describe
        opts.enable_remote_services = describe  # Docling refuses remote calls unless told
        if describe:
            opts.picture_description_options = _describe(cfg.figures)
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf),
            InputFormat.DOCX: WordFormatOption(pipeline_options=office),
            InputFormat.PPTX: PowerpointFormatOption(pipeline_options=office),
        }
    )


def convert(path: Path, conv: DocumentConverter) -> Result:
    t0 = time.time()
    doc = conv.convert(str(path)).document
    from docling_core.types.doc import ContentLayer

    pics = [p for p in doc.pictures if p.content_layer == ContentLayer.BODY]  # headers/footers are not exported
    described = sum(bool(p.meta and p.meta.description) for p in pics)
    return Result(
        markdown=doc.export_to_markdown(),
        pages=len(doc.pages),
        figures=len(pics),
        described=described,
        seconds=round(time.time() - t0, 1),
    )
