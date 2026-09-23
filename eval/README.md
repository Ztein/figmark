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

`questions/ppr-2026-03.yaml` is a first question set in the format the PRD
describes: 119 categorical questions (number with tolerance, yes/no, choice)
over 13 figures of one report, keys read from the rendered figures by a person.

```bash
pip install pyyaml
python eval/fetch.py
```
