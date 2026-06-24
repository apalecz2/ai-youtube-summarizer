import sqlite3
from pathlib import Path

# This has to point to the folder that's persisted in docker
DB_DIR = Path("data")
DB_PATH = DB_DIR / "data.db"
# Polling re-scans every entry in each channel's RSS feed (~15 most recent
# uploads) on each poll and skips ones already in this table. The cap must
# therefore comfortably exceed (number of channels x feed window), or a video
# still visible in the feed could be pruned and re-summarized (duplicate email).
# Rows are tiny (id + timestamp), so keep generous headroom: ~66 channels here.
PROCESSED_VIDEOS_MAX = 1000

def get_connection():
    return sqlite3.connect(DB_PATH)

# Database setup if it hasn't been already
def init_db():
    
    # Create the directory if it doesn't exist (prevents FileNotFoundError)
    DB_DIR.mkdir(exist_ok=True)
    
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY
            )
        """)

        # Per-channel filter rules. Extensible: `field` is what to test
        # (e.g. "title"), `match_type` is how (e.g. "contains"), `value` is the
        # operand, and `action` is "include" or "exclude".
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channel_filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                field TEXT NOT NULL DEFAULT 'title',
                match_type TEXT NOT NULL DEFAULT 'contains',
                value TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT 'include',
                FOREIGN KEY(channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
            )
        """)

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_filters_channel_id ON channel_filters(channel_id)"
        )

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_videos (
                video_id TEXT PRIMARY KEY,
                processed_at INTEGER
            )
        """)

        cursor.execute("PRAGMA table_info(processed_videos)")
        processed_videos_columns = {row[1] for row in cursor.fetchall()}
        if "processed_at" not in processed_videos_columns:
            cursor.execute("ALTER TABLE processed_videos ADD COLUMN processed_at INTEGER")
            cursor.execute("UPDATE processed_videos SET processed_at = strftime('%s','now') WHERE processed_at IS NULL")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_processed_videos_processed_at ON processed_videos(processed_at)")

        conn.commit()


# Channel helper functions

def add_channel(channel_id: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO channels (channel_id) VALUES (?)",
            (channel_id,)
        )
        conn.commit()

def remove_channel(channel_id: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM channel_filters WHERE channel_id = ?",
            (channel_id,)
        )
        cursor.execute(
            "DELETE FROM channels WHERE channel_id = ?",
            (channel_id,)
        )
        conn.commit()


# Channel filter helpers

def add_channel_filter(channel_id: str, value: str, field: str = "title",
                       match_type: str = "contains", action: str = "include") -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO channel_filters (channel_id, field, match_type, value, action)
            VALUES (?, ?, ?, ?, ?)
            """,
            (channel_id, field, match_type, value, action)
        )
        conn.commit()
        return cursor.lastrowid

def remove_channel_filter(filter_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM channel_filters WHERE id = ?",
            (filter_id,)
        )
        conn.commit()

def get_channel_filters(channel_id: str) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, channel_id, field, match_type, value, action "
            "FROM channel_filters WHERE channel_id = ?",
            (channel_id,)
        )
        return [
            {
                "id": row[0],
                "channel_id": row[1],
                "field": row[2],
                "match_type": row[3],
                "value": row[4],
                "action": row[5],
            }
            for row in cursor.fetchall()
        ]


# Processed video helpers

def get_channels() -> list[str]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT channel_id FROM channels")
        return [row[0] for row in cursor.fetchall()]
    
def is_video_processed(video_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM processed_videos WHERE video_id = ?",
            (video_id,)
        )
        return cursor.fetchone() is not None

def prune_processed_videos(max_rows: int):
    if max_rows <= 0:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM processed_videos
            WHERE video_id NOT IN (
                SELECT video_id
                FROM processed_videos
                ORDER BY processed_at DESC
                LIMIT ?
            )
            """,
            (max_rows,)
        )
        conn.commit()

def mark_video_processed(video_id: str, max_rows: int = PROCESSED_VIDEOS_MAX):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO processed_videos (video_id, processed_at)
            VALUES (?, strftime('%s','now'))
            ON CONFLICT(video_id) DO UPDATE SET processed_at = excluded.processed_at
            """,
            (video_id,)
        )
        conn.commit()

    prune_processed_videos(max_rows)
