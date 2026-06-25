# YouTube Summarizer v2

A self-hosted service that watches YouTube channels, summarizes new uploads with
AI, emails you the summary, and stores everything in a searchable web app — while
deliberately mimicking human browsing so YouTube never flags the fetcher as a bot.

This is a ground-up rewrite of [`../youtube-summary-service`](../youtube-summary-service)
(v1, kept for reference). See [ARCHITECTURE.md](./ARCHITECTURE.md) for the design.

## What's built (this version)

- **Human-like fetching (item 1).** Uploads are discovered every 30 min via the
  cheap RSS feed; the expensive transcript fetches are then queued at *random*
  times spread across the window, one at a time, with jitter between calls.
  `yt-dlp` only, authenticated with cookies from a **dedicated throwaway** account.
- **Stored + browsable summaries (item 2).** Transcripts, summaries, and quizzes
  are persisted in SQLite (with FTS5 full-text search). A React web app lets you
  browse, read, search, and generate **multiple-choice quizzes** on any video.
  Email alerts remain a core feature and now link straight to the web app.
- **Channel & filter management + instant summarize (item 5).** v1-compatible API,
  so the existing browser extension keeps working; per-channel title filters; and
  right-click / paste-a-URL instant summaries that jump the queue.
- **Intelligent global backoff (item 6).** Every YouTube call goes through one
  gate. On a block signature ("Sign in to confirm you're not a bot", HTTP 429, …)
  *all* requests pause for an exponential, capped window that escalates if the
  block persists and resets on the first clean success. State survives restarts.

**Deferred (designed-for, not built):** item 3 (channel deep-dive agent) and item
4 (topic-research AI viewer). They slot in as new job types behind the same gate —
no schema or anti-bot rework needed.

## Layout

```
youtube-summarizer-v2/
├── backend/            FastAPI app (API + scheduler + worker)
│   └── app/
│       ├── api/        routers: auth, channels, content, actions
│       ├── db/         SQLite schema + repositories (FTS5)
│       ├── youtube/    yt-dlp fetcher + the backoff gate
│       ├── llm/        provider, summarizer, quiz (Gemini)
│       ├── email/      Gmail OAuth2 SMTP
│       ├── discovery.py / jobs.py / worker.py / scheduler.py
│       └── main.py
└── frontend/           React + Vite (TypeScript) SPA
```

## Quick start (Docker — recommended)

1. **Configure env:**
   ```bash
   cd youtube-summarizer-v2/backend
   cp .env.example .env
   # then edit .env (see below)
   ```
2. **Add the throwaway-account cookies.** Log into YouTube in a browser as the
   dedicated throwaway Google account, export cookies in Netscape format (e.g. the
   "Get cookies.txt" extension), and save them to `backend/data/cookies.txt`.
3. **Run:**
   ```bash
   cd youtube-summarizer-v2
   docker compose up -d --build
   ```
   The app (API + web UI) is at `http://localhost:8000`. The in-process scheduler
   polls every 30 min automatically — no external cron needed.

### Required `.env` values

| Var | What |
|-----|------|
| `APP_PASSWORD_SHA256` | SHA-256 of your web login password (see below) |
| `SESSION_SECRET` | any long random string (signs session cookies) |
| `API_AUTH_TOKEN` | random hex; the extension's `X-API-Key` |
| `GEMINI_API_KEY` | Google Gemini key |
| `EMAIL_*`, `GMAIL_*` | Gmail OAuth2 SMTP (same as v1) |
| `YTDLP_COOKIES_FILE` | path to the throwaway cookies (default `data/cookies.txt`) |

Generate the password hash:
```bash
python -c "import hashlib;print(hashlib.sha256(b'YOUR_PASSWORD').hexdigest())"
```

Tunable anti-bot / backoff knobs (`POLL_INTERVAL_MINUTES`, `FETCH_SPREAD_MINUTES`,
`FETCH_JITTER_*`, `BACKOFF_SCHEDULE_MINUTES`) are documented in `.env.example`.

## Local development

Two terminals:

```bash
# backend
cd youtube-summarizer-v2/backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000

# frontend (Vite proxies /api -> :8000, so the cookie just works)
cd youtube-summarizer-v2/frontend
npm install
npm run dev                            # http://localhost:5173
```

## API (auth via session cookie *or* `X-API-Key`)

v1-compatible: `GET /health`, `POST/GET/DELETE /api/channels`, channel filter CRUD,
`POST /api/summarize`, `POST /api/poll`.

New: `GET /api/videos`, `GET /api/videos/{id}`, `GET /api/summaries`,
`GET /api/transcripts/{id}`, `GET /api/search?q=`, `POST/GET /api/videos/{id}/quiz`,
`GET /api/status` (queue + backoff), and `/api/auth/{login,logout,me}`.

## Notes

- **One worker, on purpose.** All YouTube access is serialized through a single
  worker so the global backoff is coherent and traffic stays human-paced.
- **Throwaway account.** Cookies tie requests to a Google account; using a
  dedicated one keeps any ban risk away from your real account.
- This service is intended for **personal, low-volume** use behind something like a
  Cloudflare tunnel (as in v1).
