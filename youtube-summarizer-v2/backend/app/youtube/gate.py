"""The global YouTube gate (item 6: intelligent backoff).

Every YouTube/yt-dlp interaction in the app must consult this module. It owns a
single piece of shared state — the backoff window — persisted in
`rate_limit_state` so it survives restarts.

Strategy:
- When a request fails with a block signature, escalate the backoff level and set
  a global `blocked_until` from BACKOFF_SCHEDULE_MINUTES. The first level is short
  (retry as soon as YouTube is likely to un-flag the IP); each repeat block jumps
  to the next, longer step, capped at the last value.
- Any successful request resets the level to 0.
- Because the worker is single-threaded, "serialization" of YouTube access falls
  out for free; this module just adds the timing/backoff policy on top.
"""
import time

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
        "currently_blocked": is_blocked(),
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


def register_block() -> int:
    """Escalate backoff. Returns the new blocked_until epoch."""
    now = int(time.time())
    state = repos.get_rate_limit_state()
    level = int(state["backoff_level"]) + 1
    blocked_until = now + _backoff_seconds(level)
    repos.set_rate_limit_state(blocked_until=blocked_until, backoff_level=level, last_block_at=now)
    return blocked_until


def register_success() -> None:
    repos.mark_success()


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
    }
