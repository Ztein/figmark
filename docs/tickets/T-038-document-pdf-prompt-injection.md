# T-038: Threat model omits PDF-text prompt injection

**Status:** Open
**Priority:** Low — low risk for the stated use case, but undocumented
**Source:** External code review (2026-06-24), verified against the code.

## Symptom

The text context around a figure is concatenated straight into the model prompt
(`compose_prompt`, [describe.py:113-141](../../src/figmark/describe.py); context
gathered in [context.py](../../src/figmark/context.py)). A crafted PDF could embed
instructions in its body text that reach the model as if they were part of the
task. SECURITY.md does not mention this vector.

## Root cause

Untrusted document text flows into the prompt with no delimiting and no threat-model
note. The surrounding scaffolding labels (`[Document type]`, `[Task]`) are
structural but do not tell the model that context is *data, not commands*.

## Impact

Low for trusted government documents (the project's stated use case), but real and
currently undocumented. Honesty about the trust boundary belongs in SECURITY.md.

## Options

1. **Document the vector and the trust assumption in SECURITY.md** (minimum).
2. Add structural delimiting and an explicit instruction that the provided context
   is data to be described, not instructions to follow.
3. Both.

Recommendation: **Option 1 now** (honest threat model); consider Option 2 as a
follow-up if untrusted PDFs ever become an intended input.

## Acceptance criteria

- [ ] SECURITY.md documents the PDF-text prompt-injection vector and states the
      trust assumption (trusted-document use case).
- [ ] Any optional mitigation is noted as an explicit follow-up, not silently
      assumed.
