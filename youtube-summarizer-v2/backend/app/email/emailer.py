"""Gmail OAuth2 SMTP email (ported from v1). Email alerts remain a core feature.

Now also links back to the local web app so a summary email is one click from the
full stored summary + transcript + quiz.
"""
import base64
import smtplib
from email.message import EmailMessage

import markdown
import requests

from app import config

_REQUIRED = (config.EMAIL_USERNAME, config.GMAIL_CLIENT_ID,
             config.GMAIL_CLIENT_SECRET, config.GMAIL_REFRESH_TOKEN)


def email_configured() -> bool:
    return all(_REQUIRED)


def _access_token() -> str:
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": config.GMAIL_CLIENT_ID,
            "client_secret": config.GMAIL_CLIENT_SECRET,
            "refresh_token": config.GMAIL_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _xoauth2(email: str, token: str) -> str:
    return base64.b64encode(f"user={email}\x01auth=Bearer {token}\x01\x01".encode()).decode()


def _send(msg: EmailMessage) -> None:
    token = _access_token()
    with smtplib.SMTP(config.EMAIL_HOST, config.EMAIL_PORT, timeout=30) as server:
        server.starttls()
        server.docmd("AUTH", "XOAUTH2 " + _xoauth2(config.EMAIL_USERNAME, token))
        server.send_message(msg)


def _normalize_markdown(md: str) -> str:
    lines, fixed = md.splitlines(), []
    for line in lines:
        if line.lstrip().startswith("* ") and fixed and fixed[-1].strip() != "":
            fixed.append("")
        fixed.append(line)
    return "\n".join(fixed)


def _md_to_html(md_text: str) -> str:
    return markdown.markdown(_normalize_markdown(md_text), extensions=["extra", "sane_lists"])


def send_summary_email(*, video_title: str, channel_name: str, summary: str,
                       youtube_url: str, app_url: str | None = None) -> None:
    if not email_configured():
        print("[email] not configured; skipping summary email")
        return

    msg = EmailMessage()
    msg["From"] = config.EMAIL_USERNAME
    msg["To"] = config.EMAIL_SENDTO
    msg["Subject"] = f"YouTube Summary: {video_title}"

    app_line = f"\n\nOpen in app:\n{app_url}" if app_url else ""
    msg.set_content(
        f"Channel: {channel_name}\n\nTitle: {video_title}\n\nSummary:\n{summary}\n\n"
        f"Watch here:\n{youtube_url}{app_line}\n"
    )

    app_html = f'<p><a href="{app_url}">Open in app</a></p>' if app_url else ""
    msg.add_alternative(
        f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<p><strong>Channel:</strong> {channel_name}</p>
<p><strong>Title:</strong> {video_title}</p>
<hr>
{_md_to_html(summary)}
<hr>
<p><a href="{youtube_url}">Watch on YouTube</a></p>
{app_html}
</body></html>""",
        subtype="html",
    )

    try:
        _send(msg)
    except Exception as e:  # noqa: BLE001
        print(f"[email] failed to send summary: {e}")


def send_error_email(*, subject: str, error_message: str, stage: str | None = None,
                     video_id: str | None = None, video_title: str | None = None,
                     channel_name: str | None = None, youtube_url: str | None = None,
                     app_url: str | None = None) -> None:
    """Send a diagnostic error email. All context fields are optional so callers
    can pass whatever they have; the more they pass, the more actionable the
    email. `error_message` should be the full exception detail, not a summary."""
    if not email_configured():
        return

    # Build an ordered list of context rows from whatever the caller provided.
    rows: list[tuple[str, str]] = []
    if stage:
        rows.append(("Stage", stage))
    if channel_name:
        rows.append(("Channel", channel_name))
    if video_title:
        rows.append(("Title", video_title))
    if video_id:
        rows.append(("Video ID", video_id))
    if youtube_url:
        rows.append(("YouTube", youtube_url))
    if app_url:
        rows.append(("Open in app", app_url))

    msg = EmailMessage()
    msg["From"] = config.EMAIL_USERNAME
    msg["To"] = config.EMAIL_SENDTO
    msg["Subject"] = f"YouTube Summary Error: {subject}"

    context_txt = "".join(f"{label}: {value}\n" for label, value in rows)
    msg.set_content(
        "An error occurred during the YouTube Summary process.\n\n"
        f"{context_txt}\n"
        f"Error details:\n{error_message}\n"
    )

    context_html = "".join(
        f"<p style='margin:2px 0;'><strong>{label}:</strong> {_linkify(label, value)}</p>"
        for label, value in rows
    )
    msg.add_alternative(
        f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<p>An error occurred during the YouTube Summary process.</p>
{context_html}
<hr>
<p><strong>Error details:</strong></p>
<pre style="white-space:pre-wrap;background:#f5f5f5;padding:12px;border-radius:6px;">{_escape(error_message)}</pre>
</body></html>""",
        subtype="html",
    )

    try:
        _send(msg)
    except Exception as e:  # noqa: BLE001
        print(f"[email] failed to send error email: {e}")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _linkify(label: str, value: str) -> str:
    if value.startswith("http"):
        return f'<a href="{value}">{_escape(value)}</a>'
    return _escape(value)
