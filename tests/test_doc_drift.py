"""The doc-drift guard (T-077) runs in the offline suite and actually catches drift.

Two assertions: the repo is currently in sync, and — crucially — the guard is not
a no-op (inject a fake module and it must fail). The second test is what keeps a
future refactor from silently neutering the check.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_doc_drift.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_doc_drift", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_docs_are_in_sync():
    assert _load().main() == 0, (
        "doc-drift guard reported drift; run python scripts/check_doc_drift.py"
    )


def test_guard_detects_injected_drift(monkeypatch):
    mod = _load()
    real = mod.src_modules()
    monkeypatch.setattr(mod, "src_modules", lambda: real | {"definitely_not_a_real_module.py"})
    assert mod.main() == 1, "guard did not flag an injected phantom module — it is a no-op"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
