"""The global YouTube gate: decides when the main (yt-dlp) fetch path is trusted.

State lives in `rate_limit_state` so it survives restarts. Modes:

  normal    Main path in use. A block-style failure (429 etc.) on one video does NOT
            pause anything: that video is held as the "suspect" and the next job
            (a different video) decides what it means.
  suspect   One video failed; waiting for a different video to try the main path.
              - it succeeds  -> not a global block. Suspect goes through the Gemini
                                direct fallback; backoff level resets; carry on.
              - it also fails -> CONFIRMED block. The main path is suspended for
                                BACKOFF_SCHEDULE_MINUTES[level] (a day, then longer);
                                both videos and everything after use the fallback.
  fallback  Main path suspended (blocked_until in the future, not manual). When it
            ends we are back in `normal` with the level kept, so the first videos
            re-run the same two-video check, and a second confirmed failure moves to
            the next, longer suspension.
  manual    An admin-set pause (see below); the worker does nothing at all.
"""
import time

from app import events
from app import config
from app.config import BACKOFF_SCHEDULE_MINUTES
from app.db import repos

# Substrings (lowercased) that indicate YouTube is rate-limiting / bot-blocking us,
# as opposed to an ordinary "video unavailable" / "no subtitles" error.
BLOCK_SIGNATURES = (
    "sign in to confirm you're not a bot",
    "sign in to confirm you’re not a bot",
    "http error 429",
    "too many requests",
    "this content isn't available",  # often returned to flagged IPs
    "confirm your age",
    "unable to download api page",
    "the following content is not available on this app",
    "please try again later",
    "blocked it in your country",
    "we have detected unusual traffic",
)


# A YouTube IP flag typically persists 12–24h. Within this window after the last
# block, a "missing transcript" is far more likely the lingering rate-limit than a
# genuinely caption-less video, so we say so in the failure reason / email.
RECENT_BLOCK_WINDOW_SECONDS = 18 * 3600


class BlockedError(Exception):
    """Raised when YouTube appears to be actively blocking us."""


def is_block_error(error: str | Exception) -> bool:
    s = str(error).lower()
    return any(sig in s for sig in BLOCK_SIGNATURES)


def block_diagnosis() -> dict:
    """Snapshot of rate-limit context, for annotating individual failures."""
    state = repos.get_rate_limit_state()
    now = int(time.time())
    last_block = int(state["last_block_at"] or 0)
    since = (now - last_block) if last_block else None
    return {
        # Excludes an admin-set manual cooldown — that's not YouTube's doing.
        "currently_blocked": is_blocked() and not is_manual_cooldown(),
        "backoff_level": int(state["backoff_level"]),
        "last_block_at": last_block or None,
        "seconds_since_block": since,
        "recently_blocked": bool(last_block and since is not None and since < RECENT_BLOCK_WINDOW_SECONDS),
    }


def rate_limit_note() -> str | None:
    """A human-readable explanation when rate-limiting is the likely root cause of
    a failure, or None if there's no current sign of an IP block. Used to enrich
    'no transcript' failures (the symptom an IP flag usually produces here)."""
    d = block_diagnosis()
    if d["currently_blocked"]:
        mins = seconds_until_unblocked() // 60
        return (
            f"YouTube is actively rate-limiting this server's IP "
            f"(backoff level {d['backoff_level']}, ~{mins}m remaining). This failure is "
            f"almost certainly the IP block — not a genuinely missing transcript. "
            f"Remedy: route YouTube traffic through a different egress IP "
            f"(Cloudflare WARP, a proxy, or a relay VPS)."
        )
    if d["recently_blocked"]:
        hrs = round((d["seconds_since_block"] or 0) / 3600, 1)
        return (
            f"This server was rate-limited by YouTube ~{hrs}h ago. IP flags typically "
            f"last 12–24h and Google's subtitle servers may still be returning 429s, so a "
            f"'missing transcript' here is likely the lingering block rather than the video "
            f"lacking captions."
        )
    return None


def _backoff_seconds(level: int) -> int:
    # level is 1-based once a block has happened; index into the schedule, capped.
    idx = min(max(level, 1), len(BACKOFF_SCHEDULE_MINUTES)) - 1
    return BACKOFF_SCHEDULE_MINUTES[idx] * 60


def seconds_until_unblocked() -> int:
    state = repos.get_rate_limit_state()
    remaining = int(state["blocked_until"]) - int(time.time())
    return max(0, remaining)


def is_blocked() -> bool:
    return seconds_until_unblocked() > 0


def is_fallback_mode() -> bool:
    """True while a CONFIRMED block has the main fetch path suspended (jobs run
    through the direct-Gemini fallback instead)."""
    return is_blocked() and not is_manual_cooldown()


