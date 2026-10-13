"""Centralized configuration loaded from the environment.

Everything reads settings from here so there's one place to see what's
configurable and what the defaults are.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _minutes_list(name: str, default: str) -> list[int]:
    raw = os.getenv(name, default)
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return out or [1440, 2880, 5760, 10080]


# ── Paths ─────────────────────────────────────────────────────
# Mounted as a Docker volume so the DB + cookies survive restarts.
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "data.db"

# ── Web auth ──────────────────────────────────────────────────
APP_PASSWORD_SHA256 = os.getenv("APP_PASSWORD_SHA256", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")
SESSION_COOKIE_NAME = "yts_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days

# ── Gemini ────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── Email ─────────────────────────────────────────────────────
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = _int("EMAIL_PORT", 587)
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
EMAIL_SENDTO = os.getenv("EMAIL_SENDTO")
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")

# ── YouTube / anti-bot timing ─────────────────────────────────
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "data/cookies.txt")
# Optional egress controls to escape an IP rate-limit without code changes.
# YTDLP_PROXY: e.g. "http://user:pass@host:port" (routes all yt-dlp traffic).
# YTDLP_IMPERSONATE: a curl_cffi target like "chrome:windows-10" (requires the
# curl_cffi package). Empty = disabled.
YTDLP_PROXY = os.getenv("YTDLP_PROXY", "")
YTDLP_IMPERSONATE = os.getenv("YTDLP_IMPERSONATE", "")
POLL_INTERVAL_MINUTES = _int("POLL_INTERVAL_MINUTES", 30)
FETCH_SPREAD_MINUTES = _int("FETCH_SPREAD_MINUTES", 28)
FETCH_JITTER_MIN_SECONDS = _int("FETCH_JITTER_MIN_SECONDS", 20)
FETCH_JITTER_MAX_SECONDS = _int("FETCH_JITTER_MAX_SECONDS", 90)
# When fetching resumes after a pause/backoff, the overdue backlog is re-spread
# one job at a time, ~this many seconds apart on average (each gap randomized to
# 50%-150% of it), capped at RESUME_SPREAD_MAX_MINUTES in total. Much gentler than
# the discovery window, since a big backlog is exactly what re-triggers a 429.
RESUME_SPREAD_SECONDS_PER_JOB = _int("RESUME_SPREAD_SECONDS_PER_JOB", 180)
RESUME_SPREAD_MAX_MINUTES = _int("RESUME_SPREAD_MAX_MINUTES", 480)

# ── Backoff (item 6) ──────────────────────────────────────────
# How long the main (yt-dlp) fetch path is suspended once a block is CONFIRMED
# (two different videos failing in a row). During that time every video goes
# through the direct-Gemini fallback instead. Each repeat confirmation after a
# suspension moves one step further down the list (the last step repeats).
# Deliberately a new variable name: the old BACKOFF_SCHEDULE_MINUTES held 5-720
# minute steps and an existing .env would otherwise override these.
BACKOFF_SCHEDULE_MINUTES = _minutes_list("FETCH_SUSPEND_SCHEDULE_MINUTES", "1440,2880,5760,10080")
# A first failure waits for a second, different video to confirm a block. If none
# turns up within this long, that video is summarized via the fallback anyway.
SUSPECT_TIMEOUT_MINUTES = _int("SUSPECT_TIMEOUT_MINUTES", 180)

# ── Gemini model chain + daily request limits ─────────────────
# "model:requests-per-day" pairs in fallback order. A model whose daily count has
# reached its limit is skipped BEFORE a request is made (the counter resets at
# midnight Pacific, like Google's). The last entry is the safety net.
def _model_chain(name: str, default: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for part in os.getenv(name, default).split(","):
        model, _, limit = part.strip().partition(":")
        if model:
            try:
                out.append((model, int(limit)))
            except ValueError:
                out.append((model, 10**9))   # no/invalid limit -> effectively unlimited
    return out or _model_chain(name, default)


GEMINI_MODEL_CHAIN = _model_chain(
    "GEMINI_MODEL_CHAIN",
    "gemini-3.8-flash:20,gemini-3.7-flash:20,gemini-3.6-flash:20,gemini-3.5-flash-lite:500",
)

# ── Gemini limits / direct-video fallback ─────────────────────
# Per-model input-token budget per minute (provider quota is 250k), and the share
# of it we allow ourselves to use, so estimates that run a little low don't 429.
GEMINI_INPUT_TOKENS_PER_MINUTE = _int("GEMINI_INPUT_TOKENS_PER_MINUTE", 250_000)
GEMINI_TPM_SAFETY_PERCENT = _int("GEMINI_TPM_SAFETY_PERCENT", 85)
# Measured on gemini-3.x flash: a YouTube video costs ~103 input tokens per second.
VIDEO_TOKENS_PER_SECOND = _int("VIDEO_TOKENS_PER_SECOND", 103)
# Longest slice of a video sent in one request, in tokens (~19 min at 103 tok/s).
# Longer videos are summarized in slices and consolidated, which keeps every
# request well under the per-minute budget.
VIDEO_SEGMENT_TOKENS = _int("VIDEO_SEGMENT_TOKENS", 120_000)

# Public base URL of the web app (used for "Open in app" links in emails).
APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")

# Skip rules (seconds). Mirrors v1 thresholds.
MIN_DURATION_SECONDS = _int("MIN_DURATION_SECONDS", 60)        # below = Short
MAX_DURATION_SECONDS = _int("MAX_DURATION_SECONDS", 18000)     # above = too long for auto-poll

# Frontend served from this dir if present (built React SPA).
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", "frontend_dist"))


def serve_frontend() -> bool:
    return FRONTEND_DIST.is_dir() and (FRONTEND_DIST / "index.html").exists()
