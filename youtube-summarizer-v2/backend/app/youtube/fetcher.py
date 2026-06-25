"""yt-dlp-only access to YouTube (item 1: single tool, with cookies).

We deliberately use ONLY yt-dlp (no youtube-transcript-api) and authenticate with
a cookies file exported from the dedicated throwaway account. A single
`extract_info` call yields both the metadata we filter on *and* the subtitle
track URLs, so a full fetch is just two network hits (info + one subtitle
download) — keeping our footprint small.
"""
import json
import os
from typing import Optional
from urllib.parse import urlparse, parse_qs

import yt_dlp

from app import config
from app.config import YTDLP_COOKIES_FILE
from app.youtube import gate

# Manual subtitle languages we accept, in order of preference. "en-orig" is the
# original-language track YouTube exposes for English videos and is often the only
# one present — a plain "en" lookup misses it (see the yt-dlp `--sub-langs "en.*,en"`
# note), so we list it explicitly.
_PREFERRED_LANGS = ("en", "en-orig", "en-US", "en-GB", "en-us", "en-gb")


def _impersonate_target():
    """Parse config.YTDLP_IMPERSONATE into an ImpersonateTarget, or None if unset/
    unavailable. Lets us mimic a real browser to clear front-door bot checks."""
    if not config.YTDLP_IMPERSONATE:
        return None
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget
        return ImpersonateTarget.from_str(config.YTDLP_IMPERSONATE)
    except Exception as e:  # noqa: BLE001 - bad value or curl_cffi missing
        print(f"[fetcher] impersonation '{config.YTDLP_IMPERSONATE}' unavailable: {e}")
        return None


def extract_video_id(url: str) -> Optional[str]:
    """Supports watch?v=, youtu.be/, and /embed/ forms (same as v1)."""
    parsed = urlparse(url)
    if parsed.netloc.endswith("youtu.be"):
        return parsed.path.lstrip("/") or None
    if parsed.path == "/watch":
        return parse_qs(parsed.query).get("v", [None])[0]
    if parsed.path.startswith("/embed/"):
        parts = parsed.path.split("/")
        return parts[2] if len(parts) > 2 else None
    return None


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # We only want metadata + caption URLs, never a media stream. yt-dlp still
        # runs format selection during extract_info (before honoring skip_download),
        # so when the player client returns no selectable formats it raises
        # "Requested format is not available". Treating that as non-fatal lets the
        # info dict (with subtitles) come back instead of failing the whole job.
        "ignore_no_formats_error": True,
        "logger": None,
        # The "web" client no longer returns caption tracks (YouTube gates them
        # behind PO tokens), which surfaces as a false "no transcript". The "tv"
        # and "ios" clients still expose the auto-caption tracks and both work
        # alongside cookies — unlike "android", which YouTube silently disables
        # when cookies are supplied. (Confirmed via diagnose_transcript.py.)
        "extractor_args": {"youtube": {"player_client": ["tv", "ios"]}},
    }
    if YTDLP_COOKIES_FILE and os.path.exists(YTDLP_COOKIES_FILE):
        opts["cookiefile"] = YTDLP_COOKIES_FILE
    if config.YTDLP_PROXY:
        opts["proxy"] = config.YTDLP_PROXY
    target = _impersonate_target()
    if target is not None:
        opts["impersonate"] = target
    return opts


def _video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def extract_info(video_id: str) -> dict:
    """Single extract_info call. Raises yt_dlp.utils.DownloadError on failure
    (the worker inspects the message via gate.is_block_error)."""
    with yt_dlp.YoutubeDL(_base_opts()) as ydl:  # type: ignore
        return ydl.extract_info(_video_url(video_id), download=False)


def metadata_from_info(info: dict) -> dict:
    return {
        "title": info.get("title", "Unknown Title"),
        "channel": info.get("uploader") or info.get("channel") or "Unknown Channel",
        "channel_id": info.get("channel_id"),
        "duration": info.get("duration") or 0,
        "live_status": info.get("live_status"),
    }


