"""FastAPI dependencies for authentication and authorisation.

Two main exports:

    get_current_user — resolves the auth cookie to a UserInfo (or 401)
    require_role     — factory that returns a dependency requiring
                       the user to hold at least one of the listed roles

Usage examples:

    # Anyone logged in:
    @app.get("/api/cases")
    def list_cases(user: UserInfo = Depends(get_current_user)):
        ...

    # Only DQO or Admin:
    @app.post("/api/imports/upload")
    def upload(
        file: UploadFile,
        user: UserInfo = Depends(require_role(["DQO", "ADMIN"])),
    ):
        ...

    # Use as decorator-style if you don't need the user object:
    @app.post(
        "/api/periods/close",
        dependencies=[Depends(require_role(["DIRECTOR", "ADMIN", "FO"]))],
    )
    def close_period(year_month: str):
        ...
"""

from fastapi import Cookie, Depends, HTTPException, status

from .models import UserInfo
from .tokens import TokenError, decode_access_token
from backend.data.connection import get_connection


# Cookie name used to carry the JWT. Used by the login endpoint when
# setting the cookie and here when reading it.
COOKIE_NAME = "auth_token"


def get_current_user(
    auth_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> UserInfo:
    """Resolve the current user from the auth cookie.

    Decodes the JWT, looks up the user in the DB to confirm they're still
    active and to refresh their role list, returns a UserInfo.

    Raises 401 if there's no cookie, the token is invalid/expired, the
    user no longer exists, or the user is INACTIVE.
    """
    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
        )

    try:
        claims = decode_access_token(auth_token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )

    user_id = int(claims["sub"])

    # Fetch user + current roles. We deliberately re-read roles every
    # request rather than trusting the token's snapshot, so role
    # grants/revocations take effect immediately.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    u.id,
                    u.email,
                    u.display_name,
                    u.staff_id,
                    u.employment_status,
                    rs.canonical_name AS linked_staff_name,
                    COALESCE(
                        ARRAY_AGG(r.code ORDER BY r.code)
                            FILTER (WHERE r.code IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS roles
                FROM app_user u
                LEFT JOIN ref_staff rs      ON rs.id = u.staff_id
                LEFT JOIN app_user_role aur ON aur.user_id = u.id
                LEFT JOIN dim_app_role r    ON r.id = aur.role_id
                WHERE u.id = %s
                GROUP BY u.id, rs.canonical_name
                """,
                (user_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user no longer exists",
        )

    if row["employment_status"] != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="account is inactive",
        )

    return UserInfo(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        roles=list(row["roles"]),
        staff_id=row["staff_id"],
        linked_staff_name=row["linked_staff_name"],
    )


def require_role(allowed_roles: list[str]):
    """Factory returning a dependency that requires one of the listed roles.

    Use the result as a Depends() value:

        def handler(
            user: UserInfo = Depends(require_role(["DQO", "ADMIN"])),
        ):
            # user is guaranteed to hold DQO or ADMIN
            ...

    Or as a dependencies=[...] entry on the route if the user object
    isn't needed inside the handler:

        @app.post(
            "/api/...",
            dependencies=[Depends(require_role(["DIRECTOR"]))],
        )
        def handler():
            ...

    Raises 403 if the current user has none of the allowed roles.
    Implicitly requires the user to be logged in (chains get_current_user).
    """
    allowed_set = set(allowed_roles)

    def role_check(
        user: UserInfo = Depends(get_current_user),
    ) -> UserInfo:
        if not allowed_set.intersection(user.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"this action requires one of: {sorted(allowed_set)}. "
                    f"Your roles: {sorted(user.roles)}"
                ),
            )
        return user

    return role_check
