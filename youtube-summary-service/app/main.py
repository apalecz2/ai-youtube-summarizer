from fastapi import FastAPI
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

app = FastAPI(
    title="YouTube Summary Service",
    version="0.1.0"
)

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "youtube-summary-service"
    }
