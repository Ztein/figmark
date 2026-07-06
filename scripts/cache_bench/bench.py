"""Cache production-readiness scorecard (T-072..T-076).

One reproducible measurement covering every cache ticket, so the same run can
be made BEFORE the changes (the committed baseline) and AFTER, on the same
machine, and diffed row by row:

- T-074  latency numbers: per-op cost, tail under concurrent readers, and how
         long a large ``put`` freezes the asyncio event loop.
- T-073  stampede count: N concurrent uploads of one document → how many full
         conversions actually run (target: 1).
- T-072  robustness probes: does a corrupt cache database fail boot / reads /
         writes (target: degrade loudly, never raise into the request)?
- T-075  quality probe: does a token-cap-truncated description end up in the
         shared cross-request cache (target: not silently)?
- T-076  envelope probes: divergent schema handling, directory/file
         permissions, on-disk high-water mark after churn + clear.

Usage (from the repo root, offline — a fake vision client, no network):

    .venv/bin/python scripts/cache_bench/bench.py
    .venv/bin/python scripts/cache_bench/bench.py --write BASELINE.md

Numbers are machine-dependent: only compare runs from the same machine. The
report records platform + commit so a stale baseline is self-evident.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import platform
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # for tests.fakes (the offline test doubles)
os.environ.setdefault("FIGMARK_API_KEY", "bench-key")

from figmark.cache import CacheStore  # noqa: E402

DOC_PAYLOAD = b"x" * 200_000  # a typical small document result
BIG_PAYLOAD = b"y" * 32_000_000  # a large result, for the event-loop stall probe
DESC_PAYLOAD = b"d" * 500  # a figure description
DIGEST_A = "a" * 64

rows: list[tuple[str, str, str, str]] = []  # (id, ticket, metric, value)


def row(rid: str, ticket: str, metric: str, value: str) -> None:
    rows.append((rid, ticket, metric, value))
    print(f"  {rid:<4} {metric:<62} {value}")


def _fresh_store(tmp: Path, name: str, max_mb: int = 512) -> CacheStore:
    return CacheStore(tmp / name, max_bytes=max_mb * 1024 * 1024, max_age_hours=24)


def _timeit(fn, n: int) -> tuple[float, float]:
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return statistics.median(times), times[int(len(times) * 0.95)]


# ---------------------------------------------------------------- T-074: speed
def bench_latency(tmp: Path) -> None:
    store = _fresh_store(tmp, "latency")
    store.put("doc-1", DOC_PAYLOAD, doc_digest=DIGEST_A, kind="document")
    for i in range(500):
        store.put(f"desc-{i}", DESC_PAYLOAD, doc_digest=DIGEST_A, kind="description")

    med, p95 = _timeit(lambda: store.get("doc-1"), 300)
    row("B1a", "T-074", "get hit, 200 kB document payload (median / p95, ms)", f"{med:.2f} / {p95:.2f}")
    i = [0]

    def putter():
        store.put(f"p-{i[0]}", DESC_PAYLOAD, doc_digest=DIGEST_A, kind="description")
        i[0] += 1

    med, p95 = _timeit(putter, 200)
    row("B1b", "T-074", "put, small description (median / p95, ms)", f"{med:.2f} / {p95:.2f}")
    med, p95 = _timeit(lambda: store.get("absent", kind="description"), 300)
    row("B1c", "T-074", "get miss (median / p95, ms)", f"{med:.2f} / {p95:.2f}")


def bench_concurrency(tmp: Path) -> None:
    store = _fresh_store(tmp, "concurrency")
    for i in range(50):
        store.put(f"desc-{i}", DESC_PAYLOAD, doc_digest=DIGEST_A, kind="description")
    times: list[float] = []
    errors: list[str] = []
    lock = threading.Lock()

    def worker(tid: int) -> None:
        for i in range(50):
            t0 = time.perf_counter()
            try:
                store.get(f"desc-{(tid * 7 + i) % 50}", kind="description")
            except Exception as e:  # noqa: BLE001 — the count IS the measurement
                with lock:
                    errors.append(repr(e))
            with lock:
                times.append((time.perf_counter() - t0) * 1000)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    times.sort()
    row(
        "B2",
        "T-074",
        "8 threads × 50 gets (median / p95 / max, ms; errors)",
        f"{times[len(times) // 2]:.2f} / {times[int(len(times) * 0.95)]:.2f}"
        f" / {times[-1]:.1f}; {len(errors)} errors",
    )


def bench_loop_stall(tmp: Path) -> None:
    """Max gap in a 5 ms asyncio heartbeat while cache ops run ON the loop —
    the exact pattern of today's convert_endpoint."""
    store = _fresh_store(tmp, "stall", max_mb=512)

    async def measure() -> tuple[float, float]:
        gaps: list[float] = []
        stop = asyncio.Event()

        async def ticker() -> None:
            last = time.perf_counter()
            while not stop.is_set():
                await asyncio.sleep(0.005)
                now = time.perf_counter()
                gaps.append((now - last) * 1000)
                last = now

        task = asyncio.create_task(ticker())
        await asyncio.sleep(0.05)
        baseline_gap = max(gaps) if gaps else 0.0
        gaps.clear()
        store.put("big", BIG_PAYLOAD, doc_digest=DIGEST_A, kind="document")  # as the endpoint does
        store.get("big")
        await asyncio.sleep(0.05)
        stop.set()
        await task
        return baseline_gap, max(gaps)

    idle_gap, op_gap = asyncio.run(measure())
    row(
        "B3",
        "T-074",
        "event-loop heartbeat max gap: idle / during 32 MB put+get (ms)",
        f"{idle_gap:.0f} / {op_gap:.0f}",
    )


