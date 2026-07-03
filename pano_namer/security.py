from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import importlib.util
import secrets

_PBKDF2_ALGORITHM = "sha256"
_PBKDF2_ITERATIONS = 600_000


def _passlib_context():
    if importlib.util.find_spec("passlib") is None:
        return None
    passlib_context = importlib.import_module("passlib.context")
    return passlib_context.CryptContext(schemes=["bcrypt"], deprecated="auto")


def _hash_password_with_stdlib(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(_PBKDF2_ALGORITHM, password.encode(), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def _verify_stdlib_password(password: str, password_hash: str) -> bool:
    parts = password_hash.split("$", 3)
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        salt = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
        expected = base64.urlsafe_b64decode(parts[3] + "=" * (-len(parts[3]) % 4))
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac(_PBKDF2_ALGORITHM, password.encode(), salt, iterations)
    return hmac.compare_digest(digest, expected)


def hash_password(password: str) -> str:
    """Return a one-way hash for a plain-text password."""
    context = _passlib_context()
    if context is not None:
        return context.hash(password)
    return _hash_password_with_stdlib(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plain-text password against a stored hash."""
    if not password_hash:
        return False
    if password_hash.startswith("pbkdf2_sha256$"):
        return _verify_stdlib_password(password, password_hash)
    context = _passlib_context()
    if context is None:
        return False
    return bool(context.verify(password, password_hash))
