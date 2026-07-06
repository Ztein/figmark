# Cache production-readiness scorecard

- **Commit:** `7f701f4`
- **Date:** 2026-07-06
- **Machine:** macOS-26.5.1-arm64-arm-64bit-Mach-O (arm64)
- **Python:** 3.14.3

Compare only against runs from the same machine.
Regenerate with: `.venv/bin/python scripts/cache_bench/bench.py --write <file>`

| # | Ticket | Metric | Result |
|---|--------|--------|--------|
| B1a | T-074 | get hit, 200 kB document payload (median / p95, ms) | 1.67 / 5.86 |
| B1b | T-074 | put, small description (median / p95, ms) | 3.43 / 7.09 |
| B1c | T-074 | get miss (median / p95, ms) | 4.14 / 6.87 |
| B2 | T-074 | 8 threads × 50 gets (median / p95 / max, ms; errors) | 3.28 / 11.08 / 67.8; 0 errors |
| B3 | T-074 | event-loop heartbeat max gap: idle / during 32 MB put+get (ms) | 6 / 132 |
| S1 | T-073 | 4 concurrent uploads of one document → full conversions run (target 1) | 4 (statuses [200, 200, 200, 200]) |
| S2 | T-073 | sequential re-upload afterwards is a cache hit (sanity) | PASS |
| R1 | T-072 | corrupt cache.sqlite3 at startup → service still boots | FAIL (DatabaseError) |
| R2 | T-072 | get against corrupted store → returns miss, no raise | FAIL (DatabaseError would 500 the request) |
| R3 | T-072 | put against corrupted store → dropped loudly, no raise | FAIL (DatabaseError would 500 a PAID conversion) |
| Q1 | T-075 | token-cap-truncated description stored in the SHARED cache | FAIL (stored as if complete) |
| E1 | T-076 | divergent-schema database → recreated loudly, then works | FAIL (OperationalError) |
| E2 | T-076 | cache dir 0700 and database owner-only | FAIL (dir 755, db 644) |
| E3 | T-076 | on-disk MB at 5 MB cap: after churn (logical) / after clear | 9.6 (5.2) / 9.6 |
