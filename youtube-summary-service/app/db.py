import sqlite3
from pathlib import Path

DB_PATH = Path("data.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

# Database setup if it hasn't been already
def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_videos (
                video_id TEXT PRIMARY KEY
            )
        """)

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

def mark_video_processed(video_id: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO processed_videos (video_id) VALUES (?)",
            (video_id,)
        )
        conn.commit()
