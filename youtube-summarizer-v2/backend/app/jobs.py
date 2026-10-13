"""Processing a single fetch job — the full pipeline for one video.

Pulls metadata + transcript via yt-dlp (one extract_info call + one subtitle
download), applies the same skip rules as v1, summarizes, persists everything, and
emails. This function is BLOCKING (yt-dlp / requests / SMTP) and is run in a
thread by the worker loop.

Block detection lives here only to the extent of raising BlockedError; the WORKER
owns the backoff policy (so all job types share one place that escalates).
"""
from typing import Optional

import yt_dlp

from app import config, events
from app.db import repos
from app.email.emailer import send_summary_email, send_error_email
from app.llm import video as video_llm
from app.llm.provider import LLMRateLimited
from app.llm.summarizer import safe_summarize
from app.youtube import fetcher, gate


class JobResult:
    DONE = "done"
    SKIPPED = "skipped"          # terminal skip (live / short / too long)
    RETRY_LATER = "retry_later"  # not ready yet (upcoming premiere) — worker re-queues
    NO_TRANSCRIPT = "no_transcript"
    FAILED = "failed"


def _app_url(video_id: str) -> Optional[str]:
    return f"{config.APP_BASE_URL}/videos/{video_id}" if config.APP_BASE_URL else None


def send_failure_email(*, subject: str, error_message: str, stage: str, video_id: str,
                        job: dict, meta: Optional[dict] = None) -> None:
    """Send a diagnostic failure email with as much context as we have at this
    stage. Falls back to the stored video row for title/channel when `meta`
    isn't available yet (e.g. a metadata-stage failure)."""
    video = repos.get_video(video_id) or {}
    meta = meta or {}
    send_error_email(
        subject=subject,
        error_message=error_message,
        stage=stage,
        video_id=video_id,
        video_title=meta.get("title") or video.get("title"),
        channel_name=meta.get("channel") or video.get("channel_name"),
        youtube_url=job.get("url") or video.get("url") or f"https://www.youtube.com/watch?v={video_id}",
        app_url=_app_url(video_id),
    )


