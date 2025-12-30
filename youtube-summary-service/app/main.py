from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv
import os

from app.db import init_db

from app.youtube import extract_video_id, fetch_transcript
from fastapi import HTTPException

from app.gemini import safe_summarize

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

# temp test endpoint
@app.post("/test/transcript")
def test_transcript(url: str):
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
def test_summarize(url: str):
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
