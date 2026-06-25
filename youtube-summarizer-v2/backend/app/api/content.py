"""Browsing + search + quizzes over stored summaries/transcripts (item 2)."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import repos
from app.llm.quiz import generate_quiz
from app.security import require_auth

router = APIRouter(tags=["content"], dependencies=[Depends(require_auth)])


@router.get("/videos")
def list_videos(status: str | None = None, channel_id: str | None = None,
                limit: int = Query(50, le=200), offset: int = 0):
    return {"videos": repos.list_videos(status=status, channel_id=channel_id, limit=limit, offset=offset)}


@router.get("/videos/{video_id}")
def get_video(video_id: str):
    video = repos.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return {
        "video": video,
        "summary": repos.get_latest_summary(video_id),
        "transcript": repos.get_transcript(video_id),
        "quiz": repos.get_latest_quiz(video_id),
    }


@router.get("/summaries")
def list_summaries(limit: int = Query(50, le=200), offset: int = 0):
    return {"summaries": repos.list_summaries(limit=limit, offset=offset)}


@router.get("/summaries/{summary_id}")
def get_summary(summary_id: int):
    summary = repos.get_summary(summary_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary


@router.get("/transcripts/{video_id}")
def get_transcript(video_id: str):
    transcript = repos.get_transcript(video_id)
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return transcript


@router.get("/search")
def search(q: str = Query(..., min_length=2), limit: int = Query(30, le=100)):
    return {"query": q, "results": repos.search(q, limit=limit)}


@router.get("/videos/{video_id}/quiz")
def get_quiz(video_id: str):
    quiz = repos.get_latest_quiz(video_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="No quiz yet")
    return quiz


@router.post("/videos/{video_id}/quiz")
def make_quiz(video_id: str, num_questions: int = Query(5, ge=1, le=15)):
    summary = repos.get_latest_summary(video_id)
    transcript = repos.get_transcript(video_id)
    if not summary and not transcript:
        raise HTTPException(status_code=400, detail="Nothing to quiz on yet (no summary/transcript).")
    try:
        questions, model = generate_quiz(
            summary=summary["summary_md"] if summary else "",
            transcript=transcript["text"] if transcript else None,
            num_questions=num_questions,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Quiz generation failed: {e}")
    repos.save_quiz(video_id, questions, model=model)
    return {"video_id": video_id, "model": model, "questions": questions}
