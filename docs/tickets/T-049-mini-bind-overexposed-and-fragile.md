# T-049: Mini deploy binds `0.0.0.0` via an uncommitted edit to the canonical `compose.yaml` — over-exposed on the LAN and silently revertible

**Status:** Closed — implemented 2026-06-26 (Option 2, `tailscale serve`). The
Mini's `compose.yaml` is back to the canonical loopback bind (`git status` clean);
the build-from-source override now lives in a **committed** `compose.deploy.yaml`
(no ports change); figmark is published tailnet-only over HTTPS via
`tailscale serve --bg --https=8443 http://localhost:8000`. Verified from the
MacBook: `https://joelmacmini9s-mac-mini.tailee9420.ts.net:8443/readyz` ok + full
`paper.pdf`→Markdown (200); both the raw Tailscale-IP `:8000` and the LAN-IP
`192.168.68.55:8000` now refuse. ztein-infra inventory updated to the MagicDNS
endpoint.
**Priority:** Medium — the "Tailscale-internal" figmark is actually LAN-reachable, and one `git` operation can take it offline.

## Symptom

On the Mac Mini clone (`~/sites/figmark`), `git status` is permanently dirty:

```
$ ssh joelmacmini9@100.78.120.47 'cd ~/sites/figmark && git diff'
-      - "127.0.0.1:8000:8000"
+      - "0.0.0.0:8000:8000"
```

The host then listens on **all** interfaces, not just the tailnet:

```
$ ssh joelmacmini9@100.78.120.47 'lsof -nP -iTCP:8000 -sTCP:LISTEN'
ssh   85316 joelmacmini9  12u  IPv4 ...  TCP *:8000 (LISTEN)
$ ssh joelmacmini9@100.78.120.47 'ipconfig getifaddr en0'
192.168.68.55
```

So figmark answers at `http://192.168.68.55:8000` from anyone on the home LAN —
not only at `http://100.78.120.47:8000` over Tailscale, which is what the
ztein-infra inventory claims ("Tailscale-internal ONLY"). The transport is also
plain HTTP on a hardcoded IP. (The app bearer token still gates every request, so
this is over-exposure, not an open door.)

The Mini-specific override `compose.deploy.yaml` exists but is **untracked**, so
the whole single-host deploy recipe is uncommitted.

## Root cause

Two things, both about *where* the host-specific bind lives:

1. The bind override was applied by editing the **canonical, committed**
   `compose.yaml` — whose `127.0.0.1` default is correct for the generic
   GHCR/air-gapped deploy (T-017). A host-specific change doesn't belong there:
   any `git checkout` / `git pull` / `git reset` on the Mini silently reverts it.

2. `0.0.0.0` is used because, under **colima**, the host-IP in a compose `ports`
   entry refers to the **guest VM's** interfaces — which don't include the Mac's
   tailnet IP. colima then forwards the published guest port to the host on all
   interfaces (hence `*:8000`). So you cannot scope the bind to the tailnet from
   compose alone; `0.0.0.0` is the only value that makes it reachable at all, and
   it necessarily also exposes the LAN.

Related: T-047 (host figmark on the Mini) — that deploy diverged from its
public-tunnel plan to this Tailscale-internal one; this ticket hardens the
networking of what was actually shipped.

## Impact

- **Fragility:** a routine git operation on the Mini clone reverts the bind to
  loopback → figmark becomes unreachable over the tailnet with no code change and
  no obvious cause.
- **Over-exposure:** figmark is reachable from every device on the home LAN, not
  just tailnet members — broader than documented and than intended.
- **No TLS, opaque address:** clients use `http://<ip>:8000`; no transport
  encryption, and the IP is baked into the registry and any caller config.

## Options

### 1. Config hygiene only — move the bind into a committed override

Revert `compose.yaml` to the canonical `127.0.0.1:8000:8000`; put the host bind in
`compose.deploy.yaml` and **commit** it. Compose merges `ports` by *appending*, so
a bare add would try to bind `:8000` twice — use the override tag to replace:

```yaml
services:
  app:
    ports: !override
      - "0.0.0.0:8000:8000"
```

✅ Fixes the dirty-file fragility and puts the host concern in the host file.
❌ Still binds all interfaces → still LAN-exposed; still plain HTTP.

### 2. `tailscale serve` — expose tailnet-only over HTTPS (DECIDED — Joel, 2026-06-26)

Keep the container on the canonical loopback bind (`127.0.0.1:8000:8000`, so
colima forwards only to host `localhost:8000`) and publish it on the tailnet with
Tailscale's own proxy:

```
tailscale serve --bg --https=8443 http://localhost:8000
```

- Reachable **only on the tailnet** (not the LAN) — directly matches
  "Tailscale-internal ONLY".
- **HTTPS** via a Tailscale-issued cert + a stable MagicDNS name
  (`https://joelmacmini9s-mac-mini.<tailnet>.ts.net:8443`) instead of a raw IP.
- **Tailnet ACLs** become an enforceable second layer on top of the app bearer
  token (defense in depth).
- Already the **established pattern on this host** — openclaw is exposed the same
  way (`tailscale serve` → `http://localhost:18789`). Use a distinct HTTPS port
  (e.g. `8443`) so it doesn't clash with that existing `/` mapping.
- `compose.deploy.yaml` still gets committed (build-from-source override), but with
  **no** ports change — the canonical loopback bind is used as-is.

### 3. Bind the tailnet IP directly in compose — rejected

`100.78.120.47:8000:8000` cannot work under colima (the compose host-IP is a guest
interface; the VM has no tailnet IP). Listed only to record why it's not viable.

## Acceptance criteria

- [x] `~/sites/figmark` on the Mini has a **clean** `git status` (no edit to the
  committed `compose.yaml`).
- [x] `compose.deploy.yaml` is committed to the repo; a fresh checkout +
  documented deploy steps reproduce the running service with no manual file edits.
- [x] figmark is reachable over the tailnet via the `tailscale serve` HTTPS
  endpoint, and a sample **public** PDF converts end-to-end (`POST /v1/convert`,
  `Authorization: Bearer <token>`).
- [x] figmark is **not** reachable on the LAN IP (`curl http://192.168.68.55:8000`
  fails) nor on the raw Tailscale IP `:8000`.
- [x] `LOCAL_DEPLOY.md` documents the loopback-bind + `tailscale serve` model (and
  the colima reason it must be this way).
- [x] The ztein-infra inventory is updated: the figmark URL becomes the MagicDNS
  HTTPS endpoint, and "Tailscale-internal ONLY" is then literally true.