# ------------------------------------------------------------ T-073: stampede
def _make_app(client, tmp: Path):
    from figmark.api import ServerSettings, create_app
    from figmark.config import load_config

    cfg = load_config(ROOT / "config.example.yaml")
    if not cfg.cache.enabled:
        cfg = dataclasses.replace(
            cfg, cache=dataclasses.replace(cfg.cache, enabled=True, max_size_mb=256, max_age_hours=24)
        )
    settings = ServerSettings(
        auth_token="bench",
        config_path=ROOT / "config.example.yaml",
        max_upload_bytes=50 * 1024 * 1024,
        work_dir=tmp / "work",
        request_timeout_seconds=120.0,
        max_concurrent_jobs=8,
        cache_dir=tmp / "http-cache",
    )
    return create_app(settings=settings, cfg=cfg, client=client)


class _CountingClient:
    """Offline OpenAI-shaped client: counts describe calls (thread-safe), can
    delay them (to guarantee request overlap) and fake a token-cap truncation."""

    def __init__(self, *, describe_delay: float = 0.0, finish_reason: str = "stop"):
        from tests.fakes import make_response

        self._make_response = make_response
        self.describe_delay = describe_delay
        self.finish_reason = finish_reason
        self.describe_calls = 0
        self.language_calls = 0
        self._lock = threading.Lock()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, max_tokens, messages, **kwargs):
        content = messages[0]["content"]
        if isinstance(content, str):
            if "Identify the language" in content:
                with self._lock:
                    self.language_calls += 1
                return self._make_response("Swedish")
            return self._make_response("A bench document.")
        with self._lock:
            self.describe_calls += 1
        if self.describe_delay:
            time.sleep(self.describe_delay)
        return self._make_response("A bar chart of quarterly revenue.", finish_reason=self.finish_reason)


def _serve(app):
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("bench app did not start")
    return server, thread, f"http://127.0.0.1:{port}"


