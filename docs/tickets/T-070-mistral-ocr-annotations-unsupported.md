# T-070: Mistral OCR Annotations (bbox / document structured extraction) are unsupported

**Status:** Icebox — **good idea, do not build now.** `/v1/ocr` rejects the
annotation parameters loudly (422, T-057); this ticket records *why we are
choosing not to implement them yet*, not a plan to. Revisit only if the trigger
below fires.
**Priority:** Low (Icebox)

## Symptom

Mistral OCR's headline structured-extraction feature — **Annotations** — is
unavailable. `/v1/ocr` rejects its three parameters with a 422:

- `bbox_annotation_format` — return structured JSON *per detected figure/bbox*,
  shaped by a caller-supplied JSON schema (e.g. `{type, caption, key_values}`
  per chart). Response would carry `pages[].images[].image_annotation`.
- `document_annotation_format` / `document_annotation_prompt` — return a
  structured *document-level* extraction per a caller schema/prompt
  (key-information extraction). Response would carry a top-level
  `document_annotation`.

## Root cause

figmark emits its figure interpretations as **free-form Markdown prose** (a
blockquote caption per figure), not as structured JSON adhering to an arbitrary
caller schema, and it does **no document-level key-information extraction** at
all. So the intelligence for `bbox_annotation` largely exists (figmark already
runs a vision model per figure) but the *output shape* does not;
`document_annotation` is a genuinely different capability figmark does not have.

## Why this is Icebox, not Open (the analysis, 2026-07-03)

Assessed for concrete value **to figmark's actual audience** (downstream LLM
consumers — RAG, assistant context), not to a generic OCR buyer:

- **`bbox_annotation` is a serialization shape over intelligence we already
  have.** figmark already finds the figure and interprets it; annotation would
  re-emit that as JSON-per-schema instead of prose. The value of *structured*
  output accrues mostly to **non-LLM** consumers (strict parsers, form-filling).
  figmark's whole thesis is that the consumer *is* an LLM, which reads figmark's
  prose descriptions perfectly well — so the marginal value for our audience is
  low. (Note: figures.json, T-041, already gives machine-addressable figure
  records; annotation would mostly let the caller pick the per-figure fields.)
- **`document_annotation` is downstream KIE — arguably not figmark's job.**
  figmark's role is to produce the *representation*; extracting "these 5 fields"
  is a task the consumer's own LLM does better with figmark's full output as
  context. Baking it in is scope creep against "produce the representation, not
  the answer."
- **The only real driver is strategic market-parity**, not feature value: a
  client that *requires* annotations (invoice/form pipelines) literally cannot
  adopt figmark while we 422. That is a deliberate "do we want the full Mistral
  OCR market?" bet — out of scope for the current LibreChat-shaped goal (T-052).

Counterweight kept for honesty: **if** we ever take that bet, `bbox_annotation`
is unusually *cheap for figmark specifically* — we already run the vision model
per figure, so it is a prompt + response-format change, not new infrastructure.
`document_annotation` would remain the scope-creep half.

## Trigger to move back to Open

Either (a) "full Mistral OCR API parity / be a drop-in for the broad OCR market"
becomes an explicit product goal, or (b) a concrete consumer needs per-figure
structured extraction and prose + figures.json (T-041) demonstrably doesn't
suffice. Absent those, stay iced.

## Options (only if un-iced)

1. **`bbox_annotation` via the existing describe path.** Add a per-figure
   response-format/JSON-schema mode to the vision call figmark already makes;
   populate `images[].image_annotation`. The cheap, on-thesis half.
2. **`document_annotation` as a separate KIE pass.** A document-level structured
   extraction call against the assembled Markdown. The expensive, scope-creep
   half — do only if a real use case demands it.
3. **Stay rejected (status quo).** Keep the loud 422; the LibreChat surface is
   unaffected.

## Acceptance criteria (conditional on un-icing)

- [ ] A recorded go decision tied to the trigger above.
- [ ] If built: the implemented parameter(s) leave T-057's reject list, with
      tests for the structured output and a note in the README OCR section.
