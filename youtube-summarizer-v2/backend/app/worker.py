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

from app import events
from app.config import (FETCH_JITTER_MIN_SECONDS, FETCH_JITTER_MAX_SECONDS,
                        RESUME_SPREAD_MAX_MINUTES, RESUME_SPREAD_SECONDS_PER_JOB)
from app.db import repos
from app.jobs import JobResult, process_job, process_job_fallback, send_failure_email
from app.llm.provider import LLMRateLimited
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

# Gap between jobs while the main path is suspended. The YouTube-friendly jitter is
# pointless when we aren't calling YouTube; Gemini's own limits are enforced by the
# token limiter in llm/provider.py.
_FALLBACK_GAP_SECONDS = 3


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
            events.log("error", "worker", f"loop exited via unhandled exception, restarting: "
                       f"{type(exc).__name__}: {exc}")
            traceback.print_exception(type(exc), exc, exc.__traceback__)
        else:
            events.log("error", "worker", "loop exited unexpectedly (no exception), restarting")
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
        events.log("info", "worker", "worker loop started")
        # Tracks manual-pause -> resume so the backlog can be re-spread.
        was_paused = gate.seconds_paused() > 0
        while not self._stop.is_set():
            self._last_heartbeat = time.time()
            try:
                # An admin-set manual cooldown stops the worker completely. (A
                # confirmed YouTube block does not: it switches jobs to the Gemini
                # fallback, see _handle.)
                paused = gate.seconds_paused()
                if paused > 0:
                    was_paused = True
                    await self._sleep(min(paused, _BACKOFF_CHECK_CAP_SECONDS))
                    continue
                if was_paused:
                    was_paused = False
                    self._respread_backlog()

                # A held first failure that no second video ever came to confirm.
                stale = gate.stale_suspect()
                if stale:
                    await self._run_held_via_fallback(stale)

                # The held video waits for a *different* video to test the main path.
                suspect = gate.suspect_video_id()
                if suspect and not repos.has_pending_job(suspect):
                    gate.clear_suspect()  # its job was cancelled/removed
                    suspect = None

                job = repos.claim_due_job(exclude_video_id=suspect)
                if not job:
                    await self._sleep(_IDLE_POLL_SECONDS)
                    continue

                await self._run_job(job)

                if gate.is_fallback_mode():
                    await self._sleep(_FALLBACK_GAP_SECONDS)
                else:
                    # Human-like gap before the next YouTube request.
                    await self._sleep(random.uniform(FETCH_JITTER_MIN_SECONDS, FETCH_JITTER_MAX_SECONDS))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - loop must never die silently
                events.log("error", "worker", f"loop iteration error (continuing): {type(e).__name__}: {e}")
                traceback.print_exc()
                await self._sleep(_CRASH_RESTART_DELAY_SECONDS)
        events.log("info", "worker", "worker loop stopped")

    def _respread_backlog(self) -> None:
        """Fetching just resumed after a manual cooldown. Jobs that came due while
        paused would otherwise run back-to-back, which is exactly the burst that gets
        the IP flagged again. Re-time them one at a time, a few minutes apart,
        however long that takes (see config)."""
        n, span = repos.respread_overdue_jobs(
            avg_gap_seconds=RESUME_SPREAD_SECONDS_PER_JOB,
            max_total_seconds=RESUME_SPREAD_MAX_MINUTES * 60,
        )
        if n:
            events.log("info", "worker",
                       f"fetching resumed — re-spread {n} backlogged job(s), ~{RESUME_SPREAD_SECONDS_PER_JOB}s "
                       f"apart, over the next ~{span // 60}m")

    async def _run_job(self, job: dict) -> None:
        events.log("info", "worker", f"claimed job (attempt {job.get('attempts', 0) + 1}, "
                   f"priority {job.get('priority', 0)})", video_id=job["video_id"], job_id=job["id"])
        events.begin_job({**job, "attempts": job.get("attempts", 0) + 1})
        try:
            await self._handle(job)
        finally:
            events.end_job()

    async def _handle(self, job: dict) -> None:
        video_id = job["video_id"]

        # Main path suspended after a confirmed block: go straight to Gemini.
        if gate.is_fallback_mode():
            await self._process_fallback(job)
            return

        try:
            result = await asyncio.to_thread(process_job, job)
        except gate.BlockedError as e:
            await self._on_blocked(job, e)
            return
        except Exception as e:  # noqa: BLE001 - transient/unexpected
            self._on_error(job, e)
            return

        self._finish(job, result)

        # The caption download worked: the main path is healthy. If a first failure
        # was waiting on this, it was a one-off — summarize that video via Gemini.
        if job.get("_fetch_ok"):
            held = gate.report_fetch_success()
            if held and held != video_id:
                await self._run_held_via_fallback(held)

    async def _on_blocked(self, job: dict, e: Exception) -> None:
        """The main path hit a block-style failure (429 etc.)."""
        video_id = job["video_id"]
        decision = gate.report_fetch_failure(video_id)
        events.log("warn", "worker", f"main fetch blocked: {str(e)[:300]}", video_id=video_id, job_id=job["id"])
        if decision == "held":
            # First failure: don't pause anything. Park this video (no attempt
            # charged) and let the next, different video tell us what it means.
            repos.hold_job(job["id"], "held: waiting for a second video to show whether YouTube is blocking us")
            repos.set_video_status(video_id, "queued", "waiting to confirm a YouTube block")
            return
        # Confirmed: a different video failed first. The main path is now suspended
        # (gate logged it). This video goes through Gemini; the held one is released
        # and is picked up in fallback mode on the next claim.
        await self._process_fallback(job)

    async def _process_fallback(self, job: dict) -> None:
        try:
            result = await asyncio.to_thread(process_job_fallback, job)
        except Exception as e:  # noqa: BLE001
            self._on_error(job, e)
            return
        self._finish(job, result)

    async def _run_held_via_fallback(self, video_id: str) -> None:
        job = repos.claim_pending_job_for_video(video_id)
        if not job:
            return
        events.log("info", "worker", "processing the held video via direct Gemini",
                   video_id=video_id, job_id=job["id"])
        events.begin_job({**job, "attempts": job.get("attempts", 0) + 1})
        try:
            await self._process_fallback(job)
        finally:
            events.end_job()

    def _on_error(self, job: dict, e: Exception) -> None:
        video_id = job["video_id"]
        detail = f"{type(e).__name__}: {e}"
        attempts = int(job.get("attempts", 0))
        if isinstance(e, LLMRateLimited):
            # Gemini quota, not this video's fault: retry later without using up an attempt.
            repos.hold_job(job["id"], f"Gemini rate limited — retrying: {str(e)[:300]}")
            repos.reschedule_job(job["id"], int(time.time()) + _TRANSIENT_RETRY_SECONDS,
                                 f"Gemini rate limited — retrying: {str(e)[:300]}")
            repos.set_video_status(video_id, "queued", "waiting on Gemini rate limit")
            events.log("warn", "worker", f"all Gemini models rate limited; retry in {_TRANSIENT_RETRY_SECONDS}s",
                       video_id=video_id, job_id=job["id"])
            return
        if attempts >= _MAX_ATTEMPTS:
            reason = f"failed after {attempts} attempts — {detail}"
            repos.fail_job(job["id"], reason[:1000])
            repos.set_video_status(video_id, "failed", reason[:1000])
            send_failure_email(
                subject=f"Processing Failed: {video_id}",
                error_message=f"{reason}\n\n{traceback.format_exc()}",
                stage="worker (unexpected error)", video_id=video_id, job=job,
            )
            events.log("error", "worker", f"failed permanently after {attempts} attempts: {detail}",
                       video_id=video_id, job_id=job["id"])
        else:
            reason = f"transient error (attempt {attempts}/{_MAX_ATTEMPTS}) — {detail}"
            repos.reschedule_job(job["id"], int(time.time()) + _TRANSIENT_RETRY_SECONDS, reason[:1000])
            repos.set_video_status(video_id, "queued", reason[:500])
            events.log("warn", "worker", f"transient error, retry in {_TRANSIENT_RETRY_SECONDS}s: {detail}",
                       video_id=video_id, job_id=job["id"])

    def _finish(self, job: dict, result: str) -> None:
        if result == JobResult.RETRY_LATER:
            repos.reschedule_job(job["id"], int(time.time()) + _RETRY_LATER_SECONDS, "retry later (upcoming)")
        else:
            repos.complete_job(job["id"])
        events.log("info" if result in (JobResult.DONE, JobResult.SKIPPED, JobResult.RETRY_LATER) else "warn",
                   "worker", f"job finished -> {result}", video_id=job["video_id"], job_id=job["id"])


worker = Worker()
