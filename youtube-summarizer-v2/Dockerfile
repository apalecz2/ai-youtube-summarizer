# ── Stage 1: build the React SPA ───────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python backend (also serves the built SPA) ────────
FROM python:3.11-slim AS app
WORKDIR /app
ENV PYTHONUNBUFFERED=1

# ca-certificates for HTTPS (yt-dlp / Gemini / Gmail). No build tools needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
# FRONTEND_DIST defaults to ./frontend_dist (see config.py), served by FastAPI.
COPY --from=frontend /frontend/dist ./frontend_dist

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
