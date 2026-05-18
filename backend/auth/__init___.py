"""Authentication subsystem.

Public API:

    from backend.auth import (
        hash_password,
        verify_password,
        create_access_token,
        decode_access_token,
        TokenError,
        get_current_user,
        require_role,
        COOKIE_NAME,
        UserInfo,
        LoginRequest,
        LoginResponse,
    )
"""

from .dependencies import COOKIE_NAME, get_current_user, require_role
from .models import LoginRequest, LoginResponse, UserInfo
from .passwords import hash_password, verify_password
from .tokens import TokenError, create_access_token, decode_access_token

__all__ = [
    "COOKIE_NAME",
    "LoginRequest",
    "LoginResponse",
    "TokenError",
    "UserInfo",
    "create_access_token",
    "decode_access_token",
    "get_current_user",
    "hash_password",
    "require_role",
    "verify_password",
]
