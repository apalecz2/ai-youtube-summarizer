"""SQLite connection + schema.

One writer (the worker) and the API both touch this DB, so we enable WAL mode
for better read/write concurrency and set a busy_timeout so brief lock contention
retries instead of erroring. FTS5 virtual tables mirror transcripts + summaries
to power /search.
"""
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import DATA_DIR, DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                title      TEXT,
                added_at   INTEGER DEFAULT (strftime('%s','now')),
                active     INTEGER NOT NULL DEFAULT 1
            )
        """)

        # Carried over from v1 (same semantics).
        c.execute("""
            CREATE TABLE IF NOT EXISTS channel_filters (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                field      TEXT NOT NULL DEFAULT 'title',
                match_type TEXT NOT NULL DEFAULT 'contains',
                value      TEXT NOT NULL,
                action     TEXT NOT NULL DEFAULT 'include',
                FOREIGN KEY(channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_filters_channel ON channel_filters(channel_id)")

        # Replaces v1's processed_videos: now a full record per video.
        # status: discovered | queued | fetching | summarized | skipped | failed
        c.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                video_id      TEXT PRIMARY KEY,
                channel_id    TEXT,
                title         TEXT,
                channel_name  TEXT,
                duration      INTEGER,
                published_at  INTEGER,
                url           TEXT,
                status        TEXT NOT NULL DEFAULT 'discovered',
                skip_reason   TEXT,
                discovered_at INTEGER DEFAULT (strftime('%s','now')),
                updated_at    INTEGER DEFAULT (strftime('%s','now'))
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_videos_discovered ON videos(discovered_at)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                video_id   TEXT PRIMARY KEY,
                lang       TEXT,
                source     TEXT,
                text       TEXT NOT NULL,
                fetched_at INTEGER DEFAULT (strftime('%s','now')),
                FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id     TEXT NOT NULL,
                detail_level INTEGER NOT NULL DEFAULT 2,
                model        TEXT,
                summary_md   TEXT NOT NULL,
                created_at   INTEGER DEFAULT (strftime('%s','now')),
                FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_summaries_video ON summaries(video_id)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS quizzes (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id       TEXT NOT NULL,
                model          TEXT,
                questions_json TEXT NOT NULL,
                created_at     INTEGER DEFAULT (strftime('%s','now')),
                FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_quizzes_video ON quizzes(video_id)")

        # The work queue. The worker picks rows where status='pending' and
        # scheduled_at <= now, ordered by priority desc then scheduled_at.
        # job_type: transcript (fetch+summarize+email)
        c.execute("""
            CREATE TABLE IF NOT EXISTS fetch_jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id     TEXT NOT NULL,
                job_type     TEXT NOT NULL DEFAULT 'transcript',
                priority     INTEGER NOT NULL DEFAULT 0,
                scheduled_at INTEGER NOT NULL,
                attempts     INTEGER NOT NULL DEFAULT 0,
                status       TEXT NOT NULL DEFAULT 'pending',
                last_error   TEXT,
                detail_level INTEGER NOT NULL DEFAULT 2,
                send_email   INTEGER NOT NULL DEFAULT 1,
                created_at   INTEGER DEFAULT (strftime('%s','now'))
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_pickup ON fetch_jobs(status, scheduled_at)")

        # Single-row global backoff state (item 6).
        c.execute("""
            CREATE TABLE IF NOT EXISTS rate_limit_state (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                blocked_until   INTEGER NOT NULL DEFAULT 0,
                backoff_level   INTEGER NOT NULL DEFAULT 0,
                last_block_at   INTEGER,
                last_success_at INTEGER
            )
        """)
        c.execute("INSERT OR IGNORE INTO rate_limit_state (id, blocked_until, backoff_level) VALUES (1, 0, 0)")

        # ── FTS5 search indexes ───────────────────────────────
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts
            USING fts5(video_id UNINDEXED, text, content='transcripts', content_rowid='rowid')
        """)
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts
            USING fts5(video_id UNINDEXED, summary_md, content='summaries', content_rowid='id')
        """)

        # Keep FTS in sync via triggers.
        c.executescript("""
            CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
                INSERT INTO transcripts_fts(rowid, video_id, text) VALUES (new.rowid, new.video_id, new.text);
            END;
            CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
                INSERT INTO transcripts_fts(transcripts_fts, rowid, video_id, text) VALUES ('delete', old.rowid, old.video_id, old.text);
            END;
            CREATE TRIGGER IF NOT EXISTS transcripts_au AFTER UPDATE ON transcripts BEGIN
                INSERT INTO transcripts_fts(transcripts_fts, rowid, video_id, text) VALUES ('delete', old.rowid, old.video_id, old.text);
                INSERT INTO transcripts_fts(rowid, video_id, text) VALUES (new.rowid, new.video_id, new.text);
            END;

            CREATE TRIGGER IF NOT EXISTS summaries_ai AFTER INSERT ON summaries BEGIN
                INSERT INTO summaries_fts(rowid, video_id, summary_md) VALUES (new.id, new.video_id, new.summary_md);
            END;
            CREATE TRIGGER IF NOT EXISTS summaries_ad AFTER DELETE ON summaries BEGIN
                INSERT INTO summaries_fts(summaries_fts, rowid, video_id, summary_md) VALUES ('delete', old.id, old.video_id, old.summary_md);
            END;
            CREATE TRIGGER IF NOT EXISTS summaries_au AFTER UPDATE ON summaries BEGIN
                INSERT INTO summaries_fts(summaries_fts, rowid, video_id, summary_md) VALUES ('delete', old.id, old.video_id, old.summary_md);
                INSERT INTO summaries_fts(rowid, video_id, summary_md) VALUES (new.id, new.video_id, new.summary_md);
            END;
        """)
