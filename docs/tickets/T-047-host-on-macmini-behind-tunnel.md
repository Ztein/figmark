# T-047: No hosted figmark — run it on the Mac Mini behind the ztein tunnel with an issued API token

**Status:** Open
**Priority:** Medium — turns figmark from a local CLI into a shareable service.

## Symptom

There is no always-on figmark anyone can call. Every conversion is a manual local
run (`figmark <pdf>`), or a container someone starts by hand. The HTTP service
(`figmark-server`, `POST /v1/convert`) and its bearer auth exist and are
container-ready, but nothing is deployed and reachable.

## Root cause

The compose stack has never been brought up on a host and wired to the tunnel: no
running container on the Mac Mini, no `figmark.ztein.dev` route, no issued auth
token, no chosen LLM backend for that host.

## Impact

figmark can't be handed to anyone — no URL, no key. It also can't be dogfooded
continuously (the kind of always-on use that surfaced the 14-day live-test gap).

## Context (from the ztein-infra source of truth, 2026-06-25)

- **Host:** Mac Mini `joelmacmini9`, reachable, already running **colima/docker**,
  so `compose.yaml` runs there directly.
- **Free port:** figmark's compose default **8000** does not collide with the
  existing tunneled services (assets 8789, the MCPs 8096/8808) or local services
  (ollama 11434, openclaw 18789, claude-max-proxy 3456).
- **Tunnel:** "ztein" routes `ztein.dev` subdomains via
  `cloudflared tunnel route dns ztein figmark` (cert.pem covers ztein.dev only).
  `figmark.ztein.dev` fits the DEV/TECH front.
- **Local LLM available:** ollama on `:11434` is OpenAI-compatible and on-host — a
  candidate vision endpoint (free, no external key), provided a vision-capable
  model is pulled.
- **Hard rule:** this setup must process **only public/synthetic PDFs** — never
  sensitive Riksbank material. TLS terminates at Cloudflare's edge, so genuinely
  sensitive input must stay off it regardless. This must be stated wherever the
  endpoint is documented/shared.

## Options

### A. How users authenticate
1. **App bearer token over the public tunnel (recommended for an API).** Issue a
   strong `FIGMARK_AUTH_TOKEN` (the existing Docker secret), expose
   `figmark.ztein.dev` publicly, hand the token to whoever should call it. This is
   exactly the "an API key for whoever wants to use it" model. Pair with the
   service's concurrency gate + timeouts; consider Cloudflare rate-limiting.
2. **Cloudflare Access in front.** SSO/login gate — good for a human-facing path,
   wrong for a machine API (callers can't do an interactive login). At most a
   second, admin-only hostname.
3. **Tailscale-only / private.** No public exposure; only tailnet devices reach
   it. Safest, but defeats "for whoever wants to use it."

### B. Which LLM backend the hosted instance uses
1. **Local ollama (`http://host.docker.internal:11434/v1`) with a pulled vision
   model.** Free, on-host, no external dependency or dead-key risk; fits the
   air-gap ethos. Needs a vision model and enough RAM on the Mini.
2. **External OpenAI-compatible endpoint (e.g. Berget).** Matches current
   `config.yaml`, but needs a live key (the current one returns 402) and sends
   image payloads off-host.

## Acceptance criteria

- [ ] The compose stack runs on the Mac Mini from the published image (arm64 —
  depends on [T-046](T-046-multiarch-arm64-image.md)) and survives a host reboot
  (autostart).
- [ ] `https://figmark.ztein.dev/readyz` is green through the tunnel.
- [ ] A strong auth token is issued (Docker secret, never committed) and a sample
  **public** PDF converts end-to-end via `POST /v1/convert` with `Authorization:
  Bearer <token>`.
- [ ] The chosen LLM backend (Option B) is configured and a figure is actually
  described.
- [ ] The service is registered in the ztein-infra inventory (hostname, port,
  access policy) and the public/synthetic-only constraint is documented.
