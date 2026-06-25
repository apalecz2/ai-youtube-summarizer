"""FastAPI entrypoint.

Serves the JSON API under /api and (in production) the built React SPA as static
files from the same origin, so the browser session cookie just works. The
in-process scheduler + worker start/stop with the app lifespan — no external cron.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config, scheduler
from app.api import actions, auth, channels, content
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(title="YouTube Summarizer v2", version="2.0.0", lifespan=lifespan)

# Same-origin SPA needs no CORS; the extension uses X-API-Key (no cookie). Allow
# the dev frontend + extensions to call the API with credentials.
_origins = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.head("/health")
def health_head():
    return Response(status_code=status.HTTP_200_OK)


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "youtube-summarizer-v2"}


# ── API routers (all under /api) ──────────────────────────────
for r in (auth.router, channels.router, content.router, actions.router):
    app.include_router(r, prefix="/api")


# ── Serve the built SPA (if present) ──────────────────────────
if config.serve_frontend():
    assets_dir = config.FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    _index = config.FRONTEND_DIST / "index.html"

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # Let unknown API paths 404 as JSON rather than returning the SPA shell.
        if full_path.startswith("api/"):
            return Response(status_code=404)
        candidate = config.FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_index)
