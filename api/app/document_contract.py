"""Shared names and limits for the three planning documents."""

from typing import Literal

DocumentKind = Literal["project", "agents", "backlog"]

DOCUMENT_KINDS: tuple[DocumentKind, ...] = ("project", "agents", "backlog")
DOCUMENT_FILENAMES: dict[DocumentKind, str] = {
    "project": "PROJECT.md",
    "agents": "AGENTS.md",
    "backlog": "BACKLOG.md",
}
TEMPLATE_SOURCES: dict[DocumentKind, str] = {
    "project": "PROJECT.md.example",
    "agents": "AGENTS.md.example",
    "backlog": "BACKLOG.md.example",
}

# nginx permits a 1 MiB JSON request; the document itself is bounded well below it.
MAX_DOCUMENT_BYTES = 128 * 1024
MAX_REVISION_NUMBER = 2_147_483_647
HISTORY_PAGE_SIZE = 50
