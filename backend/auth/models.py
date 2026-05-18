"""Pydantic schemas for the auth subsystem.

Kept separate from the rest of main.py's models so the auth module can
be imported standalone (useful for tests).
"""

from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """POST /api/auth/login request body."""

    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1)


class UserInfo(BaseModel):
    """The current user's identity as exposed to the frontend.

    Returned by GET /api/auth/me and embedded in the login response.
    Never includes the password hash.
    """

    id: int
    email: str
    display_name: str
    roles: list[str]
    staff_id: Optional[int] = None
    linked_staff_name: Optional[str] = None


class LoginResponse(BaseModel):
    """POST /api/auth/login response body.

    The actual token is set in an HttpOnly cookie (not in the body).
    The body returns the user info so the frontend can display the
    user's name and conditionally render UI based on their roles.
    """

    user: UserInfo
