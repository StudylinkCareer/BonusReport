"""JWT creation and verification using PyJWT.

Tokens carry user identity and roles so the API can authorise requests
without a database lookup on every call. Signed with HMAC-SHA256 using a
shared secret loaded from JWT_SECRET in the environment (backend/.env).

Token claims:
    sub         subject — user id, as string per the JWT spec
    email       user email
    roles       list of role codes (e.g. ["DIRECTOR", "ADMIN"])
    staff_id    linked ref_staff.id, or None for function users
    iat         issued-at  (Unix timestamp)
    exp         expiry     (Unix timestamp)

Tokens are typically delivered as an HttpOnly cookie, NOT in the response
body — keeps them out of JavaScript-accessible storage.

Install:  pip install pyjwt
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt


JWT_ALGORITHM = "HS256"
DEFAULT_EXPIRY_HOURS = 8


class TokenError(Exception):
    """Raised when token creation or verification fails."""


def _require_secret() -> str:
    """Load JWT_SECRET from env with a clear error if missing.

    Loaded fresh each call rather than at import time so the .env file
    can be reloaded without restarting Python. Cheap to re-read.
    """
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise TokenError(
            "JWT_SECRET environment variable is not set. "
            "Add a strong random value to backend/.env. "
            "Generate one with: python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\""
        )
    return secret


def create_access_token(
    user_id: int,
    email: str,
    roles: list[str],
    staff_id: Optional[int],
    expires_in_hours: int = DEFAULT_EXPIRY_HOURS,
) -> str:
    """Create a signed JWT carrying the user's identity and roles.

    Returns the encoded token as a string, suitable for setting in a
    cookie. The roles list embedded in the token is a snapshot at
    issue-time — the get_current_user dependency refreshes them from
    the DB on each request, so role grants/revocations take effect
    immediately, not after the token expires.
    """
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "email": email,
        "roles": roles,
        "staff_id": staff_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_in_hours)).timestamp()),
    }
    return jwt.encode(claims, _require_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Verify and decode a JWT, returning the claim dict.

    Raises TokenError on any validation failure (bad signature, expired,
    malformed, wrong algorithm). Never returns invalid data.
    """
    try:
        return jwt.decode(
            token,
            _require_secret(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise TokenError("token has expired")
    except jwt.InvalidTokenError as exc:
        raise TokenError(f"invalid token: {exc}")
