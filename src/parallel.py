"""Parallell utförande av syntolkningsjobb med rich live-CLI.

Pipelinen samlar alla bilder och diagram som behöver syntolkas in en lista av Job.
Cache-träffar görs INNAN här (av main.run), så det enda som skickas hit är
faktiska API-anrop. run_jobs schemalägger dem på ThreadPoolExecutor och visar
en live-uppdaterad rich-vy med:

- Total progress (procent, antal klara/totalt)
- Förlöpt tid (timer från start)
- Uppskattad återstående tid
- Lista över pågående anrop med individuell timer
- Lista över senaste klara med körtid
- Slut-sammanfattning med snittider
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

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

# Vid ett fel — försök avbryta övriga schemalagda workers. Pågående får köra klart.
# Vi tror inte på "samla alla fel och fortsätt"-mönstret; första fel = stopp.
FAIL_FAST = True


@dataclass
class Job:
    """Ett syntolkningsjobb: en funktion som returnerar text + var resultatet ska lagras."""
    label: str                       # ex "sida 11 diagram 2"
    func: Callable[[], str]          # tar inga args, returnerar beskrivning
    on_done: Callable[[str], None]   # callback som lagrar resultatet i page_data


def _format_duration(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def run_jobs(
    jobs: list[Job],
    max_workers: int,
    header: str,
    console: Console | None = None,
) -> None:
    """Kör en lista jobs parallellt med live-CLI.

    Failar tydligt om något jobb kastar undantag (FAIL_FAST=True).
    """
    if not jobs:
        return

    console = console or Console()

    progress = Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30),
        TaskProgressColumn(),
        TextColumn("[cyan]{task.completed}/{task.total} klara"),
        TextColumn("•"),
        TextColumn("Förlöpt"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TextColumn("ETA"),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )
    overall_task = progress.add_task(header, total=len(jobs))

    active: dict[str, float] = {}             # label → start_time
    completed: list[tuple[str, float]] = []   # (label, elapsed)
    lock = threading.Lock()

    def render() -> Group:
        now = time.time()
        table = Table.grid(padding=(0, 2))
        # Pågående
        with lock:
            active_snapshot = list(active.items())
            recent_done = completed[-5:]
        for label, start in active_snapshot:
            elapsed = now - start
            table.add_row(f"  [yellow]↻[/] {label}", f"[dim]{elapsed:>5.1f}s")
        # Senaste 5 klara
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
                        # Försök att avbryta de övriga schemalagda
                        if FAIL_FAST:
                            for f in futures:
                                if not f.done():
                                    f.cancel()
                        raise RuntimeError(
                            f"\n\nFel vid syntolkning av '{failed_job.label}': "
                            f"{type(e).__name__}: {e}"
                        ) from e
                    job.on_done(result)
                    with lock:
                        completed.append((job.label, elapsed))
                    progress.update(overall_task, advance=1)
                    live.update(render())
            finally:
                # Sista uppdatering så vyn visar slutläget
                live.update(render())

    total_time = time.time() - pipeline_start
    total_api_time = sum(e for _, e in completed)
    avg_time = total_api_time / len(completed) if completed else 0.0
    speedup = total_api_time / total_time if total_time > 0 else 0.0
    console.print(
        f"\n[bold green]Klart på {_format_duration(total_time)}.[/] "
        f"{len(completed)} anrop, snittid {avg_time:.1f}s/anrop, "
        f"total API-tid {_format_duration(total_api_time)} "
        f"([cyan]{speedup:.1f}× snabbare än sekventiellt[/])."
    )
