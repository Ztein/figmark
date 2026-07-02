# T-062: Cache management shares the conversion bearer token — no privilege separation, no per-consumer partitioning

**Status:** Open
**Priority:** Low — figmark's auth model is single-tenant (one token = one trust
domain), and within that model nothing here is exploitable. The weakness only
materialises when one instance is shared by consumers that should not affect or
observe each other.

## Symptom

Two related consequences of the single-token model, found in the T-060/T-061
security review (2026-07-02, see SECURITY.md "The cross-request cache"):

1. **No privilege separation.** The same bearer token that converts documents
   can also `DELETE /v1/cache` (full wipe) and `DELETE /v1/cache/{sha256}`.
   A compromised or misbehaving consumer can repeatedly wipe the cache — a
   bounded cost/latency degradation (every conversion becomes a cold run), not
   data loss.
2. **No per-consumer partitioning.** All consumers share one cache, so any
   token holder can probe whether a specific document *they already possess*
   was processed before (`X-Figmark-Cache` header, `cached` field, latency).
   An existence oracle across consumers — harmless single-tenant, information
   leakage when consumers are mutually untrusted.

## Root cause

Deliberate scope: figmark authenticates *a deployment*, not *users*. The cache
inherited that model.

## Impact

Only multi-consumer deployments (e.g. one figmark instance backing several
independent products/teams). Single-tenant deployments — the documented model —
are unaffected.

## Options

1. **Document only (status quo+).** SECURITY.md already states the model and
   says "partition per consumer". Zero code; relies on operators reading it.
2. **Optional admin token** (`FIGMARK_CACHE_ADMIN_TOKEN`): when set, the cache
   management endpoints require it instead of the conversion token. Small,
   backwards-compatible; removes the wipe vector but not the oracle.
3. **Per-token cache namespaces**: partition entries by a hash of the caller's
   token, killing both the oracle and cross-consumer wipes — but also killing
   cross-consumer cache sharing (often the point of a shared instance) and
   complicating the single-tenant common case. Only worth it with a real
   multi-consumer deployment demanding it.

Recommendation: Option 2 when a shared deployment first appears; revisit 3 only
on concrete demand.

## Acceptance criteria

- [ ] A decision recorded for the multi-consumer story (admin token and/or
      partitioning), implemented behind config that leaves the single-tenant
      default unchanged.
- [ ] SECURITY.md updated to match whatever ships.
