# T-020: Remove the deprecated BERGET_API_KEY fallback and the last Berget-specific references

**Status:** Closed — verified 2026-06-24. The `BERGET_API_KEY` fallback is already
gone from `config.py` and `api.py`; the only remaining references are *negative*
tests (`test_legacy_berget_key_is_not_a_fallback`, `test_legacy_berget_key_file_is_not_surfaced`)
asserting the old name is **not** honoured — those are kept as regression guards.
No Berget references remain in `src/`, docs, or examples.
**Priority:** Medium — closes out the provider-neutral migration and honours the project's restrictive-fallback principle

## Symptom / motivation

T-010 made figmark provider-neutral but **deliberately kept `BERGET_API_KEY` /
`BERGET_API_KEY_FILE` as a loud deprecation fallback "for one release."** That
release — v0.2.0 — has now shipped. The deprecation window is spent, so the
shim, its tests, and the remaining Berget-named examples should go.

This also aligns the code with the project's stated design principle
(`CONTRIBUTING.md`, `README.md`, `docs/architecture.md`):

> **Fail loudly. No silent fallbacks.**

The current fallback is *loud* (it prints a WARNING), so it does not violate the
letter of that rule — but it is still fallback surface kept only for a migration
that is now complete. Removing it is the restrictive, principle-consistent move.

### When the fallback currently fires

Only when **neither** `FIGMARK_API_KEY` nor `FIGMARK_API_KEY_FILE` is set/non-empty:

- `src/figmark/api.py` — `ServerSettings.from_env`:
  `key = _read_secret("FIGMARK_API_KEY", "FIGMARK_API_KEY_FILE") or _read_secret("BERGET_API_KEY", "BERGET_API_KEY_FILE")`
- `src/figmark/config.py` — `_resolve_api_key`: if `FIGMARK_API_KEY` (env) is
  empty, it consults `BERGET_API_KEY` (env), prints a deprecation WARNING, and
  uses it; otherwise raises `RuntimeError`.

## Inventory — what to remove

- **`src/figmark/config.py`** — `_resolve_api_key`: drop the `BERGET_API_KEY`
  branch and its WARNING. Keep only `FIGMARK_API_KEY` (plus the `=none` keyless
  opt-in) and the provider-neutral "not set" error.
- **`src/figmark/api.py`** — `ServerSettings.from_env`: drop the
  `or _read_secret("BERGET_API_KEY", "BERGET_API_KEY_FILE")` tail and the
  comment naming the deprecated fallback.
- **`tests/test_config.py`** — remove `test_legacy_berget_key_still_works_with_warning`;
  keep the `delenv("BERGET_API_KEY")` hygiene so a future leak is caught.
- **`tests/test_api_startup_fails_loud.py`** — remove
  `test_legacy_berget_key_file_still_surfaced`; add (or keep) a test that a
  BERGET-only environment now **fails loudly** with the standard error.
- **`docs/tickets/T-003-parallel-image-description.md`** — the "Berget rate
  limits" / "Berget typically tolerates 4-8" tuning notes. Tickets are
  historical records, so this is optional — decide whether to neutralise the
  wording ("your provider's rate limits") or leave it as history.
- **`CHANGELOG.md`** — add a **breaking-change** entry for the next release
  ("`BERGET_API_KEY` removed — use `FIGMARK_API_KEY`"). Leave the historical
  lines untouched.

## Impact

Anyone still running the old env var or the old `berget_api_key` secret name
breaks at startup. They have had one full release with a loud warning, so this
is an intentional breaking change — schedule it for the next minor/major
(v0.3.0) and call it out in the changelog.

## Options

1. **Remove now, in v0.3.0, documented as a breaking change.** Deprecation
   window is satisfied; consistent with the restrictive-fallback principle.
   *(Recommended.)*
2. **Keep it one more release.** Rejected — adds no value and prolongs fallback
   surface the project explicitly wants to avoid.

## Acceptance criteria

- [ ] `grep -riE "berget"` over the repo (excluding `CHANGELOG.md` history and
      `docs/tickets/`) returns nothing
- [ ] Starting with **only** `BERGET_API_KEY` / `BERGET_API_KEY_FILE` set fails
      loudly with the standard "`FIGMARK_API_KEY` is not set" error — no fallback,
      no warning-then-continue
- [ ] The two deprecation tests are removed and the suite is green
- [ ] `CHANGELOG.md` documents the removal as a breaking change for v0.3.0
- [ ] README / CONTRIBUTING still state the single requirement (a vision-capable
      model behind an OpenAI-compatible API) with no provider names
