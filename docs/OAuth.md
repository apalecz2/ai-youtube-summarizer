## YouTube Summary Emailer – Gmail OAuth2 SMTP
Project Overview

This project is a Python service that sends plain-text YouTube video summaries to your Gmail account using SMTP with OAuth2 authentication.
It replaces the traditional username/password SMTP login with the modern, secure OAuth2 flow required by Gmail.

Features

Sends a summary email with:

Channel name

Video title

Summary

YouTube URL

Uses Gmail OAuth2 to authenticate via SMTP

Supports deployment on platforms like Render without exposing passwords

Safe: no long-term passwords stored, only refresh tokens

File Structure
youtube-summary-service/
│
├─ app/
│   ├─ main.py             # Your FastAPI / script entrypoint
│   ├─ email_sender.py     # Contains send_summary_email(), OAuth helpers
│   └─ .env                # Environment variables
│
└─ README.md

Environment Variables (.env)
# Gmail SMTP
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USERNAME=your_email@gmail.com

# Google OAuth2 Credentials
GMAIL_CLIENT_ID=<YOUR_CLIENT_ID>
GMAIL_CLIENT_SECRET=<YOUR_CLIENT_SECRET>
GMAIL_REFRESH_TOKEN=<YOUR_REFRESH_TOKEN>


Notes:

No quotes, no spaces around =.

EMAIL_USERNAME is the Gmail account sending the email.

GMAIL_REFRESH_TOKEN is generated once via OAuth2 (see below).

OAuth2 Setup (Gmail)
1. Create Google Cloud Project

Go to Google Cloud Console
 → New Project

Name it (e.g., YoutubeAISummaryTool) and select it.

2. Enable Gmail API

APIs & Services → Library → search for "Gmail API" → Enable

3. Configure OAuth Consent Screen

APIs & Services → OAuth consent screen

Select External

Add:

App name: anything

User support email: your Gmail

Developer email: your Gmail

Scopes: https://mail.google.com/

Test users: add your Gmail (EMAIL_USERNAME)

Save

4. Create OAuth Client

Credentials → Create Credentials → OAuth Client ID

Application type: Desktop App

Copy:

Client ID → GMAIL_CLIENT_ID

Client Secret → GMAIL_CLIENT_SECRET

5. Generate Refresh Token (One-time)

Open this URL in a browser (replace CLIENT_ID):

https://accounts.google.com/o/oauth2/v2/auth
?client_id=CLIENT_ID
&redirect_uri=http://localhost
&response_type=code
&scope=https://mail.google.com/
&access_type=offline
&prompt=consent


Login with your Gmail. You’ll get redirected to:

http://localhost/?code=AUTH_CODE


Exchange AUTH_CODE for refresh token:

curl -X POST https://oauth2.googleapis.com/token \
  -d client_id=YOUR_CLIENT_ID \
  -d client_secret=YOUR_CLIENT_SECRET \
  -d code=AUTH_CODE \
  -d grant_type=authorization_code \
  -d redirect_uri=http://localhost


Response includes:

{
  "access_token": "ya29...",
  "expires_in": 3599,
  "refresh_token": "1//0g..."
}


Save refresh_token to .env as GMAIL_REFRESH_TOKEN.

You will never need to generate it again unless revoked.

Python Implementation
email_sender.py

Contains three main parts:

Get Access Token

def get_gmail_access_token() -> str:
    # Exchanges refresh token for a short-lived access token


Build XOAUTH2 String

def build_xoauth2_string(email: str, access_token: str) -> str:
    # Returns base64-encoded auth string for SMTP


Send Summary Email

def send_summary_email(video_title, channel_name, summary, youtube_url) -> bool:
    # Connects to smtp.gmail.com via TLS and sends email


Important:
Do not call server.login(). OAuth2 replaces password-based login.

Troubleshooting
Symptom	Cause	Solution
Missing required parameter: refresh_token	GMAIL_REFRESH_TOKEN not loaded	Check .env location, ensure no quotes, load_dotenv() points to correct path
invalid_grant	Refresh token invalid or revoked	Generate a new refresh token with correct scope
access_denied	Test user not added	Add your Gmail to OAuth consent screen test users
535 5.7.8	Wrong XOAUTH2 string	Ensure build_xoauth2_string is used and server.login() is not called
Deployment Notes (Render / Production)

Add .env values via Render Environment Variables (never commit .env!)

Ensure access token caching if sending multiple emails per minute to reduce requests

Refresh tokens do not expire unless revoked or OAuth app changes

References

Gmail SMTP OAuth2 Guide

Google OAuth2 Docs

Python smtplib with OAuth2

Summary / Context

Started with traditional SMTP + password → Gmail blocked login

Migrated to OAuth2 with refresh_token + access_token

Added .env-based configuration for safe deployment

Fully tested sending summary emails from personal Gmail account

Future improvements: token caching, FastAPI background tasks, multiple recipients