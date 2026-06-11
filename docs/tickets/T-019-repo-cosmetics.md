# T-019: Disable unused repo tabs (Wiki, Projects)

**Status:** Closed — done 2026-06-11
**Priority:** Low — cosmetic; a tidy repo signals maintenance

## Symptom

The repository shows Wiki and Projects tabs that are enabled but empty. Empty
tabs read as neglect; all documentation lives in `docs/` and the README.

## What to do

`gh repo edit Ztein/figmark --enable-wiki=false --enable-projects=false`

## Acceptance criteria

- [x] Wiki and Projects tabs no longer appear on the repository page
