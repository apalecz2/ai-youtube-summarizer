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


# If the loop dies unexpectedly and gets auto-restarted, don't let a persistent
# error (e.g. a wedged DB) spin it in a tight crash loop.
_CRASH_RESTART_DELAY_SECONDS = 5


class Worker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # Updated at the top of every loop iteration. Lets /api/status (and
        # anyone reading logs) tell "alive but idle/blocked" apart from "the
        # loop died and nobody noticed" — see the incident this guards against
        # in worker.py's module docstring history: an unguarded DB call threw,
        # the task ended, and nothing was left to claim jobs ever again.
        self._last_heartbeat: float = 0.0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._last_heartbeat = time.time()
            self._task = asyncio.create_task(self._run(), name="yt-worker")
            self._task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        """The loop body catches everything it can, so this only fires on a
        truly unexpected escape (or cancellation). Restart rather than leave
        the worker dead with no supervisor to notice."""
        if self._stop.is_set() or task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            print(f"[worker] loop exited via unhandled exception, restarting: "
                  f"{type(exc).__name__}: {exc}")
            traceback.print_exception(type(exc), exc, exc.__traceback__)
        else:
            print("[worker] loop exited unexpectedly (no exception), restarting")
        self.start()

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except asyncio.TimeoutError:
                self._task.cancel()

    def is_alive(self) -> bool:
        return self._task is not None and not self._task.done()

    def seconds_since_heartbeat(self) -> float | None:
        return (time.time() - self._last_heartbeat) if self._last_heartbeat else None

    async def _sleep(self, seconds: float) -> None:
        """Interruptible sleep so shutdown is prompt."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _run(self) -> None:
        print("[worker] started")
        while not self._stop.is_set():
            self._last_heartbeat = time.time()
            try:
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
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - loop must never die silently
                print(f"[worker] loop iteration error (continuing): {type(e).__name__}: {e}")
                traceback.print_exc()
                await self._sleep(_CRASH_RESTART_DELAY_SECONDS)
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
