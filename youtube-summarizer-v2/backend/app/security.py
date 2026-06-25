"""Authentication.

Two accepted credentials, either of which satisfies `require_auth`:
  • a signed session cookie (web UI, set by /auth/login), or
  • the X-API-Key header (browser extension / scripts, v1-compatible).

The web password is checked against a SHA-256 hash from the env, never stored
plaintext. Session cookies are signed (itsdangerous) so they can't be forged.
"""
import hashlib
import hmac

from fastapi import Cookie, Header, HTTPException, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import config

_SESSION_VALUE = "ok"


def _serializer() -> URLSafeTimedSerializer:
    if not config.SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET not set")
    return URLSafeTimedSerializer(config.SESSION_SECRET, salt="yts-session")


def verify_password(password: str) -> bool:
    if not config.APP_PASSWORD_SHA256:
        return False
    digest = hashlib.sha256(password.encode()).hexdigest()
    # Constant-time compare (compare_digest lives in hmac, not hashlib).
    return hmac.compare_digest(digest, config.APP_PASSWORD_SHA256.lower())


def issue_session(response: Response) -> None:
    token = _serializer().dumps(_SESSION_VALUE)
    response.set_cookie(
        config.SESSION_COOKIE_NAME, token,
        max_age=config.SESSION_MAX_AGE_SECONDS,
        httponly=True, samesite="lax", secure=True,
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(config.SESSION_COOKIE_NAME)


def _session_valid(token: str | None) -> bool:
    if not token:
        return False
    try:
        _serializer().loads(token, max_age=config.SESSION_MAX_AGE_SECONDS)
        return True
    except (BadSignature, SignatureExpired):
        return False


def _api_key_valid(key: str | None) -> bool:
    return bool(config.API_AUTH_TOKEN) and key == config.API_AUTH_TOKEN


def require_auth(
    x_api_key: str | None = Header(None),
    session: str | None = Cookie(None, alias=config.SESSION_COOKIE_NAME),
) -> None:
    if _session_valid(session) or _api_key_valid(x_api_key):
        return
    raise HTTPException(status_code=401, detail="Unauthorized")