def seconds_paused() -> int:
    """Seconds the worker must do nothing at all — only for an admin-set manual
    cooldown. A confirmed block doesn't pause the worker; it switches methods."""
    return seconds_until_unblocked() if is_manual_cooldown() else 0


def suspect_video_id() -> str | None:
    return repos.get_rate_limit_state().get("suspect_video_id")


def report_fetch_failure(video_id: str) -> str:
    """The main path hit a block-style failure on `video_id`. Returns:
      "held"      first failure (or the same video again): hold it, wait for a second.
      "confirmed" a DIFFERENT video already failed: block confirmed, suspension started.
    """
    state = repos.get_rate_limit_state()
    suspect = state.get("suspect_video_id")
    if not suspect or suspect == video_id:
        repos.set_suspect(video_id)
        events.log("warn", "gate", "fetch failed — holding it until a second video tries the main path "
                   "to tell a global block from a one-off", video_id=video_id)
        return "held"
    level = int(state["backoff_level"]) + 1
    minutes = _backoff_seconds(level) // 60
    repos.start_suspension(blocked_until=int(time.time()) + minutes * 60, backoff_level=level)
    events.log("warn", "gate",
               f"BLOCK CONFIRMED (also failed earlier: {suspect}) — main fetch path suspended for "
               f"{_fmt_minutes(minutes)} (level {level}); using direct Gemini meanwhile", video_id=video_id)
    return "confirmed"


def report_fetch_success() -> str | None:
    """The main path fetched a transcript. Clears any backoff level. If a first
    failure was waiting on this, returns its video_id: it was a one-off, so the
    caller should run that video through the Gemini fallback."""
    state = repos.get_rate_limit_state()
    suspect = state.get("suspect_video_id")
    if suspect:
        events.log("info", "gate", f"main path works — block ruled out; {suspect} was a one-off failure")
    elif int(state["backoff_level"]) > 0:
        events.log("info", "gate", "main path works again — suspension level reset to 0")
    repos.mark_success()
    return suspect


def stale_suspect() -> str | None:
    """A held first failure that no second video ever confirmed or cleared within
    SUSPECT_TIMEOUT_MINUTES (e.g. nothing else was queued). Returns its video_id and
    clears the suspicion without escalating; the caller runs it via the fallback."""
    state = repos.get_rate_limit_state()
    suspect, at = state.get("suspect_video_id"), state.get("suspect_at")
    if suspect and at and time.time() - int(at) > config.SUSPECT_TIMEOUT_MINUTES * 60:
        repos.set_suspect(None)
        events.log("info", "gate", f"no second video arrived within {config.SUSPECT_TIMEOUT_MINUTES}m — "
                   "treating the failure as a one-off", video_id=suspect)
        return suspect
    return None


def clear_suspect() -> None:
    repos.set_suspect(None)


def _fmt_minutes(m: int) -> str:
    return f"{m // 1440}d" if m >= 1440 and m % 1440 == 0 else (f"{m // 60}h" if m >= 120 else f"{m}m")


# Manual cooldown (admin-triggered pause of the worker). Shares the same
# blocked_until window the worker already checks (worker.py), so pausing it
# needs no worker changes — and discovery.py never consults this module, so
# RSS scanning keeps running normally while fetches are paused.
MAX_MANUAL_COOLDOWN_MINUTES = 30 * 24 * 60  # 30 days


def is_manual_cooldown() -> bool:
    state = repos.get_rate_limit_state()
    return bool(state["manual"]) and is_blocked()


def set_manual_cooldown(minutes: int) -> int:
    """Pause the worker for `minutes` without touching the backoff escalation
    level. Returns the new blocked_until epoch."""
    minutes = max(1, min(int(minutes), MAX_MANUAL_COOLDOWN_MINUTES))
    blocked_until = int(time.time()) + minutes * 60
    repos.set_manual_cooldown(blocked_until)
    return blocked_until


def clear_manual_cooldown() -> None:
    repos.clear_manual_cooldown()


def status() -> dict:
    state = repos.get_rate_limit_state()
    diag = block_diagnosis()
    return {
        "blocked": is_blocked(),
        "blocked_until": int(state["blocked_until"]),
        "seconds_remaining": seconds_until_unblocked(),
        "backoff_level": int(state["backoff_level"]),
        "last_block_at": state["last_block_at"],
        "last_success_at": state["last_success_at"],
        "recently_blocked": diag["recently_blocked"],
        "manual": is_manual_cooldown(),
        # normal | suspect | fallback | manual (see module docstring)
        "mode": ("manual" if is_manual_cooldown() else "fallback" if is_fallback_mode()
                 else "suspect" if state.get("suspect_video_id") else "normal"),
        "suspect_video_id": state.get("suspect_video_id"),
    }
