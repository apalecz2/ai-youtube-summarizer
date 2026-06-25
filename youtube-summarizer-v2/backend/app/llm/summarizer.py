"""Transcript summarization (ported from v1's gemini.py).

Same detail levels (1=overview, 2=thorough, 3=expert structured) and the same
chunk-then-consolidate strategy for very long transcripts, but the model call now
goes through the provider abstraction.
"""
import time
from typing import Optional

from app.llm.provider import generate

# ~100k tokens at ~4 chars/token.
MAX_SINGLE_PASS_CHARS = 400_000
CHUNK_SIZE_CHARS = 400_000

DETAIL_PROMPTS = {
    1: (
        "You are summarizing a YouTube video transcript. "
        "Provide a brief overview of what this video is about — its main topic "
        "and the central thesis or purpose. Ignore all sponsors and intro/outro filler. "
        "Keep it short and high-level (several sentences to a short paragraph).\n\n"
    ),
    2: (
        "You are summarizing a YouTube video transcript. "
        "Produce a thorough, well-structured summary that captures the key points, "
        "arguments, examples, and takeaways from the video. Reading this summary should "
        "allow a reader to understand the content comprehensively. "
        "Provide a key takeaways section at the very end with the most important points. "
        "Use clear headings or logical groupings where appropriate.\n\n"
    ),
    3: (
        "You are an expert technical synthesizer tasked with summarizing a raw YouTube video transcript. "
        "Your goal is to extract the highest-signal information and present it in a dense, highly readable format. "
        "The reader should be able to fully grasp the core arguments and actionable insights without watching the video.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "- Ignore all sponsor reads, promotional segments, intro/outro filler, and requests to like/subscribe.\n"
        "- Do not attempt to transcribe every single example; synthesize the overarching concepts and provide only the most illustrative evidence.\n"
        "- Maintain an objective, informative tone.\n\n"
        "OUTPUT FORMAT (strict):\n\n"
        "Executive Summary\n[A concise overview of the video's main thesis and purpose.]\n\n"
        "Detailed Breakdown\n[Use headers to divide the content into logical chapters or themes, with detailed bullet points.]\n\n"
        "Key Takeaways\n[3-5 high-impact, actionable bullet points.]\n"
    ),
}


def _context_block(channel_name: Optional[str], video_title: Optional[str]) -> str:
    if not (channel_name or video_title):
        return ""
    out = "Context:\n"
    if channel_name:
        out += f"- Channel: {channel_name}\n"
    if video_title:
        out += f"- Title: {video_title}\n"
    return out + "\n"


def _chunks(text: str) -> list[str]:
    return [text[i:i + CHUNK_SIZE_CHARS] for i in range(0, len(text), CHUNK_SIZE_CHARS)]


def summarize(transcript: str, *, detail: int = 2, channel_name: Optional[str] = None,
              video_title: Optional[str] = None) -> tuple[str, str]:
    """Return (summary_markdown, model_used). Raises on failure."""
    context = _context_block(channel_name, video_title)

    if len(transcript) <= MAX_SINGLE_PASS_CHARS:
        return generate(DETAIL_PROMPTS[detail] + context + transcript)

    # Long transcript: summarize each chunk, then consolidate.
    chunk_instructions = (
        "Summarize the following YouTube transcript chunk thoroughly. "
        "Capture every key point, argument, example, and detail — do not skip anything.\n\n"
    )
    partials: list[str] = []
    last_model = ""
    for chunk in _chunks(transcript):
        text, last_model = generate(chunk_instructions + context + chunk)
        partials.append(text)
        time.sleep(1)

    combined = "\n\n".join(partials)
    final_instructions = (
        "You are given summaries of parts of a YouTube video. Combine them into a "
        "single, well-structured summary that preserves all key points and details.\n\n"
    )
    return generate(final_instructions + context + combined)


def safe_summarize(transcript: str, *, detail: int = 2, channel_name: Optional[str] = None,
                   video_title: Optional[str] = None) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    """Return ((summary_markdown, model_used), None) on success, or
    (None, error_detail) on failure — the caller records/emails the detail
    instead of the error being lost to a print."""
    try:
        return summarize(transcript, detail=detail, channel_name=channel_name, video_title=video_title), None
    except Exception as e:  # noqa: BLE001
        detail_msg = f"{type(e).__name__}: {e}"
        print(f"[summarizer] failed: {detail_msg}")
        return None, detail_msg
