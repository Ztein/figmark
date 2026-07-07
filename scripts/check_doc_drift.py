#!/usr/bin/env python3
"""Doc-drift guard (T-077) — fail loud when hand-maintained docs fall out of sync.

Per the T-077 title-policy decision (Option B), this does **not** check that the
ticket-index ``Title`` matches the ticket file's heading — the index intentionally
annotates closed tickets with their outcome. It checks only the unambiguous
invariants:

  (a) presence   — every ``docs/tickets/T-*.md`` has an index row, and every
                   non-reserved index row has a file (reserved rows use ``—`` and
                   must have no file);
  (b) status/pri — a row's Status/Priority agrees with the ticket file's
                   ``**Status:**`` / ``**Priority:**`` (compared on the leading
                   keyword, so curated trailing notes are ignored);
  (c) numbering  — index ticket numbers are contiguous (reserved rows fill gaps);
  (d) module map — every ``src/figmark/*.py`` module appears in the
                   architecture.md "Module map" table, and vice-versa.

Run locally:  python scripts/check_doc_drift.py
Exit status:  0 = in sync, 1 = drift (each problem printed), 2 = usage error.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TICKETS_DIR = ROOT / "docs" / "tickets"
INDEX = TICKETS_DIR / "README.md"
ARCH = ROOT / "docs" / "architecture.md"
SRC = ROOT / "src" / "figmark"

_TID = re.compile(r"\bT-(\d+)\b")
_KEYWORD = re.compile(r"[A-Za-z]+")
_STATUS_LINE = re.compile(r"^\*\*Status:\*\*\s*(.+)$", re.MULTILINE)
_PRIORITY_LINE = re.compile(r"^\*\*Priority:\*\*\s*(.+)$", re.MULTILINE)
_MAP_ROW = re.compile(r"^\|\s*`([a-z_][a-z0-9_]*\.py)`\s*\|")


def _kw(text: str | None) -> str | None:
    """Leading alphabetic keyword, lowercased — or None (e.g. the ``—`` marker)."""
    if not text:
        return None
    m = _KEYWORD.search(text)
    return m.group(0).lower() if m else None


def _tid(cell: str) -> str | None:
    m = _TID.search(cell)
    return f"T-{int(m.group(1)):03d}" if m else None


def parse_index() -> dict[str, dict]:
    """Return {tid: {status, priority, reserved}} from the index table."""
    rows: dict[str, dict] = {}
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        tid = _tid(cells[0])
        if tid is None:  # header / separator / stray row
            continue
        status = _kw(cells[1])
        rows[tid] = {
            "status": status,
            "priority": _kw(cells[2]),
            "reserved": status is None,  # "—" placeholder => reserved
        }
    return rows


def parse_ticket_files() -> dict[str, dict]:
    """Return {tid: {status, priority, path}} from docs/tickets/T-*.md."""
    files: dict[str, dict] = {}
    for path in sorted(TICKETS_DIR.glob("T-*.md")):
        tid = _tid(path.name)
        if tid is None:
            continue
        text = path.read_text(encoding="utf-8")
        sm = _STATUS_LINE.search(text)
        pm = _PRIORITY_LINE.search(text)
        files[tid] = {
            "status": _kw(sm.group(1)) if sm else None,
            "priority": _kw(pm.group(1)) if pm else None,
            "path": path.name,
        }
    return files


def parse_module_map() -> set[str]:
    """Module filenames listed in architecture.md's '## Module map' table only."""
    text = ARCH.read_text(encoding="utf-8").splitlines()
    in_section = False
    mods: set[str] = set()
    for line in text:
        if line.startswith("## "):
            in_section = line.strip().lower() == "## module map"
            continue
        if in_section:
            m = _MAP_ROW.match(line)
            if m:
                mods.add(m.group(1))
    return mods


def src_modules() -> set[str]:
    return {p.name for p in SRC.glob("*.py") if p.name != "__init__.py"}


def main() -> int:
    problems: list[str] = []

    index = parse_index()
    files = parse_ticket_files()

    index_real = {t for t, r in index.items() if not r["reserved"]}
    index_reserved = {t for t, r in index.items() if r["reserved"]}
    file_tids = set(files)

    add = problems.append

    # (a) presence
    for tid in sorted(file_tids - index_real):
        add(f"(a) {tid}: ticket file has no row in the index")
    for tid in sorted(index_real - file_tids):
        add(f"(a) {tid}: index row has no matching ticket file")
    for tid in sorted(index_reserved & file_tids):
        add(f"(a) {tid}: marked reserved (—) in the index but a ticket file exists")

    # (b) status / priority agreement
    for tid in sorted(index_real & file_tids):
        irow, frow = index[tid], files[tid]
        if frow["status"] is None:
            add(f"(b) {tid}: ticket file has no parseable **Status:** line")
        elif irow["status"] != frow["status"]:
            add(f"(b) {tid}: status — index {irow['status']} != file {frow['status']}")
        if frow["priority"] is None:
            add(f"(b) {tid}: ticket file has no parseable **Priority:** line")
        elif irow["priority"] != frow["priority"]:
            add(f"(b) {tid}: priority — index {irow['priority']} != file {frow['priority']}")

    # (c) numbering — contiguous across the whole index (reserved rows fill gaps)
    nums = sorted(int(t.split("-")[1]) for t in index)
    if nums:
        missing = sorted(set(range(nums[0], nums[-1] + 1)) - set(nums))
        for n in missing:
            add(f"(c) T-{n:03d}: gap in index numbering — add or reserve it")

    # (d) module map completeness (both directions)
    mapped = parse_module_map()
    actual = src_modules()
    for mod in sorted(actual - mapped):
        add(f"(d) {mod}: src/figmark module missing from the module map")
    for mod in sorted(mapped - actual):
        add(f"(d) {mod}: module map lists a module that no longer exists")

    if problems:
        print(f"doc-drift guard: {len(problems)} problem(s) found\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("\nSee docs/tickets/T-077-doc-drift-guard.md for the policy.", file=sys.stderr)
        return 1

    print("doc-drift guard: OK — index, ticket files, and module map are in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
