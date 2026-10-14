"""Command line side of the Monday pipeline: the `monday` and `backfill` commands.

Both go through `services.pipeline.run_pipeline`, which does the locking, the transaction and the
`job_runs` bookkeeping. Exit code 1 when any tenant failed, so a scheduled run turns red.
"""

import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from app.core.clock import today_ist
from app.core.db import get_session_factory
from app.core.logging import get_logger
from app.services.pipeline import PipelineOutcome, monday_of, run_pipeline, tenant_ids

log = get_logger(__name__)


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def _summary_line(slug: str, o: PipelineOutcome, seconds: float) -> str:
    detail = o.reason or o.error or f"version {o.version}, {o.lines} lines"
    return f"| {slug} | {o.as_of.isoformat()} | {o.status} | {seconds:.1f} s | {detail} |"


def write_step_summary(rows: list[str]) -> None:
    """Append a table to the GitHub Actions step summary when it is available."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target or not rows:
        return
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write("| Business | Week | Status | Time | Detail |\n|---|---|---|---|---|\n")
        handle.write("\n".join(rows) + "\n")


def run_monday(tenant: str, profile: str, force: bool, as_of: date | None) -> int:
    factory = get_session_factory()
    week = monday_of(as_of or today_ist())
    targets = tenant_ids(factory, tenant)
    if not targets:
        out(f"No business matches {tenant!r}.")
        return 2
    rows: list[str] = []
    failed = 0
    for tid, slug in targets:
        started = time.monotonic()
        outcome = run_pipeline(factory, tid, week, profile, force=force, live=True)
        seconds = time.monotonic() - started
        rows.append(_summary_line(slug, outcome, seconds))
        out(rows[-1])
        failed += outcome.status == "failed"
    write_step_summary(rows)
    return 1 if failed else 0


def run_backfill(tenant: str, weeks: int, as_of: date | None) -> int:
    """Plans for the past Mondays, light profile, each with the data cutoff of its own date."""
    from app.services.backfill import backfill_tenant

    factory = get_session_factory()
    last = monday_of(as_of or today_ist()) - timedelta(days=7)
    targets = tenant_ids(factory, tenant)
    if not targets:
        out(f"No business matches {tenant!r}.")
        return 2
    failed = 0
    for tid, slug in targets:
        started = time.monotonic()
        done = backfill_tenant(factory, tid, last, weeks)
        failed += sum(1 for o in done if o.status == "failed")
        out(
            f"{slug}: {len(done)} weeks in {time.monotonic() - started:.1f} s, "
            f"{sum(1 for o in done if o.status == 'succeeded')} written"
        )
    return 1 if failed else 0
