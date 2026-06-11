# T-025: Let the client choose the response format (JSON, Markdown, or both) on /v1/convert

**Status:** Open
**Priority:** Low — ergonomics; the data is already available, this is about delivery

## Symptom / motivation

`POST /v1/convert` always returns JSON:

```json
{"markdown": "...", "page_count": 72, "figure_count": 43, "skipped_count": 3, "language": "Swedish"}
```

A caller who just wants the Markdown file has to parse the JSON and pull out the
`markdown` field every time (`... | ConvertFrom-Json | %{$_.markdown} | Set-Content out.md`).
That is friction for the most common interactive use ("give me the .md"), and it
forces the whole 250 KB+ Markdown string through a JSON round-trip even when the
metadata is not wanted.

We want the client to choose, per request: the structured **JSON** (markdown +
metadata, as today), the raw **Markdown** body, or **both**.

## Current behaviour

- `src/figmark/api.py` — `convert_endpoint(...)` returns a `ConvertResponse`
  pydantic model → always `application/json`. Fields: `markdown`, `page_count`,
  `figure_count`, `skipped_count`, `language`.
- The CLI (`figmark <pdf>`) already writes a `.md` to disk — this ticket is only
  about the HTTP service.

## Design question to settle first: what does "both" mean?

The JSON response *already* carries both the Markdown and the metadata. So:

- **JSON** = content + metadata in one object (today's behaviour).
- **Markdown** = the raw `markdown` string as the body, `Content-Type:
  text/markdown; charset=utf-8`. Metadata would otherwise be lost — echo it in
  `X-Figmark-*` response headers (page-count, figure-count, skipped-count,
  language) so nothing disappears.
- **Both** = either (a) an alias for JSON (since JSON is already "both"), or
  (b) a `multipart/mixed` response with a `text/markdown` part and an
  `application/json` metadata part. (b) is more "honest" but heavier for clients
  to parse; (a) is trivial. This choice is the main decision in this ticket.

## Options

1. **A `format` form field / query param.** `format=json` (default, unchanged) |
   `md` | `both`. Explicit, matches the three-way ask, easy to use from `curl`
   (`-F format=md`). Cons: introduces an enum we must validate.
2. **HTTP content negotiation via the `Accept` header.** `Accept:
   application/json` (default) vs `text/markdown`. RESTful, no new body field.
   Cons: "both" has no clean single media type (would need `multipart/mixed`),
   and headers are clumsier to set from quick `curl` one-liners.
3. **Both mechanisms.** `Accept` for json-vs-md, JSON stays the "both". Most
   flexible, most surface area.

Recommendation to evaluate: **Option 1** with `both` treated as an alias for
`json` (document it), since that satisfies the literal request with the least
machinery; revisit `multipart/mixed` only if a real consumer needs a true
two-part body.

## Must NOT silently default (project principle)

An unrecognised `format` value must **fail loudly** with `422` and a message
listing the allowed values — not silently fall back to JSON. (See the
"fail loudly, no silent fallbacks" principle and T-024.) The *absence* of the
parameter is the one defined default (`json`), for backward compatibility.

## Acceptance criteria

- [ ] `format=json` (and no `format`) returns today's JSON unchanged — back-compat.
- [ ] `format=md` returns the raw Markdown as the body with
      `Content-Type: text/markdown; charset=utf-8` and the metadata in
      `X-Figmark-*` response headers.
- [ ] `format=both` is implemented per the chosen interpretation and documented.
- [ ] An unknown `format` returns `422` with the allowed values — no silent default.
- [ ] OpenAPI schema + `docs/deployment.md` show a `curl` example for each format.
- [ ] Tests cover each format, the default, and the invalid-value 422.
