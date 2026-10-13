"""Summarize a YouTube video by giving Gemini its URL — no transcript fetch at all.

This is the fallback while the main yt-dlp path is suspended (see youtube/gate.py).
Gemini reads the video itself, so nothing here touches YouTube from our IP.

Cost/limits: a video is ~VIDEO_TOKENS_PER_SECOND input tokens per second, and each
model has a per-minute input-token quota. Videos too big for one request are cut
into equal slices (Gemini supports start/end offsets on YouTube URLs), each slice is
summarized, and the parts are consolidated — the same shape as the long-transcript
path. The token limiter in provider.generate() spaces the slices out.
"""
import math
from typing import Optional

from google.genai import types

from app import config, events
from app.llm import provider
from app.llm.summarizer import DETAIL_PROMPTS, _context_block

_PROMPT_OVERHEAD_TOKENS = 700   # the instructions around the video


def _url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _video_part(video_id: str, start: Optional[int] = None, end: Optional[int] = None) -> types.Part:
    meta = None
    if start is not None and end is not None:
        meta = types.VideoMetadata(start_offset=f"{start}s", end_offset=f"{end}s")
    return types.Part(file_data=types.FileData(file_uri=_url(video_id)), video_metadata=meta)


def probe_duration(video_id: str) -> int:
    """Video length in seconds, derived from Gemini's token count for it (free, and
    needs no YouTube access from us). Accurate to a few seconds."""
    total = provider.count_tokens(types.Content(parts=[_video_part(video_id), types.Part(text="x")]))
    return max(1, round(max(0, total - 20) / config.VIDEO_TOKENS_PER_SECOND))


def _adapt(prompt: str) -> str:
    """The shared prompts are written for a transcript; point them at the video."""
    return prompt.replace("raw YouTube video transcript", "YouTube video") \
                 .replace("YouTube video transcript", "YouTube video")


def _mmss(s: int) -> str:
    return f"{s // 60}:{s % 60:02d}"


def summarize_video(video_id: str, *, duration: int, detail: int = 2,
                    channel_name: Optional[str] = None,
                    video_title: Optional[str] = None) -> tuple[str, str]:
    """Return (summary_markdown, model_used). Raises provider.LLMRateLimited when
    every model is rate limited, RuntimeError on other failure."""
    context = _context_block(channel_name, video_title)
    rate = config.VIDEO_TOKENS_PER_SECOND
    max_slice = max(60, config.VIDEO_SEGMENT_TOKENS // rate)
    slices = max(1, math.ceil(duration / max_slice))

    if slices == 1:
        prompt = _adapt(DETAIL_PROMPTS[detail]) + context
        return provider.generate(
            types.Content(parts=[_video_part(video_id), types.Part(text=prompt)]),
            est_tokens=duration * rate + _PROMPT_OVERHEAD_TOKENS,
        )

    length = math.ceil(duration / slices)
    events.log("info", "llm", f"{_mmss(duration)} video — summarizing in {slices} slices of ~{_mmss(length)}",
               video_id=video_id)
    partials: list[str] = []
    model = ""
    for i in range(slices):
        start, end = i * length, min(duration, (i + 1) * length)
        prompt = (
            f"This is part {i + 1} of {slices} of a YouTube video (from {_mmss(start)} to {_mmss(end)}). "
            "Summarize this part thoroughly. Capture every key point, argument, example, and detail — "
            "do not skip anything. Ignore sponsor reads and subscribe requests.\n\n" + context
        )
        text, model = provider.generate(
            types.Content(parts=[_video_part(video_id, start, end), types.Part(text=prompt)]),
            est_tokens=(end - start) * rate + _PROMPT_OVERHEAD_TOKENS,
        )
        partials.append(f"[Part {i + 1} ({_mmss(start)}–{_mmss(end)})]\n{text}")

    final = (
        "You are given summaries of consecutive parts of a YouTube video. Combine them into a single, "
        "well-structured summary that preserves all key points and details.\n\n"
        + _adapt(DETAIL_PROMPTS[detail]) + context + "\n\n".join(partials)
    )
    return provider.generate(final)
