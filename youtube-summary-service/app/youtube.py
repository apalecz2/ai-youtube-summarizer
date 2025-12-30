from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi

def extract_video_id(url: str) -> str | None:
    """
    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    """
    parsed = urlparse(url)

    # youtu.be/VIDEO_ID
    if parsed.netloc == "youtu.be":
        return parsed.path.lstrip("/")

    # youtube.com/watch?v=VIDEO_ID
    if parsed.path == "/watch":
        query = parse_qs(parsed.query)
        return query.get("v", [None])[0]

    # youtube.com/embed/VIDEO_ID
    if parsed.path.startswith("/embed/"):
        return parsed.path.split("/")[2]

    return None

# Fetch transcript helper (no timestamps)
from youtube_transcript_api import YouTubeTranscriptApi

def fetch_transcript(video_id: str) -> str | None:
    try:
        # 1. Create an instance of the API
        ytt_api = YouTubeTranscriptApi()
        # 2. Get transcripts
        transcript_list = ytt_api.list(video_id)
        
        # 3. Find the best English transcript
        # Look for manual first, then auto-generated
        transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
        
        # 4. Fetch the transcript object
        fetched_transcript = transcript.fetch()
        
        # 5. The snippets are objects with a .text attribute
        # Join them into one long string
        text_parts = [snippet.text for snippet in fetched_transcript]
        full_text = " ".join(text_parts)
        
        return full_text.replace("\n", " ").strip()

    except Exception as e:
        print(f"DEBUG: Failed to fetch transcript for {video_id}. Error: {e}")
        return None