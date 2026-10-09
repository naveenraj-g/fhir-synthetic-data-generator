"""JWT/JWKS verification — entirely optional. Nothing in this starter kit
requires auth by default; app/routers/item.py applies
Depends(get_current_user) to exactly one endpoint (delete) to demonstrate
the pattern, and leaves the rest open. Wire it onto whichever routes your
own app actually needs to protect, via require_permission() (app/auth/rbac.py)
or get_current_user directly.

Requires settings.JWKS_URL / settings.JWT_ISSUER to be set — if you don't
need auth at all, just never depend on get_current_user anywhere and these
two settings can stay unset."""

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import settings
from app.core.logging import get_logger
from app.errors.auth import AuthenticationError

logger = get_logger(__name__)
_security = HTTPBearer(auto_error=False)

_jwk_client: PyJWKClient | None = (
    PyJWKClient(settings.JWKS_URL) if settings.JWKS_URL else None
)


def decode_token(token: str) -> dict:
    if _jwk_client is None:
        raise AuthenticationError("Auth is not configured (JWKS_URL unset)")
    signing_key = _jwk_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=settings.auth.algorithms,
        issuer=settings.JWT_ISSUER,
        options={"verify_aud": False},
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
):
    if credentials is None:
        logger.warning(
            "Missing bearer token", extra={"event": "auth.failed", "reason": "missing_token"}
        )
        raise AuthenticationError("Missing bearer token")

    try:
        claims = decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        logger.warning(
            "Token verification failed",
            extra={"event": "auth.failed", "reason": str(exc)},
        )
        raise AuthenticationError("Invalid or expired token") from exc

    request.state.user = {
        "sub": claims.get("sub"),
        "org_id": claims.get("org_id"),
        "permissions": claims.get("permissions", []),
    }
    return request.state.user
