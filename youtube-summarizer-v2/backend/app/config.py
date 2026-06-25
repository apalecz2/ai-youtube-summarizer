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
    return out or [5, 15, 45, 120, 360, 720]


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

# ── Backoff (item 6) ──────────────────────────────────────────
BACKOFF_SCHEDULE_MINUTES = _minutes_list("BACKOFF_SCHEDULE_MINUTES", "5,15,45,120,360,720")

# Public base URL of the web app (used for "Open in app" links in emails).
APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")

# Skip rules (seconds). Mirrors v1 thresholds.
MIN_DURATION_SECONDS = _int("MIN_DURATION_SECONDS", 60)        # below = Short
MAX_DURATION_SECONDS = _int("MAX_DURATION_SECONDS", 18000)     # above = too long for auto-poll

# Frontend served from this dir if present (built React SPA).
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", "frontend_dist"))


def serve_frontend() -> bool:
    return FRONTEND_DIST.is_dir() and (FRONTEND_DIST / "index.html").exists()
