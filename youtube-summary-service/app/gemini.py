import os
import time
from google import genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY not set")

# Initialize the global client
client = genai.Client(api_key=api_key)

MODEL_NAME = "gemini-2.5-flash"
MAX_CHARS_PER_CHUNK = 30000


def chunk_text(text: str) -> list[str]:
    chunks = []
    for i in range(0, len(text), MAX_CHARS_PER_CHUNK):
        chunks.append(text[i : i + MAX_CHARS_PER_CHUNK])
    return chunks


def summarize_chunk(text: str) -> str:
    prompt = (
        "Summarize the following YouTube transcript chunk clearly and concisely. "
        "Focus only on factual content and key points.\n\n"
        f"{text}"
    )

    # Use the client to generate content
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )

    return response.text.strip() if response.text else ""



def summarize_full_transcript(transcript: str) -> str:
    # 1. Check if the transcript fits in a single chunk
    if len(transcript) <= MAX_CHARS_PER_CHUNK:
        # Direct summarization - no chunking or combining
        return summarize_chunk(transcript)

    # 2. Otherwise, proceed with multi-chunk logic
    chunks = chunk_text(transcript)
    chunk_summaries = []

    for chunk in chunks:
        try:
            summary = summarize_chunk(chunk)
            chunk_summaries.append(summary)
            time.sleep(1) 
        except Exception as e:
            chunk_summaries.append(f"[Error: {e}]")

    combined = "\n\n".join(chunk_summaries)

    final_prompt = (
        "You are given summaries of parts of a YouTube video. "
        "Combine them into a single, well-structured summary.\n\n"
        f"{combined}"
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=final_prompt
    )

    return response.text.strip() if response.text else ""

def safe_summarize(transcript: str) -> str | None:
    try:
        return summarize_full_transcript(transcript)
    except Exception as e:
        print(f"Summarization failed: {e}")
        return None
