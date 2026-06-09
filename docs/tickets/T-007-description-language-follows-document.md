# T-007: Description language is hardcoded to Swedish — should follow the document

**Status:** Closed — implemented 2026-06-09 (Option 1 + auto-detect)
**Priority:** Medium — correctness/quality for any non-Swedish document
**Discovered:** 2026-06-09 reviewing `output/paper/paper.md` (English U-Net paper)

## Resolution

A `language.output` setting in [config.yaml](../../config.yaml) now controls the
output language of image descriptions, diagram descriptions, and the document
summary:

- `auto` (default) — the document's language is detected once
  ([detect_language](../../src/figmark/summarize.py), cached to
  `output/<pdf>/document_language.txt`) and then injected into every prompt as an
  explicit instruction.
- an explicit name (`Swedish`, `English`, `French`, …) forces that language — set
  `Swedish` to reproduce the original "myndighetssvenska" alt text for any
  document.

The Swedish-pinning clause was also removed from the default prompts (they still
describe the task and formal register in Swedish, but no longer force Swedish
output) — that in-prompt directive otherwise overrode the language setting.

**A soft "answer in the document's language" instruction proved unreliable**
against Swedish-written prompts (it kept answering in Swedish for English
documents), which is why `auto` detects the language *name* and instructs the
model explicitly. Verified live: the English U-Net paper now yields English
descriptions and summary; `language.output: Swedish` forces Swedish, `French`
forces French.

## Symptom

Running figmark on an English document (`examples/paper.pdf`) produces figure
descriptions in **Swedish**, embedded in an otherwise **English** Markdown
document:

```
![Image, page 3](images/page-003-img-01.png)

> En svartvit bild som visar en segmentering av neuronala strukturer i en
> elektronmikroskopisk bildstack. Bilden består av ett nätverk av oregelbundna …
```

The body text is English; the caption is Swedish. The document summary is Swedish
too. The output language of the descriptions does not match the surrounding
document.

## Root cause

The `description.prompt`, `diagrams.prompt`, and `document_summary.prompt` in
[config.yaml](../../config.yaml) are written in Swedish ("myndighetssvenska" is
the product's original domain output), and the prompt language drives the model's
output language. Nothing ties the description output to the document's own
language. `ocr.language` exists but only controls Tesseract — not the description
output.

The Swedish default is correct for the original use case, but wrong as a general
default for an open-source tool that will be pointed at documents in any language.

## Impact

- For every non-Swedish document the `.md` is bilingual — body in the source
  language, figure captions in Swedish. Confusing for readers and screen-reader
  users, and it undercuts the "content-faithful approximation of the PDF" goal.
- The annotated-PDF alt text (`--annotate-pdf`) inherits the same mismatch.

## Options

### Option 1: Explicit output-language setting
Add a config field (e.g. `description.language` or a top-level `language`) and
inject an "answer in <language>" clause into the description/diagram/summary
prompts.

- ✅ Simple, explicit, deterministic
- ✅ Keeps the "no hidden defaults" contract (required field)
- ❌ Does not adapt per document in a mixed corpus

### Option 2: Auto-detect the document language
Detect the language from the extracted text and instruct the model to answer in
it (the field could accept `auto`).

- ✅ Correct for mixed corpora with no per-run config
- ❌ Adds a detection dependency/heuristic and a failure mode on short or garbled
  text (e.g. mostly-scanned pages)

### Option 3: "Answer in the same language as the context text"
Lean on the surrounding-text context (T-006) already sent with each figure: tell
the model to match that language.

- ✅ Zero new config or dependencies
- ❌ Unreliable when the context is thin, multilingual, or mostly numbers

### Option 4: Separate instruction language from output language
Template the prompts so the output-language clause is injected while the
instructions themselves can stay in any language.

- ✅ Cleanest separation; composes with Options 1–3
- ❌ More prompt-plumbing

## Recommendation

**Option 1 as the MVP**, with `auto` (Option 2) as a possible value of the same
field later. Inject the output-language clause into all three prompts
(description, diagram, summary) so they stay consistent. Default value should make
the choice explicit rather than silently Swedish.

## Acceptance criteria

- [ ] A config field controls the output language of descriptions, diagram
      descriptions, and the document summary.
- [ ] Running on an English PDF yields English descriptions; a Swedish PDF yields
      Swedish.
- [ ] The document summary follows the same language setting.
- [ ] The existing Swedish behaviour is reproducible (set the language explicitly).
- [ ] Cache interaction documented: changing the language requires clearing
      `output/<pdf>/descriptions/` (and `diagram_descriptions/`,
      `document_summary.txt`), since descriptions are cached per figure regardless
      of language (same caveat as the context config in T-006).
- [ ] The Swedish-by-design prompts in `config.yaml` are preserved as the domain
      default — this ticket adds language control, it does not remove Swedish.