def process_job(job: dict) -> str:
    """Run one job. Returns a JobResult. Raises gate.BlockedError if YouTube blocks
    us (the worker turns that into global backoff + reschedule)."""
    video_id = job["video_id"]
    detail_level = job.get("detail_level", 2)
    send_email = bool(job.get("send_email", 1))
    allow_long = job.get("priority", 0) > 0  # manual requests may exceed the length cap

    repos.set_video_status(video_id, "fetching")
    events.set_stage("metadata (yt-dlp extract_info)")

    # ── 1. Metadata + caption availability (single extract_info call) ──
    try:
        info = fetcher.extract_info(video_id)
    except yt_dlp.utils.DownloadError as e:
        if gate.is_block_error(e):
            raise gate.BlockedError(str(e))
        # Genuine "unavailable / private / removed" — record and move on.
        reason = f"metadata fetch failed — {type(e).__name__}: {e}"
        events.log("error", "job", reason[:500], video_id=video_id, job_id=job.get("id"))
        repos.set_video_status(video_id, "failed", reason)
        send_failure_email(subject=f"Metadata Fetch Failed: {video_id}", error_message=reason,
                            stage="metadata (yt-dlp extract_info)", video_id=video_id, job=job)
        return JobResult.FAILED

    meta = fetcher.metadata_from_info(info)
    repos.update_video_metadata(video_id, title=meta["title"], channel_name=meta["channel"],
                                duration=meta["duration"])

    # ── 2. Skip rules (same thresholds as v1) ──
    live = meta["live_status"]
    events.log("info", "job", f"metadata ok: \"{meta['title']}\" ({meta['duration']}s, {live})",
               video_id=video_id, job_id=job.get("id"))
    if live == "is_upcoming":
        # Don't mark terminal — the worker re-queues this job for later, once it airs.
        repos.set_video_status(video_id, "queued", "upcoming premiere")
        events.log("info", "job", "upcoming premiere — will check again later", video_id=video_id, job_id=job.get("id"))
        return JobResult.RETRY_LATER
    if live == "is_live":
        repos.set_video_status(video_id, "skipped", "currently live")
        events.log("info", "job", "skipped: currently live", video_id=video_id, job_id=job.get("id"))
        return JobResult.SKIPPED
    duration = meta["duration"] or 0
    if 0 < duration < config.MIN_DURATION_SECONDS:
        repos.set_video_status(video_id, "skipped", f"short ({duration}s)")
        events.log("info", "job", f"skipped: short ({duration}s)", video_id=video_id, job_id=job.get("id"))
        return JobResult.SKIPPED
    if duration > config.MAX_DURATION_SECONDS and not allow_long:
        repos.set_video_status(video_id, "skipped", f"too long ({duration}s)")
        events.log("info", "job", f"skipped: too long ({duration}s)", video_id=video_id, job_id=job.get("id"))
        return JobResult.SKIPPED

    # ── 3. Transcript ──
    events.set_stage("transcript (subtitle download)")
    transcript_error: Optional[str] = None
    try:
        transcript = fetcher.fetch_transcript_from_info(info)
    except gate.BlockedError:
        # A 429 on the subtitle download — let the worker back off + requeue.
        raise
    except yt_dlp.utils.DownloadError as e:
        if gate.is_block_error(e):
            raise gate.BlockedError(str(e))
        transcript = None
        transcript_error = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001 - subtitle download/parse issues
        if gate.is_block_error(e):
            raise gate.BlockedError(str(e))
        transcript = None
        transcript_error = f"{type(e).__name__}: {e}"

    if transcript:
        # The caption download itself worked, which is what tells the worker the main
        # path is healthy (see worker._after_main_success). A video with no captions
        # at all never gets here, so it can't mask a block.
        job["_fetch_ok"] = True

    if not transcript or not transcript.get("text"):
        # Explain *why* there's no transcript: a download/parse error, or simply
        # no usable English captions (in which case list what the video does expose).
        if transcript_error:
            reason = f"transcript download failed — {transcript_error}"
        else:
            langs = fetcher.available_caption_langs(info)
            reason = (
                "no usable English transcript "
                f"(manual captions: {', '.join(langs['manual']) or 'none'}; "
                f"auto captions: {', '.join(langs['automatic']) or 'none'})"
            )
        # Rate-limit root-cause detection: an IP flag commonly *looks* like a
        # missing transcript. If we're blocked / were recently blocked, say so —
        # the "[rate-limited]" marker is what the UI keys off to flag it.
        rl_note = gate.rate_limit_note()
        if rl_note:
            reason = f"[rate-limited] {reason} — {rl_note}"
        subject = ("Rate-Limited (No Transcript): " if rl_note else "Missing Transcript: ") + meta["title"]
        events.log("warn", "job", f"no transcript: {reason}"[:1500], video_id=video_id, job_id=job.get("id"))
        repos.set_video_status(video_id, "failed", reason)
        send_failure_email(subject=subject, error_message=reason,
                           stage="transcript", video_id=video_id, job=job, meta=meta)
        return JobResult.NO_TRANSCRIPT

    repos.save_transcript(video_id, transcript["text"], lang=transcript.get("lang"),
                          source=transcript.get("source"))
    events.log("info", "job", f"transcript ok: {len(transcript['text'])} chars, "
               f"lang={transcript.get('lang')}, source={transcript.get('source')}",
               video_id=video_id, job_id=job.get("id"))

    events.set_stage("summarizing (LLM)")

    # ── 4. Summarize ──
    result, summarize_error = safe_summarize(transcript["text"], detail=detail_level,
                                             channel_name=meta["channel"], video_title=meta["title"])
    if not result:
        reason = f"summarization failed — {summarize_error or 'unknown error'}"
        events.log("error", "job", reason[:1000], video_id=video_id, job_id=job.get("id"))
        repos.set_video_status(video_id, "failed", reason)
        send_failure_email(subject=f"Summarization Failed: {meta['title']}", error_message=reason,
                            stage="summarization (LLM)", video_id=video_id, job=job, meta=meta)
        return JobResult.FAILED

    summary_md, model = result
    repos.save_summary(video_id, summary_md, detail_level=detail_level, model=model)
    repos.set_video_status(video_id, "summarized")
    events.log("info", "job", f"summarized with {model} ({len(summary_md)} chars)",
               video_id=video_id, job_id=job.get("id"))

    # ── 5. Email (core feature retained) ──
    if send_email:
        events.set_stage("emailing summary")
        video = repos.get_video(video_id) or {}
        send_summary_email(
            video_title=meta["title"], channel_name=meta["channel"], summary=summary_md,
            youtube_url=video.get("url") or f"https://www.youtube.com/watch?v={video_id}",
            app_url=_app_url(video_id),
        )

    return JobResult.DONE


