import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from dotenv import load_dotenv
import requests
import base64
import markdown

# Load .env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Env vars
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")
EMAIL_SENDTO = os.getenv("EMAIL_SENDTO")

if not all([EMAIL_USERNAME, GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN]):
    raise RuntimeError("Missing one or more required Gmail OAuth2 env variables")

# Get access token
def get_gmail_access_token() -> str:
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "refresh_token": GMAIL_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }

    r = requests.post(token_url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

# Build XOAUTH2 string
def build_xoauth2_string(email: str, access_token: str) -> str:
    auth_string = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(auth_string.encode()).decode()

def normalize_markdown(md: str) -> str:
    lines = md.splitlines()
    fixed = []

    for i, line in enumerate(lines):
        if line.lstrip().startswith("* "):
            # If previous line exists and is not blank, insert a blank line
            if fixed and fixed[-1].strip() != "":
                fixed.append("")
        fixed.append(line)

    return "\n".join(fixed)

def markdown_to_html(md_text: str) -> str:
    normalized = normalize_markdown(md_text)
    return markdown.markdown(
        normalized,
        extensions=["extra", "sane_lists"]
    )

# Send email
def send_summary_email(
    *,
    video_title: str,
    channel_name: str,
    summary: str,
    youtube_url: str,
) -> bool:

    msg = EmailMessage()
    msg["From"] = EMAIL_USERNAME
    msg["To"] = EMAIL_SENDTO
    msg["Subject"] = f"YouTube Summary: {video_title}"

    msg.set_content(
        f"""Channel: {channel_name}

Title: {video_title}

Summary:
{summary}

Watch here:
{youtube_url}
"""
    )
    
    html_summary = markdown_to_html(summary)
    
    html_body = f"""
<!DOCTYPE html>
<html>
  <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
    <p><strong>Channel:</strong> {channel_name}</p>
    <p><strong>Title:</strong> {video_title}</p>

    <hr>

    {html_summary}

    <hr>

    <p>
      <a href="{youtube_url}">Watch on YouTube</a>
    </p>
  </body>
</html>
"""
    
    msg.add_alternative(html_body, subtype="html")

    try:
        access_token = get_gmail_access_token()
        if not EMAIL_USERNAME:
            return False
        auth_string = build_xoauth2_string(EMAIL_USERNAME, access_token)

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=30) as server:
            server.starttls()
            server.docmd("AUTH", "XOAUTH2 " + auth_string)
            server.send_message(msg)

        return True

    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False
