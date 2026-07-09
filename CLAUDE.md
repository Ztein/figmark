# figmark — working agreement for Claude

figmark converts documents (PDF, EPUB, Office) to Markdown, describing figures
and vector diagrams with a vision model instead of dropping them. Lean and
air-gap-friendly (PyMuPDF + Tesseract + Pillow + an OpenAI-compatible client),
with a "fail loud, never silently degrade" principle.

**Product goal — keep this in view when prioritising:** extract as much
*valuable information* from a document as possible, in a form LLM-based
products (LibreChat-style platforms, RAG pipelines, assistant chat context)
can use effectively. figmark fulfils the Mistral-OCR API contract but aims to
beat plain OCR by *interpreting* content that text extraction can't see —
charts, diagrams, images that carry information. Extraction quality is a
spectrum, not 1-or-0: text alone gets a downstream LLM far, every interpreted
figure/table/heading makes it better, and a partial figure description still
beats a dropped figure (downstream LLMs are forgiving). Mass OCR of scanned
archives is a supporting path, **not** the core function; accessibility outputs
(alt-text/tagged PDF) remain a secondary surface of the same descriptions.

## Git & PR workflow

- **Never commit directly to `main`** — it is the default branch and protected.
  Always branch first, then open a PR (`gh pr create --base main`).
- **Claude is authorized to approve and merge its own PRs.** Do not wait for a
  human reviewer. Squash-merge to match the repo's history:
  - Preferred: `gh pr merge <n> --squash --auto --delete-branch` — lands the PR
    automatically once CI is green, honouring branch protection.
  - If a self-authored PR is blocked *only* on the required-review rule (you
    cannot approve your own PR via the review UI), use
    `gh pr merge <n> --squash --admin --delete-branch` to merge immediately.
    Only bypass when checks are green or the change is docs/scripts-only.
- Commit messages end with the `Co-Authored-By: Claude Opus 4.8` trailer.

## This is a PUBLIC repo — keep our deployment out of it

figmark is open source and public. The repo holds only **product-level, generic**
content — true for anyone who clones it. Anything specific to *our* running
instance stays out: host names, internal/Tailscale/LAN IPs, MagicDNS names,
tokens, the `ztein` tunnel, and any employer or data-handling context. Those live
in the **private** infra repo (`~/Documents/macmini-cloudflare`) or a **local,
gitignored** doc (`LOCAL_DEPLOY.md`), never here.

- **Litmus test before committing:** *"Would this line be appropriate for a
  stranger who clones figmark?"* If it names our host, an internal IP, a token, or
  the employer, it does not belong in this repo.
- **Tickets:** product issues (bugs, features, the image, error mapping) are
  public. "Deploy/operate *our* instance" work is infra — track it in the private
  repo, not `docs/tickets/`.
- Deployment docs here describe options **generically** (reverse proxy,
  `tailscale serve`) without our specific names, IPs, or topology.

### Two surfaces — where work goes

There are two distinct concerns. The repo is the *product*; our running service is
an *instance* of it. Route every change accordingly — when in doubt, apply the
litmus test above.

| Kind of work | Home | Surfaced as |
|---|---|---|
| Product bug / feature / image / error mapping | **This public repo** | `docs/tickets/T-NNN`, code, PRs |
| Our-instance runbook (host, token, network, bind) | Local `LOCAL_DEPLOY.md` (gitignored) | not committed |
| Local dev-env hygiene (key files, drift) | Local `LOCAL_TICKETS.md`, **`L-NNN`** series (gitignored) | not committed |
| Downstream-consumer raw feedback | Local `docs/figmark-feedback.md` (gitignored) → distilled into a public `T-NNN` | not committed |
| Deploy/operate our instance | **Private** infra repo `~/Documents/macmini-cloudflare` | private |
| Live service state (what's up, ports, deps) | **`ztein-infra` MCP** (source of truth + write-lease) | — |

- `T-NNN` = public product tickets (monotonic). `L-NNN` = local hygiene, never
  committed — don't file local-env work as a `T-NNN`.
- **Leak guard:** a pre-commit hook blocks any commit containing an instance
  marker. Enable it once per clone: `git config core.hooksPath scripts/githooks`.
  Markers live in the gitignored `.leakguard`; the hook script itself is generic.

## Tickets

- One file per ticket: `docs/tickets/T-NNN-slug.md`, indexed in
  `docs/tickets/README.md` (keep the table row in sync: ID, Status, Priority,
  Title). Numbers are monotonic — the next ticket is the highest `T-NNN` + 1.
- Title describes the **symptom, not the solution**. Body sections:
  **Status**, **Priority**, **Symptom**, **Root cause**, **Impact**,
  **Options** (numbered trade-offs, not a pre-picked answer), **Acceptance
  criteria**. Statuses: **Open** (active), **Parked** (blocked on something
  external), **Icebox** (a good idea deliberately not scheduled now — names its
  un-ice trigger), **Closed** (done on merge, or withdrawn). Full legend in
  `docs/tickets/README.md`.

## Testing — run for real

The offline suite (`pytest -m "not live"`) runs the whole pipeline against the
`mockllm` server. It is for fast iteration and is the only thing CI runs — but it
**cannot** catch a real-model regression, a changed payload contract, or a dead
endpoint/key. The cached `output/` is likewise just a snapshot of the last real
run, not evidence that the code still works today.

So **the real end-to-end suite is a local responsibility, and it must actually be
run** — not assumed green from cache or from the mock:

```bash
pytest -m live                 # the 9 live tests (real API; needs a valid FIGMARK_API_KEY)
python examples/run_eval.py    # the full eval corpus against the real model
```

- **Run it for real at regular intervals — whenever we have reason to think we
  need it:** before a release, after any change to the pipeline / `describe` /
  `ocr` / `output` path, and whenever the key or endpoint may have changed. Use
  judgement on cadence, but a long gap with code changes in between is a smell.
- **Never hide errors again.** If the live suite cannot run (dead key, no quota,
  unreachable endpoint), say so **loudly** and treat any cached output as stale —
  never present cached or mock-backed results as if they were a fresh, verified
  real run. A degraded or skipped live run is reported, not silently swallowed.

## Principles to uphold in code

- **Fail loud.** No silent fallbacks or hidden defaults; a degraded path is
  logged/warned, not swallowed (see T-024).
- **Bench before code** for any detection/extraction change. Build a small
  labelled bench, write the decision threshold down, record the numbers in the PR
  (the table work in T-026/T-030 is the template).
- **Stay lean.** Adding a runtime dependency needs an explicit, justified reason
  in the relevant ticket; the air-gapped Docker image is a hard constraint.
- **No arbitrary limits.** A hard limit that gates behaviour — an image/payload
  size cap, a token/DPI ceiling, a timeout, a mimetype allowlist — must have a
  *validated* reason (measured against the model/endpoint or a bench), not a
  by-feel guess. Validate against the model; don't assume. When a limit is
  genuinely operator-specific, make it config-driven rather than frozen in a
  constant (see T-083/T-084).
