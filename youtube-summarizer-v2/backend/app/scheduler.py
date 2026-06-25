"""Lifecycle: the in-process scheduler + worker that replace v1's external cron.

APScheduler fires discovery every POLL_INTERVAL_MINUTES; the worker coroutine
drains the resulting jobs over time. This means the app is self-contained — no
home-server-scheduler needed — though `POST /poll` still triggers discovery on
demand.
"""
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import POLL_INTERVAL_MINUTES
from app.discovery import run_discovery
from app.worker import worker

_scheduler: AsyncIOScheduler | None = None


async def _discovery_job() -> None:
    import asyncio
    try:
        stats = await asyncio.to_thread(run_discovery)
        print(f"[discovery] {stats}")
    except Exception as e:  # noqa: BLE001
        print(f"[discovery] error: {e}")


def start() -> None:
    global _scheduler
    worker.start()
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _discovery_job,
        "interval",
        minutes=max(1, POLL_INTERVAL_MINUTES),
        id="discovery",
        max_instances=1,        # never overlap discovery runs
        coalesce=True,
        # Run the first scan shortly after startup, then every interval. NOTE:
        # APScheduler treats next_run_time=None as "add the job PAUSED" (it never
        # fires), so we must pass a real datetime here.
        next_run_time=datetime.now() + timedelta(seconds=10),
    )
    _scheduler.start()
    print(f"[scheduler] discovery every {POLL_INTERVAL_MINUTES} min")


async def stop() -> None:
    if _scheduler:
        _scheduler.shutdown(wait=False)
    await worker.stop()


def next_poll_at() -> int | None:
    """Epoch seconds of the next scheduled discovery run, or None if the
    scheduler isn't running yet."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job("discovery")
    if job is None or job.next_run_time is None:
        return None
    return int(job.next_run_time.timestamp())
