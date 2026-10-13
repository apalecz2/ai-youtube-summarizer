"""Transparency endpoints for the UI's System page: one-shot health snapshot,
event log, job list, and per-video trace, plus two small repair actions."""
import os
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from app import config, events, scheduler
from app.db import repos
from app.llm import provider
from app.security import require_auth
from app.worker import worker
from app.youtube import gate

router = APIRouter(tags=["diagnostics"], dependencies=[Depends(require_auth)])

_WORKER_STALL_SECONDS = 600
_STALE_RUNNING_SECONDS = 1800


def _file_info(path: Path) -> dict:
    try:
        st = path.stat()
        return {"exists": True, "bytes": st.st_size, "modified_at": int(st.st_mtime)}
    except OSError:
        return {"exists": False, "bytes": 0, "modified_at": None}


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:  # noqa: BLE001
        return False


def _config_snapshot() -> dict:
    """Effective settings, with secrets reduced to set/unset booleans."""
    try:
        import yt_dlp
        ytdlp_version = yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        ytdlp_version = None
    cookies = _file_info(Path(config.YTDLP_COOKIES_FILE)) if config.YTDLP_COOKIES_FILE else {"exists": False}
    return {
        "poll_interval_minutes": config.POLL_INTERVAL_MINUTES,
        "fetch_spread_minutes": config.FETCH_SPREAD_MINUTES,
        "fetch_jitter_seconds": [config.FETCH_JITTER_MIN_SECONDS, config.FETCH_JITTER_MAX_SECONDS],
        "backoff_schedule_minutes": config.BACKOFF_SCHEDULE_MINUTES,
        "suspect_timeout_minutes": config.SUSPECT_TIMEOUT_MINUTES,
        "gemini_models": provider.MODELS,
        "gemini_tpm_budget": config.GEMINI_INPUT_TOKENS_PER_MINUTE * config.GEMINI_TPM_SAFETY_PERCENT // 100,
        "min_duration_seconds": config.MIN_DURATION_SECONDS,
        "max_duration_seconds": config.MAX_DURATION_SECONDS,
        "cookies_file": config.YTDLP_COOKIES_FILE or None,
        "cookies": cookies,
        "proxy_set": bool(config.YTDLP_PROXY),
        "impersonate": config.YTDLP_IMPERSONATE or None,
        "curl_cffi_installed": _module_available("curl_cffi"),
        "ytdlp_version": ytdlp_version,
        "python_version": sys.version.split()[0],
        "gemini_key_set": bool(config.GEMINI_API_KEY),
        "email_configured": bool(config.EMAIL_USERNAME and config.EMAIL_SENDTO),
        "app_base_url_set": bool(config.APP_BASE_URL),
        "data_dir": str(config.DATA_DIR),
    }


def _health_checks(*, now: int, worker_state: dict, backoff: dict, problems: dict,
                   cfg: dict, queue: dict, activity: dict | None) -> list[dict]:
    """Each check: {id, level: ok|warn|bad, title, detail}. Ordered worst-first by the UI."""
    checks: list[dict] = []

    def add(id_, level, title, detail=""):
        checks.append({"id": id_, "level": level, "title": title, "detail": detail})

    # Worker
    if not worker_state["alive"]:
        add("worker", "bad", "Worker is not running",
            "No background task is claiming jobs. Restart the container.")
    elif worker_state["stalled"]:
        add("worker", "bad", "Worker heartbeat is stale",
            f"No heartbeat for {int(worker_state['seconds_since_heartbeat'] or 0)}s — the loop may be wedged.")
    else:
        add("worker", "ok", "Worker is running",
            f"Heartbeat {int(worker_state['seconds_since_heartbeat'] or 0)}s ago.")

    # Rate limit
    mode = backoff.get("mode")
    if mode == "fallback":
        mins = backoff["seconds_remaining"] // 60
        add("backoff", "warn", f"YouTube fetching suspended (level {backoff['backoff_level']}) — using direct Gemini",
            f"A block was confirmed by two videos failing in a row. The main fetch path retries in "
            f"{mins // 1440}d {(mins % 1440) // 60}h {mins % 60}m; until then videos are summarized from "
            "their URL by Gemini (no transcript is stored for them).")
    elif mode == "suspect":
        add("backoff", "warn", "One video failed to fetch — waiting for a second to confirm a block",
            f"{backoff.get('suspect_video_id')} is held. The next different video decides whether this was a "
            "one-off (it then uses Gemini) or a real block (fetching is suspended for a day).")
    elif backoff["blocked"] and backoff.get("manual"):
        add("backoff", "warn", "Manual cooldown active",
            f"Transcript fetching is paused by you for {backoff['seconds_remaining'] // 60}m more. "
            "Discovery keeps running.")
    elif backoff["blocked"]:
        add("backoff", "bad", f"Rate-limit backoff active (level {backoff['backoff_level']})",
            f"No YouTube requests for {backoff['seconds_remaining']}s more. All queued jobs wait.")
    elif backoff["recently_blocked"]:
        add("backoff", "warn", "Recently rate-limited by YouTube",
            "IP flags often last 12-24h; fetches may still fail with 429s.")
    else:
        add("backoff", "ok", "No YouTube rate-limiting")

    # Long-running job
    if activity and activity["running_seconds"] > 300:
        add("slow_job", "warn", "A job has been running for a long time",
            f"{activity['video_id']} is {activity['running_seconds']}s in, stage: {activity['stage']}.")

    # Inconsistencies
    labels = {
        "stale_running_jobs": ("bad", "Jobs stuck in 'running'",
                               "Probably orphaned by a restart/crash. Use 'Fix stuck jobs'."),
        "fetching_without_job": ("bad", "Videos stuck in 'fetching' with no running job",
                                 "Nothing is working on them."),
        "queued_without_job": ("bad", "Videos marked 'queued' but with no pending job",
                               "Nothing will ever pick these up. Retry them from the video page."),
        "job_for_finished_video": ("warn", "Active jobs for already-finished videos",
                                   "Harmless but unexpected."),
        "overdue_pending_jobs": ("warn", "Pending jobs overdue by more than an hour",
                                 "Worker blocked/stalled, or the queue is backed up."),
    }
    for key, (level, title, detail) in labels.items():
        rows = problems.get(key) or []
        if rows:
            add(key, level, f"{title} ({len(rows)})", detail)
    if not any(problems.get(k) for k in labels):
        add("consistency", "ok", "Queue and video states are consistent")

    # Config
    if not cfg["cookies"].get("exists"):
        add("cookies", "warn", "No cookies file", f"{cfg['cookies_file']} not found — requests are anonymous, "
            "which makes YouTube blocks more likely.")
    if cfg["impersonate"] and not cfg["curl_cffi_installed"]:
        add("curl_cffi", "warn", "YTDLP_IMPERSONATE is set but curl_cffi is not installed", "Impersonation is ignored.")
    if not cfg["gemini_key_set"]:
        add("gemini", "bad", "GEMINI_API_KEY is not set", "Summaries cannot be generated.")
    if not cfg["email_configured"]:
        add("email", "warn", "Email is not configured", "Summaries and failure alerts won't be emailed.")
    if scheduler.next_poll_at() is None:
        add("scheduler", "bad", "Discovery scheduler is not running", "New uploads will not be found.")
    return checks


