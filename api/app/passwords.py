"""Bounded Argon2id password operations and opaque token primitives."""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
_HASH_SLOTS = threading.BoundedSemaphore(value=2)
_HASH_SLOT_TIMEOUT_SECONDS = 0.25
_USERNAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._@+-]{2,126}\Z")


class PasswordHashCapacityError(RuntimeError):
    """Raised when the bounded password-hashing pool is saturated."""


def normalize_username(username: str) -> str:
    normalized = username.strip().casefold()
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("Username must be 3–127 ASCII letters, digits, or . _ @ + -")
    return normalized


def validate_new_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    if len(password) > 256 or len(password.encode("utf-8")) > 1024:
        raise ValueError("Password is too long")


def _acquire_hash_slot() -> None:
    if not _HASH_SLOTS.acquire(timeout=_HASH_SLOT_TIMEOUT_SECONDS):
        raise PasswordHashCapacityError("Password hashing capacity is temporarily full")


def hash_password(password: str) -> str:
    validate_new_password(password)
    _acquire_hash_slot()
    try:
        return PASSWORD_HASHER.hash(password)
    finally:
        _HASH_SLOTS.release()


def verify_password(password_hash: str, password: str) -> bool:
    _acquire_hash_slot()
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False
    finally:
        _HASH_SLOTS.release()


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """Use the same expensive Argon2id path for unknown and inactive accounts."""
    return hash_password(secrets.token_urlsafe(32))


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes | None:
    if len(token) != 43 or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    return hashlib.sha256(token.encode("ascii")).digest()


def csrf_hash_matches(token: str, expected_hash: bytes) -> bool:
    candidate_hash = token_hash(token)
    return candidate_hash is not None and secrets.compare_digest(candidate_hash, expected_hash)
