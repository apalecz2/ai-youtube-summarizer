from contextlib import asynccontextmanager
from fastapi import FastAPI, Form, Header, Depends, HTTPException
from dotenv import load_dotenv
import os
import sys
from typing import Any, Optional
import feedparser

from app.db import init_db, add_channel, remove_channel, get_channels, is_video_processed, mark_video_processed

from app.youtube import extract_video_id, fetch_transcript

from app.gemini import safe_summarize

from app.emailer import send_summary_email
from app.youtube import fetch_video_metadata

# Load environment variables
load_dotenv()

# Ensure db created automatically, and tables exist before any api calls
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="YouTube Summary Service",
    version="0.1.0",
    lifespan=lifespan
)

# Check app status endpoint
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "youtube-summary-service"
    }

API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN")
if not API_AUTH_TOKEN:
    print("Ensure .env file is configured correctly - no API_AUTH_TOKEN.")
    # Exit the process with a non-zero status code to stop the server
    sys.exit(1)

def check_auth(x_api_key: str | None = Header(None)):
    if x_api_key != API_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# Add a channel
@app.post("/channels")
def api_add_channel(channel_id: str = Form(...), auth=Depends(check_auth)):
    add_channel(channel_id)
    return {"status": "channel added", "channel_id": channel_id}

# Remove channel
@app.delete("/channels/{channel_id}")
def api_remove_channel(channel_id: str, auth=Depends(check_auth)):
    remove_channel(channel_id)
    return {"status": "channel removed", "channel_id": channel_id}

# List channels
@app.get("/channels")
def api_list_channels(auth=Depends(check_auth)):
    channels = get_channels()
    return {"channels": channels}

# Summary endpoint to send email for given video
@app.post("/summarize")
def api_summarize(url: str = Form(...), auth=Depends(check_auth)):
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    result = summarize_video_and_email(
        video_id=video_id,
        video_url=url,
    )

    if result["status"] == "no_transcript":
        raise HTTPException(status_code=404, detail="Transcript unavailable")
    if result["status"] == "summarization_failed":
        raise HTTPException(status_code=500, detail="Summarization failed")

    return result

@app.post("/poll")
def api_poll(auth=Depends(check_auth)):
    channels = get_channels()
    results = []

    for channel_id in channels:
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            continue

        latest = feed.entries[0]
        video_id = extract_video_id_from_entry(latest)
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        if not video_id or not video_url:
            continue
            
        if is_video_processed(video_id):
            continue
        
        # Note that this still marks videos processed even if the summary / transcript / email fails
        result = summarize_video_and_email(
            video_id=video_id,
            video_url=video_url,
            mark_processed=True,
        )

        results.append(result)

    return {"results": results}


# Abstracted function to not duplicate summarization logic, called by /poll and /summarize (/poll marks them as processed)
def summarize_video_and_email(
    *,
    video_id: str,
    video_url: str,
    mark_processed: bool = False,
) -> dict:
    transcript = fetch_transcript(video_id)
    if not transcript:
        return {"status": "no_transcript"}

    summary = safe_summarize(transcript)
    if not summary:
        return {"status": "summarization_failed"}

    metadata = fetch_video_metadata(video_id)

    email_success = send_summary_email(
        video_title=metadata["title"],
        channel_name=metadata["channel"],
        summary=summary,
        youtube_url=video_url,
    )

    if mark_processed:
        mark_video_processed(video_id)

    return {
        "status": "ok",
        "summary": summary,
        "email_sent": email_success,
        "video_id": video_id,
    }

def extract_video_id_from_entry(entry: Any) -> Optional[str]:
    video_id = getattr(entry, "yt_videoid", None)

    if isinstance(video_id, str):
        return video_id

    # Sometimes feedparser returns a list
    if isinstance(video_id, list) and len(video_id) > 0:
        first = video_id[0]
        if isinstance(first, dict) and "yt_videoid" in first:
            return first["yt_videoid"]

    return None
