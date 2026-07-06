# T-076: The cache's operational envelope is unenforced — no schema version, disk use beyond the configured cap, world-readable directory, undocumented scaling assumptions

**Status:** Closed — **Option 1 shipped 2026-07-06** (`PRAGMA user_version`
schema gate with loud drop-and-recreate, `0700`/`0600` permissions with a
tighten-and-warn pass, `auto_vacuum=INCREMENTAL` + vacuum on eviction and
vacuum+WAL-truncate on clear/delete, `disk_bytes` in `/v1/cache/stats`, and a
"deployment assumptions" section in the deployment docs; scorecard rows E1/E2
PASS, E3 after-clear 9.6 → 0.1 MB).
**Priority:** Medium — none of these bites in a demo; all of them bite in a
professional deployment, and two (schema, permissions) get more expensive to
retrofit with every release that ships without them.

## Symptom

Four related gaps, all "the cache works until the deployment around it moves":

1. **No schema version.** `CacheStore.__init__` runs `CREATE TABLE IF NOT
   EXISTS` and nothing else. The first release that adds or renames a column
   will crash at *runtime* (`OperationalError` on the first SELECT) against any
   pre-existing `cache.sqlite3` on a persistent volume — precisely the setup
   the docs recommend.
   *Update 2026-07-06:* T-072's quarantine-and-rebuild largely covers this at
   *open* time — scorecard row E1 now PASSes, because the startup reconcile
   query touches the `entries` columns and a mismatch is treated as corruption
   (the old file is set aside as `.corrupt-<ts>`). What remains of this item:
   a mismatch that only surfaces *after* open (e.g. an extra column, or a
   changed column used by a later query) is not caught, and a merely-old
   schema being labelled "corrupt" is misleading in the quarantine filename
   and log. An explicit `schema_version` check stays the honest fix, but it is
   now a refinement, not a crash fix.
2. **Disk footprint exceeds `max_size_mb`.** The cap counts payload bytes
   only. The SQLite file is a high-water mark that never shrinks after
   eviction or `/v1/cache` clear (no vacuum), and the WAL adds more. An
   operator who sizes a 600 MB volume for a 500 MB cache can still fill the
   disk — and a full cache volume today also fails conversions (T-072).
3. **Cache directory created with default umask.** The store holds every
   converted document's full text and figure descriptions in cleartext; the
   directory should be `0700` and the docs should say plainly that the cache
   directory is as sensitive as the documents themselves — including that the
   live SQLite file must not be file-copied for backup (SQLite backup API or
   exclude it; it is a cache).
4. **Single-writer-host assumption undocumented.** WAL supports multiple
   *local* processes but corrupts over network filesystems (NFS/SMB), and the
   server currently runs one uvicorn process. Nothing warns the operator who
   points two replicas at one shared volume.

## Measurement

Rows E1–E3 of the cache scorecard: run
`scripts/cache_bench/bench.py` and diff against the committed baseline
(`scripts/cache_bench/BASELINE.md`, same machine). The ticket is done when its
rows flip to their targets with no regression in the others.

## Root cause

The cache was built (T-060…T-064) for functional correctness on the happy
deployment; the operational envelope — upgrades, disk accounting, permissions,
topology limits — was never specified, so nothing enforces or documents it.

## Impact

- A routine figmark upgrade can hard-break a long-lived instance (1).
- Volume sizing done from `max_size_mb` is wrong by an unbounded margin (2).
- Document content is readable by any local user on a shared host (3).
- A plausible-looking scale-out (shared volume, two replicas / NFS) corrupts
  the store with no prior warning (4).

## Options

1. **Enforce what's cheap, document the rest.**
   - Schema: a `schema_version` pragma/row checked at open; on mismatch, the
     cache is disposable — drop and recreate loudly (no migration machinery).
   - Disk: `PRAGMA auto_vacuum=INCREMENTAL` + an incremental vacuum after
     eviction/clear, or (simpler) document a sizing rule of thumb
     (file ≈ high-water mark + WAL; provision ~1.5× `max_size_mb`) and reuse
     T-064's stats to expose the real file size.
   - Permissions: create the directory and database `0700`/`0600`.
   - Topology: a short "deployment assumptions" section in the server docs —
     one host, local disk, no network filesystems, backup by exclusion.
2. **Full migration framework + strict disk enforcement** (versioned
   migrations, hard cap on file size with vacuum-on-threshold). Over-built for
   a disposable cache of derived data; contradicts the lean constraint.
3. **Docs only.** Zero code risk, but leaves the runtime crash (1) and the
   permissions default (3) in place — those two are code bugs, not
   documentation gaps.

Option 1: items (1) and (3) are small code changes with tests; (2) is a stats
field plus a documented rule; (4) is documentation.

## Acceptance criteria

- [x] Opening a cache database written by a different (older/newer) schema
      version recreates it loudly instead of crashing at first use — covered by
      a test that plants a divergent-schema file.
- [x] Cache directory and database file are created owner-only (`0700`/`0600`).
- [x] `/v1/cache/stats` (or the docs) makes the *actual* on-disk footprint
      visible/predictable; the sizing guidance is written down.
- [x] Server/deployment docs state the topology envelope (single host, local
      volume, no NFS/SMB, one writer service) and the backup guidance — in
      generic terms, per the public-repo litmus test.
