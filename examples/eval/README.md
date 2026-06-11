# Evaluation corpus

A curated set of 31 real economic reports from 9 central banks and institutions,
used to evaluate figmark's figure-interpretation quality against demanding,
chart-dense, multi-language documents. Like the rest of the sample corpus, the
PDFs are **not committed** — only the manifest and the tooling are.

## What's here

| File | Purpose |
|------|---------|
| [`manifest.yaml`](manifest.yaml) | The 31 documents: name, source, language, and a verified direct URL |
| [`../download_eval.py`](../download_eval.py) | Fetches + validates each PDF into `examples/eval/<name>.pdf` |
| [`../run_eval.py`](../run_eval.py) | Runs each through the pipeline, collecting stats into `output/eval/results.json` |

The corpus spans BIS, ECB, US Federal Reserve, Bank of England, Bank of Canada,
Bank of Japan, Czech National Bank, Sveriges Riksbank (Swedish), and Norges Bank
— deliberately varied in institution, layout, length (29–157 pages), and
language (en/sv).

## Reproduce the evaluation

```bash
python examples/download_eval.py     # fetch + validate the 31 PDFs (gitignored)
python examples/run_eval.py          # convert all of them; writes output/eval/results.json
# a subset: python examples/run_eval.py bis-ar-2024 riksbank-ppr-202512
```

`run_eval.py` runs two documents concurrently, caches descriptions per document
(so re-runs are cheap), and survives a bad document rather than aborting the
batch. Each document's full output (Markdown, extracted figures, per-figure
descriptions) lands under `output/eval/<name>/` for manual review.

> Needs a configured `config.yaml` and an LLM key — see the top-level
> [README](../../README.md). A full run is ~1 500 figure descriptions, so it
> costs real API budget.

## Results

The findings of the 2026-06-11 run are written up in
**[docs/eval-report-2026-06-11.md](../../docs/eval-report-2026-06-11.md)**:
31/31 documents converted, 2 642 pages, 1 498 figures described, correct
language behaviour throughout, a manual quality review of the interpretations,
and the two bugs the corpus uncovered (T-021, T-022) plus one open improvement
(T-023). Write a dated companion report for each future run.

## Licensing

The documents are public reports from public institutions, downloaded for local
evaluation only and never redistributed as part of this repository.
