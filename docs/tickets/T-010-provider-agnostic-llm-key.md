# T-010: Purge provider-specific references — figmark is provider-neutral

**Status:** Open
**Priority:** Medium — first-run experience and project identity

## Symptom / motivation

figmark requires a vision-capable model behind an OpenAI-compatible API — that
is the whole contract. But the codebase is littered with one specific provider
(Berget, which the maintainer happens to use), and the README briefly named
OpenRouter as an example. Neither belongs in the project: provider names in
code/config/docs make a neutral tool look vendor-tied and confuse every user who
runs something else.

A repo-wide inventory (2026-06-10) found `berget`/`openrouter` references in 22
files, clustering into:

- **The env var `BERGET_API_KEY`** (+ `BERGET_API_KEY_FILE`) — config loader,
  API server, compose, tests, docs, `.env.example`.
- **The shipped `config.yaml` default** `api.base_url: https://api.berget.ai/v1`
  and its comments.
- **Docs**: README (install section), SECURITY.md, docs/deployment.md,
  CONTRIBUTING.md, examples/README.md, CHANGELOG (historical — leave).
- **Tests**: `_require_real_key` messages, fixtures, compose assertions, the
  `live` pytest marker description ("runs against the real Berget API").
- **compose.yaml** secret name `berget_api_key`.

(Existing ticket files are historical records and are left untouched.)

## What should be built

1. **Neutral env var** (e.g. `FIGMARK_API_KEY` / `FIGMARK_API_KEY_FILE`), with
   `BERGET_API_KEY` as a deprecated fallback for one release (loader checks the
   new name first, warns loudly on the old one).
2. **Keyless mode** for endpoints that need no auth (local vLLM/Ollama): an
   explicit opt-in (e.g. `FIGMARK_API_KEY=none`), failing loudly on ambiguity.
3. **Shipped config.yaml** loses the Berget URL: ship a placeholder
   (`https://your-endpoint.example/v1`) so the strict loader forces a conscious
   choice, or document clearly that it must be edited before first run.
4. **Rename the compose secret** (`berget_api_key` → `figmark_api_key`) and the
   `*_FILE` plumbing in `api.py`/`compose.yaml`/`docs/deployment.md`/`SECURITY.md`.
5. **Scrub docs and tests**: provider-neutral wording everywhere ("your
   OpenAI-compatible vision endpoint"); the `live` marker description and
   `_require_real_key` messages stop naming Berget; no provider examples beyond
   generic local servers (vLLM, Ollama).
6. README keeps exactly one statement of the requirement: you must connect a
   vision-capable model behind an OpenAI-compatible API. (Already in place.)

## Acceptance criteria

- [ ] `grep -riE "berget|openrouter"` over the repo (excluding `docs/tickets/`
      history and CHANGELOG) returns nothing
- [ ] Fresh clone + any OpenAI-compatible endpoint + key → `figmark <pdf>` works
      with provider-neutral messages end to end
- [ ] `BERGET_API_KEY` still works with a deprecation warning (documented)
- [ ] Keyless local endpoint works via the explicit opt-in
- [ ] compose/deployment/SECURITY use the neutral secret name
- [ ] Live tests gate on "a key exists", with provider-neutral failure messages
