# figmark documentation

- **[architecture.md](architecture.md)** — how the pipeline works end to end: the
  stages, the module map, the outputs, and how configuration maps to behaviour.
  Start here to understand or extend the codebase.
- **[deployment.md](deployment.md)** — the air-gapped runbook: load the image,
  configure secrets, run the docker compose stack, point it at your LLM.
- **[../SECURITY.md](../SECURITY.md)** — threat model, secret handling, and the
  Trivy/SBOM scanning policy.
- **[tickets/](tickets/)** — the design notes and bug/improvement log (`T-NNN`).
  Each ticket records the symptom, root cause, options considered, and acceptance
  criteria for a change.

For installation, usage, and configuration, see the top-level
[README](../README.md). For development setup and contribution guidelines, see
[CONTRIBUTING](../CONTRIBUTING.md).