def process_job_fallback(job: dict) -> str:
    """Same job, but without touching YouTube: Gemini reads the video from its URL.
    Used while the main fetch path is suspended, and for the video(s) that tripped a
    block check. No transcript is stored for these, so search/quiz work off the
    summary alone. Raises LLMRateLimited if every model is rate limited."""
    video_id = job["video_id"]
    detail_level = job.get("detail_level", 2)
    send_email = bool(job.get("send_email", 1))
    allow_long = job.get("priority", 0) > 0

    video = repos.get_video(video_id) or {}
    title = video.get("title") or video_id
    channel = video.get("channel_name")
    repos.set_video_status(video_id, "fetching")
    events.log("info", "job", "using direct Gemini video summary (main fetch path unavailable)",
               video_id=video_id, job_id=job.get("id"))

    # ── Size the video (free token count; also gives us skip-rule inputs) ──
    events.set_stage("direct video: sizing (Gemini)")
    duration = int(video.get("duration") or 0)
    if not duration:
        try:
            duration = video_llm.probe_duration(video_id)
        except LLMRateLimited:
            raise
        except Exception as e:  # noqa: BLE001 - private / removed / live / unreachable
            reason = f"direct video summary failed — couldn't read the video via Gemini: {type(e).__name__}: {e}"
            events.log("error", "job", reason[:500], video_id=video_id, job_id=job.get("id"))
            repos.set_video_status(video_id, "failed", reason[:1000])
            send_failure_email(subject=f"Direct Video Summary Failed: {title}", error_message=reason,
                               stage="direct video (sizing)", video_id=video_id, job=job)
            return JobResult.FAILED
        repos.update_video_metadata(video_id, duration=duration)

    if 0 < duration < config.MIN_DURATION_SECONDS:
        repos.set_video_status(video_id, "skipped", f"short ({duration}s)")
        events.log("info", "job", f"skipped: short ({duration}s)", video_id=video_id, job_id=job.get("id"))
        return JobResult.SKIPPED
    if duration > config.MAX_DURATION_SECONDS and not allow_long:
        repos.set_video_status(video_id, "skipped", f"too long ({duration}s)")
        events.log("info", "job", f"skipped: too long ({duration}s)", video_id=video_id, job_id=job.get("id"))
        return JobResult.SKIPPED

    # ── Summarize straight from the video ──
    events.set_stage("direct video: summarizing (Gemini)")
    try:
        summary_md, model = video_llm.summarize_video(
            video_id, duration=duration, detail=detail_level, channel_name=channel, video_title=title)
    except LLMRateLimited:
        raise
    except Exception as e:  # noqa: BLE001
        reason = f"direct video summary failed — {type(e).__name__}: {e}"
        events.log("error", "job", reason[:500], video_id=video_id, job_id=job.get("id"))
        repos.set_video_status(video_id, "failed", reason[:1000])
        send_failure_email(subject=f"Direct Video Summary Failed: {title}", error_message=reason,
                           stage="direct video (summarization)", video_id=video_id, job=job)
        return JobResult.FAILED

    repos.save_summary(video_id, summary_md, detail_level=detail_level, model=f"{model} (direct video)")
    repos.set_video_status(video_id, "summarized")
    events.log("info", "job", f"summarized from video URL with {model} ({duration}s video, {len(summary_md)} chars)",
               video_id=video_id, job_id=job.get("id"))

    if send_email:
        events.set_stage("emailing summary")
        send_summary_email(
            video_title=title, channel_name=channel or "Unknown Channel", summary=summary_md,
            youtube_url=video.get("url") or f"https://www.youtube.com/watch?v={video_id}",
            app_url=_app_url(video_id),
        )
    return JobResult.DONE
