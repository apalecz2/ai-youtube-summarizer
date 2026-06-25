"""Multiple-choice quiz generation (item 2) — a single-shot prompt.

Given a video's summary (and optionally transcript), produce a small MCQ quiz as
structured JSON. We ask for strict JSON and parse defensively (stripping any code
fences the model may add).
"""
import json
import re
from typing import Optional

from app.llm.provider import generate

MAX_CONTENT_CHARS = 120_000

_PROMPT = (
    "You are a quiz generator. Based ONLY on the content below, write {n} multiple-choice "
    "questions that test understanding of the video's key ideas. Each question has exactly 4 "
    "options, one correct. Vary difficulty. Do not reference 'the summary' or 'the video' in the "
    "questions — ask about the actual content.\n\n"
    "Respond with STRICT JSON only (no prose, no code fences) in this exact shape:\n"
    '{{"questions": [{{"question": "...", "options": ["A","B","C","D"], '
    '"correct_index": 0, "explanation": "why the answer is correct"}}]}}\n\n'
    "CONTENT:\n{content}\n"
)


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Strip ```json ... ``` fences if present.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Grab the outermost {...} as a fallback.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])
        raise


def _validate(questions: list) -> list[dict]:
    cleaned: list[dict] = []
    for q in questions:
        opts = q.get("options")
        ci = q.get("correct_index")
        if (isinstance(q.get("question"), str) and isinstance(opts, list)
                and len(opts) == 4 and isinstance(ci, int) and 0 <= ci < 4):
            cleaned.append({
                "question": q["question"],
                "options": [str(o) for o in opts],
                "correct_index": ci,
                "explanation": str(q.get("explanation", "")),
            })
    return cleaned


def generate_quiz(*, summary: str, transcript: Optional[str] = None, num_questions: int = 5) -> tuple[list[dict], str]:
    """Return (questions, model_used). Raises if no valid questions are produced."""
    # Prefer the summary (dense, on-topic); fall back to a transcript slice if no summary.
    content = summary.strip() if summary and summary.strip() else (transcript or "")[:MAX_CONTENT_CHARS]
    content = content[:MAX_CONTENT_CHARS]
    text, model = generate(_PROMPT.format(n=num_questions, content=content))
    data = _extract_json(text)
    questions = _validate(data.get("questions", []))
    if not questions:
        raise RuntimeError("Quiz generation produced no valid questions.")
    return questions, model
