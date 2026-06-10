# T-010: Work with any OpenAI-compatible provider key — not just Berget

**Status:** Open
**Priority:** Medium — first-run experience for every non-Berget user

## Symptom / motivation

The tool already works against any OpenAI-compatible endpoint (`api.base_url` is
configurable), but the **key handling says otherwise**: the environment variable
is `BERGET_API_KEY`, `.env.example` mentions only Berget, the config loader's
error message tells the user to get a Berget key, and the live tests hard-fail
(`pytest.fail`) specifically demanding `BERGET_API_KEY`.

Requirement: figmark must work — including its tests — as long as the user has
**at least one key to any vision-capable LLM** behind an OpenAI-compatible API.
OpenRouter is a perfectly good example, as is a local vLLM/Ollama endpoint (which
may need no key at all). This must also be clear in the README.

## What should be built

- A provider-neutral variable (e.g. `FIGMARK_API_KEY` or `LLM_API_KEY`), with
  `BERGET_API_KEY` kept as a deprecated fallback for compatibility (loader checks
  the new name first, warns on the old one).
- Allow a keyless mode for endpoints that don't require auth (e.g. local vLLM):
  e.g. `FIGMARK_API_KEY=none` or an explicit `api.auth: none` config — decide in
  implementation, fail loudly on ambiguity.
- Update `.env.example`, the config-loader error message, `SECURITY.md`,
  `docs/deployment.md` (`BERGET_API_KEY_FILE` → neutral name), `compose.yaml`
  secret naming, and the API server's `*_FILE` convention.
- Live tests gate on "a key exists", not "a Berget key exists"; README documents
  an OpenRouter example end-to-end (base_url + model + key).

## Acceptance criteria

- [ ] Fresh clone + OpenRouter key + `config.yaml` pointing at OpenRouter →
      `figmark <pdf>` works with no Berget mention anywhere in the path
- [ ] `BERGET_API_KEY` still works (deprecation warning, documented)
- [ ] README shows at least one non-Berget provider example
- [ ] Live tests run with any provider key; error messages are provider-neutral
- [ ] compose/deployment docs use the neutral secret name
