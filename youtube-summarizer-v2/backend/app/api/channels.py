"""Channel + per-channel filter management (v1-compatible so the existing
extension keeps working)."""
from fastapi import APIRouter, Depends, Form, HTTPException

from app.db import repos
from app.filters import VALID_ACTIONS, VALID_FIELDS, VALID_MATCH_TYPES
from app.security import require_auth

router = APIRouter(tags=["channels"], dependencies=[Depends(require_auth)])


@router.post("/channels")
def add_channel(channel_id: str = Form(...), title: str | None = Form(None)):
    repos.add_channel(channel_id, title)
    return {"status": "channel added", "channel_id": channel_id}


@router.delete("/channels/{channel_id}")
def remove_channel(channel_id: str):
    repos.remove_channel(channel_id)
    return {"status": "channel removed", "channel_id": channel_id}


@router.get("/channels")
def list_channels():
    return {"channels": repos.get_channels(active_only=False)}


@router.get("/channels/{channel_id}/filters")
def list_filters(channel_id: str):
    return {"channel_id": channel_id, "filters": repos.get_channel_filters(channel_id)}


@router.post("/channels/{channel_id}/filters")
def add_filter(channel_id: str, value: str = Form(...), field: str = Form("title"),
               match_type: str = Form("contains"), action: str = Form("include")):
    if not value.strip():
        raise HTTPException(status_code=400, detail="Filter value cannot be empty.")
    if field not in VALID_FIELDS:
        raise HTTPException(status_code=400, detail=f"Invalid field. Must be one of {VALID_FIELDS}.")
    if match_type not in VALID_MATCH_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid match_type. Must be one of {VALID_MATCH_TYPES}.")
    if action not in VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid action. Must be one of {VALID_ACTIONS}.")
    filter_id = repos.add_channel_filter(channel_id, value.strip(), field, match_type, action)
    return {"status": "filter added", "filter": {
        "id": filter_id, "channel_id": channel_id, "field": field,
        "match_type": match_type, "value": value.strip(), "action": action}}


@router.delete("/channels/filters/{filter_id}")
def remove_filter(filter_id: int):
    repos.remove_channel_filter(filter_id)
    return {"status": "filter removed", "filter_id": filter_id}
