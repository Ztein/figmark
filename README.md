# figmark

Turn documents into text that an LLM can use — including what only the figures
say: charts, diagrams and process sketches become structured, readable text.
Runs fully locally.

Status: **phase 1 done, at its decision point** — a first converter on Docling,
measured against the floor and ceiling ([`docs/phase-1.md`](docs/phase-1.md));
the yardstick is in [`docs/phase-0.md`](docs/phase-0.md).

```bash
uv sync
cp figmark.example.yaml figmark.yaml     # point `figures` at an OpenAI-compatible VLM
uv run figmark convert report.pdf slides.pptx -o out/
uv run figmark cache stats             # descriptions are cached locally, keyed on image + model + prompt
```

- [`docs/PRD.md`](docs/PRD.md) — what is being built, how it is measured, and the
  hypotheses each phase has to pass (in Swedish).
- [`eval/`](eval/README.md) — the public evaluation documents and question sets.

This is a new project. The first figmark (2026) is archived at
[Ztein/figmark-legacy](https://github.com/Ztein/figmark-legacy).

MIT licensed.
