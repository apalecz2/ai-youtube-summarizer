"""Web session auth endpoints."""
from fastapi import APIRouter, Cookie, Form, HTTPException, Response

from app import config, security

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(response: Response, password: str = Form(...)):
    if not security.verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    security.issue_session(response)
    return {"status": "ok"}


@router.post("/logout")
def logout(response: Response):
    security.clear_session(response)
    return {"status": "ok"}


@router.get("/me")
def me(session: str | None = Cookie(None, alias=config.SESSION_COOKIE_NAME)):
    return {"authenticated": security._session_valid(session)}
