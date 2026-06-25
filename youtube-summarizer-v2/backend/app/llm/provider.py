"""Thin provider interface over the LLM.

v2 uses Gemini, but every call site goes through `generate()` here so items 3/4
(agentic deep-dives) can add Claude or a router later without touching the
summarizer or quiz code. Keep this surface small and provider-neutral.
"""
from google import genai

from app.config import GEMINI_API_KEY

# Fallback chain — first model that succeeds wins (mirrors v1).
MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
]

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def generate(prompt: str) -> tuple[str, str]:
    """Return (text, model_used). Raises if all models fail."""
    client = _get_client()
    for model_name in MODELS:
        try:
            resp = client.models.generate_content(model=model_name, contents=prompt)
            text = resp.text.strip() if resp.text else ""
            if text:
                return text, model_name
        except Exception as e:  # noqa: BLE001 - try next model
            print(f"[llm] model {model_name} failed: {e}")
            continue
    raise RuntimeError("All configured LLM models failed to generate content.")
