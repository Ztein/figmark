# Evaluation documents

The only thing carried over from the first figmark: the documents it was
evaluated on. All are public. Manifests list them; `fetch.py` downloads them
into `files/` (gitignored).

| Manifest | Documents | What it stresses |
| --- | --- | --- |
| `central-banks.yaml` | 33 | Chart-heavy reports, many layouts, en/sv/de |
| `riksbank-ppr.yaml` | 57 | One publisher over ten years, Swedish, dense charts |
| `office.yaml` | 29 | docx/pptx/xlsx, including charts with values in chart XML |
| `papers.yaml` | 1 | Academic figures (architecture diagrams) |

`questions/` holds the figure questions in the format the PRD describes:
categorical answers (number with tolerance, yes/no, choice), keys read from the
rendered figure, never from a description or alt text. 174 questions on 21
figures: 119 on 13 charts of one Riksbank report, 55 on flowcharts, a map, a
pie chart and a scatter plot (the 55 are pending human review).

```bash
uv sync                          # Python 3.12, Docling and the eval tools
uv run eval/fetch.py             # download the documents into files/
uv run eval/inventory.py         # format, pages, text layer, figures per class → inventory/
uv run eval/inventory.py --summary   # → inventory.csv
uv run eval/native_truth.py      # Office → PDF, chart XML / SmartArt / text truth → truth/ (gitignored)
```

## Inventory (phase 0)

120 documents, 5 911 pages, 4 762 figures detected by Docling in the PDFs (layout
without OCR, DocumentFigureClassifier). Line charts are 79 % of all figures
(3 746), bar charts 444; flowcharts 37, scatter plots 25, maps 4, pie charts 2.
68 documents are Swedish, 51 English, 1 German. **No scanned documents**: every
PDF has a text layer on nearly every page, so the scanned stratum is empty.

Office: 20 embedded charts carry exact values in chart XML (8 of them in one
Swedish workbook, the rest fixtures) and 2 SmartArt graphics carry their nodes
and edges — the free ground truth the PRD counts on is small.

## Test set v1

`testset-v1.yaml`, drawn by `testset.py` from `inventory.csv` with rules written
in the script, then frozen: 49 documents (31 PDF, 10 DOCX, 8 PPTX; 28 en, 20 sv,
1 de), 1 633 figures. Every document with a flowchart, map or pie chart; one
report per central-bank publisher; one Riksbank PPR per year; the Office files
with figures or chart XML; every document that has figure questions.

## Figure questions (phase 0)

```bash
cp eval/config.example.yaml eval/config.yaml   # point it at your endpoints
uv run eval/floor.py                 # floor reading: text layer only → runs/floor/
uv run eval/qa.py floor --repeat 2   # score a reading (retrieval form, +1 / 0 / −1)
uv run eval/qa.py floor --ceiling --repeat 2   # same retrieval plus the figure image
uv run eval/h0.py build              # H0 variants of known quality → runs/h0-*/
uv run eval/h0.py report [figure|all|<kind>]
```

A *reading* is one Markdown/text file per document under `runs/<reading>/`; any
pipeline is scored by writing its output there. H0 is pre-registered in
`h0/README.md`; results and the proposed thresholds are in `docs/phase-0.md`.
