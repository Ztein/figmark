"""Parallel execution of description jobs with a rich live CLI.

The pipeline gathers every image and diagram that needs describing into a list of
Job. Cache hits are resolved BEFORE this point (by main.run), so the only thing
reaching here is actual API calls. run_jobs schedules them on a ThreadPoolExecutor
and shows a live-updating rich view with:

- Overall progress (percent, done/total)
- Elapsed time (timer from the start)
- Estimated time remaining
- A list of in-flight calls with individual timers
- A list of recently finished calls with their runtime
- A final summary with average times
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from rich.console import Console, Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

# On error — try to cancel the other scheduled workers. In-flight ones finish.
# We don't believe in the "collect all errors and continue" pattern; first error = stop.
FAIL_FAST = True


@dataclass
class Job:
    """A description job: a function returning text + where to store the result."""

    label: str  # e.g. "page 11 diagram 2"
    func: Callable[[], str]  # takes no args, returns a description
    on_done: Callable[[str], None]  # callback that stores the result in page_data


def _format_duration(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _run_jobs_quiet(jobs: list[Job], max_workers: int) -> None:
    """Run the jobs with no console output — used under the server (no TTY).

    Same FAIL_FAST semantics as the live path: the first job to raise cancels the
    rest and re-raises loudly.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(j.func): j for j in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                result = future.result()
            except Exception as e:
                if FAIL_FAST:
                    for f in futures:
                        if not f.done():
                            f.cancel()
                raise RuntimeError(
                    f"Error while describing '{job.label}': {type(e).__name__}: {e}"
                ) from e
            job.on_done(result)


def run_jobs(
    jobs: list[Job],
    max_workers: int,
    header: str,
    console: Console | None = None,
    quiet: bool = False,
) -> None:
    """Run a list of jobs in parallel.

    With ``quiet`` (e.g. under the API server, where there is no TTY) the rich live
    view is skipped. Fails loudly if any job raises an exception (FAIL_FAST=True).
    """
    if not jobs:
        return

    if quiet:
        _run_jobs_quiet(jobs, max_workers)
        return

    console = console or Console()

    progress = Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30),
        TaskProgressColumn(),
        TextColumn("[cyan]{task.completed}/{task.total} done"),
        TextColumn("•"),
        TextColumn("Elapsed"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TextColumn("ETA"),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )
    overall_task = progress.add_task(header, total=len(jobs))

    active: dict[str, float] = {}  # label → start_time
    completed: list[tuple[str, float]] = []  # (label, elapsed)
    lock = threading.Lock()

    def render() -> Group:
        now = time.time()
        table = Table.grid(padding=(0, 2))
        # In flight
        with lock:
            active_snapshot = list(active.items())
            recent_done = completed[-5:]
        for label, start in active_snapshot:
            elapsed = now - start
            table.add_row(f"  [yellow]↻[/] {label}", f"[dim]{elapsed:>5.1f}s")
        # Last 5 finished
        for label, elapsed in recent_done:
            table.add_row(f"  [green]✓[/] {label}", f"[dim]{elapsed:>5.1f}s")
        return Group(progress, table)

    def worker(job: Job) -> tuple[Job, str, float]:
        start = time.time()
        with lock:
            active[job.label] = start
        try:
            result = job.func()
            elapsed = time.time() - start
            return job, result, elapsed
        finally:
            with lock:
                active.pop(job.label, None)

    pipeline_start = time.time()

    with Live(render(), console=console, refresh_per_second=6) as live:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(worker, j): j for j in jobs}
            try:
                for future in as_completed(futures):
                    try:
                        job, result, elapsed = future.result()
                    except Exception as e:
                        failed_job = futures[future]
                        # Try to cancel the other scheduled jobs.
                        if FAIL_FAST:
                            for f in futures:
                                if not f.done():
                                    f.cancel()
                        raise RuntimeError(
                            f"\n\nError while describing '{failed_job.label}': "
                            f"{type(e).__name__}: {e}"
                        ) from e
                    job.on_done(result)
                    with lock:
                        completed.append((job.label, elapsed))
                    progress.update(overall_task, advance=1)
                    live.update(render())
            finally:
                # Final update so the view shows the end state.
                live.update(render())

    total_time = time.time() - pipeline_start
    total_api_time = sum(e for _, e in completed)
    avg_time = total_api_time / len(completed) if completed else 0.0
    speedup = total_api_time / total_time if total_time > 0 else 0.0
    console.print(
        f"\n[bold green]Done in {_format_duration(total_time)}.[/] "
        f"{len(completed)} calls, avg {avg_time:.1f}s/call, "
        f"total API time {_format_duration(total_api_time)} "
        f"([cyan]{speedup:.1f}× faster than sequential[/])."
    )
