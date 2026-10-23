"""Canonical project-name validation and owner-scoped uniqueness keys."""

from __future__ import annotations

import hashlib
import unicodedata

MAX_PROJECT_NAME_LENGTH = 120


def normalize_project_name(value: str) -> str:
    """Trim and validate a display name; names are never interpreted as paths."""
    name = unicodedata.normalize("NFC", value).strip()
    if not name:
        raise ValueError("Project names must contain at least one non-space character.")
    if len(name) > MAX_PROJECT_NAME_LENGTH:
        raise ValueError(f"Project names may contain at most {MAX_PROJECT_NAME_LENGTH} characters.")
    if name in {".", ".."}:
        raise ValueError("Project names cannot be '.' or '..'.")
    if any(character in "/\\" for character in name):
        raise ValueError("Project names cannot contain path separators.")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in name):
        raise ValueError("Project names cannot contain control or formatting characters.")
    return name


def project_name_key(name: str) -> str:
    """Bound the indexed key even when Unicode compatibility folding expands a name."""
    canonical = unicodedata.normalize("NFKC", name).strip().casefold()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
