from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi import Form
from fastapi import Header
from fastapi import Depends
from dotenv import load_dotenv
import os
import sys

from app.db import init_db, add_channel, remove_channel, get_channels

from app.youtube import extract_video_id, fetch_transcript
from fastapi import HTTPException

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





# temp test endpoint
@app.post("/test/transcript")
def test_transcript(url: str = Form(...)):
    video_id = extract_video_id(url)

    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    transcript = fetch_transcript(video_id)

    if not transcript:
        raise HTTPException(
            status_code=404,
            detail="Transcript unavailable"
        )

    return {
        "video_id": video_id,
        "transcript_preview": transcript[:500]
    }

# temp summary endpoint
@app.post("/test/summarize")
def test_summarize(url: str = Form(...)):
    from app.youtube import extract_video_id, fetch_transcript
    from fastapi import HTTPException

    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    transcript = fetch_transcript(video_id)
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript unavailable")

    summary = safe_summarize(transcript)
    if not summary:
        raise HTTPException(status_code=500, detail="Gemini summarization failed")

    return {
        "video_id": video_id,
        "summary": summary
    }


@app.post("/test/email")
def test_email(url: str = Form(...)):
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    transcript = fetch_transcript(video_id)
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript unavailable")

    summary = safe_summarize(transcript)
    if not summary:
        raise HTTPException(status_code=500, detail="Gemini summarization failed")

    metadata = fetch_video_metadata(video_id)

    success = send_summary_email(
        video_title=metadata["title"],
        channel_name=metadata["channel"],
        summary=summary,
        youtube_url=url
    )

    if not success:
        raise HTTPException(status_code=500, detail="Email send failed")

    return {"status": "email sent"}
