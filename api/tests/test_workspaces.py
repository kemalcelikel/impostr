from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.document_contract import (
    DOCUMENT_FILENAMES,
    DOCUMENT_KINDS,
    MAX_DOCUMENT_BYTES,
    DocumentKind,
)
from app.workspaces import WorkspaceError, WorkspaceStore


def test_workspace_root_symlink_is_rejected_without_writing_outside(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    root_link = tmp_path / "workspace-link"
    root_link.symlink_to(outside, target_is_directory=True)
    project_id = uuid.uuid4()

    with pytest.raises(WorkspaceError):
        WorkspaceStore(root_link).write_document(project_id, "project", "private draft")

    assert list(outside.iterdir()) == []


def test_project_directory_symlink_is_rejected_without_traversal(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    root.mkdir(mode=0o700)
    outside = tmp_path / "sibling-project"
    outside.mkdir(mode=0o700)
    project_id = uuid.uuid4()
    (root / str(project_id)).symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceError):
        WorkspaceStore(root).write_document(project_id, "project", "private draft")

    assert list(outside.iterdir()) == []


def test_workspace_document_symlink_is_denied_without_following_or_replacing_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspaces"
    outside = tmp_path / "outside.md"
    outside.write_text("must remain private", encoding="utf-8")
    store = WorkspaceStore(root)
    project_id = uuid.uuid4()
    store.ensure_project(project_id)
    document_path = root / str(project_id) / "PROJECT.md"
    document_path.symlink_to(outside)

    with pytest.raises(WorkspaceError):
        store.write_document(project_id, "project", "must not replace the link")

    assert document_path.is_symlink()
    assert document_path.resolve() == outside
    assert outside.read_text(encoding="utf-8") == "must remain private"


def test_workspace_replaces_an_existing_regular_document(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    store = WorkspaceStore(root)
    project_id = uuid.uuid4()
    store.write_document(project_id, "project", "first draft")

    store.write_document(project_id, "project", "current draft")

    document_path = root / str(project_id) / "PROJECT.md"
    assert not document_path.is_symlink()
    assert document_path.read_text(encoding="utf-8") == "current draft"


def _bounded_project_documents(label: str) -> dict[DocumentKind, str]:
    documents: dict[DocumentKind, str] = {}
    for kind, filename in DOCUMENT_FILENAMES.items():
        prefix = f"{label}:{filename}\n"
        documents[kind] = prefix + ("x" * (MAX_DOCUMENT_BYTES - len(prefix)))
    return documents


def test_workspace_cache_evicts_old_projects_across_restart_with_bounded_size(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspaces"
    first, second, third, fourth = (uuid.uuid4() for _ in range(4))
    store = WorkspaceStore(root, max_cached_projects=2)
    store.write_project(first, _bounded_project_documents("first"))
    store.write_project(second, _bounded_project_documents("second"))

    os.utime(root / str(first), ns=(1_000, 1_000))
    os.utime(root / str(second), ns=(2_000, 2_000))
    store.write_project(third, _bounded_project_documents("third"))

    assert not (root / str(first)).exists()
    assert (root / str(second)).is_dir()
    assert (root / str(third)).is_dir()
    cached_bytes = sum(
        item.stat().st_size
        for project_directory in root.iterdir()
        for item in project_directory.iterdir()
    )
    assert cached_bytes <= 2 * len(DOCUMENT_KINDS) * MAX_DOCUMENT_BYTES

    # A new process has no in-memory LRU state; filesystem timestamps still bound eviction.
    os.utime(root / str(second), ns=(3_000, 3_000))
    os.utime(root / str(third), ns=(4_000, 4_000))
    restarted_store = WorkspaceStore(root, max_cached_projects=2)
    restarted_store.write_project(fourth, _bounded_project_documents("fourth"))

    assert not (root / str(second)).exists()
    assert (root / str(third)).is_dir()
    assert (root / str(fourth)).is_dir()
    assert sorted(path.name for path in root.iterdir()) == sorted((str(third), str(fourth)))


def test_workspace_rejects_oversized_direct_cache_writes(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"

    with pytest.raises(WorkspaceError):
        WorkspaceStore(root).write_document(uuid.uuid4(), "project", "x" * (MAX_DOCUMENT_BYTES + 1))

    assert not root.exists()
