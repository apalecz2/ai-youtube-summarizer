"""The single worker loop — the only thing that drives YouTube fetches.

One coroutine pulls due jobs one at a time and runs the (blocking) pipeline in a
thread. It is the one place that:
  • honors the global backoff window before every YouTube touch (item 6),
  • adds random jitter between requests (item 1),
  • escalates backoff + reschedules when YouTube blocks us.

Because it's a single consumer, all YouTube access is naturally serialized.
"""
import asyncio
import random
import time
import traceback

from app.config import FETCH_JITTER_MIN_SECONDS, FETCH_JITTER_MAX_SECONDS
from app.db import repos
from app.jobs import JobResult, process_job, send_failure_email
from app.youtube import gate

# How often to wake and look for due work when idle / when backed off.
_IDLE_POLL_SECONDS = 8
_BACKOFF_CHECK_CAP_SECONDS = 60  # don't sleep longer than this in one go while blocked

# A transient (non-block) error is retried a few times before the video is failed,
# so a single network blip during summarization doesn't lose the video forever.
_MAX_ATTEMPTS = 5
_TRANSIENT_RETRY_SECONDS = 300
_RETRY_LATER_SECONDS = 3600  # upcoming premiere: check back in ~an hour


class Worker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="yt-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def _sleep(self, seconds: float) -> None:
        """Interruptible sleep so shutdown is prompt."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _run(self) -> None:
        print("[worker] started")
        while not self._stop.is_set():
            # Respect the global backoff window before touching YouTube.
            remaining = gate.seconds_until_unblocked()
            if remaining > 0:
                await self._sleep(min(remaining, _BACKOFF_CHECK_CAP_SECONDS))
                continue

            job = repos.claim_due_job()
            if not job:
                await self._sleep(_IDLE_POLL_SECONDS)
                continue

            await self._handle(job)

            # Human-like gap before the next YouTube request.
            jitter = random.uniform(FETCH_JITTER_MIN_SECONDS, FETCH_JITTER_MAX_SECONDS)
            await self._sleep(jitter)
        print("[worker] stopped")

    async def _handle(self, job: dict) -> None:
        video_id = job["video_id"]
        try:
            result = await asyncio.to_thread(process_job, job)
        except gate.BlockedError as e:
            blocked_until = gate.register_block()
            # Reschedule just past the backoff window (+ jitter). The block isn't
            # this job's fault, so reschedule_after_block refunds the attempt.
            repos.reschedule_after_block(job["id"], blocked_until + random.randint(5, 60))
            repos.set_video_status(video_id, "queued", "waiting on backoff")
            wait = max(0, blocked_until - int(time.time()))
            print(f"[worker] BLOCKED — backing off all requests for ~{wait}s "
                  f"(level {gate.status()['backoff_level']}); job {job['id']} requeued")
            return
        except Exception as e:  # noqa: BLE001 - transient/unexpected
            detail = f"{type(e).__name__}: {e}"
            attempts = int(job.get("attempts", 0))
            if attempts >= _MAX_ATTEMPTS:
                reason = f"failed after {attempts} attempts — {detail}"
                repos.fail_job(job["id"], reason[:1000])
                repos.set_video_status(video_id, "failed", reason[:1000])
                send_failure_email(
                    subject=f"Processing Failed: {video_id}",
                    error_message=f"{reason}\n\n{traceback.format_exc()}",
                    stage="worker (unexpected error)", video_id=video_id, job=job,
                )
                print(f"[worker] job {job['id']} ({video_id}) failed permanently: {detail}")
            else:
                reason = f"transient error (attempt {attempts}/{_MAX_ATTEMPTS}) — {detail}"
                repos.reschedule_job(job["id"], int(time.time()) + _TRANSIENT_RETRY_SECONDS, reason[:1000])
                repos.set_video_status(video_id, "queued", reason[:500])
                print(f"[worker] job {job['id']} ({video_id}) transient error; will retry: {detail}")
            return

        # Reached YouTube without a block — clear any standing backoff level.
        gate.register_success()
        if result == JobResult.RETRY_LATER:
            repos.reschedule_job(job["id"], int(time.time()) + _RETRY_LATER_SECONDS, "retry later (upcoming)")
        else:
            repos.complete_job(job["id"])
        print(f"[worker] job {job['id']} ({video_id}) -> {result}")


worker = Worker()
