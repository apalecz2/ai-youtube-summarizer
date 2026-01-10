from contextlib import asynccontextmanager
from fastapi import FastAPI, Form, Header, Depends, HTTPException, BackgroundTasks
from dotenv import load_dotenv
import os
import sys
from typing import Any, Optional
import feedparser
import time

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
def api_summarize(background_tasks: BackgroundTasks, url: str = Form(...), auth=Depends(check_auth)):
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    # Add the long-running function to the background
    background_tasks.add_task(summarize_video_and_email, video_id=video_id, video_url=url)

    return {"status": "processing", "message": "Summarization started in the background", "video_id": video_id}

@app.post("/poll")
def api_poll(background_tasks: BackgroundTasks, auth=Depends(check_auth)):
    background_tasks.add_task(run_poll_in_background)
    return {"status": "polling_started", "message": "Checking channels for new videos in background."}

def run_poll_in_background():
    channels = get_channels()
    for channel_id in channels:
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            continue

        latest = feed.entries[0]
        
        video_id = extract_video_id_from_entry(latest)
        
        if not video_id or is_video_processed(video_id):
            continue
            
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        video_title = getattr(latest, "title", "Unknown Title")
        channel_name = getattr(latest, "author", "Unknown Channel")

        # Run the summarization logic
        summarize_video_and_email(
            video_id=video_id,
            video_url=video_url,
            video_title=video_title,
            channel_name=channel_name,
            mark_processed=True,
        )
        
        # Avoid rate limits for gemini
        time.sleep(2)


# Abstracted function to not duplicate summarization logic, called by /poll and /summarize (/poll marks them as processed)
def summarize_video_and_email(
    *,
    video_id: str,
    video_url: str,
    video_title: Optional[str] = None,
    channel_name: Optional[str] = None,
    mark_processed: bool = False,
) -> None:
    
    # 1. FETCH METADATA FIRST
    metadata = fetch_video_metadata(video_id)
    
    # 2. APPLY FILTERS
    if metadata["live_status"] == "is_upcoming":
        print(f"SKIP: {video_id} is an upcoming live event (will retry later).")
        return

    if metadata["live_status"] == "is_live":
        print(f"SKIP: {video_id} is currently live.")
        return

    if metadata["duration"] and metadata["duration"] < 60:
        print(f"SKIP: {video_id} is a Short ({metadata['duration']}s).")
        if mark_processed: mark_video_processed(video_id) # Mark so we don't check this short again
        return
    
    if metadata["duration"] and metadata["duration"] > 3600:
        print(f"SKIP: {video_id} is too long ({metadata['duration']}s).")
        if mark_processed: mark_video_processed(video_id) # Mark so we don't check this long video again
        return
    
    # 3. PROCEED TO TRANSCRIPT
    transcript = fetch_transcript(video_id)
    if not transcript:
        print(f"ERROR: No transcript for {video_id}")
        return

    summary = safe_summarize(transcript)
    if not summary:
        print(f"ERROR: Summarization failed for {video_id}")
        return
    
    # Finalize names (prioritize RSS feed data)
    final_title = video_title or metadata["title"]
    final_channel = channel_name or metadata["channel"]

    # FIX: Use final_title and final_channel here
    send_summary_email(
        video_title=final_title,
        channel_name=final_channel,
        summary=summary,
        youtube_url=video_url,
    )

    if mark_processed:
        mark_video_processed(video_id)

    print(f"SUCCESS: Summary sent for {video_id}")


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
