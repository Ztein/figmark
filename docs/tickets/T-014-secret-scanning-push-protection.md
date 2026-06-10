# T-014: Verify GitHub secret scanning + push protection on the repo

**Status:** Closed — verified enabled 2026-06-10 on Ztein/figmark
(`secret_scanning: enabled`, `secret_scanning_push_protection: enabled` via the
repos API, right after the first push)
**Priority:** Medium — forward-looking guard; history is verified clean

## Motivation

Trivy's secret scan covers the working tree in CI, and the full git history was
manually audited clean before the first push (no keys, no `.env`, no token files
in any revision). What's missing is the *forward* guard: GitHub-side secret
scanning and push protection, which block a secret from ever entering a push.

GitHub enables secret scanning (and, since 2024, push protection) by default on
public repositories — so this is likely already on, but it must be **verified**,
not assumed.

## What to do

- After the repo is public: Settings → Code security → confirm "Secret scanning"
  and "Push protection" are enabled (or enable via
  `gh api -X PATCH repos/<owner>/<repo> -f security_and_analysis...`).
- Optionally add a `gitleaks` CI step if pre-receive protection is ever
  insufficient (e.g. for forks/mirrors outside GitHub).

## Acceptance criteria

- [ ] Secret scanning shows as enabled on the repository
- [ ] Push protection shows as enabled
- [ ] A test push containing a dummy canary secret is rejected (optional sanity check)
