"""Private, disposable project workspace files; PostgreSQL remains authoritative."""

from __future__ import annotations

import os
import secrets
import stat
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from app.document_contract import (
    DOCUMENT_FILENAMES,
    DOCUMENT_KINDS,
    MAX_DOCUMENT_BYTES,
    DocumentKind,
)

_DIRECTORY_FLAGS: Final[int] = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
_FILE_FLAGS: Final[int] = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
_EXISTING_FILE_FLAGS: Final[int] = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW

# A project can contribute at most three 128 KiB heads. Capping the cache at 64
# projects keeps its document payload below 24 MiB plus filesystem overhead.
MAX_CACHED_PROJECTS: Final[int] = 64


class WorkspaceError(OSError):
    """Raised when a workspace path is missing or cannot be opened safely."""


class WorkspaceStore:
    """Maintain a bounded, disposable mirror of DB-backed project drafts."""

    def __init__(self, root: Path, *, max_cached_projects: int = MAX_CACHED_PROJECTS) -> None:
        if max_cached_projects < 1:
            raise ValueError("The workspace cache must allow at least one project.")
        self.root = root
        self.max_cached_projects = max_cached_projects
        self._cache_lock = threading.RLock()

    def ensure_project(self, project_id: uuid.UUID) -> None:
        with self._cache_lock:
            root_fd = self._open_root()
            try:
                self._make_room(root_fd, project_id)
                project_fd = self._open_project(root_fd, project_id)
                os.close(project_fd)
            finally:
                os.close(root_fd)

    def write_document(self, project_id: uuid.UUID, kind: DocumentKind, content: str) -> None:
        filename = DOCUMENT_FILENAMES.get(kind)
        if filename is None:
            raise WorkspaceError("The requested document kind is not allowed.")

        encoded = self._encode_content(content)
        with self._cache_lock:
            root_fd = self._open_root()
            try:
                self._make_room(root_fd, project_id)
                project_fd = self._open_project(root_fd, project_id)
                try:
                    self._replace_file(project_fd, kind, filename, encoded)
                finally:
                    os.close(project_fd)
            finally:
                os.close(root_fd)

    def write_project(self, project_id: uuid.UUID, documents: Mapping[DocumentKind, str]) -> None:
        """Mirror one complete set of current heads after authorization in the API."""
        if set(documents) != set(DOCUMENT_KINDS):
            raise WorkspaceError("A project mirror must contain all three draft documents.")
        encoded = {kind: self._encode_content(documents[kind]) for kind in DOCUMENT_KINDS}

        with self._cache_lock:
            root_fd = self._open_root()
            try:
                self._make_room(root_fd, project_id)
                project_fd = self._open_project(root_fd, project_id)
                try:
                    for kind in DOCUMENT_KINDS:
                        filename = DOCUMENT_FILENAMES[kind]
                        self._replace_file(project_fd, kind, filename, encoded[kind])
                    os.fsync(project_fd)
                except OSError as exc:
                    try:
                        self._remove_project_contents(project_fd)
                    except WorkspaceError:
                        pass
                    if isinstance(exc, WorkspaceError):
                        raise
                    raise WorkspaceError(
                        "The project workspace could not be mirrored safely."
                    ) from exc
                finally:
                    os.close(project_fd)
            finally:
                os.close(root_fd)

    def discard_project(self, project_id: uuid.UUID) -> None:
        """Remove a possibly stale cache entry without following any workspace links."""
        with self._cache_lock:
            root_fd = self._open_root()
            try:
                self._remove_project(root_fd, str(project_id))
            finally:
                os.close(root_fd)

    @staticmethod
    def _encode_content(content: str) -> bytes:
        try:
            encoded = content.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise WorkspaceError("The project workspace requires valid UTF-8 text.") from exc
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise WorkspaceError("A workspace document exceeds the 128 KiB cache limit.")
        return encoded

    def _open_root(self) -> int:
        if not self.root.is_absolute() or self.root == Path("/"):
            raise WorkspaceError("The private workspace root must be an absolute child of '/'.")

        components = self.root.parts[1:]
        if not components or any(part in {"", ".", ".."} for part in components):
            raise WorkspaceError("The private workspace root is not a safe directory path.")

        current_fd = os.open("/", _DIRECTORY_FLAGS)
        try:
            for index, component in enumerate(components):
                is_root = index == len(components) - 1
                try:
                    next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
                except FileNotFoundError as exc:
                    if not is_root:
                        raise WorkspaceError(
                            "The private workspace parent is unavailable."
                        ) from exc
                    try:
                        os.mkdir(component, 0o700, dir_fd=current_fd)
                        next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=current_fd)
                    except OSError as create_error:
                        raise WorkspaceError("The private workspace root is unavailable.") from (
                            create_error
                        )

                os.close(current_fd)
                current_fd = next_fd

            self._secure_directory(current_fd)
            result_fd = current_fd
            current_fd = -1
            return result_fd
        except OSError as exc:
            if isinstance(exc, WorkspaceError):
                raise
            raise WorkspaceError("The private workspace root could not be opened safely.") from exc
        finally:
            if current_fd >= 0:
                os.close(current_fd)

    def _open_project(self, root_fd: int, project_id: uuid.UUID) -> int:
        directory_name = str(project_id)
        try:
            try:
                os.mkdir(directory_name, 0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
            project_fd = os.open(directory_name, _DIRECTORY_FLAGS, dir_fd=root_fd)
            self._secure_directory(project_fd)
            return project_fd
        except OSError as exc:
            if isinstance(exc, WorkspaceError):
                raise
            raise WorkspaceError("The project workspace could not be opened safely.") from exc

    def _make_room(self, root_fd: int, project_id: uuid.UUID) -> None:
        project_name = str(project_id)
        cached_projects = self._list_cached_projects(root_fd)
        target_exists = project_name in cached_projects
        required_count = len(cached_projects) + (0 if target_exists else 1)
        if required_count <= self.max_cached_projects:
            return

        eviction_candidates = sorted(
            (modified, name) for name, modified in cached_projects.items() if name != project_name
        )
        while required_count > self.max_cached_projects and eviction_candidates:
            _, oldest_name = eviction_candidates.pop(0)
            self._remove_project(root_fd, oldest_name)
            required_count -= 1
        if required_count > self.max_cached_projects:
            raise WorkspaceError("The bounded project workspace cache is full.")

    @staticmethod
    def _list_cached_projects(root_fd: int) -> dict[str, int]:
        projects: dict[str, int] = {}
        try:
            names = os.listdir(root_fd)
        except OSError as exc:
            raise WorkspaceError("The workspace cache could not be enumerated safely.") from exc
        for name in names:
            try:
                if str(uuid.UUID(name)) != name:
                    raise ValueError
            except ValueError as exc:
                raise WorkspaceError("The workspace root contains an unexpected entry.") from exc
            try:
                info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise WorkspaceError(
                    "A cached project workspace cannot be inspected safely."
                ) from exc
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
                raise WorkspaceError("A cached project workspace is not a trusted directory.")
            projects[name] = info.st_mtime_ns
        return projects

    def _remove_project(self, root_fd: int, project_name: str) -> None:
        try:
            info = os.stat(project_name, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise WorkspaceError(
                "The cached project workspace cannot be inspected safely."
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            try:
                os.unlink(project_name, dir_fd=root_fd)
                os.fsync(root_fd)
            except OSError as exc:
                raise WorkspaceError(
                    "The cached workspace link could not be removed safely."
                ) from exc
            return
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise WorkspaceError("A cached project workspace is not a trusted directory.")

        try:
            project_fd = os.open(project_name, _DIRECTORY_FLAGS, dir_fd=root_fd)
            try:
                self._secure_directory(project_fd)
                self._remove_project_contents(project_fd)
            finally:
                os.close(project_fd)
            os.rmdir(project_name, dir_fd=root_fd)
            os.fsync(root_fd)
        except OSError as exc:
            if isinstance(exc, WorkspaceError):
                raise
            raise WorkspaceError(
                "The cached project workspace could not be removed safely."
            ) from exc

    @staticmethod
    def _remove_project_contents(project_fd: int) -> None:
        try:
            for name in os.listdir(project_fd):
                # unlink removes symlinks themselves; it never traverses their targets.
                os.unlink(name, dir_fd=project_fd)
            os.fsync(project_fd)
        except OSError as exc:
            if isinstance(exc, WorkspaceError):
                raise
            raise WorkspaceError(
                "The cached project workspace could not be cleared safely."
            ) from exc

    @staticmethod
    def _secure_directory(directory_fd: int) -> None:
        info = os.fstat(directory_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise WorkspaceError("The workspace directory is not owned by the API user.")
        if stat.S_IMODE(info.st_mode) & 0o077:
            os.fchmod(directory_fd, 0o700)

    @staticmethod
    def _replace_file(directory_fd: int, kind: DocumentKind, filename: str, content: bytes) -> None:
        WorkspaceStore._validate_document_entry(directory_fd, filename)
        temporary_prefix = f".draft-{kind}-"
        try:
            for name in os.listdir(directory_fd):
                if name.startswith(temporary_prefix) and name.endswith(".tmp"):
                    os.unlink(name, dir_fd=directory_fd)
        except OSError as exc:
            raise WorkspaceError("Stale workspace files could not be cleared safely.") from exc

        temporary_name = f".draft-{kind}-{secrets.token_hex(16)}.tmp"
        try:
            file_fd = os.open(temporary_name, _FILE_FLAGS, 0o600, dir_fd=directory_fd)
            try:
                view = memoryview(content)
                while view:
                    written = os.write(file_fd, view)
                    if written <= 0:
                        raise WorkspaceError("The project workspace could not be written safely.")
                    view = view[written:]
                os.fsync(file_fd)
            finally:
                os.close(file_fd)
            WorkspaceStore._validate_document_entry(directory_fd, filename)
            os.replace(
                temporary_name,
                filename,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
        except OSError as exc:
            if isinstance(exc, WorkspaceError):
                raise
            raise WorkspaceError("The project workspace could not be updated safely.") from exc
        finally:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass

    @staticmethod
    def _validate_document_entry(directory_fd: int, filename: str) -> None:
        try:
            before_open = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise WorkspaceError(
                "The existing workspace document cannot be inspected safely."
            ) from exc

        if not stat.S_ISREG(before_open.st_mode) or before_open.st_uid != os.geteuid():
            raise WorkspaceError("An existing workspace document is not a trusted regular file.")

        try:
            file_fd = os.open(filename, _EXISTING_FILE_FLAGS, dir_fd=directory_fd)
        except OSError as exc:
            raise WorkspaceError(
                "The existing workspace document cannot be opened safely."
            ) from exc
        try:
            opened = os.fstat(file_fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or (opened.st_dev, opened.st_ino) != (before_open.st_dev, before_open.st_ino)
            ):
                raise WorkspaceError("The existing workspace document changed unexpectedly.")
        finally:
            os.close(file_fd)
