#!/usr/bin/env python3
"""Quick experiment: summarize a YouTube video by handing Gemini the URL directly,
with no transcript fetch at all (so no yt-dlp / timedtext 429s).

Uses the app's own GEMINI_API_KEY, model list and detail-level prompts. It only
prints; it never touches the database, queue, or email.

The key is read from GEMINI_API_KEY in the environment, or else from the v1
service's .env (../../youtube-summary-service/.env), so it runs locally as is:
    python3 test_gemini_url.py <video_id_or_url> [--detail 1|2|3] [--model NAME]

Prints the model used, wall time, input/output token counts (so you can estimate
cost per video), and the summary.
"""
import os
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

# Pull ONLY the Gemini key from the v1 service's .env (nothing else from it), and
# do it before importing app modules, which read config at import time.
_ENV = Path(__file__).resolve().parents[2] / "youtube-summary-service" / ".env"
if not os.getenv("GEMINI_API_KEY") and _ENV.is_file():
    _key = dotenv_values(_ENV).get("GEMINI_API_KEY")
    if _key:
        os.environ["GEMINI_API_KEY"] = _key

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from app.llm import provider  # noqa: E402
from app.llm.summarizer import DETAIL_PROMPTS  # noqa: E402
from app.youtube import fetcher  # noqa: E402


def main(argv: list[str]) -> int:
    detail, model_arg, target = 2, None, None
    it = iter(argv)
    for tok in it:
        if tok == "--detail":
            detail = int(next(it))
        elif tok == "--model":
            model_arg = next(it)
        elif tok != "--":
            target = tok
    if not target or detail not in DETAIL_PROMPTS:
        print("usage: test_gemini_url.py <video_id_or_url> [--detail 1|2|3] [--model NAME]")
        return 2

    vid = fetcher.extract_video_id(target) or target
    url = f"https://www.youtube.com/watch?v={vid}"
    # The prompts are written for a transcript; point them at the video instead.
    prompt = DETAIL_PROMPTS[detail].replace("YouTube video transcript", "YouTube video") \
                                   .replace("raw YouTube video transcript", "YouTube video")
    contents = types.Content(parts=[
        types.Part(file_data=types.FileData(file_uri=url)),
        types.Part(text=prompt),
    ])

    # Fail fast instead of hanging: video calls can be slow, but not unbounded.
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                          http_options=types.HttpOptions(timeout=180_000))
    models = [model_arg] if model_arg else provider.MODELS
    print(f"video: {url}\ndetail: {detail}\n")
    for model in models:
        print(f"[{model}] requesting…")
        t0 = time.time()
        try:
            resp = client.models.generate_content(model=model, contents=contents)
        except Exception as e:  # noqa: BLE001
            print(f"    FAILED: {type(e).__name__}: {e}\n")
            continue
        secs = time.time() - t0
        text = (resp.text or "").strip()
        u = resp.usage_metadata
        print(f"    time: {secs:.1f}s   input tokens: {getattr(u, 'prompt_token_count', '?')}   "
              f"output tokens: {getattr(u, 'candidates_token_count', '?')}")
        if not text:
            print("    EMPTY response (video may be private/age-restricted/too long)\n")
            continue
        print(f"    VERDICT: SUCCESS ✅ ({len(text)} chars)\n")
        print(text)
        return 0
    print("VERDICT: no model produced a summary from the URL.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
