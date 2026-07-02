"""T-046: the release workflow must publish a multi-arch (amd64 + arm64) image.

Structural assertions against .github/workflows/release.yml (offline, no Docker):
the ticket's root cause was a plain `docker build` on an amd64 runner, so these
pin the buildx/QEMU setup, the platform list, the gate ordering, and the
per-arch tarballs in the air-gap bundle — so a refactor can't silently regress
to a single-arch push.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

SHA_PIN = re.compile(r"@[0-9a-f]{40}\b")


def _image_bundle_steps() -> list[dict]:
    data = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    return data["jobs"]["image-bundle"]["steps"]


def _step_index(steps: list[dict], needle: str) -> int:
    for i, step in enumerate(steps):
        if needle.lower() in (step.get("name") or step.get("uses") or "").lower():
            return i
    raise AssertionError(f"no step matching {needle!r} in image-bundle")


def test_qemu_and_buildx_are_set_up_and_sha_pinned():
    steps = _image_bundle_steps()
    uses = [s["uses"] for s in steps if "uses" in s]
    for action in ("docker/setup-qemu-action", "docker/setup-buildx-action"):
        pinned = [u for u in uses if u.startswith(f"{action}@")]
        assert pinned, f"{action} missing from image-bundle"
        assert SHA_PIN.search(pinned[0]), f"{action} must be SHA-pinned (T-015): {pinned[0]}"


def test_publish_pushes_a_multiarch_manifest():
    steps = _image_bundle_steps()
    publish = steps[_step_index(steps, "Publish")]
    run = publish["run"]
    assert "buildx build" in run
    assert "--platform linux/amd64,linux/arm64" in run
    assert "--push" in run
    # Sign/attest by immutable manifest digest, not by mutable tag (T-016).
    assert "containerimage.digest" in run


def test_trivy_gate_still_runs_before_publish():
    steps = _image_bundle_steps()
    trivy = steps[_step_index(steps, "Trivy image gate")]
    assert trivy["with"]["exit-code"] == "1", "Trivy must stay a blocking gate (T-013)"
    assert _step_index(steps, "Trivy image gate") < _step_index(steps, "Publish"), (
        "the Trivy gate must pass before anything is pushed to GHCR"
    )


def test_pushed_manifest_is_verified_to_list_both_architectures():
    steps = _image_bundle_steps()
    verify = steps[_step_index(steps, "Verify")]
    run = verify["run"]
    assert "imagetools inspect" in run
    assert "linux/amd64" in run and "linux/arm64" in run


def test_bundle_ships_a_tarball_per_architecture():
    steps = _image_bundle_steps()
    export = steps[_step_index(steps, "Export")]
    run = export["run"]
    assert "figmark-${VERSION}.tar.gz" in run, "amd64 tarball keeps its existing name"
    assert "figmark-${VERSION}-arm64.tar.gz" in run, "arm64 hosts need their own tarball"
    assert "--platform linux/arm64" in run
