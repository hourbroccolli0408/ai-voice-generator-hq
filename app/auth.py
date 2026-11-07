from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from .config import settings


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    if not settings.supabase_url:
        raise RuntimeError("VOICEFORGE_SUPABASE_URL is required")
    return PyJWKClient(f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def get_current_user(authorization: str | None = Header(default=None)) -> str:
    """Return the authenticated account ID, or a stable local development identity."""
    if settings.auth_mode == "disabled":
        return "local-development-user"
    if settings.auth_mode != "supabase":
        raise HTTPException(status_code=500, detail="Unsupported authentication mode")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to continue")

    token = authorization.split(" ", 1)[1].strip()
    try:
        if settings.supabase_jwt_secret:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        else:
            signing_key = _jwks_client().get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience="authenticated",
            )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Your session is invalid or expired") from exc

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=401, detail="Your session has no account ID")
    return str(subject)
