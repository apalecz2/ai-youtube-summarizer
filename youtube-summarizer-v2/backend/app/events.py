"""Persistent event log + live "what is the worker doing right now" state.

Everything interesting that happens internally (worker claims, stage changes,
blocks, failures, discovery scans, restarts, manual actions) is recorded here so
the UI's System page can show it. Events go to stdout (so `docker logs` still
works) AND to the `events` table (so they survive restarts and can be filtered).

`log()` must never raise: observability must not be able to break the pipeline.
"""
import threading
import time
from typing import Optional

from app.db import repos

# Rows kept in the events table; older ones are pruned by the scheduler.
KEEP_EVENTS = 5000

_lock = threading.Lock()
_activity: dict = {}  # what the worker is doing right now; empty when idle


def log(level: str, source: str, message: str, *, video_id: Optional[str] = None,
        job_id: Optional[int] = None) -> None:
    """level: info | warn | error. source: worker | job | discovery | gate | scheduler | api | startup."""
    print(f"[{source}] {level.upper()} {message}"
          + (f" (video {video_id})" if video_id else "")
          + (f" (job {job_id})" if job_id else ""))
    try:
        repos.add_event(level, source, message, video_id=video_id, job_id=job_id)
    except Exception as e:  # noqa: BLE001 - never let logging break the caller
        print(f"[events] failed to persist event: {type(e).__name__}: {e}")


# ── live activity (worker thread writes, API reads) ───────────
def begin_job(job: dict) -> None:
    now = time.time()
    with _lock:
        _activity.clear()
        _activity.update({
            "job_id": job["id"], "video_id": job["video_id"], "attempt": job.get("attempts"),
            "stage": "starting", "job_started_at": now, "stage_started_at": now,
        })


def set_stage(stage: str) -> None:
    with _lock:
        if _activity:
            _activity["stage"] = stage
            _activity["stage_started_at"] = time.time()


def end_job() -> None:
    with _lock:
        _activity.clear()


def current_activity() -> Optional[dict]:
    with _lock:
        if not _activity:
            return None
        now = time.time()
        a = dict(_activity)
    a["running_seconds"] = int(now - a["job_started_at"])
    a["stage_seconds"] = int(now - a["stage_started_at"])
    return a
