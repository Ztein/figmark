# T-039: Dockerfile base comment has drifted from the pinned image

**Status:** Closed — fixed 2026-06-24. The Dockerfile comment now matches the
pinned 3.14-slim base (kept current by Dependabot) and notes that the Tesseract
apt packages and PyMuPDF/Pillow wheels are available for it.
**Priority:** Low — misleading comment; verify the bleeding-edge base is stable
**Source:** External code review (2026-06-24), verified against the code.

## Symptom

The Dockerfile comment ([Dockerfile:7](../../Dockerfile)) says
"`python:3.12-slim-bookworm` is the reliable choice", but `FROM` pins **3.14**-slim
([Dockerfile:12](../../Dockerfile), [:31](../../Dockerfile)). Comment and code have
drifted.

## Root cause

The base image was bumped (Dependabot digest bumps) without updating the rationale
comment.

## Impact

Misleading documentation in a security-conscious image, plus an open question:
`3.14-slim` is a recent base — confirm the Tesseract apt packages and the
PyMuPDF / Pillow wheels are stably available for it (otherwise a future rebuild can
break the air-gapped image).

## Options

1. **Update the comment to match 3.14 and state the rationale**, and confirm
   wheel/apt availability for the pinned base.
2. Pin back to 3.12-slim if 3.14 wheels/packages prove unstable.

Recommendation: **Option 1** (align the comment + verify), unless a build problem
surfaces.

## Acceptance criteria

- [ ] The Dockerfile comment matches the actual base image and explains the choice.
- [ ] Tesseract apt packages and PyMuPDF/Pillow wheels are confirmed available for
      the pinned base (note the check in the PR).
