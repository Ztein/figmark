# Riksbank PPR corpus — hand-written figure descriptions as a quality baseline

Every Monetary Policy Report (*penningpolitisk rapport*, `ppr-`) and Monetary
Policy Update (*penningpolitisk uppdatering*, `ppu-`) published on riksbank.se
— 57 documents, 2017–2026, Swedish.

**Why this corpus exists (T-082).** From November 2020 the Riksbank ships these
as tagged PDFs where every chart carries a **hand-written accessibility
description** (an `/Alt` entry in the PDF structure tree — invisible to plain
text extraction). That is a rare thing: a *human-authored description of every
figure*, written by the publisher, at scale. It gives the description-quality
work an external reference point that no synthetic gold set can: **is figmark's
model-written description at least as good as the publisher's own?**

The descriptions are honest but modest — typically 2–4 sentences naming what
the chart shows and the headline movement, not a full reading of the data. So
they are a *floor to clear, not a ceiling to aim for*: a useful measuring
point, with the judge (T-082) deciding "at least as good" on correctness,
relevance and detail level.

## What is committed vs downloaded

Only this README, `manifest.yaml` and the downloader are committed. The PDFs
land in `files/` (gitignored — the repo-wide `*.pdf` rule):

```bash
python examples/download_ppr.py              # scrape listing, sync manifest, download all
python examples/download_ppr.py --no-scrape  # offline: download from the manifest only
```

The script scrapes the riksbank.se listing (server-side `?year=` filter), merges
new publications into the manifest, validates every file (PDF magic + PyMuPDF)
and prints the alt-text census below. A manifest entry that disappears from the
listing, or whose URL changes, is reported loudly — never silently dropped.

## Alt-text census (2026-08-13)

| Window | Documents | Hand-written figure descriptions |
|---|---|---|
| 2017-02 … 2020-09 (20 reports) | 20 | **0** — pre-accessibility era |
| **2020-11 … 2026-06** (26 reports) | 26 | **34–62 per report**, every report |
| Updates 2024-02 … 2026-05 | 10 | 8–12 each, except `ppu-2024-11` and `ppu-2025-01` (0) |

≈ 1 300 descriptions in total across the 30 gold-window documents.

Reading them (they are structure-tree entries, not page text):

```python
import fitz
doc = fitz.open("examples/eval/ppr/files/ppr-2026-03.pdf")
for xref in range(1, doc.xref_length()):
    kind, value = doc.xref_get_key(xref, "Alt")
    if kind == "string" and len(value) >= 60:
        print(value)
```

## Relation to the main eval corpus

`examples/eval/manifest.yaml` already includes single Riksbank documents
(e.g. `riksbank-ppr-202503`) for *coverage* evaluation. This corpus is the
same publication series but complete and kept in sync, for *description
quality* — comparing figmark output against the publisher's own text per
figure. The overlap is intentional; the two manifests serve different benches.
