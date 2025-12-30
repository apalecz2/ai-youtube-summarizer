from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv
import os

from app.db import init_db

# Load environment variables
load_dotenv()

# Ensure db created automatically, and tables exist before any api calls
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="YouTube Summary Service",
    version="0.1.0",
    lifespan=lifespan
)

# Check app status endpoint
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "youtube-summary-service"
    }
