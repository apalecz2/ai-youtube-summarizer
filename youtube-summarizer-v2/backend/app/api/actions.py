"""On-demand actions: instant summarize (item 5 right-click), manual poll, and
system status (queue + backoff, for the UI)."""
import asyncio
import time

from fastapi import APIRouter, Depends, Form, HTTPException

from app.db import repos
from app.discovery import run_discovery
from app.security import require_auth
from app.youtube import fetcher, gate

router = APIRouter(tags=["actions"], dependencies=[Depends(require_auth)])

# Manual requests jump the queue but still pass through the global gate.
_MANUAL_PRIORITY = 10


@router.post("/summarize")
def summarize_now(url: str = Form(...), detail: int = Form(2)):
    video_id = fetcher.extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    if detail not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="detail must be 1, 2, or 3")

    repos.upsert_video(video_id=video_id, url=url, status="queued")
    if not repos.has_pending_job(video_id):
        repos.enqueue_job(video_id=video_id, scheduled_at=int(time.time()),
                          priority=_MANUAL_PRIORITY, detail_level=detail, send_email=True)
    return {"status": "queued", "video_id": video_id, "detail": detail,
            "backoff": gate.status()}


def _requeue(video_id: str, *, priority: int) -> bool:
    """Set a video back to 'queued' and enqueue a job if none is pending.
    Returns True if a new job was enqueued."""
    repos.set_video_status(video_id, "queued", "retry requested")
    if repos.has_pending_job(video_id):
        return False
    repos.enqueue_job(video_id=video_id, scheduled_at=int(time.time()),
                      priority=priority, detail_level=2, send_email=True)
    return True


@router.post("/videos/{video_id}/retry")
def retry_video(video_id: str):
    """Re-queue a single failed video (e.g. after fixing the root cause)."""
    if not repos.get_video(video_id):
        raise HTTPException(status_code=404, detail="Video not found")
    enqueued = _requeue(video_id, priority=_MANUAL_PRIORITY)
    return {"status": "queued", "video_id": video_id, "enqueued": enqueued}


@router.post("/videos/{video_id}/dismiss")
def dismiss_video(video_id: str):
    """Acknowledge a failed video so it drops out of the 'needs attention' list."""
    if not repos.dismiss_video(video_id):
        raise HTTPException(status_code=404, detail="No failed video to dismiss")
    return {"status": "dismissed", "video_id": video_id}


@router.post("/failures/retry")
def retry_failures():
    """Bulk re-queue every failed video. Spread out by the worker's own jitter."""
    failed = repos.list_videos(status="failed", limit=500)
    count = sum(1 for v in failed if _requeue(v["video_id"], priority=0))
    return {"status": "queued", "count": count, "total": len(failed)}


@router.post("/failures/dismiss")
def dismiss_failures():
    """Bulk acknowledge every failed video, clearing the 'needs attention' list."""
    return {"status": "dismissed", "count": repos.dismiss_failed()}


@router.post("/poll")
async def poll():
    """Trigger discovery immediately (v1-compatible). Fetches still spread out."""
    stats = await asyncio.to_thread(run_discovery)
    return {"status": "discovery_complete", **stats}


@router.get("/status")
def status():
    return {"queue": repos.job_queue_stats(), "backoff": gate.status()}
