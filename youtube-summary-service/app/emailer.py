import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from dotenv import load_dotenv
import requests
import base64

# Load .env
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# Env vars
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")

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
    msg["To"] = EMAIL_USERNAME
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
