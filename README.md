# AI YouTube Summarizer

> An intelligent, production-ready service that automatically monitors YouTube channels for new uploads, extracts video transcripts, and delivers AI-powered summaries via email using Google's Gemini AI.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.128.0-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)](https://www.docker.com/)
[![Google Gemini](https://img.shields.io/badge/Gemini-2.5--Flash-4285F4?logo=google)](https://ai.google.dev/)

---

## Features

### **AI-Powered Summarization**
- Leverages Google Gemini 2.5 Flash for intelligent, context-aware summaries
- Handles long-form content with chunking (30K char chunks)
- Multi-stage summarization: chunk-level processing → final consolidation

### **Smart Channel Monitoring**
- Automatic RSS feed polling for the selected YouTube channels
- Duplicate detection to prevent reprocessing videos
- Intelligent filtering:
  - Skips YouTube Shorts (< 60 seconds)
  - Skips live streams and handles upcoming premieres gracefully

### **Email Delivery System**
- OAuth2-authenticated Gmail integration
- Simple HTML with markdown rendering to properly display the summary
- Automatic email delivery upon video processing

### **Production-Ready API**
- RESTful API with API key authentication
- Background task processing for long-running operations
- CORS middleware for web client integration
- Health check endpoints for monitoring

### **Containerized Deployment**
- Dockerized application with optimized Python slim image
- Docker Compose configuration for easy deployment
- Persistent data storage with volume mounting

### **Web Client Interface**
- Just a quick and simple HTML UI to send requests to the API

---

## Deployment / Usage

### **Poll Mechanism**
- The poll endpoint needs to be sent a request periodically to tell the service to check for new uploads, create a summary for them (if any), and send the corresponding email(s).
- I have another service running to schedule these every half hour, but any cron job, systemd timer, or similar service would work.
- [Check out the service I use here](https://github.com/apalecz2/home-server-scheduler)



>I have this deployed on my home server (running linux) using docker, and set up Cloudflare tunnels to expose the REST API securely to the internet without any port forwarding on my local network. Since this deployment is just for myself to use (low traffic), this set up works nicely. 

---

## Architecture

```
┌─────────────────┐
│   Web Client    │ (Static HTML/JS Interface)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   FastAPI App   │ (REST API + Background Tasks)
└────────┬────────┘
         │
    ┌────┴────┬──────────┬──────────┐
    ▼         ▼          ▼          ▼
┌────────┐ ┌──────┐ ┌─────────┐ ┌──────┐
│ SQLite │ │YouTube│ │ Gemini │ │ Gmail│
│   DB   │ │  API  │ │   AI   │ │ OAuth│
└────────┘ └──────┘ └─────────┘ └──────┘
```

---

## Tech Stack

| Category | Technology |
|----------|-----------|
| **Backend Framework** | FastAPI |
| **Language** | Python 3.11+ |
| **AI/ML** | Google Gemini 2.5 Flash |
| **Database** | SQLite |
| **Email** | Gmail OAuth2 (SMTP) |
| **YouTube APIs** | `youtube-transcript-api`, `yt-dlp` |
| **Containerization** | Docker, Docker Compose |
| **Web Server** | Uvicorn (ASGI) |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional, for containerized deployment)
- Google Gemini API key
- Gmail OAuth2 credentials (Client ID, Secret, Refresh Token)

### Local Development Setup

1. **Clone and navigate to the service directory:**
   ```bash
   cd youtube-summary-service
   ```

2. **Create virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Create a `.env` file in `youtube-summary-service/` with:
   ```env
   API_AUTH_TOKEN=your-secure-api-key-here
   GEMINI_API_KEY=your-gemini-api-key
   EMAIL_USERNAME=your-email@gmail.com
   EMAIL_SENDTO=recipient@example.com
   GMAIL_CLIENT_ID=your-client-id
   GMAIL_CLIENT_SECRET=your-client-secret
   GMAIL_REFRESH_TOKEN=your-refresh-token
   ```

5. **Run the application:**
   ```bash
   python -m uvicorn app.main:app --reload
   ```

6. **Verify it's running:**
   ```bash
   curl http://127.0.0.1:8000/health
   ```

### Docker Deployment

1. **Build and run with Docker Compose:**
   ```bash
   cd youtube-summary-service
   docker compose up -d
   ```

2. **View logs:**
   ```bash
   docker logs -f youtube-summary
   ```

---

## API Documentation

### Base URL
```
http://localhost:8000
```

### Authentication
All endpoints (except `/health`) require an `X-API-Key` header:
```
X-API-Key: your-api-token
```

### Endpoints

#### `GET /health`
Health check endpoint (no authentication required).

**Response:**
```json
{
  "status": "ok",
  "service": "youtube-summary-service"
}
```

#### `POST /channels`
Add a YouTube channel to monitor.

**Request:**
```bash
curl -X POST http://localhost:8000/channels \
  -H "X-API-Key: your-token" \
  -F "channel_id=UC_x5XG1O"
```

#### `GET /channels`
List all monitored channels.

**Response:**
```json
{
  "channels": ["UC_x5XG1O", "..."]
}
```

#### `DELETE /channels/{channel_id}`
Remove a channel from monitoring.

#### `POST /summarize`
Manually trigger summarization for a specific video URL.

**Request:**
```bash
curl -X POST http://localhost:8000/summarize \
  -H "X-API-Key: your-token" \
  -F "url=https://www.youtube.com/watch?v=VIDEO_ID"
```

**Response:**
```json
{
  "status": "processing",
  "message": "Summarization started in the background",
  "video_id": "VIDEO_ID"
}
```

#### `POST /poll`
Check all monitored channels for new videos and process them.

**Request:**
```bash
curl -X POST http://localhost:8000/poll \
  -H "X-API-Key: your-token"
```

---

## Security Features

- **API Key Authentication**: All endpoints protected with `X-API-Key` header validation
- **OAuth2 Email**: Gmail integration uses secure OAuth2 token refresh
- **Environment Variables**: Sensitive credentials stored in `.env` (gitignored)
- **CORS Configuration**: Controlled cross-origin resource sharing

---

## Key Technical Highlights

### **Intelligent Transcript Processing**
- Handles multiple YouTube URL formats (`youtube.com/watch`, `youtu.be`, `/embed`)
- Prefers manual transcripts over auto-generated for accuracy
- Graceful fallback for unavailable transcripts

### **Smart Content Filtering**
- Metadata-based filtering before expensive transcript extraction
- Prevents processing of live streams, upcoming premieres, shorts, and overly long videos
- Reduces API costs and processing time

### **Scalable Summarization**
- Chunking strategy for transcripts exceeding 30K characters
- Parallel chunk processing with error handling
- Final consolidation pass for coherent summaries

### **Background Task Architecture**
- Non-blocking API responses using FastAPI `BackgroundTasks`
- Rate limiting considerations for external APIs
- Robust error handling and logging

