"""Password hashing and verification using stdlib only.

Uses PBKDF2-HMAC-SHA256 with 600,000 iterations (OWASP 2023 recommendation
for password storage). Hash format matches Migration 14l:

    pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>

This is the same format Django uses by default and is self-describing —
the algorithm and iteration count are stored alongside each hash, allowing
parameters to be rotated without breaking existing users.

No third-party dependencies.
"""

import base64
import hashlib
import secrets


# These constants MUST match Migration 14l for hash compatibility.
# If you change ITERATIONS, existing hashes still verify (they carry their
# own iteration count); new hashes use the new value.
ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000
SALT_BYTES = 16
HASH_BYTES = 32


def hash_password(plaintext: str) -> str:
    """Hash a password for storage.

    Returns a self-describing hash string:
        pbkdf2_sha256$600000$<salt_base64>$<hash_base64>

    Each call generates a unique salt, so the same password produces
    different hashes every time — this is correct, secure behaviour.
    """
    if not plaintext:
        raise ValueError("password cannot be empty")

    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        plaintext.encode("utf-8"),
        salt,
        ITERATIONS,
        dklen=HASH_BYTES,
    )
    return f"{ALGORITHM}${ITERATIONS}${_b64_no_pad(salt)}${_b64_no_pad(derived)}"


def verify_password(plaintext: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored hash.

    Returns True if it matches, False otherwise. Never raises — invalid
    hash formats, wrong algorithm, base64 errors etc. all return False.
    This avoids leaking information about the failure mode to callers.

    Uses constant-time comparison to defend against timing attacks.
    """
    if not plaintext or not stored_hash:
        return False

    try:
        algo, iters_str, salt_b64, hash_b64 = stored_hash.split("$")
    except ValueError:
        return False

    if algo != ALGORITHM:
        return False

    try:
        iterations = int(iters_str)
        salt = _b64_decode(salt_b64)
        expected = _b64_decode(hash_b64)
    except (ValueError, TypeError):
        return False

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        plaintext.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected),
    )
    return secrets.compare_digest(derived, expected)


def _b64_no_pad(data: bytes) -> str:
    """Encode bytes as base64 without the '=' padding (Django format)."""
    return base64.b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(s: str) -> bytes:
    """Decode base64 string, re-adding padding as needed."""
    padding = "=" * ((4 - len(s) % 4) % 4)
    return base64.b64decode(s + padding)
