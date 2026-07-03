# T-063: Cross-document description reuse cannot be turned off (context bleed between documents)

**Status:** Closed — **Option 1 shipped 2026-07-03.**
`cache.share_descriptions_across_documents` (explicit in `config.example.yaml`,
default `true` = today's behaviour). With `false`, description keys include the
document digest: within-document and same-document-re-upload reuse still work,
cross-document reuse stops. SECURITY.md's cache section points at the toggle.
**Priority:** Low — within figmark's single-tenant model this is a quality
trade-off, not a leak; the ticket exists so privacy-strict deployments get a
switch instead of a surprise.

## Symptom

The shared description cache (T-061) reuses a figure description across
documents by image content digest. Descriptions are generated with the
*originating* document's surrounding text and summary as context (T-006), so a
description first created inside document A can carry wording shaped by A
("as the report on X shows…") and later surface verbatim inside document B's
output. There is no way to disable cross-document reuse short of disabling the
cache entirely.

Found in the T-060/T-061 security review (2026-07-02); the trade-off is
documented in SECURITY.md and was accepted as the default because figure
descriptions are overwhelmingly image-driven and partial fidelity beats
re-spend (the product goal).

## Root cause

The cache key is content + config fingerprint by design — document identity is
deliberately not part of it, because that is what makes revised-document and
recurring-logo reuse work.

## Impact

- **Quality:** an occasionally context-tinged description appearing in the
  "wrong" document. Bounded: the text is still a description of the same
  pixels.
- **Privacy (multi-consumer only):** wording derived from one consumer's
  document text can reach another consumer's output. Same boundary discussion
  as T-062.

## Options

1. **Config toggle** `cache.share_descriptions_across_documents: true|false`
   (default true). False → description keys include the document digest:
   within-document and same-document-re-upload reuse still work; cross-document
   reuse stops. Small, honest, testable.
2. **Context-free cached descriptions**: generate descriptions destined for the
   shared cache without document-specific context. Removes the bleed at the
   cost of description quality for everyone — against the product goal.
   Rejected as default; could be a third toggle value if ever demanded.

## Acceptance criteria

- [x] The toggle exists (explicit in config, no hidden default), default
      preserves today's behaviour.
- [x] With it off: same image in two documents → two description calls, and a
      re-upload of the *same* document still reuses (tests for both,
      `tests/test_shared_description_cache.py`).
- [x] SECURITY.md's cache section points at the toggle.
