"""Data-access functions. Thin wrappers around SQL so the rest of the app never
writes raw queries. Grouped by entity.
"""
import json
import time
from typing import Any, Optional

from app.db.database import db


def _now() -> int:
    return int(time.time())


# ── Channels ──────────────────────────────────────────────────
def add_channel(channel_id: str, title: Optional[str] = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO channels (channel_id, title) VALUES (?, ?) "
            "ON CONFLICT(channel_id) DO UPDATE SET title=COALESCE(excluded.title, channels.title), active=1",
            (channel_id, title),
        )


def remove_channel(channel_id: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))


def get_channels(active_only: bool = True) -> list[dict]:
    with db() as conn:
        q = "SELECT channel_id, title, added_at, active FROM channels"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY added_at DESC"
        return [dict(r) for r in conn.execute(q).fetchall()]


def get_channel_ids(active_only: bool = True) -> list[str]:
    return [c["channel_id"] for c in get_channels(active_only)]


# ── Channel filters (v1 semantics) ────────────────────────────
def add_channel_filter(channel_id: str, value: str, field: str = "title",
                       match_type: str = "contains", action: str = "include") -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO channel_filters (channel_id, field, match_type, value, action) "
            "VALUES (?, ?, ?, ?, ?)",
            (channel_id, field, match_type, value, action),
        )
        return cur.lastrowid


