# T-006: Send the text context around the image along with the description

**Status:** Closed — TDD-implemented 2026-05-20 (option 1: fixed word count)
**Priority:** Medium — noticeably raises the quality of the descriptions
**Requested:** 2026-05-20

## Symptom / motivation

Today Gemma gets only the image + the prompt. The model doesn't know what the PDF is about. For a chart in a monetary policy report it sees lines and numbers, but has no idea that it's specifically about CPIF forecasts or from which scenario. The interpretation becomes generic instead of domain-specific.

A concrete example: a chart with two lines around 2026-2029 could be *anything* (GDP, inflation, interest rate, unemployment). The text above the image usually says "Chart 1.3: Inflation according to the CPIF measure, forecast vs outcome" — if we send that clue along, the model could write a correct description directly without guessing.

## What should be built

- Before each image/chart is sent to Gemma — gather N words of text **before** and M words **after** from the PDF
- The context is taken from the PDF's reading order (text blocks sorted by y,x — we already have that)
- At a page boundary: jump to the previous/next page if we haven't filled the quota
- Skip other image/chart blocks — we want text, not placeholders
- The context is formatted clearly in the prompt so the model knows what is context vs task

## Configuration

New required fields per our "no defaults in the code" policy:

```yaml
context:
  enabled: true
  words_before: 100
  words_after: 100
```

## Options

### Option 1: Fixed number of words before/after
Count words linearly — `text.split()` gives the word count, back up N TextBlocks' worth of words. Predictable token cost.

- ✅ Simple, robust
- ✅ Configurable limit
- ❌ Can cut off mid-sentence

### Option 2: Whole paragraphs
Whole TextBlocks groups, no halved sentences. More natural language in the prompt.

- ✅ Better linguistic quality in the context
- ❌ Varying size — some paragraphs are 500 words, others 10
- ❌ Harder to predict token cost

### Option 3: The whole page's text
Send all text on the same page as the image. No distance calculations.

- ✅ Simplest to implement
- ❌ Chart-heavy pages → the context contains other charts' text → distracts the model
- ❌ Expensive on text-heavy pages

### Option 4: Hybrid — paragraphs but capped at N words
Pick whole paragraphs up to a cap (say 150 words) — stop at the word quota but round off to a paragraph boundary.

- ✅ Combines Option 1's predictability with Option 2's language quality
- ❌ More code

## Recommendation

**Option 1** as the MVP. Simple word counting is robust and predictable. We can upgrade to Option 4 later if we notice that the context cuts off carelessly.

## Acceptance criteria

- [ ] `context.enabled`, `context.words_before`, `context.words_after` are required in config.yaml
- [ ] TDD: unit tests for `get_text_context_around(pages, page_num, bbox, words_before, words_after)`
  - Image in the middle of a page → context from the same page
  - Image at the top of the page → jumps to the previous page
  - Image at the bottom → jumps to the next page
  - Image on the first page → empty `before`
  - Image on the last page → empty `after`
  - Page with only images → backs up until text is found
- [ ] The prompt clearly shows what is context, with headings like
      `[Text context before the image]\n...\n[Text context after the image]\n...\n[Task]\n...`
- [ ] A live test against a real case where the context makes a difference
      (compare the description of the same chart with/without context)
- [ ] CLI logs show the number of words of context actually sent per call

## Things to keep in mind

- **Token cost**: 100 words ≈ 130 tokens in Swedish. 100 before + 100 after = ~260 extra tokens per call.
  That's manageable. With 30 calls total ≈ 8000 extra tokens. Marginal cost.
- **Cache invalidation**: Today we cache descriptions per image file. If we change the context config,
  stale cache without context is returned. Either:
  a) Document that you have to clear `output/<pdf>/descriptions/` on a context-config change
  b) Hash prompt+context-config into the cache filename (more work, worth it?)
  → Probably (a) as the MVP, (b) as its own ticket if it turns out to be a problem.
- **Word counting in Swedish**: `.split()` is good enough. No special characters or hyphenation to handle.
- **Tables**: The PDF's "text" sometimes includes table content. That adds a bit of noise to the context but is not
  a big problem — the model can filter it out.