@router.get("/diagnostics")
def diagnostics():
    now = int(time.time())
    activity = events.current_activity()
    heartbeat_age = worker.seconds_since_heartbeat()
    worker_state = {
        "alive": worker.is_alive(),
        "seconds_since_heartbeat": heartbeat_age,
        "stalled": (not worker.is_alive())
        or (heartbeat_age is not None and heartbeat_age > _WORKER_STALL_SECONDS),
        "activity": activity,
    }
    backoff = gate.status()
    problems = repos.find_inconsistencies(
        now=now, running_stale_seconds=_STALE_RUNNING_SECONDS,
        ignore_job_id=activity["job_id"] if activity else None)
    cfg = _config_snapshot()
    db_file = Path(config.DB_PATH)
    queue = repos.job_queue_stats()
    next_poll = scheduler.next_poll_at()
    return {
        "now": now,
        "health": _health_checks(now=now, worker_state=worker_state, backoff=backoff,
                                 problems=problems, cfg=cfg, queue=queue, activity=activity),
        "worker": worker_state,
        "backoff": backoff,
        "scheduler": {
            "next_poll_at": next_poll,
            "next_poll_in_seconds": (next_poll - now) if next_poll else None,
            "last_discovery": scheduler.last_discovery,
        },
        "queue": queue,
        "videos": repos.video_status_counts(),
        "videos_last_24h": repos.recent_status_counts(now - 86400),
        "tables": repos.table_counts(),
        "database": {
            "path": str(db_file),
            "db": _file_info(db_file),
            "wal": _file_info(Path(str(db_file) + "-wal")),
        },
        "problems": problems,
        "config": cfg,
    }


@router.get("/events")
def list_events(limit: int = Query(200, le=1000), before_id: int | None = None,
                level: str | None = Query(None, pattern="^(warn|error)$"),
                source: str | None = None, video_id: str | None = None, q: str | None = None):
    return {"events": repos.list_events(limit=limit, before_id=before_id, level=level,
                                        source=source, video_id=video_id, q=q)}


@router.get("/jobs")
def list_jobs(status: str | None = None, limit: int = Query(100, le=500)):
    return {"jobs": repos.list_jobs(status=status, limit=limit)}


@router.get("/videos/{video_id}/trace")
def video_trace(video_id: str):
    """Everything the system knows about one video's processing: its jobs and
    its event history, oldest first."""
    evs = repos.list_events(limit=500, video_id=video_id)
    evs.reverse()
    return {"video_id": video_id, "jobs": repos.jobs_for_video(video_id), "events": evs}


@router.post("/diagnostics/fix-stuck")
def fix_stuck():
    """Requeue jobs stuck in 'running' (never the one the worker is on right now)."""
    activity = events.current_activity()
    n = repos.requeue_stale_jobs(running_stale_seconds=_STALE_RUNNING_SECONDS,
                                 ignore_job_id=activity["job_id"] if activity else None)
    events.log("warn" if n else "info", "api", f"manual 'fix stuck jobs': requeued {n}")
    return {"requeued": n}