def remove_channel_filter(filter_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM channel_filters WHERE id = ?", (filter_id,))


def get_channel_filters(channel_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, channel_id, field, match_type, value, action "
            "FROM channel_filters WHERE channel_id = ?",
            (channel_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Videos ────────────────────────────────────────────────────
def video_exists(video_id: str) -> bool:
    with db() as conn:
        return conn.execute("SELECT 1 FROM videos WHERE video_id = ?", (video_id,)).fetchone() is not None


def upsert_video(*, video_id: str, channel_id: Optional[str] = None, title: Optional[str] = None,
                 channel_name: Optional[str] = None, url: Optional[str] = None,
                 published_at: Optional[int] = None, status: str = "discovered") -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, channel_id, title, channel_name, url, published_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                channel_id   = COALESCE(excluded.channel_id, videos.channel_id),
                title        = COALESCE(excluded.title, videos.title),
                channel_name = COALESCE(excluded.channel_name, videos.channel_name),
                url          = COALESCE(excluded.url, videos.url),
                updated_at   = strftime('%s','now')
            """,
            (video_id, channel_id, title, channel_name, url, published_at, status),
        )


def set_video_status(video_id: str, status: str, skip_reason: Optional[str] = None) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE videos SET status = ?, skip_reason = ?, updated_at = strftime('%s','now') WHERE video_id = ?",
            (status, skip_reason, video_id),
        )


def dismiss_video(video_id: str) -> bool:
    """Acknowledge a failed video: move it to 'dismissed' so it drops out of the
    'needs attention' list, while preserving skip_reason for later inspection.
    Only acts on currently-failed videos. Returns True if a row changed."""
    with db() as conn:
        cur = conn.execute(
            "UPDATE videos SET status='dismissed', updated_at=strftime('%s','now') "
            "WHERE video_id = ? AND status = 'failed'",
            (video_id,),
        )
        return cur.rowcount > 0


def dismiss_failed() -> int:
    """Dismiss every failed video at once. Returns how many were dismissed."""
    with db() as conn:
        cur = conn.execute(
            "UPDATE videos SET status='dismissed', updated_at=strftime('%s','now') WHERE status='failed'"
        )
        return cur.rowcount


def update_video_metadata(video_id: str, *, title: Optional[str] = None,
                          channel_name: Optional[str] = None, duration: Optional[int] = None) -> None:
    with db() as conn:
        conn.execute(
            """UPDATE videos SET
                 title        = COALESCE(?, title),
                 channel_name = COALESCE(?, channel_name),
                 duration     = COALESCE(?, duration),
                 updated_at   = strftime('%s','now')
               WHERE video_id = ?""",
            (title, channel_name, duration, video_id),
        )


def get_video(video_id: str) -> Optional[dict]:
    with db() as conn:
        row = conn.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        return dict(row) if row else None


def list_videos(*, status: Optional[str] = None, channel_id: Optional[str] = None,
                limit: int = 50, offset: int = 0) -> list[dict]:
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if channel_id:
        clauses.append("channel_id = ?")
        params.append(channel_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.extend([limit, offset])
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM videos{where} ORDER BY discovered_at DESC LIMIT ? OFFSET ?", params
        ).fetchall()
        return [dict(r) for r in rows]


# ── Transcripts ───────────────────────────────────────────────
def save_transcript(video_id: str, text: str, lang: Optional[str] = None, source: Optional[str] = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO transcripts (video_id, lang, source, text) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(video_id) DO UPDATE SET text=excluded.text, lang=excluded.lang, "
            "source=excluded.source, fetched_at=strftime('%s','now')",
            (video_id, lang, source, text),
        )


def get_transcript(video_id: str) -> Optional[dict]:
    with db() as conn:
        row = conn.execute("SELECT * FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()
        return dict(row) if row else None


# ── Summaries ─────────────────────────────────────────────────
def save_summary(video_id: str, summary_md: str, detail_level: int = 2, model: Optional[str] = None) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO summaries (video_id, detail_level, model, summary_md) VALUES (?, ?, ?, ?)",
            (video_id, detail_level, model, summary_md),
        )
        return cur.lastrowid


def get_summary(summary_id: int) -> Optional[dict]:
    with db() as conn:
        row = conn.execute("SELECT * FROM summaries WHERE id = ?", (summary_id,)).fetchone()
        return dict(row) if row else None


def get_latest_summary(video_id: str) -> Optional[dict]:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM summaries WHERE video_id = ? ORDER BY created_at DESC LIMIT 1", (video_id,)
        ).fetchone()
        return dict(row) if row else None


def list_summaries(*, limit: int = 50, offset: int = 0) -> list[dict]:
    """Latest summary per video, joined with video metadata, newest first."""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.video_id, s.detail_level, s.model, s.created_at,
                   v.title, v.channel_name, v.url, v.duration
            FROM summaries s
            JOIN (
                SELECT video_id, MAX(created_at) AS mx FROM summaries GROUP BY video_id
            ) latest ON latest.video_id = s.video_id AND latest.mx = s.created_at
            JOIN videos v ON v.video_id = s.video_id
            ORDER BY s.created_at DESC LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Quizzes ───────────────────────────────────────────────────
def save_quiz(video_id: str, questions: list[dict], model: Optional[str] = None) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO quizzes (video_id, model, questions_json) VALUES (?, ?, ?)",
            (video_id, model, json.dumps(questions)),
        )
        return cur.lastrowid


def get_latest_quiz(video_id: str) -> Optional[dict]:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM quizzes WHERE video_id = ? ORDER BY created_at DESC LIMIT 1", (video_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["questions"] = json.loads(d.pop("questions_json"))
        return d


# ── Search (FTS5) ─────────────────────────────────────────────
def search(query: str, limit: int = 30) -> list[dict]:
    """Full-text search over summaries and transcripts. Returns one row per video
    with a snippet and which source(s) matched."""
    with db() as conn:
        rows = conn.execute(
            """
            WITH hits AS (
                SELECT video_id, 'summary' AS source,
                       snippet(summaries_fts, 1, '[', ']', ' … ', 12) AS snippet,
                       bm25(summaries_fts) AS rank
                FROM summaries_fts WHERE summaries_fts MATCH ?
                UNION ALL
                SELECT video_id, 'transcript' AS source,
                       snippet(transcripts_fts, 1, '[', ']', ' … ', 12) AS snippet,
                       bm25(transcripts_fts) AS rank
                FROM transcripts_fts WHERE transcripts_fts MATCH ?
            )
            SELECT h.video_id, MIN(h.rank) AS rank,
                   GROUP_CONCAT(DISTINCT h.source) AS sources,
                   (SELECT snippet FROM hits h2 WHERE h2.video_id = h.video_id ORDER BY rank LIMIT 1) AS snippet,
                   v.title, v.channel_name, v.url
            FROM hits h JOIN videos v ON v.video_id = h.video_id
            GROUP BY h.video_id
            ORDER BY rank ASC
            LIMIT ?
            """,
            (query, query, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Fetch jobs (the work queue) ───────────────────────────────
def enqueue_job(*, video_id: str, scheduled_at: int, job_type: str = "transcript",
                priority: int = 0, detail_level: int = 2, send_email: bool = True) -> int:
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO fetch_jobs (video_id, job_type, priority, scheduled_at, detail_level, send_email)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (video_id, job_type, priority, scheduled_at, detail_level, 1 if send_email else 0),
        )
        return cur.lastrowid


def claim_due_job(now: Optional[int] = None) -> Optional[dict]:
    """Atomically grab the next due pending job and mark it 'running'.
    Returns None if nothing is due. Highest priority, then earliest scheduled."""
    now = now or _now()
    with db() as conn:
        row = conn.execute(
            """SELECT * FROM fetch_jobs
               WHERE status = 'pending' AND scheduled_at <= ?
               ORDER BY priority DESC, scheduled_at ASC LIMIT 1""",
            (now,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE fetch_jobs SET status='running', attempts=attempts+1 WHERE id=?", (row["id"],)
        )
        return dict(row)


def complete_job(job_id: int) -> None:
    with db() as conn:
        conn.execute("UPDATE fetch_jobs SET status='done', last_error=NULL WHERE id=?", (job_id,))


def fail_job(job_id: int, error: str) -> None:
    with db() as conn:
        conn.execute("UPDATE fetch_jobs SET status='failed', last_error=? WHERE id=?", (error, job_id))


def reschedule_job(job_id: int, scheduled_at: int, error: Optional[str] = None) -> None:
    """Put a job back to pending for a later time (used on transient errors / retry-later)."""
    with db() as conn:
        conn.execute(
            "UPDATE fetch_jobs SET status='pending', scheduled_at=?, last_error=? WHERE id=?",
            (scheduled_at, error, job_id),
        )


def reschedule_after_block(job_id: int, scheduled_at: int) -> None:
    """Reschedule a job that hit a global YouTube block. The block isn't the job's
    fault, so refund the attempt that claim_due_job charged for it."""
    with db() as conn:
        conn.execute(
            "UPDATE fetch_jobs SET status='pending', scheduled_at=?, "
            "attempts=MAX(0, attempts-1), last_error='blocked: backing off' WHERE id=?",
            (scheduled_at, job_id),
        )


def prune_jobs(keep_done_after: int) -> int:
    """Delete done/failed jobs older than a cutoff epoch. Returns rows removed."""
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM fetch_jobs WHERE status IN ('done','failed') AND created_at < ?",
            (keep_done_after,),
        )
        return cur.rowcount


def has_pending_job(video_id: str) -> bool:
    with db() as conn:
        return conn.execute(
            "SELECT 1 FROM fetch_jobs WHERE video_id=? AND status IN ('pending','running')",
            (video_id,),
        ).fetchone() is not None


def upcoming_jobs(limit: int = 100) -> list[dict]:
    """Pending jobs joined with their video info, in the order the worker will
    claim them (highest priority first, then earliest scheduled). Used to show
    when each video is expected to be processed."""
    with db() as conn:
        rows = conn.execute(
            """SELECT j.id, j.video_id, j.scheduled_at, j.priority, j.attempts,
                      v.title, v.channel_name, v.url
               FROM fetch_jobs j
               LEFT JOIN videos v ON v.video_id = j.video_id
               WHERE j.status = 'pending'
               ORDER BY j.priority DESC, j.scheduled_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def cancel_pending_job(video_id: str) -> bool:
    """Remove a video's pending job(s) from the queue and mark the video
    'cancelled'. Deliberately does NOT touch a job already 'running' in the
    worker (it's mid-fetch in a thread). Returns True if a pending job was
    removed. The video row stays, so discovery won't re-queue it on the next
    scan — use 'Summarize now' to re-queue it intentionally."""
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM fetch_jobs WHERE video_id = ? AND status = 'pending'",
            (video_id,),
        )
        if cur.rowcount == 0:
            return False
        conn.execute(
            "UPDATE videos SET status='cancelled', skip_reason='removed from queue', "
            "updated_at=strftime('%s','now') WHERE video_id = ?",
            (video_id,),
        )
        return True


def job_queue_stats() -> dict[str, int]:
    with db() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM fetch_jobs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}


# ── Rate limit / backoff state (item 6) ───────────────────────
def get_rate_limit_state() -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM rate_limit_state WHERE id = 1").fetchone()
        return dict(row)


def set_rate_limit_state(*, blocked_until: int, backoff_level: int, last_block_at: Optional[int] = None) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE rate_limit_state SET blocked_until=?, backoff_level=?, last_block_at=COALESCE(?, last_block_at) WHERE id=1",
            (blocked_until, backoff_level, last_block_at),
        )


def mark_success() -> None:
    """Clear backoff after a clean YouTube call."""
    with db() as conn:
        conn.execute(
            "UPDATE rate_limit_state SET backoff_level=0, blocked_until=0, last_success_at=strftime('%s','now') WHERE id=1"
        )
