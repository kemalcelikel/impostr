"""Frozen 63c853c starter bytes, never used as application runtime inputs."""

import hashlib
from pathlib import Path

from app.document_contract import DOCUMENT_KINDS
from app.project_templates import ProjectTemplate
from app.template_profiles import SUPPORTED_STARTERS

LEGACY_STARTERS = SUPPORTED_STARTERS["legacy"]


def legacy_templates():
    result = {}
    for kind, (source, digest) in zip(DOCUMENT_KINDS, LEGACY_STARTERS, strict=True):
        raw = (Path(__file__).with_suffix("") / source).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        result[kind] = ProjectTemplate(kind, source, raw.decode("utf-8"), digest)
    return result