def _pick_subtitle_track(info: dict) -> Optional[tuple[str, str, str]]:
    """Return (lang, source, url) for the best available English caption track,
    preferring manual subtitles over auto-generated. Requests json3 format."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    def find_url(table: dict, lang: str) -> Optional[str]:
        tracks = table.get(lang)
        if not tracks:
            return None
        # Prefer json3 (easy to parse); fall back to first available.
        for t in tracks:
            if t.get("ext") == "json3":
                return t.get("url")
        return tracks[0].get("url")

    for lang in _PREFERRED_LANGS:
        url = find_url(manual, lang)
        if url:
            return (lang, "manual", url)
    for lang in _PREFERRED_LANGS:
        url = find_url(auto, lang)
        if url:
            return (lang, "auto", url)
    # Last resort: any english-ish manual track key.
    for table, source in ((manual, "manual"), (auto, "auto")):
        for lang, tracks in table.items():
            if lang.lower().startswith("en") and tracks:
                return (lang, source, tracks[0].get("url"))
    return None


def available_caption_langs(info: dict) -> dict:
    """Diagnostics for the 'no usable transcript' case: which caption tracks the
    video actually exposes, so the failure reason/email can explain *why* we
    couldn't get one (e.g. only non-English, or none at all)."""
    return {
        "manual": sorted((info.get("subtitles") or {}).keys()),
        "automatic": sorted((info.get("automatic_captions") or {}).keys()),
    }


def _parse_json3(raw: bytes) -> str:
    data = json.loads(raw.decode("utf-8", errors="replace"))
    parts: list[str] = []
    for event in data.get("events", []):
        for seg in event.get("segs", []) or []:
            text = seg.get("utf8")
            if text and text != "\n":
                parts.append(text)
    return " ".join(" ".join(parts).split())


def _parse_vtt(raw: bytes) -> str:
    """Minimal WebVTT fallback: keep caption text lines, drop cues/timestamps."""
    lines: list[str] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        if line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        lines.append(line)
    # De-dupe consecutive duplicate lines (common in auto-captions).
    deduped: list[str] = []
    for ln in lines:
        if not deduped or deduped[-1] != ln:
            deduped.append(ln)
    return " ".join(" ".join(deduped).split())


def fetch_transcript_from_info(info: dict) -> Optional[dict]:
    """Download + parse the chosen caption track. Returns
    {text, lang, source} or None if no usable captions exist.
    Uses yt-dlp's urlopen so cookies/headers are applied to the subtitle request."""
    pick = _pick_subtitle_track(info)
    if not pick:
        return None
    lang, source, url = pick
    if not url:
        return None

    # The subtitle file lives on a *separate* Google video server. A flagged IP is
    # frequently let through the metadata call but gets 429'd here — the exact wall
    # described in our yt-dlp notes. Surface that as a BlockedError so the worker
    # backs off + requeues, instead of silently recording "no transcript".
    try:
        with yt_dlp.YoutubeDL(_base_opts()) as ydl:  # type: ignore
            raw = ydl.urlopen(url).read()
    except Exception as e:  # noqa: BLE001
        if gate.is_block_error(e):
            raise gate.BlockedError(f"subtitle download blocked: {e}")
        raise

    # Even with a 200, a throttled IP often gets an HTML challenge page or an empty
    # body instead of the caption file. A real track existed, so treat non-caption
    # data as a rate-limit signal rather than a caption-less video.
    head = raw[:512].lstrip().lower()
    looks_like_captions = b'"events"' in raw[:2000] or b"webvtt" in head or url.find("fmt=json3") != -1
    if not raw or (not looks_like_captions and (head.startswith(b"<") or b"too many requests" in head)):
        raise gate.BlockedError(
            f"subtitle download for '{lang}' returned {len(raw)} bytes of non-caption "
            f"data — Google's subtitle server is likely rate-limiting this IP (429)"
        )

    if b'"events"' in raw[:2000] or url.find("fmt=json3") != -1:
        text = _parse_json3(raw)
    else:
        text = _parse_vtt(raw)

    text = text.strip()
    if not text:
        return None
    return {"text": text, "lang": lang, "source": source}