def bench_stampede(tmp: Path) -> None:
    import httpx

    from tests.fakes import synthetic_pdf

    pdf = synthetic_pdf(tmp / "doc.pdf").read_bytes()
    client = _CountingClient(describe_delay=1.0)  # long enough that all N overlap
    server, thread, base = _serve(_make_app(client, tmp / "stampede"))
    try:
        headers = {"Authorization": "Bearer bench"}
        results: list[tuple[int, str]] = []
        lock = threading.Lock()

        def upload() -> None:
            r = httpx.post(
                f"{base}/v1/convert",
                files={"file": ("doc.pdf", pdf, "application/pdf")},
                headers=headers,
                timeout=120,
            )
            with lock:
                results.append((r.status_code, r.headers.get("x-figmark-cache", "?")))

        n = 4
        threads = [threading.Thread(target=upload) for _ in range(n)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        statuses = sorted(s for s, _ in results)
        concurrent_conversions = client.describe_calls  # 1 figure per conversion
        r2 = httpx.post(
            f"{base}/v1/convert",
            files={"file": ("doc.pdf", pdf, "application/pdf")},
            headers=headers,
            timeout=120,
        )
        row(
            "S1",
            "T-073",
            f"{n} concurrent uploads of one document → full conversions run (target 1)",
            f"{concurrent_conversions} (statuses {statuses})",
        )
        row(
            "S2",
            "T-073",
            "sequential re-upload afterwards is a cache hit (sanity)",
            "PASS" if r2.headers.get("x-figmark-cache") == "hit" else "FAIL",
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------- T-072: robustness
def _corrupt(db: Path) -> None:
    db.write_bytes(b"this is not a sqlite database " * 64)
    for suffix in ("-wal", "-shm"):
        side = db.with_name(db.name + suffix)
        if side.exists():
            side.unlink()


def probe_corruption(tmp: Path) -> None:
    # Boot: a corrupt database file at CacheStore construction time.
    d = tmp / "corrupt-boot"
    _fresh_store(tmp, "corrupt-boot").put("k", DESC_PAYLOAD, doc_digest=DIGEST_A, kind="description")
    _corrupt(d / "cache.sqlite3")
    try:
        _fresh_store(tmp, "corrupt-boot")
        row("R1", "T-072", "corrupt cache.sqlite3 at startup → service still boots", "PASS")
    except Exception as e:  # noqa: BLE001
        row("R1", "T-072", "corrupt cache.sqlite3 at startup → service still boots", f"FAIL ({type(e).__name__})")

    # Request path: corruption appearing under a running store.
    d = tmp / "corrupt-run"
    store = _fresh_store(tmp, "corrupt-run")
    store.put("k", DESC_PAYLOAD, doc_digest=DIGEST_A, kind="description")
    _corrupt(d / "cache.sqlite3")
    try:
        store.get("k")
        row("R2", "T-072", "get against corrupted store → returns miss, no raise", "PASS")
    except Exception as e:  # noqa: BLE001
        row("R2", "T-072", "get against corrupted store → returns miss, no raise", f"FAIL ({type(e).__name__} would 500 the request)")
    try:
        store.put("k2", DESC_PAYLOAD, doc_digest=DIGEST_A, kind="description")
        row("R3", "T-072", "put against corrupted store → dropped loudly, no raise", "PASS")
    except Exception as e:  # noqa: BLE001
        row("R3", "T-072", "put against corrupted store → dropped loudly, no raise", f"FAIL ({type(e).__name__} would 500 a PAID conversion)")


# ------------------------------------------------- T-075: truncated sharing
def probe_truncated_share(tmp: Path) -> None:
    import httpx

    from tests.fakes import synthetic_pdf

    pdf = synthetic_pdf(tmp / "trunc.pdf").read_bytes()
    cache_dir = tmp / "trunc-app" / "http-cache"
    client = _CountingClient(finish_reason="length")  # every description "hits the token cap"
    server, thread, base = _serve(_make_app(client, tmp / "trunc-app"))
    try:
        r = httpx.post(
            f"{base}/v1/convert",
            files={"file": ("trunc.pdf", pdf, "application/pdf")},
            headers={"Authorization": "Bearer bench"},
            timeout=120,
        )
        assert r.status_code == 200, r.text
        conn = sqlite3.connect(cache_dir / "cache.sqlite3")
        shared = conn.execute("SELECT COUNT(*) FROM entries WHERE kind = 'description'").fetchone()[0]
        conn.close()
        row(
            "Q1",
            "T-075",
            "token-cap-truncated description stored in the SHARED cache",
            "FAIL (stored as if complete)" if shared else "PASS (not shared silently)",
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# --------------------------------------------------------- T-076: envelope
def probe_envelope(tmp: Path) -> None:
    # Schema divergence: a pre-existing database whose entries table differs.
    d = tmp / "schema"
    d.mkdir(parents=True)
    conn = sqlite3.connect(d / "cache.sqlite3")
    conn.execute("CREATE TABLE entries (key TEXT PRIMARY KEY, payload BLOB)")  # an "old" schema
    conn.commit()
    conn.close()
    try:
        store = CacheStore(d, max_bytes=1024 * 1024, max_age_hours=1)
        store.put("k", DESC_PAYLOAD, doc_digest=DIGEST_A, kind="description")
        row("E1", "T-076", "divergent-schema database → recreated loudly, then works", "PASS")
    except Exception as e:  # noqa: BLE001
        row("E1", "T-076", "divergent-schema database → recreated loudly, then works", f"FAIL ({type(e).__name__})")

    # Permissions: cleartext document content ⇒ owner-only.
    d = tmp / "perms"
    store = _fresh_store(tmp, "perms")
    store.put("k", DESC_PAYLOAD, doc_digest=DIGEST_A, kind="description")
    dir_mode = d.stat().st_mode & 0o777
    db_mode = (d / "cache.sqlite3").stat().st_mode & 0o777
    ok = dir_mode == 0o700 and db_mode & 0o077 == 0
    row(
        "E2",
        "T-076",
        "cache dir 0700 and database owner-only",
        f"{'PASS' if ok else 'FAIL'} (dir {dir_mode:o}, db {db_mode:o})",
    )

    # Disk footprint: high-water mark after churn, and after clear().
    d = tmp / "footprint"
    store = CacheStore(d, max_bytes=5 * 1024 * 1024, max_age_hours=24)
    blob = b"z" * 100_000
    for i in range(120):  # ~12 MB through a 5 MB cap → heavy eviction churn
        store.put(f"k-{i}", blob, doc_digest=DIGEST_A, kind="document")

    def _disk() -> int:
        return sum(f.stat().st_size for f in d.glob("cache.sqlite3*"))

    after_churn = _disk() / 1e6
    logical = store.stats()["total_bytes"] / 1e6
    store.clear()
    after_clear = _disk() / 1e6
    row(
        "E3",
        "T-076",
        "on-disk MB at 5 MB cap: after churn (logical) / after clear",
        f"{after_churn:.1f} ({logical:.1f}) / {after_clear:.1f}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", metavar="FILE", help="also write the report as markdown (relative to this dir)")
    args = parser.parse_args()

    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    print(f"cache bench @ {sha} on {platform.platform()}\n")

    tmp = Path(tempfile.mkdtemp(prefix="figmark-cache-bench-"))
    try:
        bench_latency(tmp)
        bench_concurrency(tmp)
        bench_loop_stall(tmp)
        bench_stampede(tmp)
        probe_corruption(tmp)
        probe_truncated_share(tmp)
        probe_envelope(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if args.write:
        out = Path(__file__).parent / args.write
        lines = [
            "# Cache production-readiness scorecard",
            "",
            f"- **Commit:** `{sha}`",
            f"- **Date:** {time.strftime('%Y-%m-%d')}",
            f"- **Machine:** {platform.platform()} ({platform.machine()})",
            f"- **Python:** {platform.python_version()}",
            "",
            "Compare only against runs from the same machine.",
            "Regenerate with: `.venv/bin/python scripts/cache_bench/bench.py --write <file>`",
            "",
            "| # | Ticket | Metric | Result |",
            "|---|--------|--------|--------|",
        ]
        lines += [f"| {r} | {t} | {m} | {v} |" for r, t, m, v in rows]
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nreport written to {out}")


if __name__ == "__main__":
    main()
