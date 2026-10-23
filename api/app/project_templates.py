"""Load the fixed, versioned starter examples packaged with the API image."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from app.document_contract import DOCUMENT_KINDS, MAX_DOCUMENT_BYTES, TEMPLATE_SOURCES, DocumentKind
from app.template_profiles import SUPPORTED_STARTERS


class TemplateBundleError(RuntimeError):
    """Raised when the packaged starter files cannot be trusted or read."""


@dataclass(frozen=True, slots=True)
class ProjectTemplate:
    kind: DocumentKind
    source: str
    content: str
    sha256: str


def default_template_root() -> Path:
    configured = os.environ.get("IMPOSTR_TEMPLATE_DIR")
    if configured:
        return Path(configured)
    # Both checkout and image preserve the canonical nested source paths.
    source_root = Path(__file__).resolve().parents[2]
    if all((source_root / source).is_file() for source in TEMPLATE_SOURCES.values()):
        return source_root
    checkout_root = source_root.parent
    if all((checkout_root / source).is_file() for source in TEMPLATE_SOURCES.values()):
        return checkout_root
    packaged_root = Path("/app/templates")
    if packaged_root.is_dir():
        return packaged_root
    return source_root


def load_project_templates(root: Path) -> dict[DocumentKind, ProjectTemplate]:
    templates: dict[DocumentKind, ProjectTemplate] = {}
    try:
        for kind in DOCUMENT_KINDS:
            source = TEMPLATE_SOURCES[kind]
            path = root / source
            if root.is_symlink() or path.parent.is_symlink():
                raise TemplateBundleError("The packaged project templates are invalid.")
            file_info = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(file_info.st_mode) or file_info.st_size > MAX_DOCUMENT_BYTES:
                raise TemplateBundleError("The packaged project templates are invalid.")
            raw_content = path.read_bytes()
            if len(raw_content) > MAX_DOCUMENT_BYTES:
                raise TemplateBundleError("A packaged project template exceeds the size limit.")
            content = raw_content.decode("utf-8", errors="strict")
            templates[kind] = ProjectTemplate(
                kind=kind,
                source=source,
                content=content,
                sha256=hashlib.sha256(raw_content).hexdigest(),
            )
    except (OSError, UnicodeDecodeError) as exc:
        raise TemplateBundleError("The packaged project templates are unavailable.") from exc
    identity = tuple((templates[kind].source, templates[kind].sha256) for kind in DOCUMENT_KINDS)
    if identity != SUPPORTED_STARTERS["simplified"]:
        raise TemplateBundleError("The packaged project template version is not supported.")
    return templates
