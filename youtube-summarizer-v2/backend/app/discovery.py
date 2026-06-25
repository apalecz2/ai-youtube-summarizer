"""Upload discovery (item 1, cheap half).

Uses YouTube's RSS feed (plain HTTP, not bot-flagged) to find new uploads, applies
each channel's title filters, records new videos, and enqueues a transcript job
with a RANDOM scheduled time spread across the window. The expensive yt-dlp work
happens later, in the worker, sprinkled over the next ~30 minutes — never in a
burst right after discovery.
"""
import random
import time
from calendar import timegm
from typing import Any, Optional

import feedparser

from app.config import FETCH_SPREAD_MINUTES
from app.db import repos
from app.filters import passes_filters


def _video_id_from_entry(entry: Any) -> Optional[str]:
    vid = getattr(entry, "yt_videoid", None)
    if isinstance(vid, str):
        return vid
    if isinstance(vid, list) and vid and isinstance(vid[0], dict):
        return vid[0].get("yt_videoid")
    return None


def _published_epoch(entry: Any) -> Optional[int]:
    pp = getattr(entry, "published_parsed", None)
    return timegm(pp) if pp else None


def run_discovery() -> dict:
    """Scan all active channels once. Returns a small stats dict for logging/UI."""
    now = int(time.time())
    spread = max(1, FETCH_SPREAD_MINUTES) * 60
    stats = {"channels": 0, "new": 0, "filtered": 0}

    for channel_id in repos.get_channel_ids(active_only=True):
        stats["channels"] += 1
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        if not feed.entries:
            continue

        rules = repos.get_channel_filters(channel_id)

        # Feed is newest-first; walk oldest-first so a burst of uploads is queued
        # in chronological order.
        for entry in reversed(feed.entries):
            video_id = _video_id_from_entry(entry)
            if not video_id or repos.video_exists(video_id):
                continue

            title = getattr(entry, "title", "Unknown Title")
            channel_name = getattr(entry, "author", None)
            url = f"https://www.youtube.com/watch?v={video_id}"

            # Cheap title filter on the RSS data before any yt-dlp work.
            if not passes_filters(rules, {"title": title}):
                repos.upsert_video(video_id=video_id, channel_id=channel_id, title=title,
                                   channel_name=channel_name, url=url,
                                   published_at=_published_epoch(entry), status="skipped")
                repos.set_video_status(video_id, "skipped", "did not pass channel filters")
                stats["filtered"] += 1
                continue

            repos.upsert_video(video_id=video_id, channel_id=channel_id, title=title,
                               channel_name=channel_name, url=url,
                               published_at=_published_epoch(entry), status="queued")

            # Random offset within the window => human-like, spread-out fetches.
            scheduled_at = now + random.randint(0, spread)
            repos.enqueue_job(video_id=video_id, scheduled_at=scheduled_at,
                              priority=0, detail_level=2, send_email=True)
            stats["new"] += 1

    return stats
