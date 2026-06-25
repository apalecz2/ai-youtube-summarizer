# YouTube Summarizer v2 — Architecture

This is the design record for v2. It builds on the v1 app in
[`../youtube-summary-service`](../youtube-summary-service) (reference only — not modified).

Items **3** (channel deep-dives) and **4** (agentic AI viewer) from `../Version2.md`
are **deferred**. The system is designed so they slot in later without rework:
the LLM layer is provider-agnostic, the YouTube gate is the single choke point any
future agent must also go through, and transcripts/summaries are persisted and
searchable so an agent can reason over them.

## Decisions (locked)

| Area | Choice | Rationale |
|------|--------|-----------|
| Backend | Python / FastAPI | Reuse v1 logic; `yt-dlp` is Python-native; good base for future agents |
| Frontend | React + Vite (TypeScript) SPA | Richest UI; clean API boundary; room for the item-4 chat UI |
| Database | SQLite + FTS5 | One user / one worker; zero extra infra; full-text search over transcripts & summaries |
| LLM | Gemini, behind a provider interface | Cheap at volume; swap/add Claude later for items 3/4 without touching call sites |
| yt-dlp auth | Cookies from a **dedicated throwaway** Google account | Isolates ban risk from the user's real account |
| Scheduling | Internal APScheduler + DB-backed job queue | The random-spread requirement (item 1) needs the app to own timing |
| Auth | Single-user session login (web) + `X-API-Key` (extension) | App is internet-exposed via Cloudflare tunnel |

## The core idea: the app owns timing

v1 was reactive — an external cron hit `/poll` and every video was fetched
back-to-back. v2 inverts this. **One internal worker owns every YouTube
interaction**, so anti-bot timing (item 1) and global backoff (item 6) can be
enforced in exactly one place.

```
                 ┌──────────────────────────────────────────────┐
                 │                FastAPI app                     │
                 │                                                │
  RSS (cheap) ◄──┤  Discovery job (APScheduler, every 30 min)     │
                 │     • parse each channel's RSS                 │
                 │     • apply title filters                      │
                 │     • insert new videos + enqueue fetch_jobs   │
                 │       with scheduled_at spread randomly        │
                 │       across the 30-min window                 │
                 │                                                │
                 │  Worker loop (single async task)               │
                 │     • picks due jobs one at a time             │
                 │     • ALWAYS asks the Gate for permission ─────┼──► YouTube
                 │     • adds jitter between requests             │    (yt-dlp + cookies)
                 │                                                │
                 │  YouTube Gate (global)                         │
                 │     • serializes all YT access                 │
                 │     • holds backoff state (blocked_until,      │
                 │       backoff_level)                           │
                 │     • on block → exponential global backoff    │
                 └───────────────┬────────────────────────────────┘
                                 │
        ┌────────────────┬───────┴────────┬─────────────────┐
        ▼                ▼                ▼                 ▼
   SQLite+FTS5        Gemini           Gmail            React SPA
 (transcripts,     (summaries,        (OAuth2          (browse / search /
  summaries,         quizzes)          SMTP)            quizzes / channels)
  quizzes, jobs)
```

### Anti-bot timing (item 1)
- **Discovery** uses YouTube's RSS feed (`feeds/videos.xml`) — plain HTTP, cheap,
  not bot-flagged. This stays on the 30-min cadence.
- Only **transcript/metadata fetches** go through `yt-dlp`. Each is queued with
  `scheduled_at = discovery_time + random(0, ~28 min)`, so fetches are sprinkled
  across the window instead of bursting.
- The worker adds extra random jitter (a few–tens of seconds) between consecutive
  YouTube calls.
- `yt-dlp` only, with a cookies file from the throwaway account. No IPv6 tricks
  (the user's ISP can't do them).

### Intelligent backoff (item 6)
- The Gate inspects every `yt-dlp` failure for block signatures
  ("Sign in to confirm you're not a bot", HTTP 429, "blocked", etc.).
- On a block: set a **global** `blocked_until` for an exponential, capped delay
  (e.g. 5m → 15m → 45m → 2h → 6h …) that applies to **all** requests, and
  reschedule the job. The goal is to retry as soon as YouTube is likely to have
  un-flagged the IP, then escalate if still blocked.
- On success: reset the backoff level to 0.
- State lives in a single `rate_limit_state` row so it survives restarts.

### Manual / instant summarize (item 5)
Right-click summarize enqueues a **priority** job (`scheduled_at = now`,
`priority` high) that skips the random spread but still respects the global Gate
(so a manual action during a block waits rather than poking a flagged IP).

## Data model (SQLite)

- `channels(channel_id PK, title, added_at, active)`
- `channel_filters(...)` — carried over from v1 (field/match_type/value/action)
- `videos(video_id PK, channel_id, title, channel_name, duration, published_at, url, discovered_at, status)`
  - status: `discovered → queued → fetching → summarized | skipped | failed`
- `transcripts(video_id PK, lang, source, text, fetched_at)`
- `summaries(id PK, video_id, detail_level, model, summary_md, created_at)`
- `quizzes(id PK, video_id, model, questions_json, created_at)`
- `fetch_jobs(id PK, video_id, job_type, priority, scheduled_at, attempts, status, last_error, created_at)`
- `rate_limit_state(id=1, blocked_until, backoff_level, last_block_at, last_success_at)`
- FTS5 virtual tables mirroring `transcripts` and `summaries` for search.

## API surface (v1-compatible where it can be)

Reused from v1 (so the existing extension keeps working):
`GET /health`, `POST/GET/DELETE /channels`, channel filter CRUD,
`POST /summarize`, `POST /poll`.

New in v2:
- `GET /videos`, `GET /videos/{id}` — browse processed videos + status
- `GET /summaries`, `GET /summaries/{id}` — stored summaries
- `GET /transcripts/{video_id}`
- `GET /search?q=` — FTS over transcripts + summaries
- `POST /videos/{id}/quiz`, `GET /videos/{id}/quiz` — generate/fetch quiz
- `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` — web session
- `GET /status` — worker + backoff state (so the UI can show "backed off until …")

## Deployment
Single Docker image: FastAPI serves the built React SPA as static files and the
API. SQLite + cookies file live on a mounted volume. Cloudflare tunnel exposes it,
exactly as v1. APScheduler runs in-process, so no external scheduler is required.

## Deferred (items 3 & 4) — how they fit later
- **Deep dive (3):** an agent that enqueues its own `fetch_jobs` (≤3 per window)
  through the *same* Gate, reads transcripts/summaries from SQLite, and writes a
  condensed document. No new YouTube path — it inherits anti-bot + backoff for free.
- **AI viewer (4):** a chat UI (already feasible in the React SPA) drives a search
  → summarize → synthesize loop using the same provider interface and Gate.
