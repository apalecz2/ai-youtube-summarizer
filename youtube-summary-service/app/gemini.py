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
# ~100k tokens at ~4 chars/token = 400k chars
MAX_SINGLE_PASS_CHARS = 400_000
CHUNK_SIZE_CHARS = 400_000

DETAIL_PROMPTS = {
    1: (
        "You are summarizing a YouTube video transcript. "
        "Provide a brief overview of what this video is about — its main topic "
        "and the central thesis or purpose. Ignore all sponsors and into/outro filler. "
        "Keep it short and high-level (several sentences to a short paragraph).\n\n"
    ),
    2: (
        "You are summarizing a YouTube video transcript. "
        "Produce a thorough, well-structured summary that captures the key points, "
        "arguments, examples, and takeaways from the video. "
        "Reading this summary should "
        "allow a reader to understand the content comprehensively by optimally summarizing the content. "
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

        "OUTPUT FORMAT:\n"
        "You must format your response using the following strict structure:\n\n"
        "Executive Summary\n"
        "[A concise overview of the video's main thesis and purpose.]\n\n"
        "Detailed Breakdown\n"
        "[Use headers to divide the content into logical chapters or themes. Under each header, use detailed bullet points to explain the core arguments and data.]\n\n"
        "Key Takeaways\n"
        "[Provide 3-5 high-impact, actionable bullet points that represent the most important conclusions.]\n"
    ),
}


def chunk_text(text: str) -> list[str]:
    chunks = []
    for i in range(0, len(text), CHUNK_SIZE_CHARS):
        chunks.append(text[i : i + CHUNK_SIZE_CHARS])
    return chunks


def summarize_chunk(text: str) -> str:
    prompt = (
        "Summarize the following YouTube transcript chunk thoroughly. "
        "Capture every key point, argument, example, and detail — "
        "do not skip anything.\n\n"
        f"{text}"
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )

    return response.text.strip() if response.text else ""


def summarize_full_transcript(transcript: str, detail: int = 2) -> str:
    prompt = DETAIL_PROMPTS[detail]

    # If within 100k tokens, summarize in a single pass
    if len(transcript) <= MAX_SINGLE_PASS_CHARS:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt + transcript
        )
        return response.text.strip() if response.text else ""

    # Otherwise, chunk and summarize each piece
    chunks = chunk_text(transcript)
    chunk_summaries = []

    for chunk in chunks:
        try:
            summary = summarize_chunk(chunk)
            chunk_summaries.append(summary)
            time.sleep(1)
        except Exception as e:
            chunk_summaries.append(f"[Error: {e}]")

    # For overview (level 1), combine chunk summaries into a brief overview
    # For standard/complete (levels 2-3), combine with the same detail prompt
    combined = "\n\n".join(chunk_summaries)

    final_prompt = (
        "You are given summaries of parts of a YouTube video. "
        "Combine them into a single, well-structured summary that "
        "preserves all key points and details.\n\n"
        f"{combined}"
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=final_prompt
    )

    return response.text.strip() if response.text else ""

def safe_summarize(transcript: str, detail: int = 2) -> str | None:
    try:
        return summarize_full_transcript(transcript, detail=detail)
    except Exception as e:
        print(f"Summarization failed: {e}")
        return None
