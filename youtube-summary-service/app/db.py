import sqlite3
from pathlib import Path

# This has to point to the folder that's persisted in docker
DB_DIR = Path("data")
DB_PATH = DB_DIR / "data.db"
PROCESSED_VIDEOS_MAX = 100

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
            "DELETE FROM channels WHERE channel_id = ?",
            (channel_id,)
        )
        conn.commit()


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
