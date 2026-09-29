#!/usr/bin/env python3
"""Run a disposable, real-app local browser-review fixture.

The supervisor starts under a PTY, archives committed HEAD into a private temporary
directory, creates a fresh loopback-only Compose project, and keeps ownership of
that project through the browser handoff. A parent closing PTY stdin is not a stop
request. Only the browser-review member login is shown at handoff; the offline
admin password and database credentials never enter command arguments,
browser-tool calls, or output.
"""

from __future__ import annotations

import argparse
import fcntl
import http.cookiejar
import ipaddress
import json
import os
import pty
import re
import secrets
import select
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import termios
import time
import urllib.error
import urllib.request
import uuid

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, TextIO
from urllib.parse import urlsplit


MAX_RESPONSE_BYTES = 1024 * 1024
MAX_BOOTSTRAP_DIAGNOSTIC_BYTES = 16 * 1024
MAX_MIGRATION_DIAGNOSTIC_BYTES = 2 * 1024
EXPECTED_APP_MIGRATION = "20260925_0002"
EXPECTED_APP_REVISIONS = ("20260925_0001", EXPECTED_APP_MIGRATION)
DEFAULT_LIFETIME_MINUTES = 120
MIN_LIFETIME_MINUTES = 5
MAX_LIFETIME_MINUTES = 240
LOCAL_DOCKER_SOCKET = "/var/run/docker.sock"
ADMIN_PASSWORD_PROMPTS = (
    "New administrator password:",
    "Confirm new administrator password:",
)
SAFE_BOOTSTRAP_CLI = """\
import re
import sys
import app.bootstrap_admin as bootstrap_cli
from sqlalchemy.exc import (
    DataError,
    DatabaseError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
    SQLAlchemyError,
)
from sqlalchemy import inspect, text

_original_bootstrap_admin = bootstrap_cli.bootstrap_admin

def _fixture_safe_bootstrap_admin(engine, username, password):
    try:
        return _original_bootstrap_admin(engine, username, password)
    except SQLAlchemyError as error:
        cause = getattr(error, "orig", None)
        sqlstate = getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)
        if not isinstance(sqlstate, str) or re.fullmatch(r"[0-9A-Z]{5}", sqlstate) is None:
            sqlstate = "unknown"
        if isinstance(error, IntegrityError):
            category = "integrity"
        elif isinstance(error, ProgrammingError):
            category = "programming"
        elif isinstance(error, OperationalError):
            category = "operational"
        elif isinstance(error, InterfaceError):
            category = "interface"
        elif isinstance(error, DataError):
            category = "data"
        elif isinstance(error, DatabaseError):
            category = "database"
        else:
            category = "other"
        schema = "not-checked"
        migration = "not-checked"
        if sqlstate == "42P01":
            try:
                known_tables = (
                    "alembic_version",
                    "users",
                    "projects",
                    "web_sessions",
                    "rate_limit_buckets",
                    "audit_events",
                    "bootstrap_state",
                )
                with engine.connect() as connection:
                    present_tables = set(inspect(connection).get_table_names())
                    if "alembic_version" in present_tables:
                        version = connection.execute(
                            text("SELECT version_num FROM alembic_version")
                        ).scalar_one_or_none()
                    else:
                        version = None
                missing_table = next(
                    (name for name in known_tables if name not in present_tables), None
                )
                schema = f"missing-{missing_table}" if missing_table else "expected-present"
                migration = {
                    "20260925_0001": "0001",
                    "20260925_0002": "0002",
                }.get(version, "empty" if version is None else "other")
            except Exception:
                schema = "unavailable"
                migration = "unavailable"
        raise ValueError(
            f"Fixture database diagnostic: class={category} sqlstate={sqlstate} "
            f"schema={schema} migration={migration}"
        ) from None

bootstrap_cli.bootstrap_admin = _fixture_safe_bootstrap_admin
raise SystemExit(bootstrap_cli.main(["bootstrap", "--username", sys.argv[1]]))
"""
APP_SNAPSHOT_PATHS = (
    "compose.yaml",
    "db",
    "api",
    "web",
    "PROJECT.md.example",
    "AGENTS.md.example",
    "BACKLOG.md.example",
)
APP_SNAPSHOT_FILES = frozenset(
    {
        "compose.yaml",
        "PROJECT.md.example",
        "AGENTS.md.example",
        "BACKLOG.md.example",
    }
)
REVIEW_IMAGE_PROJECT_LABEL = "io.impostr.local-browser-review.project"
REVIEW_IMAGE_SERVICE_LABEL = "io.impostr.local-browser-review.service"
REVIEW_IMAGE_SERVICES = ("db", "api", "frontdoor")
REVIEW_IMAGE_TAG = "fixture"
MEMBER_RECOVERY_FILE = "member-recovery.json"
APPROVED_HANDOFF_DIRECTORY = Path("/tmp/opencode/impostr-review-handoff")
MEMBER_HANDOFF_FILE = "member-login.json"
CLEANUP_STATUS_FILE = "cleanup-status.json"
CONTROL_DIRECTORY_PREFIX = "impostr-browser-review-control-"
CONTROL_FILE = "supervisor.json"
CONTROL_LOCK_FILE = "supervisor.lock"
MAX_CHANNEL_JSON_BYTES = 4096
MAX_PTY_LINE_BYTES = 4096
STARTUP_TIMEOUT_SECONDS = 1800
CLEANUP_WAIT_SECONDS = 900
PTY_READY_LINE = re.compile(
    rb"FIXTURE_HANDOFF_READY (http://127(?:\.[0-9]{1,3}){3}:[0-9]{1,5})\r?$"
)
CHANNEL_STATUS_FIELDS = frozenset(
    {
        "schema_version",
        "phase",
        "exit_code",
        "member_login",
        "member_accounts",
        "owned_compose",
        "owned_images",
        "private_state",
        "recovery_status",
    }
)
LEGACY_CHANNEL_STATUS_FIELDS = CHANNEL_STATUS_FIELDS - {"recovery_status"}


def review_image_reference(project_name: str, service: str) -> str:
    """Return this run's unique image tag for one committed Compose service."""
    if (
        service not in REVIEW_IMAGE_SERVICES
        or not project_name.startswith("impostr-review-")
        or len(project_name.removeprefix("impostr-review-")) != 20
        or any(
            character not in "0123456789abcdef"
            for character in project_name.removeprefix("impostr-review-")
        )
    ):
        raise FixtureError("The generated review image identity is invalid.")
    return f"{project_name}-{service}:{REVIEW_IMAGE_TAG}"


def review_image_labels(project_name: str, service: str) -> dict[str, str]:
    """Identify a final image created for one service by this unique fixture run."""
    review_image_reference(project_name, service)
    return {
        REVIEW_IMAGE_PROJECT_LABEL: project_name,
        REVIEW_IMAGE_SERVICE_LABEL: service,
    }


class FixtureError(Exception):
    """A safe-to-display fixture failure with no command or response details."""


class StopRequested(Exception):
    """Raised by the supervisor's signal handler so normal cleanup can run."""


def _validate_private_directory(
    directory: Path,
    *,
    approved_directory: Path | None = None,
) -> Path:
    """Require an owner-only, non-symlink directory before handling credentials."""
    try:
        if not directory.is_absolute():
            raise FixtureError("The private handoff directory must be an absolute path.")
        info = directory.lstat()
        resolved = directory.resolve(strict=True)
    except FixtureError:
        raise
    except OSError:
        raise FixtureError("The private handoff directory is unavailable.") from None

    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or resolved != directory
    ):
        raise FixtureError("The private handoff directory must be owned and mode 0700.")
    if approved_directory is not None and directory != approved_directory:
        raise FixtureError("The requested handoff directory is not the approved private channel.")
    return directory


def validate_approved_handoff_directory(directory: Path) -> Path:
    """Restrict credential publication to the owner-approved private channel."""
    return _validate_private_directory(
        directory,
        approved_directory=APPROVED_HANDOFF_DIRECTORY,
    )


def _open_private_directory(directory: Path) -> int:
    _validate_private_directory(directory)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        raise FixtureError("The private fixture directory could not be opened safely.") from None
    info = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        os.close(descriptor)
        raise FixtureError("The private fixture directory changed during validation.")
    return descriptor


def _require_plain_private_file(info: os.stat_result) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise FixtureError("A private fixture file failed its ownership check.")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _read_private_json(directory: Path, filename: str, *, maximum_bytes: int) -> Any:
    if Path(filename).name != filename:
        raise FixtureError("A private fixture file name is invalid.")
    directory_fd = _open_private_directory(directory)
    file_fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(filename, flags, dir_fd=directory_fd)
        _require_plain_private_file(os.fstat(file_fd))
        with os.fdopen(file_fd, "rb") as file:
            file_fd = -1
            content = file.read(maximum_bytes + 1)
        if len(content) > maximum_bytes:
            raise FixtureError("A private fixture file exceeded its size limit.")
        try:
            return json.loads(content.decode("ascii"), object_pairs_hook=_unique_json_object)
        except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
            raise FixtureError("A private fixture file is malformed.") from None
    except FileNotFoundError:
        raise
    except FixtureError:
        raise
    except OSError:
        raise FixtureError("A private fixture file could not be read safely.") from None
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(directory_fd)


def _atomic_write_private_json(
    directory: Path,
    filename: str,
    payload: Mapping[str, Any],
    *,
    replace_existing: bool,
    maximum_bytes: int = MAX_CHANNEL_JSON_BYTES,
) -> None:
    """Publish one mode-0600 JSON value with a same-directory atomic rename."""
    if Path(filename).name != filename:
        raise FixtureError("A private fixture file name is invalid.")
    try:
        content = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "ascii"
        )
    except (TypeError, ValueError, UnicodeError):
        raise FixtureError("A private fixture record could not be encoded safely.") from None
    if len(content) > maximum_bytes:
        raise FixtureError("A private fixture record exceeded its size limit.")

    directory_fd = _open_private_directory(directory)
    temporary_name = f".{filename}.{secrets.token_hex(12)}.tmp"
    file_fd = -1
    try:
        try:
            current = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            current = None
        if current is not None:
            _require_plain_private_file(current)
            if not replace_existing:
                raise FixtureError("A prior private fixture handoff is still present.")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(temporary_name, flags, 0o600, dir_fd=directory_fd)
        os.fchmod(file_fd, 0o600)
        remaining = memoryview(content)
        while remaining:
            written = os.write(file_fd, remaining)
            if written <= 0:
                raise OSError("short write")
            remaining = remaining[written:]
        os.fsync(file_fd)
        os.close(file_fd)
        file_fd = -1
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except FixtureError:
        raise
    except OSError:
        raise FixtureError("A private fixture record could not be written atomically.") from None
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        os.close(directory_fd)


def _unlink_private_file(directory: Path, filename: str) -> bool:
    if Path(filename).name != filename:
        raise FixtureError("A private fixture file name is invalid.")
    directory_fd = _open_private_directory(directory)
    try:
        try:
            info = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        _require_plain_private_file(info)
        os.unlink(filename, dir_fd=directory_fd)
        os.fsync(directory_fd)
        return True
    except FixtureError:
        raise
    except OSError:
        raise FixtureError("A private fixture file could not be removed safely.") from None
    finally:
        os.close(directory_fd)


def _valid_member_login(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and set(payload) == {"username", "password"}
        and isinstance(payload["username"], str)
        and re.fullmatch(r"m[12][0-9a-f]{12}", payload["username"]) is not None
        and isinstance(payload["password"], str)
        and 32 <= len(payload["password"]) <= 256
        and re.fullmatch(r"[A-Za-z0-9_-]+", payload["password"]) is not None
    )


def write_member_handoff(directory: Path, username: str, password: str) -> None:
    """Write only one generated Member login; no URL, role, or run metadata."""
    payload = {"username": username, "password": password}
    if not _valid_member_login(payload):
        raise FixtureError("The generated browser-review Member login is invalid.")
    _atomic_write_private_json(
        directory,
        MEMBER_HANDOFF_FILE,
        payload,
        replace_existing=False,
    )


def remove_member_handoff(directory: Path, username: str, password: str) -> bool:
    """Remove this run's exact login, refusing symlinks or unexpected content."""
    try:
        payload = _read_private_json(
            directory,
            MEMBER_HANDOFF_FILE,
            maximum_bytes=MAX_CHANNEL_JSON_BYTES,
        )
    except FileNotFoundError:
        return False
    if payload != {"username": username, "password": password}:
        raise FixtureError("The private Member handoff changed during the fixture run.")
    return _unlink_private_file(directory, MEMBER_HANDOFF_FILE)


def initial_cleanup_status() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "phase": "starting",
        "exit_code": None,
        "member_login": "not-created",
        "member_accounts": "not-created",
        "owned_compose": "not-created",
        "owned_images": "not-created",
        "private_state": "not-created",
        "recovery_status": "not-needed",
    }


def validate_cleanup_status(payload: Any) -> dict[str, Any]:
    """Accept only the fixed, sanitized account/resource cleanup vocabulary."""
    if not isinstance(payload, dict) or set(payload) not in {
        CHANNEL_STATUS_FIELDS,
        LEGACY_CHANNEL_STATUS_FIELDS,
    }:
        raise FixtureError("The private cleanup status has an unexpected shape.")
    payload = dict(payload)
    if "recovery_status" not in payload:
        clean_previous_resources = (
            payload.get("phase") == "stopped"
            and payload.get("member_login") in {"not-created", "removed"}
            and payload.get("owned_compose") in {"not-created", "removed"}
            and payload.get("owned_images") in {"not-created", "removed"}
            and payload.get("private_state") in {"not-created", "removed"}
        )
        payload["recovery_status"] = "not-needed" if clean_previous_resources else "failed"
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise FixtureError("The private cleanup status version is invalid.")
    if not isinstance(payload["phase"], str) or payload["phase"] not in {
        "starting",
        "ready",
        "stopping",
        "stopped",
    }:
        raise FixtureError("The private cleanup status phase is invalid.")
    exit_code = payload["exit_code"]
    if exit_code is not None and (type(exit_code) is not int or exit_code not in {0, 1}):
        raise FixtureError("The private cleanup exit status is invalid.")
    if (payload["phase"] == "stopped") != (exit_code is not None):
        raise FixtureError("The private cleanup exit status does not match its phase.")
    allowed_values = {
        "member_login": {"not-created", "published", "removed", "not-verified"},
        "member_accounts": {
            "not-created",
            "pending",
            "verified",
            "not-verified",
            "not-applicable",
        },
        "owned_compose": {"not-created", "pending", "removed", "not-verified"},
        "owned_images": {"not-created", "pending", "removed", "not-verified"},
        "private_state": {
            "not-created",
            "pending",
            "removed",
            "retained-for-recovery",
            "not-verified",
        },
        "recovery_status": {
            "not-needed",
            "pending",
            "completed",
            "failed",
            "manual-required",
        },
    }
    for field, allowed in allowed_values.items():
        if not isinstance(payload[field], str) or payload[field] not in allowed:
            raise FixtureError("The private cleanup status contains an unknown value.")
    return dict(payload)


def read_cleanup_status(directory: Path) -> dict[str, Any] | None:
    try:
        payload = _read_private_json(
            directory,
            CLEANUP_STATUS_FILE,
            maximum_bytes=MAX_CHANNEL_JSON_BYTES,
        )
    except FileNotFoundError:
        return None
    return validate_cleanup_status(payload)


def write_cleanup_status(directory: Path, payload: Mapping[str, Any]) -> None:
    clean_payload = validate_cleanup_status(dict(payload))
    _atomic_write_private_json(
        directory,
        CLEANUP_STATUS_FILE,
        clean_payload,
        replace_existing=True,
    )


def prepare_handoff_channel(
    directory: Path,
    *,
    approved_directory: Path = APPROVED_HANDOFF_DIRECTORY,
) -> None:
    """Fail closed on an unclean prior run before creating replacement credentials."""
    _validate_private_directory(directory, approved_directory=approved_directory)
    directory_fd = _open_private_directory(directory)
    try:
        try:
            os.stat(MEMBER_HANDOFF_FILE, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FixtureError("A prior browser-review Member login is still present.")
    finally:
        os.close(directory_fd)

    previous = read_cleanup_status(directory)
    if previous is None:
        return
    if (
        previous["phase"] != "stopped"
        or previous["member_login"] not in {"not-created", "removed"}
        or previous["owned_compose"] not in {"not-created", "removed"}
        or previous["owned_images"] not in {"not-created", "removed"}
        or previous["private_state"] not in {"not-created", "removed"}
    ):
        raise FixtureError("A prior browser-review fixture has unverified cleanup.")


@dataclass(slots=True, repr=False)
class MemberCredential:
    username: str
    password: str | None
    user_id: str | None = None
    creation_unconfirmed: bool = False


@dataclass(slots=True, repr=False)
class RunIdentity:
    run_id: str
    project_name: str
    port: int
    origin: str
    admin_username: str
    admin_password: str | None
    postgres_password: str | None
    app_password: str | None
    rate_limit_key: str | None
    members: list[MemberCredential]
    admin_user_id: str | None = None

    @property
    def user_ids(self) -> list[str]:
        ids = [self.admin_user_id] if self.admin_user_id else []
        ids.extend(member.user_id for member in self.members if member.user_id)
        return ids


def generate_identity(port: int, *, host: str | None = None) -> RunIdentity:
    """Generate names and one-run secrets using only synthetic identifiers."""
    run_id = secrets.token_hex(10)
    # The 12-hex account label is role-prefixed, so all three synthetic users are
    # distinct within their fresh database. Keep the full 80-bit ID for the
    # Compose namespace; separate per-run databases contain any short-label collision.
    username_tag = run_id[:12]
    loopback_host = host or choose_loopback_host()
    return RunIdentity(
        run_id=run_id,
        project_name=f"impostr-review-{run_id}",
        port=port,
        origin=f"http://{loopback_host}:{port}",
        admin_username=f"a{username_tag}",
        admin_password=secrets.token_urlsafe(48),
        postgres_password=secrets.token_hex(32),
        app_password=secrets.token_hex(32),
        rate_limit_key=secrets.token_hex(32),
        members=[
            MemberCredential(
                username=f"m1{username_tag}",
                password=secrets.token_urlsafe(32),
            ),
            MemberCredential(
                username=f"m2{username_tag}",
                password=secrets.token_urlsafe(32),
            ),
        ],
    )


def denied_member_username(identity: RunIdentity, member_index: int) -> str:
    """Return a validator-compatible synthetic name for a denied admin request."""
    if member_index not in {1, 2}:
        raise FixtureError("The synthetic member index is invalid.")
    return f"reviewdenied{identity.run_id}{member_index}"


def classify_bootstrap_diagnostic(output: bytes) -> str:
    """Map a bounded CLI transcript to one fixed, non-sensitive diagnostic code."""
    sample = output[:MAX_BOOTSTRAP_DIAGNOSTIC_BYTES].lower()
    database_match = re.search(
        rb"fixture database diagnostic: class="
        rb"(integrity|programming|operational|interface|data|database|other) "
        rb"sqlstate=([0-9a-z]{5}|unknown) "
        rb"schema=(missing-[a-z_]+|expected-present|unavailable|not-checked) "
        rb"migration=(0001|0002|empty|other|unavailable|not-checked)",
        sample,
    )
    if database_match is not None:
        category = database_match.group(1).decode("ascii")
        sqlstate = database_match.group(2).decode("ascii")
        schema = database_match.group(3).decode("ascii").replace("_", "-")
        migration = database_match.group(4).decode("ascii")
        return f"database-{category}-{sqlstate}-{schema}-migration-{migration}"
    markers = (
        (b"username must be", "username-validation"),
        (b"run this command in an interactive terminal", "interactive-terminal-required"),
        (b"the passwords did not match", "password-confirmation-mismatch"),
        (b"password must contain", "password-validation"),
        (b"administrator bootstrap has already been completed", "bootstrap-already-completed"),
        (b"bootstrap requires an empty users table", "users-table-not-empty"),
        (b"bootstrap state is missing", "migration-state-missing"),
        (b"database operation failed", "database-operation-failed"),
    )
    return next((code for marker, code in markers if marker in sample), "unclassified")


def migration_revision_status(output: str) -> str:
    """Return a fixed status for Alembic's current-revision output."""
    if EXPECTED_APP_MIGRATION in output.split():
        return "expected"
    return "empty" if not output.strip() else "unexpected"


MIGRATION_DIAGNOSTIC_PYTHON = """\
import json
from pathlib import Path

expected_migrations = Path("/app/migrations")
result = {
    "probe_stage": "imports",
    "discovery_status": "not-checked",
    "database_probe_status": "not-checked",
    "image_files_status": "not-checked",
    "script_location": "unavailable",
    "script_directory": "unavailable",
    "versions_directory": "unavailable",
    "migration_directory_mode": "unavailable",
    "migration_directory_owner": "unavailable",
    "runtime_migration_access": "unavailable",
    "versions_directory_mode": "unavailable",
    "versions_directory_owner": "unavailable",
    "runtime_versions_access": "unavailable",
    "image_files": {
        "alembic_ini": "unavailable",
        "env_py": "unavailable",
        "revision_0001": "unavailable",
        "revision_0002": "unavailable",
    },
    "discovered_revisions": [],
    "heads": [],
    "database_config": "unavailable",
    "database": "unavailable",
    "schema": "unavailable",
    "alembic_version_table": "unavailable",
    "current": "unavailable",
    "users": "unavailable",
}

result["probe_stage"] = "image-files"
try:
    import os
    import stat

    def file_status(path):
        try:
            info = os.stat(path)
        except FileNotFoundError:
            return "absent"
        except PermissionError:
            return "permission-denied"
        except OSError:
            return "unavailable"
        return "present" if stat.S_ISREG(info.st_mode) else "wrong-type"

    result["image_files"] = {
        "alembic_ini": file_status("/app/alembic.ini"),
        "env_py": file_status("/app/migrations/env.py"),
        "revision_0001": file_status(
            "/app/migrations/versions/20260925_0001_initial_baseline.py"
        ),
        "revision_0002": file_status(
            "/app/migrations/versions/20260925_0002_identity_and_project_metadata.py"
        ),
    }
    def directory_permissions(path):
        try:
            info = os.stat(path)
        except OSError:
            return "unavailable", "unavailable", "unavailable"
        mode = stat.S_IMODE(info.st_mode)
        owner = "root" if info.st_uid == 0 else "app" if info.st_uid == 10001 else "other"
        if os.geteuid() == info.st_uid:
            effective_bits = mode >> 6
        elif info.st_gid in {os.getegid(), *os.getgroups()}:
            effective_bits = mode >> 3
        else:
            effective_bits = mode
        access = "yes" if effective_bits & 0o5 == 0o5 else "no"
        return f"{mode:04o}", owner, access

    (
        result["migration_directory_mode"],
        result["migration_directory_owner"],
        result["runtime_migration_access"],
    ) = directory_permissions("/app/migrations")
    (
        result["versions_directory_mode"],
        result["versions_directory_owner"],
        result["runtime_versions_access"],
    ) = directory_permissions("/app/migrations/versions")
    if "permission-denied" in result["image_files"].values():
        result["image_files_status"] = "permission-denied"
    elif "unavailable" in result["image_files"].values():
        result["image_files_status"] = "error"
    else:
        result["image_files_status"] = "ok"
except Exception:
    result["image_files_status"] = "error"

result["probe_stage"] = "imports"
try:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text

    from app.database import database_url_from_environment, get_database_engine
except Exception:
    print(json.dumps(result, separators=(",", ":")))
    raise SystemExit(0)

expected_revisions = {"20260925_0001", "20260925_0002"}
result["probe_stage"] = "complete"
try:
    config = Config("/app/alembic.ini")
    configured_location = Path(config.get_main_option("script_location"))
    if not configured_location.is_absolute():
        configured_location = Path("/app") / configured_location
    resolved_location = configured_location.resolve()
    result["script_location"] = (
        "expected" if resolved_location == expected_migrations else "other"
    )
    result["script_directory"] = "present" if resolved_location.is_dir() else "missing"
    versions_location = resolved_location / "versions"
    result["versions_directory"] = "present" if versions_location.is_dir() else "missing"
    if resolved_location == expected_migrations:
        script_directory = ScriptDirectory.from_config(config)

        def safe_revision_list(values):
            revisions = []
            for index, value in enumerate(values):
                if index >= 8 or not isinstance(value, str) or value not in expected_revisions:
                    return ["other"]
                revisions.append(value)
            return sorted(set(revisions))

        result["discovered_revisions"] = safe_revision_list(
            script.revision for script in script_directory.walk_revisions()
        )
        result["heads"] = safe_revision_list(script_directory.get_heads())
        result["discovery_status"] = "ok"
    else:
        result["discovery_status"] = "not-checked"
except Exception:
    result["discovery_status"] = "error"

engine = None
try:
    database_url = database_url_from_environment()
    result["database_config"] = (
        "expected"
        if database_url.host == "db" and database_url.database == "impostr_review"
        else "other"
    )
    engine = get_database_engine()
    with engine.connect() as connection:
        database_name, schema_name = connection.execute(
            text("SELECT current_database(), current_schema()")
        ).one()
        result["database"] = "expected" if database_name == "impostr_review" else "other"
        result["schema"] = "public" if schema_name == "public" else "other"
        result["database_probe_status"] = "ok"
        if schema_name is not None:
            tables = set(inspect(connection).get_table_names(schema=schema_name))
            result["alembic_version_table"] = (
                "yes" if "alembic_version" in tables else "no"
            )
            result["users"] = "yes" if "users" in tables else "no"
            if "alembic_version" not in tables:
                result["current"] = "table-absent"
            else:
                current_revisions = connection.execute(
                    text("SELECT version_num FROM alembic_version ORDER BY version_num")
                ).scalars().all()
                if not current_revisions:
                    result["current"] = "empty"
                elif current_revisions == ["20260925_0002"]:
                    result["current"] = "expected"
                else:
                    result["current"] = "other"
except Exception:
    result["database_probe_status"] = "error"
finally:
    if engine is not None:
        try:
            engine.dispose()
        except Exception:
            result["database_probe_status"] = "error"

print(json.dumps(result, separators=(",", ":")))
"""


def parse_migration_diagnostic(output: str) -> dict[str, Any] | None:
    """Validate bounded diagnostic JSON and retain only allowlisted evidence."""
    try:
        if len(output.encode("utf-8")) > MAX_MIGRATION_DIAGNOSTIC_BYTES:
            return None
        raw: Any = json.loads(output)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return None

    expected_keys = {
        "probe_stage",
        "discovery_status",
        "database_probe_status",
        "image_files_status",
        "script_location",
        "script_directory",
        "versions_directory",
        "migration_directory_mode",
        "migration_directory_owner",
        "runtime_migration_access",
        "versions_directory_mode",
        "versions_directory_owner",
        "runtime_versions_access",
        "image_files",
        "discovered_revisions",
        "heads",
        "database_config",
        "database",
        "schema",
        "alembic_version_table",
        "current",
        "users",
    }
    if not isinstance(raw, dict) or set(raw) != expected_keys:
        return None

    status_fields = {
        "probe_stage": {"complete", "imports", "image-files"},
        "discovery_status": {"ok", "error", "not-checked"},
        "database_probe_status": {"ok", "error", "not-checked"},
        "image_files_status": {"ok", "permission-denied", "error", "not-checked"},
        "script_location": {"expected", "other", "unavailable"},
        "script_directory": {"present", "missing", "unavailable"},
        "versions_directory": {"present", "missing", "unavailable"},
        "migration_directory_owner": {"root", "app", "other", "unavailable"},
        "runtime_migration_access": {"yes", "no", "unavailable"},
        "versions_directory_owner": {"root", "app", "other", "unavailable"},
        "runtime_versions_access": {"yes", "no", "unavailable"},
        "database_config": {"expected", "other", "unavailable"},
        "database": {"expected", "other", "unavailable"},
        "schema": {"public", "other", "unavailable"},
        "alembic_version_table": {"yes", "no", "unavailable"},
        "current": {"expected", "empty", "table-absent", "other", "unavailable"},
        "users": {"yes", "no", "unavailable"},
    }
    if any(
        not isinstance(raw[field], str) or raw[field] not in allowed
        for field, allowed in status_fields.items()
    ):
        return None
    directory_mode = raw["migration_directory_mode"]
    versions_directory_mode = raw["versions_directory_mode"]
    for mode in (directory_mode, versions_directory_mode):
        if not isinstance(mode, str) or (
            mode != "unavailable" and re.fullmatch(r"0[0-7]{3}", mode) is None
        ):
            return None

    image_files = raw["image_files"]
    expected_file_keys = {"alembic_ini", "env_py", "revision_0001", "revision_0002"}
    if (
        not isinstance(image_files, dict)
        or set(image_files) != expected_file_keys
        or any(
            not isinstance(status, str)
            or status
            not in {"present", "absent", "permission-denied", "wrong-type", "unavailable"}
            for status in image_files.values()
        )
    ):
        return None

    def allowed_revisions(value: Any) -> list[str] | None:
        if not isinstance(value, list) or len(value) > 8:
            return None
        if any(
            not isinstance(revision, str)
            or revision not in {*EXPECTED_APP_REVISIONS, "other"}
            for revision in value
        ):
            return None
        if "other" in value and value != ["other"]:
            return None
        return sorted(set(value))

    discovered_revisions = allowed_revisions(raw["discovered_revisions"])
    heads = allowed_revisions(raw["heads"])
    if discovered_revisions is None or heads is None:
        return None

    return {
        **{field: raw[field] for field in status_fields},
        "migration_directory_mode": directory_mode,
        "versions_directory_mode": versions_directory_mode,
        "image_files": dict(image_files),
        "discovered_revisions": discovered_revisions,
        "heads": heads,
    }


def classify_migration_diagnostic_stderr(output: bytes) -> str:
    """Reduce command stderr to a fixed category; never retain its text."""
    sample = output[: 4 * 1024].lower()
    if not sample.strip():
        return "empty"
    if b"traceback (most recent call last)" in sample:
        for exception_name, category in (
            (b"syntaxerror", "python-syntax"),
            (b"indentationerror", "python-indentation"),
            (b"modulenotfounderror", "python-module-missing"),
            (b"importerror", "python-import"),
            (b"keyerror", "python-key"),
            (b"indexerror", "python-index"),
            (b"assertionerror", "python-assertion"),
            (b"typeerror", "python-type"),
            (b"valueerror", "python-value"),
            (b"attributeerror", "python-attribute"),
            (b"nameerror", "python-name"),
            (b"oserror", "python-os"),
            (b"permissionerror", "python-permission"),
            (b"filenotfounderror", "python-file-missing"),
            (b"notadirectoryerror", "python-path"),
            (b"timeouterror", "python-timeout"),
            (b"recursionerror", "python-recursion"),
            (b"jsondecodeerror", "python-json"),
            (b"operationalerror", "python-database-operation"),
            (b"programmingerror", "python-database-programming"),
            (b"integrityerror", "python-database-integrity"),
            (b"interfaceerror", "python-database-interface"),
            (b"nosuchtableerror", "python-database-table"),
            (b"noresultfound", "python-database-result"),
            (b"multipleresultsfound", "python-database-result"),
            (b"commanderror", "python-alembic-command"),
            (b"systemexit", "python-system-exit"),
            (b"runtimeerror", "python-runtime"),
        ):
            if re.search(
                rb"(?m)^(?:[a-z_][a-z0-9_.]*\.)?"
                + exception_name
                + rb"(?::|\s|$)",
                sample,
            ):
                return category
        return "python-exception"
    for marker, category in (
        (b"no such service", "compose-service"),
        (b"unknown flag", "compose-option"),
        (b"error response from daemon", "container-runtime"),
        (b"oci runtime", "container-runtime"),
        (b"failed to create task", "container-runtime"),
    ):
        if marker in sample:
            return category
    return "suppressed"


def format_migration_diagnostic(diagnostic: Mapping[str, Any]) -> str:
    """Render only fixed statuses, known revision IDs, and expected image paths."""
    script_location = (
        "/app/migrations"
        if diagnostic["script_location"] == "expected"
        else diagnostic["script_location"]
    )

    def revision_list(value: Sequence[str]) -> str:
        return ",".join(value) if value else "none"

    file_labels = (
        ("alembic.ini", "alembic_ini"),
        ("env.py", "env_py"),
        ("0001", "revision_0001"),
        ("0002", "revision_0002"),
    )
    files = ",".join(
        f"{label}:{diagnostic['image_files'][key]}" for label, key in file_labels
    )
    return (
        f"probe_stage={diagnostic['probe_stage']} "
        f"discovery_status={diagnostic['discovery_status']} "
        f"database_probe_status={diagnostic['database_probe_status']} "
        f"image_files_status={diagnostic['image_files_status']} "
        f"script_location={script_location} "
        f"script_directory={diagnostic['script_directory']} "
        f"versions_directory={diagnostic['versions_directory']} "
        f"migration_directory_mode={diagnostic['migration_directory_mode']} "
        f"migration_directory_owner={diagnostic['migration_directory_owner']} "
        f"runtime_migration_access={diagnostic['runtime_migration_access']} "
        f"versions_directory_mode={diagnostic['versions_directory_mode']} "
        f"versions_directory_owner={diagnostic['versions_directory_owner']} "
        f"runtime_versions_access={diagnostic['runtime_versions_access']} "
        f"image_files={files} "
        f"revisions={revision_list(diagnostic['discovered_revisions'])} "
        f"heads={revision_list(diagnostic['heads'])} "
        f"database_config={diagnostic['database_config']} "
        f"database={diagnostic['database']} schema={diagnostic['schema']} "
        f"alembic_version_table={diagnostic['alembic_version_table']} "
        f"catalog_current={diagnostic['current']} users={diagnostic['users']}"
    )


def migration_diagnostic_is_complete(diagnostic: Mapping[str, Any]) -> bool:
    """Require the committed IMP-003 image, head, and schema before auth setup."""
    return (
        diagnostic["probe_stage"] == "complete"
        and diagnostic["discovery_status"] == "ok"
        and diagnostic["database_probe_status"] == "ok"
        and diagnostic["image_files_status"] == "ok"
        and diagnostic["script_location"] == "expected"
        and diagnostic["script_directory"] == "present"
        and diagnostic["versions_directory"] == "present"
        and diagnostic["migration_directory_owner"] in {"root", "app"}
        and diagnostic["runtime_migration_access"] == "yes"
        and diagnostic["versions_directory_owner"] in {"root", "app"}
        and diagnostic["runtime_versions_access"] == "yes"
        and all(status == "present" for status in diagnostic["image_files"].values())
        and diagnostic["discovered_revisions"] == list(EXPECTED_APP_REVISIONS)
        and diagnostic["heads"] == [EXPECTED_APP_MIGRATION]
        and diagnostic["database_config"] == "expected"
        and diagnostic["database"] == "expected"
        and diagnostic["schema"] == "public"
        and diagnostic["alembic_version_table"] == "yes"
        and diagnostic["current"] == "expected"
        and diagnostic["users"] == "yes"
    )


def choose_loopback_host() -> str:
    """Use a per-run 127/8 address so browser cookies cannot cross local app ports."""
    while True:
        host = "127." + ".".join(str(secrets.randbelow(254) + 1) for _ in range(3))
        if host != "127.0.0.1":
            return host


def choose_loopback_port(host: str) -> int:
    """Ask the OS for a currently free IPv4 loopback port on this run's host."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((host, 0))
            return int(listener.getsockname()[1])
    except OSError:
        raise FixtureError("A free loopback port could not be reserved.") from None


def create_private_state_dir(repository_root: Path) -> Path:
    """Create private supervisor state outside the checkout and its worktree."""
    try:
        temp_root = Path(tempfile.gettempdir()).resolve()
        repository = repository_root.resolve()
        if temp_root == repository or repository in temp_root.parents:
            raise FixtureError("The system temporary directory is inside the checkout.")
        state_dir = Path(tempfile.mkdtemp(prefix="impostr-browser-review-", dir=temp_root))
        os.chmod(state_dir, 0o700)
        if stat.S_IMODE(state_dir.stat().st_mode) != 0o700:
            shutil.rmtree(state_dir, ignore_errors=True)
            raise FixtureError("The private temporary directory could not be protected.")
        return state_dir
    except FixtureError:
        raise
    except OSError:
        raise FixtureError("A private temporary directory could not be created.") from None


def _git_environment(home: Path) -> dict[str, str]:
    """Avoid inherited Git overrides, global config, prompts, and host secrets."""
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _tracked_secret_path(path: str) -> bool:
    """Refuse common committed dotenv files before building any Docker context."""
    for component in PurePosixPath(path).parts:
        if component == ".env":
            return True
        if component.startswith(".env.") and component != ".env.example":
            return True
    return False


def _is_app_snapshot_path(path: str) -> bool:
    return path in APP_SNAPSHOT_FILES or any(
        path.startswith(f"{directory}/") for directory in ("db", "api", "web")
    )


def _extract_git_tar(archive_bytes: bytes, destination: Path) -> None:
    """Extract only ordinary Git archive files; symlinks and special files fail closed."""
    try:
        root = destination.resolve()
        directories: set[Path] = set()
        with tarfile.open(fileobj=BytesIO(archive_bytes), mode="r:") as archive:
            for member in archive.getmembers():
                relative = PurePosixPath(member.name)
                if (
                    relative.is_absolute()
                    or not relative.parts
                    or any(part in {"", ".", ".."} for part in relative.parts)
                ):
                    raise FixtureError("The committed source archive has an unsafe path.")
                target = root.joinpath(*relative.parts)
                try:
                    target.resolve(strict=False).relative_to(root)
                except ValueError:
                    raise FixtureError("The committed source archive has an unsafe path.") from None

                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o755)
                    directories.add(target)
                    continue
                if not member.isfile():
                    raise FixtureError("The committed source archive contains a special file.")

                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                parent = target.parent
                while parent != root:
                    directories.add(parent)
                    parent = parent.parent
                source = archive.extractfile(member)
                if source is None:
                    raise FixtureError("The committed source archive is incomplete.")
                mode = 0o755 if member.mode & 0o111 else 0o644
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(mode)
        # main() holds a private umask for credential files. Restore searchable,
        # readable directory modes so Docker COPY can expose migrations to the
        # committed image's unprivileged runtime user.
        for directory in directories:
            directory.chmod(0o755)
    except FixtureError:
        raise
    except (OSError, tarfile.TarError, ValueError):
        raise FixtureError("The committed source archive could not be extracted safely.") from None


def archive_head_snapshot(repository_root: Path, destination: Path, *, private_home: Path) -> str:
    """Create an isolated source tree from one resolved HEAD commit, never the worktree."""
    git_env = _git_environment(private_home)
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=repository_root,
            env=git_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        if revision.returncode != 0:
            raise FixtureError("The checkout does not have a committed HEAD snapshot.")
        commit = revision.stdout.decode("ascii", "ignore").strip()
        if len(commit) not in {40, 64} or any(
            character not in "0123456789abcdef" for character in commit
        ):
            raise FixtureError("The committed source revision could not be verified.")

        tree = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "-z", commit],
            cwd=repository_root,
            env=git_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        if tree.returncode != 0:
            raise FixtureError("The committed source tree could not be inspected.")
        tracked_paths = tree.stdout.decode("utf-8", "surrogateescape").split("\0")
        if any(
            path and _is_app_snapshot_path(path) and _tracked_secret_path(path)
            for path in tracked_paths
        ):
            raise FixtureError("A committed dotenv file prevents building a safe review snapshot.")

        archived = subprocess.run(
            ["git", "archive", "--format=tar", commit, *APP_SNAPSHOT_PATHS],
            cwd=repository_root,
            env=git_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=120,
        )
        if archived.returncode != 0:
            raise FixtureError("The committed source snapshot could not be archived.")
        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        _extract_git_tar(archived.stdout, destination)
        required = (
            destination / "compose.yaml",
            destination / "api" / "app" / "bootstrap_admin.py",
            destination / "api" / "app" / "admin.py",
            destination / "api" / "app" / "auth.py",
            destination / "web" / "src" / "App.tsx",
            destination / "db" / "Dockerfile",
            destination / "PROJECT.md.example",
            destination / "AGENTS.md.example",
            destination / "BACKLOG.md.example",
        )
        if not all(path.is_file() for path in required):
            raise FixtureError("The committed snapshot is missing the IMP-003 app surface.")
        return commit
    except FixtureError:
        raise
    except (OSError, subprocess.SubprocessError):
        raise FixtureError("The committed source snapshot could not be prepared.") from None


def create_compose_env(path: Path, identity: RunIdentity) -> None:
    """Write only generated Compose credentials into a mode-0600 private file."""
    required = (
        identity.postgres_password,
        identity.app_password,
        identity.rate_limit_key,
    )
    if any(value is None for value in required):
        raise FixtureError("The generated database credentials are incomplete.")
    values = {
        "POSTGRES_DB": "impostr_review",
        "POSTGRES_USER": "review_owner",
        "POSTGRES_PASSWORD": identity.postgres_password,
        "DB_USER": "review_app",
        "DB_PASSWORD": identity.app_password,
        "IMPOSTR_RATE_LIMIT_KEY": identity.rate_limit_key,
        "IMPOSTR_PUBLIC_ORIGIN": identity.origin,
        "APP_PORT": str(identity.port),
    }
    for key, value in values.items():
        if not isinstance(value, str) or "\n" in value or "\r" in value:
            raise FixtureError("A generated Compose setting is invalid.")

    descriptor = -1
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as file:
            descriptor = -1
            for key, value in values.items():
                file.write(f"{key}={value}\n")
        path.chmod(0o600)
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise FixtureError("The generated Compose environment file is not private.")
    except FixtureError:
        raise
    except OSError:
        raise FixtureError(
            "The generated Compose environment file could not be protected."
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def create_member_recovery_file(state_dir: Path, identity: RunIdentity) -> None:
    """Keep both generated Member logins recoverable if owned teardown fails.

    The file is created before any Docker command can create an account. It is
    removed with the private state only after the disposable volume is gone.
    No admin or infrastructure credentials are written to this file.
    """
    if stat.S_IMODE(state_dir.stat().st_mode) != 0o700:
        raise FixtureError("The member recovery directory is not private.")
    members = [
        {"username": member.username, "password": member.password} for member in identity.members
    ]
    if len(members) != 2 or any(not member["password"] for member in members):
        raise FixtureError("The generated member credentials are incomplete.")
    descriptor = -1
    try:
        descriptor = os.open(
            state_dir / MEMBER_RECOVERY_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="ascii") as file:
            descriptor = -1
            json.dump(members, file)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        if stat.S_IMODE((state_dir / MEMBER_RECOVERY_FILE).stat().st_mode) != 0o600:
            raise FixtureError("The member recovery file is not private.")
    except FixtureError:
        raise
    except OSError:
        raise FixtureError("The member recovery file could not be protected.") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def set_snapshot_loopback_host(source_dir: Path, host: str) -> None:
    """Change only the committed Compose bind IP in the private archived snapshot."""
    try:
        address = ipaddress.ip_address(host)
        if not address.is_loopback or address.version != 4:
            raise FixtureError("The generated front-door address is not IPv4 loopback.")
        compose_file = source_dir / "compose.yaml"
        compose_text = compose_file.read_text(encoding="utf-8")
        original = '"127.0.0.1:${APP_PORT:-8080}:8080"'
        if compose_text.count(original) != 1:
            raise FixtureError(
                "The committed front-door binding does not match the expected safe form."
            )
        compose_file.write_text(
            compose_text.replace(original, f'"{host}:${{APP_PORT:-8080}}:8080"'),
            encoding="utf-8",
        )
    except FixtureError:
        raise
    except (OSError, ValueError):
        raise FixtureError("The private Compose snapshot could not be bound to loopback.") from None


def set_snapshot_review_images(source_dir: Path, project_name: str) -> None:
    """Tag and label only the three app images in this private Compose snapshot."""
    compose_file = source_dir / "compose.yaml"
    try:
        compose_text = compose_file.read_text(encoding="utf-8")
        replacements = (
            (
                "  db:\n    build:\n      context: ./db\n",
                "  db:\n"
                f"    image: {review_image_reference(project_name, 'db')}\n"
                "    build:\n"
                f"      labels:\n        {REVIEW_IMAGE_PROJECT_LABEL}: {project_name}\n"
                f"        {REVIEW_IMAGE_SERVICE_LABEL}: db\n"
                "      context: ./db\n",
            ),
            (
                "  api:\n    build:\n      context: ./api\n      target: runtime\n",
                "  api:\n"
                f"    image: {review_image_reference(project_name, 'api')}\n"
                "    build:\n"
                f"      labels:\n        {REVIEW_IMAGE_PROJECT_LABEL}: {project_name}\n"
                f"        {REVIEW_IMAGE_SERVICE_LABEL}: api\n"
                "      context: ./api\n"
                "      target: runtime\n",
            ),
            (
                "  frontdoor:\n    build:\n      context: ./web\n      target: runtime\n",
                "  frontdoor:\n"
                f"    image: {review_image_reference(project_name, 'frontdoor')}\n"
                "    build:\n"
                f"      labels:\n        {REVIEW_IMAGE_PROJECT_LABEL}: {project_name}\n"
                f"        {REVIEW_IMAGE_SERVICE_LABEL}: frontdoor\n"
                "      context: ./web\n"
                "      target: runtime\n",
            ),
        )
        for original, replacement in replacements:
            if compose_text.count(original) != 1:
                raise FixtureError(
                    "The committed Compose image definitions do not match the safe fixture form."
                )
            compose_text = compose_text.replace(original, replacement, 1)
        compose_file.write_text(compose_text, encoding="utf-8")
    except FixtureError:
        raise
    except OSError:
        raise FixtureError("The private Compose images could not be isolated by run.") from None


def private_docker_environment(state_dir: Path) -> dict[str, str]:
    """Use an empty private Docker config, not the operator's Docker credentials."""
    docker_config = state_dir / "docker-config"
    docker_config.mkdir(mode=0o700, exist_ok=True)
    os.chmod(docker_config, 0o700)
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(state_dir),
        "DOCKER_CONFIG": str(docker_config),
        "TMPDIR": str(state_dir),
    }


class DockerClient:
    """Bounded Docker CLI access pinned to a local Unix socket and private config."""

    def __init__(
        self,
        *,
        executable: str,
        docker_socket: str,
        state_dir: Path,
    ) -> None:
        self.executable = executable
        self.docker_socket = docker_socket
        self.state_dir = state_dir
        self.environment = private_docker_environment(state_dir)
        self.global_args = [
            "--config",
            str(state_dir / "docker-config"),
            "--host",
            f"unix://{docker_socket}",
        ]

    def command(self, arguments: Sequence[str]) -> list[str]:
        return [self.executable, *self.global_args, *arguments]

    def run(
        self,
        arguments: Sequence[str],
        *,
        label: str,
        timeout: int = 60,
        capture_stdout: bool = False,
    ) -> str:
        try:
            completed = subprocess.run(
                self.command(arguments),
                cwd=self.state_dir,
                env=self.environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            raise FixtureError(f"The {label} could not be completed.") from None
        if completed.returncode != 0:
            raise FixtureError(
                f"The {label} failed (exit {completed.returncode}); details suppressed."
            )
        if not capture_stdout:
            return ""
        try:
            return completed.stdout.decode("utf-8", "strict")
        except (AttributeError, UnicodeDecodeError):
            raise FixtureError(f"The {label} returned invalid output.") from None

    def probe_local_engine(self) -> None:
        socket_path = Path(self.docker_socket)
        if not socket_path.is_absolute() or not socket_path.is_socket():
            raise FixtureError("A local Docker Unix socket is required.")
        self.run(["info", "--format", "{{.ServerVersion}}"], label="local Docker check", timeout=20)

    def project_resource_ids(self, resource: str, project_name: str) -> str:
        review_image_reference(project_name, "db")
        if resource == "container":
            args = ["container", "ls", "--all", "--quiet", "--no-trunc"]
        elif resource == "volume":
            args = ["volume", "ls", "--quiet"]
        elif resource == "network":
            args = ["network", "ls", "--quiet"]
        else:
            raise FixtureError("An unsupported Docker resource check was requested.")
        args.extend(["--filter", f"label=com.docker.compose.project={project_name}"])
        return self.run(args, label="fixture resource ownership check", capture_stdout=True).strip()

    def project_resource_labels(self, resource: str, resource_id: str) -> dict[str, str]:
        """Inspect labels for a filtered Compose resource before emergency recovery."""
        if resource in {"container", "network"}:
            valid_identifier = re.fullmatch(r"[0-9a-f]{12,64}", resource_id) is not None
        elif resource == "volume":
            valid_identifier = (
                re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", resource_id) is not None
            )
        else:
            raise FixtureError("An unsupported Docker ownership check was requested.")
        if not valid_identifier:
            raise FixtureError("A Docker resource check returned an invalid identifier.")

        if resource == "container":
            arguments = ["container", "inspect", "--format", "{{json .Config.Labels}}", resource_id]
        elif resource == "network":
            arguments = ["network", "inspect", "--format", "{{json .Labels}}", resource_id]
        else:
            arguments = ["volume", "inspect", "--format", "{{json .Labels}}", resource_id]
        output = self.run(
            arguments,
            label="fixture resource ownership check",
            capture_stdout=True,
        )
        try:
            labels = json.loads(output)
        except json.JSONDecodeError:
            raise FixtureError("The Docker resource ownership labels are invalid.") from None
        if not isinstance(labels, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in labels.items()
        ):
            raise FixtureError("The Docker resource ownership labels are invalid.")
        return labels

    @staticmethod
    def _parse_image_ids(output: str) -> list[str]:
        image_ids = list(
            dict.fromkeys(line.strip() for line in output.splitlines() if line.strip())
        )
        if any(
            len(image_id) != 71
            or not image_id.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in image_id[7:])
            for image_id in image_ids
        ):
            raise FixtureError("The Docker image ownership check returned invalid identifiers.")
        return image_ids

    def image_ids_for_reference(self, reference: str) -> list[str]:
        valid_reference = False
        for service in REVIEW_IMAGE_SERVICES:
            suffix = f"-{service}:{REVIEW_IMAGE_TAG}"
            if reference.endswith(suffix):
                project_name = reference[: -len(suffix)]
                if review_image_reference(project_name, service) == reference:
                    valid_reference = True
                break
        if not valid_reference:
            raise FixtureError("An image check requested an unsupported fixture reference.")
        output = self.run(
            [
                "image",
                "ls",
                "--all",
                "--quiet",
                "--no-trunc",
                "--filter",
                f"reference={reference}",
            ],
            label="fixture image ownership check",
            capture_stdout=True,
        )
        return self._parse_image_ids(output)

    def image_ids_for_project(self, project_name: str) -> list[str]:
        # Validate the generated project before interpolating it into a Docker filter.
        review_image_reference(project_name, "db")
        output = self.run(
            [
                "image",
                "ls",
                "--all",
                "--quiet",
                "--no-trunc",
                "--filter",
                f"label={REVIEW_IMAGE_PROJECT_LABEL}={project_name}",
            ],
            label="fixture image ownership check",
            capture_stdout=True,
        )
        return self._parse_image_ids(output)

    def image_config_labels(self, image_id: str) -> dict[str, str]:
        if (
            len(image_id) != 71
            or not image_id.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in image_id[7:])
        ):
            raise FixtureError("An image check requested an invalid Docker identifier.")
        output = self.run(
            ["image", "inspect", "--format", "{{json .Config.Labels}}", image_id],
            label="fixture image ownership check",
            capture_stdout=True,
        )
        try:
            labels = json.loads(output)
        except json.JSONDecodeError:
            raise FixtureError(
                "The Docker image ownership check returned invalid labels."
            ) from None
        if labels is None:
            return {}
        if not isinstance(labels, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in labels.items()
        ):
            raise FixtureError("The Docker image ownership check returned invalid labels.")
        return labels

    def remove_image_reference(self, reference: str, expected_image_id: str) -> None:
        # This removes only the run-specific tag. --no-prune deliberately keeps
        # shared parent layers and build cache intact.
        image_ids = self.image_ids_for_reference(reference)
        if image_ids != [expected_image_id]:
            raise FixtureError("A fixture image tag changed during the ownership check.")
        service = next(
            service
            for service in REVIEW_IMAGE_SERVICES
            if reference.endswith(f"-{service}:{REVIEW_IMAGE_TAG}")
        )
        project_name = reference[: -len(f"-{service}:{REVIEW_IMAGE_TAG}")]
        labels = self.image_config_labels(expected_image_id)
        expected_labels = review_image_labels(project_name, service)
        if any(labels.get(key) != value for key, value in expected_labels.items()):
            raise FixtureError("A Docker image failed the fixture ownership check.")
        self.run(
            ["image", "rm", "--no-prune", reference],
            label="fixture-owned image removal",
            timeout=120,
        )


class ComposeController:
    """Compose commands constrained to one fresh project and its private env file."""

    def __init__(
        self,
        *,
        docker: DockerClient,
        source_dir: Path,
        env_file: Path,
        project_name: str,
    ) -> None:
        self.docker = docker
        self.source_dir = source_dir
        self.env_file = env_file
        self.project_name = project_name
        self.compose_file = source_dir / "compose.yaml"

    def command(self, arguments: Sequence[str]) -> list[str]:
        return self.docker.command(
            [
                "compose",
                "--project-name",
                self.project_name,
                "--file",
                str(self.compose_file),
                "--env-file",
                str(self.env_file),
                *arguments,
            ]
        )

    def invoke(
        self,
        arguments: Sequence[str],
        *,
        label: str,
        timeout: int = 120,
        capture_stdout: bool = False,
    ) -> str:
        try:
            completed = subprocess.run(
                self.command(arguments),
                cwd=self.source_dir,
                env=self.docker.environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            raise FixtureError(f"The {label} could not be completed.") from None
        if completed.returncode != 0:
            raise FixtureError(
                f"The {label} failed (exit {completed.returncode}); details suppressed."
            )
        if not capture_stdout:
            return ""
        try:
            return completed.stdout.decode("utf-8", "strict")
        except (AttributeError, UnicodeDecodeError):
            raise FixtureError(f"The {label} returned invalid output.") from None

    def verify_no_existing_project_resources(self) -> None:
        resources = (
            self.docker.project_resource_ids("container", self.project_name),
            self.docker.project_resource_ids("volume", self.project_name),
            self.docker.project_resource_ids("network", self.project_name),
        )
        if any(resources):
            raise FixtureError("The generated Compose project name is already in use.")
        image_ids = self.docker.image_ids_for_project(self.project_name)
        for service in REVIEW_IMAGE_SERVICES:
            image_ids.extend(
                self.docker.image_ids_for_reference(
                    review_image_reference(self.project_name, service)
                )
            )
        if image_ids:
            raise FixtureError("A generated fixture image identity is already in use.")

    def verify_project_resources_owned(self) -> None:
        """Require each live resource to carry this project's expected Compose labels."""
        review_image_reference(self.project_name, "db")
        specifications = (
            ("container", "com.docker.compose.service", set(REVIEW_IMAGE_SERVICES), 8),
            ("network", "com.docker.compose.network", {"backend", "edge"}, 2),
            ("volume", "com.docker.compose.volume", {"postgres-data"}, 1),
        )
        for resource, role_label, allowed_roles, maximum_resources in specifications:
            resource_output = self.docker.project_resource_ids(resource, self.project_name)
            identifiers = [
                line.strip()
                for line in resource_output.splitlines()
                if line.strip()
            ]
            if (
                len(identifiers) > maximum_resources
                or len(identifiers) != len(set(identifiers))
            ):
                raise FixtureError("The owned project returned ambiguous Docker resources.")
            for identifier in identifiers:
                labels = self.docker.project_resource_labels(resource, identifier)
                if (
                    labels.get("com.docker.compose.project") != self.project_name
                    or labels.get(role_label) not in allowed_roles
                ):
                    raise FixtureError("A Docker resource failed the run ownership check.")
                working_directory = labels.get("com.docker.compose.project.working_dir")
                if working_directory is not None and working_directory != str(self.source_dir):
                    raise FixtureError("A Docker resource points to another Compose workspace.")
                config_files = labels.get("com.docker.compose.project.config_files")
                if config_files is not None and str(self.compose_file) not in config_files.split(
                    ","
                ):
                    raise FixtureError("A Docker resource points to another Compose file.")

    def verify_project_resources_removed(self) -> None:
        resources = (
            self.docker.project_resource_ids("container", self.project_name),
            self.docker.project_resource_ids("volume", self.project_name),
            self.docker.project_resource_ids("network", self.project_name),
        )
        if any(resources):
            raise FixtureError("Owned Compose resources remain after teardown.")

    def verify_project_images_removed(self) -> None:
        if self.docker.image_ids_for_project(self.project_name) or any(
            self.docker.image_ids_for_reference(review_image_reference(self.project_name, service))
            for service in REVIEW_IMAGE_SERVICES
        ):
            raise FixtureError("A fixture-owned app image remains after cleanup.")

    def remove_owned_images(self) -> None:
        """Remove only labeled run tags after their project containers are gone."""
        self.verify_project_resources_removed()
        labeled_ids = set(self.docker.image_ids_for_project(self.project_name))
        owned_references: list[tuple[str, str, str]] = []
        seen_ids: set[str] = set()

        for service in REVIEW_IMAGE_SERVICES:
            reference = review_image_reference(self.project_name, service)
            image_ids = self.docker.image_ids_for_reference(reference)
            if len(image_ids) > 1:
                raise FixtureError("A fixture image tag resolves to multiple Docker images.")
            if not image_ids:
                continue
            image_id = image_ids[0]
            labels = self.docker.image_config_labels(image_id)
            if (
                image_id not in labeled_ids
                or labels.get(REVIEW_IMAGE_PROJECT_LABEL) != self.project_name
                or labels.get(REVIEW_IMAGE_SERVICE_LABEL) != service
                or image_id in seen_ids
            ):
                raise FixtureError("A Docker image failed the fixture ownership check.")
            seen_ids.add(image_id)
            owned_references.append((service, reference, image_id))

        if seen_ids != labeled_ids:
            raise FixtureError("An untagged or unexpected fixture-labeled image remains.")

        for service, reference, image_id in owned_references:
            self.docker.remove_image_reference(reference, image_id)
            if self.docker.image_ids_for_reference(reference):
                raise FixtureError(f"The fixture-owned {service} image tag remains after removal.")
        self.verify_project_images_removed()

    def config_json(self) -> str:
        return self.invoke(
            ["config", "--format", "json"],
            label="private Compose configuration validation",
            timeout=30,
            capture_stdout=True,
        )

    def build(self) -> None:
        self.invoke(
            ["build", "db", "api", "frontdoor"],
            label="committed app image build",
            timeout=900,
        )

    def migrate(self) -> str:
        self.invoke(
            ["run", "--rm", "api", "alembic", "upgrade", "head"],
            label="fresh database migration",
            timeout=300,
        )
        diagnostic_exit, diagnostic_output, stderr_category = self.run_migration_diagnostic()
        diagnostic = parse_migration_diagnostic(diagnostic_output)
        if diagnostic is None:
            raise FixtureError(
                f"Fresh migration diagnostics were unavailable or exceeded their bound "
                f"(exit={diagnostic_exit}; stderr_category={stderr_category}); output suppressed."
            )
        diagnostic_summary = format_migration_diagnostic(diagnostic)
        current = self.invoke(
            ["run", "--rm", "api", "alembic", "current"],
            label="fresh database revision verification",
            timeout=120,
            capture_stdout=True,
        )
        status = migration_revision_status(current)
        if (
            diagnostic_exit != 0
            or status != "expected"
            or not migration_diagnostic_is_complete(diagnostic)
        ):
            raise FixtureError(
                f"Fresh migrations did not reach the committed application revision "
                f"(diagnostic_exit={diagnostic_exit}; alembic_current={status}; "
                f"{diagnostic_summary}); output suppressed."
            )
        return f"alembic_current={status}; {diagnostic_summary}"

    def up(self) -> None:
        self.invoke(["up", "-d"], label="disposable app startup", timeout=240)

    def run_api_python(self, code: str, *, label: str, timeout: int = 60) -> str:
        return self.invoke(
            ["run", "--rm", "--no-deps", "api", "python", "-c", code],
            label=label,
            timeout=timeout,
            capture_stdout=True,
        )

    def run_migration_diagnostic(self) -> tuple[int, str, str]:
        """Capture only bounded stdout from the fixed in-container probe."""
        try:
            completed = subprocess.run(
                self.command(
                    [
                        "run",
                        "--rm",
                        "--no-deps",
                        "api",
                        "python",
                        "-c",
                        MIGRATION_DIAGNOSTIC_PYTHON,
                    ]
                ),
                cwd=self.source_dir,
                env=self.docker.environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            raise FixtureError("Fresh migration diagnostics could not be completed.") from None

        if (
            not isinstance(completed.stdout, bytes)
            or len(completed.stdout) > MAX_MIGRATION_DIAGNOSTIC_BYTES
        ):
            return (
                completed.returncode,
                "",
                classify_migration_diagnostic_stderr(completed.stderr or b""),
            )
        try:
            output = completed.stdout.decode("utf-8", "strict")
        except UnicodeDecodeError:
            return (
                completed.returncode,
                "",
                classify_migration_diagnostic_stderr(completed.stderr or b""),
            )
        return (
            completed.returncode,
            output,
            classify_migration_diagnostic_stderr(completed.stderr or b""),
        )

    def bootstrap_admin(self, username: str, password: str) -> None:
        # Keep the committed CLI's normal prompt/bootstrap path, but translate any
        # SQLAlchemy failure to a fixed category and SQLSTATE before it reaches
        # the hidden PTY. No exception message or connection data is emitted.
        command = self.command(
            [
                "run",
                "--rm",
                "-it",
                "api",
                "python",
                "-c",
                SAFE_BOOTSTRAP_CLI,
                username,
            ]
        )
        run_hidden_password_prompts(
            command,
            prompts=ADMIN_PASSWORD_PROMPTS,
            answers=(password, password),
            cwd=self.source_dir,
            environment=self.docker.environment,
            timeout=120,
        )

    def expire_user_sessions(self, user_id: str) -> None:
        parsed_id = str(uuid.UUID(user_id))
        code = "\n".join(
            (
                "from datetime import datetime, timedelta, timezone",
                "import uuid",
                "from sqlalchemy import update",
                "from sqlalchemy.orm import Session",
                "from app.database import get_database_engine",
                "from app.models import WebSession",
                f"user_id = uuid.UUID({parsed_id!r})",
                "engine = get_database_engine()",
                "try:",
                "    with Session(engine) as db, db.begin():",
                "        result = db.execute(update(WebSession).where(",
                "            WebSession.user_id == user_id, WebSession.revoked_at.is_(None)",
                "        ).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))",
                "        if (result.rowcount or 0) < 1:",
                "            raise SystemExit(3)",
                "        print(result.rowcount)",
                "finally:",
                "    engine.dispose()",
            )
        )
        self._assert_row_count(
            self.run_api_python(code, label="synthetic session-expiry check"),
            minimum=1,
            maximum=100,
        )

    def disable_members_and_revoke_sessions(
        self,
        member_ids: Sequence[str],
        user_ids: Sequence[str],
    ) -> int:
        """Disable both synthetic members and revoke every known run session."""
        parsed_members = list(dict.fromkeys(str(uuid.UUID(user_id)) for user_id in member_ids))
        parsed_users = list(dict.fromkeys(str(uuid.UUID(user_id)) for user_id in user_ids))
        if not set(parsed_members).issubset(parsed_users):
            raise FixtureError("The fixture member ownership identifiers are inconsistent.")
        member_ids_expression = ", ".join(
            f"uuid.UUID({user_id!r})" for user_id in parsed_members
        )
        user_ids_expression = ", ".join(f"uuid.UUID({user_id!r})" for user_id in parsed_users)
        code = "\n".join(
            (
                "import uuid",
                "from sqlalchemy import func, select, update",
                "from sqlalchemy.orm import Session",
                "from app.database import get_database_engine",
                "from app.models import User, WebSession",
                f"member_ids = [{member_ids_expression}]",
                f"user_ids = [{user_ids_expression}]",
                "engine = get_database_engine()",
                "try:",
                "    with Session(engine) as db, db.begin():",
                "        found_members = set(db.scalars(",
                "            select(User.id).where(User.id.in_(member_ids))",
                "        ).all())",
                "        if found_members != set(member_ids):",
                "            raise SystemExit(3)",
                "        disabled = db.execute(update(User).where(",
                "            User.id.in_(member_ids)",
                "        ).values(is_active=False)) if member_ids else None",
                "        if user_ids:",
                "            db.execute(update(WebSession).where(",
                "                WebSession.user_id.in_(user_ids), WebSession.revoked_at.is_(None)",
                "            ).values(revoked_at=func.now()))",
                "        active_members = db.scalar(",
                "            select(func.count()).select_from(User).where(",
                "                User.id.in_(member_ids), User.is_active.is_(True)",
                "            )",
                "        ) if member_ids else 0",
                "        active_sessions = db.scalar(",
                "            select(func.count()).select_from(WebSession).where(",
                "                WebSession.user_id.in_(user_ids), WebSession.revoked_at.is_(None)",
                "            )",
                "        ) if user_ids else 0",
                "        if active_members or active_sessions:",
                "            raise SystemExit(4)",
                "        print((disabled.rowcount if disabled is not None else 0) or 0)",
                "finally:",
                "    engine.dispose()",
            )
        )
        return self._assert_row_count(
            self.run_api_python(
                code,
                label="synthetic account deactivation and session revocation",
            ),
            minimum=0,
            maximum=len(parsed_members),
        )

    @staticmethod
    def _assert_row_count(output: str, *, minimum: int, maximum: int) -> int:
        value = output.strip()
        if not value.isdecimal():
            raise FixtureError("The database session check returned invalid evidence.")
        count = int(value)
        if count < minimum or count > maximum:
            raise FixtureError("The database session check returned an unexpected row count.")
        return count

    def down(self) -> None:
        self.invoke(
            ["down", "--volumes", "--remove-orphans", "--timeout", "10"],
            label="owned Compose teardown",
            timeout=180,
        )


def validate_compose_config(config_text: str, identity: RunIdentity) -> None:
    """Reject any config that publishes services beyond the loopback front door."""
    try:
        config: Any = json.loads(config_text)
        services = config["services"]
        db = services["db"]
        api = services["api"]
        frontdoor = services["frontdoor"]
        networks = config["networks"]
        volumes = config["volumes"]
    except (TypeError, KeyError, json.JSONDecodeError):
        raise FixtureError("The committed Compose configuration is incomplete.") from None

    try:
        for name, service in services.items():
            if name != "frontdoor" and service.get("ports"):
                raise FixtureError("Only the front door may publish a host port.")
            if (
                service.get("network_mode")
                or service.get("privileged")
                or service.get("pid") == "host"
                or service.get("ipc") == "host"
                or service.get("devices")
                or service.get("volumes_from")
                or service.get("secrets")
                or service.get("configs")
            ):
                raise FixtureError("The committed Compose service has an unsafe host attachment.")
            if name != "db" and service.get("volumes"):
                raise FixtureError("Only the database may use the fixture-owned named volume.")
        ports = frontdoor.get("ports", [])
        if len(ports) != 1:
            raise FixtureError("The front door must publish exactly one host port.")
        binding = ports[0]
        expected_host = urlsplit(identity.origin).hostname
        if (
            expected_host is None
            or ipaddress.ip_address(expected_host).version != 4
            or not ipaddress.ip_address(expected_host).is_loopback
        ):
            raise FixtureError("The front-door origin is not a loopback address.")
        if (
            str(binding.get("host_ip")) != expected_host
            or str(binding.get("published")) != str(identity.port)
            or int(binding.get("target", 0)) != 8080
            or binding.get("protocol", "tcp") != "tcp"
        ):
            raise FixtureError("The front door is not bound exclusively to loopback.")

        db_environment = db.get("environment", {})
        api_environment = api.get("environment", {})
        if (
            db_environment.get("POSTGRES_PASSWORD") != identity.postgres_password
            or api_environment.get("DB_PASSWORD") != identity.app_password
            or api_environment.get("IMPOSTR_RATE_LIMIT_KEY") != identity.rate_limit_key
            or api_environment.get("IMPOSTR_PUBLIC_ORIGIN") != identity.origin
            or str(api_environment.get("APP_PORT")) != str(identity.port)
        ):
            raise FixtureError("The generated private environment was not applied to the app.")
        if db.get("ports") or api.get("ports"):
            raise FixtureError("Database and API ports must not be published.")

        for service_name in REVIEW_IMAGE_SERVICES:
            service = services[service_name]
            build = service.get("build", {})
            labels = build.get("labels", {})
            expected_labels = review_image_labels(identity.project_name, service_name)
            if (
                service.get("image") != review_image_reference(identity.project_name, service_name)
                or labels.get(REVIEW_IMAGE_PROJECT_LABEL)
                != expected_labels[REVIEW_IMAGE_PROJECT_LABEL]
                or labels.get(REVIEW_IMAGE_SERVICE_LABEL)
                != expected_labels[REVIEW_IMAGE_SERVICE_LABEL]
            ):
                raise FixtureError("The app images are not uniquely owned by this fixture run.")

        backend = networks.get("backend", {})
        if backend.get("internal") is not True:
            raise FixtureError("The database/API network must remain internal.")
        for service_name, expected_networks in (
            ("db", {"backend"}),
            ("api", {"backend"}),
            ("frontdoor", {"backend", "edge"}),
        ):
            configured_networks = services[service_name].get("networks", {})
            if not isinstance(configured_networks, (dict, list)):
                raise FixtureError("A Compose service has an unexpected network attachment.")
            actual_networks = set(configured_networks)
            if actual_networks != expected_networks:
                raise FixtureError("A Compose service has an unexpected network attachment.")
        if any(network.get("external", False) for network in networks.values()):
            raise FixtureError("All fixture networks must be project-owned.")
        volume = volumes.get("postgres-data")
        if not isinstance(volume, dict) or volume.get("external", False):
            raise FixtureError("The database must use a disposable project-owned volume.")
        configured_volume_name = volume.get("name")
        if configured_volume_name and not str(configured_volume_name).startswith(
            f"{identity.project_name}_"
        ):
            raise FixtureError("The database volume is not unique to this Compose project.")
        database_mounts = db.get("volumes", [])
        if (
            not isinstance(database_mounts, list)
            or len(database_mounts) != 1
            or not isinstance(database_mounts[0], dict)
            or database_mounts[0].get("source") != "postgres-data"
            or database_mounts[0].get("target") != "/var/lib/postgresql/data"
            or database_mounts[0].get("type") != "volume"
        ):
            raise FixtureError("The database is not using the project-owned volume.")
    except (AttributeError, TypeError, ValueError, IndexError):
        raise FixtureError("The committed Compose configuration failed safety checks.") from None


def run_hidden_password_prompts(
    command: Sequence[str],
    *,
    prompts: Sequence[str],
    answers: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    timeout: int,
) -> None:
    """Answer a bounded interactive getpass CLI over a private, unlogged PTY."""
    if len(prompts) != len(answers) or not prompts:
        raise FixtureError("The offline bootstrap prompt contract is invalid.")
    master_fd = -1
    slave_fd = -1
    process: subprocess.Popen[bytes] | None = None
    pending = bytearray()
    diagnostic_output = bytearray()
    try:
        master_fd, slave_fd = pty.openpty()
        attributes = termios.tcgetattr(slave_fd)
        attributes[3] &= ~(termios.ECHO | termios.ECHONL)
        termios.tcsetattr(slave_fd, termios.TCSANOW, attributes)
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(environment),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)
        slave_fd = -1

        prompt_index = 0
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                raise FixtureError("The offline administrator bootstrap timed out.")
            ready, _, _ = select.select([master_fd], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                available = MAX_BOOTSTRAP_DIAGNOSTIC_BYTES - len(diagnostic_output)
                if available > 0:
                    diagnostic_output.extend(chunk[:available])
                pending.extend(chunk.replace(b"\r", b""))
                while prompt_index < len(prompts):
                    prompt = prompts[prompt_index].encode("ascii")
                    position = pending.find(prompt)
                    if position < 0:
                        break
                    del pending[: position + len(prompt)]
                    os.write(master_fd, answers[prompt_index].encode("ascii") + b"\n")
                    prompt_index += 1
                if len(pending) > 64 * 1024:
                    raise FixtureError(
                        "The offline bootstrap produced unexpected terminal output."
                    )
            if process.poll() is not None and not ready:
                break

        if process.poll() is None:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        if process.returncode != 0:
            diagnostic = classify_bootstrap_diagnostic(bytes(diagnostic_output))
            raise FixtureError(
                f"The offline administrator bootstrap failed (exit {process.returncode}; "
                f"diagnostic={diagnostic}); terminal output suppressed."
            )
        if prompt_index != len(prompts):
            raise FixtureError(
                f"The offline administrator bootstrap served {prompt_index} of {len(prompts)} "
                "prompts; output suppressed."
            )
    except FixtureError:
        raise
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise FixtureError("The offline administrator bootstrap could not be completed.") from None
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except (OSError, subprocess.SubprocessError):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
                except (OSError, subprocess.SubprocessError):
                    pass
        if slave_fd >= 0:
            os.close(slave_fd)
        if master_fd >= 0:
            os.close(master_fd)
        pending.clear()
        diagnostic_output.clear()


@dataclass(frozen=True, slots=True)
class ApiResponse:
    status: int
    payload: Any
    headers: Mapping[str, str]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class ApiClient:
    """Minimal same-origin HTTP client; never consult environment proxy settings."""

    def __init__(self, origin: str) -> None:
        try:
            parsed_origin = urlsplit(origin)
            loopback = ipaddress.ip_address(parsed_origin.hostname or "").is_loopback
            if (
                parsed_origin.scheme != "http"
                or not loopback
                or parsed_origin.username is not None
                or parsed_origin.password is not None
                or not parsed_origin.port
                or parsed_origin.path
                or parsed_origin.query
                or parsed_origin.fragment
                or origin != f"http://{parsed_origin.hostname}:{parsed_origin.port}"
            ):
                raise FixtureError("The fixture API must use a canonical IPv4 loopback origin.")
        except (ValueError, TypeError):
            raise FixtureError(
                "The fixture API must use a canonical IPv4 loopback origin."
            ) from None
        self.origin = origin
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookies),
            _NoRedirectHandler(),
        )
        self.csrf_token: str | None = None

    def clear_cookies(self) -> None:
        self.cookies.clear()
        self.csrf_token = None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        csrf_token: str | None = None,
        timeout: int = 5,
    ) -> ApiResponse:
        if not path.startswith("/") or path.startswith("//"):
            raise FixtureError("A local app request used an invalid path.")
        headers = {"Accept": "application/json"}
        data: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        if method not in {"GET", "POST"}:
            raise FixtureError("The fixture attempted an unsupported HTTP method.")
        if method == "POST":
            headers["Origin"] = self.origin
            if csrf_token:
                headers["X-CSRF-Token"] = csrf_token
        request = urllib.request.Request(
            self.origin + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            response = self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            try:
                return ApiResponse(
                    status=error.code,
                    payload=None,
                    headers=dict(error.headers.items()),
                )
            finally:
                error.close()
        except OSError:
            raise FixtureError("The disposable local app could not be reached.") from None

        try:
            with response:
                payload_bytes = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload_bytes) > MAX_RESPONSE_BYTES:
                    raise FixtureError("The disposable app returned an oversized response.")
                content_type = response.headers.get("Content-Type", "")
                payload: Any = None
                if payload_bytes and "json" in content_type.lower():
                    try:
                        payload = json.loads(payload_bytes.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        raise FixtureError("The disposable app returned invalid JSON.") from None
                return ApiResponse(
                    status=response.status,
                    payload=payload,
                    headers=dict(response.headers.items()),
                )
        except FixtureError:
            raise
        except (OSError, UnicodeError):
            raise FixtureError("The disposable app response could not be read safely.") from None

    @staticmethod
    def _require_json_object(
        response: ApiResponse,
        expected_status: int,
        action: str,
    ) -> dict[str, Any]:
        if response.status != expected_status or not isinstance(response.payload, dict):
            raise FixtureError(f"The {action} did not return its expected response.")
        return response.payload

    def _login_attempt(self, username: str, password: str) -> ApiResponse:
        csrf_response = self.request("GET", "/api/auth/csrf")
        csrf_payload = self._require_json_object(csrf_response, 200, "pre-login CSRF request")
        prelogin_csrf = csrf_payload.get("csrf_token")
        if not isinstance(prelogin_csrf, str) or not prelogin_csrf:
            raise FixtureError("The real app did not issue a pre-login CSRF token.")

        response = self.request(
            "POST",
            "/api/auth/login",
            body={"username": username, "password": password},
            csrf_token=prelogin_csrf,
        )
        if response.status == 200:
            payload = self._require_json_object(response, 200, "normal account sign-in")
            session_csrf = payload.get("csrf_token")
            if not isinstance(session_csrf, str) or not session_csrf:
                raise FixtureError("The real app returned an incomplete account session.")
            self.csrf_token = session_csrf
        return response

    def login_status(self, username: str, password: str) -> int:
        """Attempt the normal CSRF-protected sign-in and return its HTTP status."""
        return self._login_attempt(username, password).status

    def login(self, username: str, password: str, *, expected_role: str) -> dict[str, Any]:
        response = self._login_attempt(username, password)
        payload = self._require_json_object(response, 200, "normal account sign-in")
        user = payload.get("user")
        session_csrf = payload.get("csrf_token")
        if (
            not isinstance(user, dict)
            or user.get("username") != username
            or user.get("role") != expected_role
            or not isinstance(user.get("id"), str)
            or not isinstance(session_csrf, str)
            or not session_csrf
        ):
            raise FixtureError("The real app returned an unexpected account or session.")
        self.csrf_token = session_csrf
        return user

    def create_member(self, username: str, password: str) -> dict[str, Any]:
        if not self.csrf_token:
            raise FixtureError("The authenticated admin session is unavailable.")
        response = self.request(
            "POST",
            "/api/admin/users",
            body={"username": username, "password": password, "role": "user"},
            csrf_token=self.csrf_token,
        )
        payload = self._require_json_object(response, 201, "admin-provisioned member creation")
        if (
            payload.get("username") != username
            or payload.get("role") != "user"
            or payload.get("is_active") is not True
            or not isinstance(payload.get("id"), str)
        ):
            raise FixtureError("The real app did not create the expected member account.")
        return payload

    def reset_member_password(self, user_id: str, password: str) -> int:
        if not self.csrf_token:
            raise FixtureError("The authenticated admin session is unavailable.")
        try:
            safe_id = str(uuid.UUID(user_id))
        except ValueError:
            raise FixtureError("The real app returned an invalid member identifier.") from None
        response = self.request(
            "POST",
            f"/api/admin/users/{safe_id}/reset-password",
            body={"password": password},
            csrf_token=self.csrf_token,
        )
        if response.status != 204:
            raise FixtureError("The synthetic member session-revocation check failed.")
        return response.status

    def attempt_admin_user_creation(self, username: str, password: str) -> int:
        if not self.csrf_token:
            raise FixtureError("The member session is unavailable for authorization checks.")
        response = self.request(
            "POST",
            "/api/admin/users",
            body={"username": username, "password": password, "role": "admin"},
            csrf_token=self.csrf_token,
        )
        return response.status

    def session_status(self) -> int:
        return self.request("GET", "/api/auth/session").status

    def admin_users_status(self) -> int:
        return self.request("GET", "/api/admin/users?limit=100&offset=0").status

    def logout(self) -> None:
        if not self.csrf_token:
            raise FixtureError("The authenticated logout token is unavailable.")
        response = self.request(
            "POST",
            "/api/auth/logout",
            csrf_token=self.csrf_token,
        )
        if response.status != 204:
            raise FixtureError("The offline administrator session could not be logged out.")
        self.csrf_token = None


def wait_for_frontdoor(client: ApiClient, *, timeout: int = 120) -> None:
    """Wait for both the actual API health route and Nginx-served app shell."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            health = client.request("GET", "/api/health", timeout=5)
            if health.status == 200 and isinstance(health.payload, dict):
                if health.payload.get("status") == "ok":
                    frontdoor = client.request("GET", "/", timeout=5)
                    if frontdoor.status == 200 and "html" in frontdoor.headers.get(
                        "Content-Type", ""
                    ).lower():
                        return
        except FixtureError:
            pass
        time.sleep(1)
    raise FixtureError("The real local front door did not become ready in time.")


def _safe_account_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise FixtureError("The real app returned an invalid account identifier.") from None


class FixtureSupervisor:
    """Own the temporary source, Compose project, synthetic users, and teardown."""

    def __init__(
        self,
        repository_root: Path,
        *,
        output: TextIO = sys.stdout,
        input_stream: TextIO = sys.stdin,
        docker_socket: str = LOCAL_DOCKER_SOCKET,
        lifetime_minutes: int = DEFAULT_LIFETIME_MINUTES,
        handoff_directory: Path | None = None,
        control_directory: Path | None = None,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.output = output
        self.input_stream = input_stream
        self.docker_socket = docker_socket
        self.lifetime_minutes = lifetime_minutes
        self.handoff_directory = handoff_directory
        self.control_directory = control_directory
        self.channel_ready = False
        self.channel_status = initial_cleanup_status()
        self.cleanup_member_accounts = "not-created"
        self.cleanup_owned_compose = "not-created"
        self.cleanup_owned_images = "not-created"
        self.cleanup_private_state = "not-created"
        self.cleanup_member_login = "not-created"
        self.cleanup_recovery_status = "not-needed"
        self.state_dir: Path | None = None
        self.source_dir: Path | None = None
        self.identity: RunIdentity | None = None
        self.docker: DockerClient | None = None
        self.compose: ComposeController | None = None
        self.project_owned = False
        self.admin_client: ApiClient | None = None
        self.admin_session_may_be_active = False
        self.api_clients: list[ApiClient] = []
        self.handoff_published = False
        self._old_signal_handlers: dict[int, Any] = {}

    def _update_channel_status(self, **changes: Any) -> None:
        if not self.channel_ready or self.handoff_directory is None:
            return
        self.channel_status.update(changes)
        write_cleanup_status(self.handoff_directory, self.channel_status)

    def _register_recovery_context(self, *, owned: bool) -> None:
        if self.control_directory is None or self.state_dir is None:
            return
        update_control_recovery(
            self.control_directory,
            state_dir=self.state_dir,
            project_name=self.identity.project_name if self.identity is not None else None,
            owned=owned,
        )

    def _say(self, message: str) -> None:
        try:
            self.output.write(message + "\n")
            self.output.flush()
        except (OSError, ValueError):
            # Closing a log/terminal must not interrupt resource teardown.
            pass

    def _install_signal_handlers(self) -> None:
        def stop_handler(_signum, _frame) -> None:
            raise StopRequested()

        for signal_number in (
            signal.SIGINT,
            signal.SIGTERM,
            getattr(signal, "SIGHUP", signal.SIGTERM),
        ):
            if signal_number in self._old_signal_handlers:
                continue
            try:
                self._old_signal_handlers[signal_number] = signal.getsignal(signal_number)
                signal.signal(signal_number, stop_handler)
            except (ValueError, OSError):
                # Signal registration is available only on the main thread.
                continue

    def _restore_signal_handlers(self) -> None:
        for signal_number, handler in self._old_signal_handlers.items():
            try:
                signal.signal(signal_number, handler)
            except (ValueError, OSError):
                pass
        self._old_signal_handlers.clear()

    def _prepare(self) -> None:
        if not self.input_stream.isatty() or not self.output.isatty():
            raise FixtureError("Start the fixture in a foreground interactive terminal.")
        if (
            self.lifetime_minutes < MIN_LIFETIME_MINUTES
            or self.lifetime_minutes > MAX_LIFETIME_MINUTES
        ):
            raise FixtureError("The fixture lifetime is outside the supported range.")

        docker_executable = shutil.which("docker")
        if docker_executable is None:
            raise FixtureError("Docker Compose is not available on PATH.")
        self.state_dir = create_private_state_dir(self.repository_root)
        self.source_dir = self.state_dir / "source"
        self._register_recovery_context(owned=False)
        host = choose_loopback_host()
        self.identity = generate_identity(choose_loopback_port(host), host=host)
        self._register_recovery_context(owned=False)
        env_file = self.state_dir / "compose.env"
        create_compose_env(env_file, self.identity)
        create_member_recovery_file(self.state_dir, self.identity)
        self.docker = DockerClient(
            executable=docker_executable,
            docker_socket=self.docker_socket,
            state_dir=self.state_dir,
        )
        commit = archive_head_snapshot(
            self.repository_root,
            self.source_dir,
            private_home=self.state_dir,
        )
        set_snapshot_loopback_host(self.source_dir, host)
        set_snapshot_review_images(self.source_dir, self.identity.project_name)
        self.compose = ComposeController(
            docker=self.docker,
            source_dir=self.source_dir,
            env_file=env_file,
            project_name=self.identity.project_name,
        )

        self._say("Checking the local Docker engine and committed app snapshot…")
        self.docker.probe_local_engine()
        config_text = self.compose.config_json()
        validate_compose_config(config_text, self.identity)
        del config_text
        self.compose.verify_no_existing_project_resources()

        # From this point on, only this random, previously empty project is ours.
        # The flag is set before the first create-capable Docker command so even a
        # partially failed build/run follows the same project-scoped cleanup path.
        self._register_recovery_context(owned=True)
        self.project_owned = True
        self._say(f"Building committed snapshot {commit[:12]} in a private temporary tree…")
        self.compose.build()
        self._say("Applying fresh migrations and starting the loopback-only front door…")
        migration_evidence = self.compose.migrate()
        self._say(f"Fresh migration evidence: {migration_evidence}")
        self.compose.up()

        api = ApiClient(self.identity.origin)
        self.api_clients.append(api)
        wait_for_frontdoor(api)

        if self.identity.admin_password is None:
            raise FixtureError("The synthetic offline administrator secret is unavailable.")
        self._say("Bootstrapping an offline synthetic administrator over a hidden PTY…")
        admin_password = self.identity.admin_password
        self.compose.bootstrap_admin(self.identity.admin_username, admin_password)
        self.identity.admin_password = None
        self.admin_client = ApiClient(self.identity.origin)
        self.api_clients.append(self.admin_client)
        try:
            self._provision_and_verify_accounts(admin_password)
        finally:
            del admin_password
        self.identity.postgres_password = None
        self.identity.app_password = None
        self.identity.rate_limit_key = None

    def _provision_and_verify_accounts(self, admin_password: str) -> None:
        """Authenticate normally, provision two members, and exercise auth denials."""
        assert self.identity is not None
        assert self.compose is not None
        assert self.admin_client is not None
        # A successful HTTP login can set a privileged session cookie before its
        # response (including the account ID) has been validated. Cleanup must
        # attempt logout even if login/ID validation raises midway through.
        self.admin_session_may_be_active = True
        admin = self.admin_client.login(
            self.identity.admin_username,
            admin_password,
            expected_role="admin",
        )
        self.identity.admin_user_id = _safe_account_id(admin["id"])

        for member in self.identity.members:
            if member.password is None:
                raise FixtureError("A generated member credential is unavailable.")
            # A request may create the account even if its response is lost or
            # cannot be tied to a usable ID, so cleanup must treat that outcome
            # as potentially live until the owned database volume is removed.
            member.creation_unconfirmed = True
            payload = self.admin_client.create_member(member.username, member.password)
            member.user_id = _safe_account_id(payload["id"])
            member.creation_unconfirmed = False

        if len(self.identity.user_ids) != 3:
            raise FixtureError("The real app did not create the expected synthetic accounts.")

        member_clients: list[tuple[MemberCredential, ApiClient]] = []
        for member_index, member in enumerate(self.identity.members, start=1):
            if member.password is None:
                raise FixtureError("A generated member credential is unavailable.")
            client = ApiClient(self.identity.origin)
            self.api_clients.append(client)
            user = client.login(member.username, member.password, expected_role="user")
            if _safe_account_id(user["id"]) != member.user_id:
                raise FixtureError("A member login resolved to an unexpected account.")
            if client.admin_users_status() != 403:
                raise FixtureError("A member was not denied access to the admin API.")
            denied_username = denied_member_username(self.identity, member_index)
            denied_password = secrets.token_urlsafe(24)
            denied_status = client.attempt_admin_user_creation(denied_username, denied_password)
            del denied_password
            if denied_status != 403:
                raise FixtureError("A member was not denied admin account creation.")
            member_clients.append((member, client))

        listed = self.admin_client.request("GET", "/api/admin/users?limit=100&offset=0")
        if listed.status != 200 or not isinstance(listed.payload, list) or len(listed.payload) != 3:
            raise FixtureError("The admin account list contains unexpected synthetic users.")
        if any(
            isinstance(account, dict)
            and str(account.get("username", "")).startswith(
                f"reviewdenied{self.identity.run_id}"
            )
            for account in listed.payload
        ):
            raise FixtureError("A denied member account-creation request had an effect.")

        first_member, first_client = member_clients[0]
        if first_member.user_id is None:
            raise FixtureError("A synthetic member account identifier is missing.")
        self.compose.expire_user_sessions(first_member.user_id)
        if first_client.session_status() != 401 or first_client.admin_users_status() != 401:
            raise FixtureError("An expired synthetic member session remained usable.")

        second_member, second_client = member_clients[1]
        if second_member.user_id is None or second_member.password is None:
            raise FixtureError("A synthetic member account identifier is missing.")
        self.admin_client.reset_member_password(second_member.user_id, second_member.password)
        if second_client.session_status() != 401 or second_client.admin_users_status() != 401:
            raise FixtureError("A reset-revoked synthetic member session remained usable.")

        self.admin_client.logout()
        self.admin_session_may_be_active = False
        if (
            self.admin_client.session_status() != 401
            or self.admin_client.admin_users_status() != 401
        ):
            raise FixtureError("The offline admin session was not revoked before browser handoff.")

        for client in self.api_clients:
            client.clear_cookies()
        self.api_clients.clear()
        self.admin_client = None
        self._say(
            "Pre-handoff checks passed: two member roles, member-to-admin denial (403), "
            "expired/revoked session denial (401), and admin logout (401)."
        )

    def _publish_handoff(self) -> None:
        if self.identity is None or not self.identity.members:
            raise FixtureError("The disposable app did not finish setup.")
        browser_member = self.identity.members[0]
        if browser_member.password is None or browser_member.user_id is None:
            raise FixtureError("The generated browser-review member is unavailable.")
        if self.handoff_directory is not None:
            # Set this before the atomic rename: a later status-write failure must
            # still run the full member/session cleanup path.
            self.handoff_published = True
            write_member_handoff(
                self.handoff_directory,
                browser_member.username,
                browser_member.password,
            )
            self.cleanup_member_login = "published"
            self._update_channel_status(
                phase="ready",
                exit_code=None,
                member_login="published",
                member_accounts="pending",
                owned_compose="pending",
                owned_images="pending",
                private_state="pending",
                recovery_status=(
                    "pending" if self.control_directory is not None else "not-needed"
                ),
            )
            # The detached PTY guardian forwards only this allowlisted URL event
            # to the launcher. All other terminal output, including diagnostics,
            # is drained and discarded rather than persisted as a raw log.
            self._say(f"FIXTURE_HANDOFF_READY {self.identity.origin}")
            return
        self._say("")
        self._say("DISPOSABLE REAL-APP BROWSER REVIEW IS READY")
        self._say(f"URL: {self.identity.origin}/")
        self._say(
            "This run uses a fresh 127/8 host address to avoid reusing other local app cookies."
        )
        self._say(
            "Automated browser-tool sign-in only; do not manually enter credentials in the UI:"
        )
        self._say(
            "1. The coordinator uses playwright_browser_navigate on the existing shared "
            "Playwright page to open this URL."
        )
        self._say(
            "2. Use playwright_browser_snapshot to confirm the signed-out form, then "
            "playwright_browser_fill_form with target #login-username (Username) and "
            "#login-password (Password) using the one Member login below. Call "
            "playwright_browser_click on the normal button[type=submit] Sign in control, "
            "then snapshot again and confirm the Welcome state. This is the real UI/CSRF flow; "
            "do not call the login API directly, inject cookies, or use a test bypass."
        )
        self._say(
            "3. Confirm the signed-in welcome state, then leave that same authenticated page "
            "and browser context open for ui-designer to inspect. Do not sign out or open a "
            "second browser context before the design review."
        )
        self._say(
            "Only this generated Member account may enter browser-tool calls. The admin, "
            "database, provider, host and owner test-account credentials are never part of "
            "this handoff; do not place them in browser calls or agent prompts."
        )
        self._say(f"Browser-review member username: {browser_member.username}")
        self._say(f"Browser-review member password: {browser_member.password}")
        self._say(
            "Do not copy session cookies, credentials, screenshots, or private logs into Git."
        )
        self._say(
            "Keep this supervisor running until the coordinator confirms that the normal UI "
            "sign-in succeeded and ui-designer finished inspecting the same page. PTY stdin EOF "
            "does not stop it; press Enter or send a handled stop signal only after review. "
            "The fixture auto-stops at its bounded lifetime limit."
        )
        self._say("")
        self.handoff_published = True

    def _wait_for_operator(self) -> None:
        deadline = time.monotonic() + self.lifetime_minutes * 60
        input_open = True
        while time.monotonic() < deadline:
            remaining = min(1.0, max(0.0, deadline - time.monotonic()))
            if not input_open:
                time.sleep(remaining)
                continue
            try:
                ready, _, _ = select.select([self.input_stream], [], [], remaining)
            except (OSError, ValueError):
                input_open = False
                continue
            if not ready:
                continue
            try:
                line = self.input_stream.readline()
            except (OSError, ValueError):
                input_open = False
                continue
            if line == "":
                # A closed parent PTY is not an operator stop request. Detached
                # runners must remain available for browser handoff until an
                # explicit signal or the bounded lifetime expires.
                input_open = False
                continue
            break
        self._say("Stopping the disposable browser-review fixture…")

    def _disable_members_and_verify_signin_denied(self) -> None:
        if self.identity is None or self.compose is None:
            raise FixtureError("Synthetic account ownership is unavailable during cleanup.")

        member_ids = [member.user_id for member in self.identity.members if member.user_id]
        if self.handoff_published and len(member_ids) != len(self.identity.members):
            raise FixtureError(
                "Both browser-review member accounts are not identified for cleanup."
            )
        if self.handoff_published and any(
            member.password is None for member in self.identity.members
        ):
            raise FixtureError("The browser-review member credentials are unavailable for cleanup.")

        if self.identity.user_ids:
            disabled = self.compose.disable_members_and_revoke_sessions(
                member_ids,
                self.identity.user_ids,
            )
            self._say(f"Synthetic member accounts disabled; newly disabled accounts: {disabled}.")

        verified = 0
        for member in self.identity.members:
            if member.user_id is None or member.password is None:
                continue
            client = ApiClient(self.identity.origin)
            try:
                status_code = client.login_status(member.username, member.password)
                if status_code == 200:
                    # Avoid leaving a session behind even if an unexpected active
                    # account slips through the deactivation check.
                    client.logout()
                    raise FixtureError("A disabled synthetic member could still sign in.")
                if status_code != 401:
                    raise FixtureError("A new synthetic member sign-in was not denied.")
                verified += 1
            finally:
                client.clear_cookies()

        expected = len(self.identity.members) if self.handoff_published else len(member_ids)
        if verified != expected:
            raise FixtureError("Synthetic member sign-in denial could not be verified.")
        if any(member.creation_unconfirmed for member in self.identity.members):
            raise FixtureError(
                "A possible synthetic member account has no confirmed identifier."
            )
        if self.handoff_published:
            self._say("New sign-in for both browser-review members was denied (HTTP 401).")

    def _cleanup(self) -> list[str]:
        """Attempt account revocation, then destroy the owned stack even if it fails."""
        errors: list[str] = []
        if self.channel_ready:
            try:
                self._update_channel_status(phase="stopping")
            except FixtureError:
                errors.append("Sanitized cleanup status could not be updated.")
        if self.channel_ready and self.handoff_directory is not None:
            if not self.handoff_published and self.cleanup_member_login == "not-created":
                self.cleanup_member_login = "not-created"
            elif self.identity is None or not self.identity.members:
                self.cleanup_member_login = "not-verified"
                errors.append("The private Member handoff could not be removed.")
            else:
                member = self.identity.members[0]
                if member.password is None:
                    self.cleanup_member_login = "not-verified"
                    errors.append("The private Member handoff could not be removed.")
                else:
                    try:
                        removed = remove_member_handoff(
                            self.handoff_directory,
                            member.username,
                            member.password,
                        )
                        if removed:
                            self.cleanup_member_login = "removed"
                        elif self.cleanup_member_login == "published":
                            self.cleanup_member_login = "not-verified"
                            errors.append("The private Member handoff could not be removed.")
                    except FixtureError:
                        self.cleanup_member_login = "not-verified"
                        errors.append("The private Member handoff could not be removed.")
            try:
                self._update_channel_status(member_login=self.cleanup_member_login)
            except FixtureError:
                errors.append("Sanitized cleanup status could not be updated.")

        admin_logout_unverified = False
        if self.admin_client is not None:
            if self.admin_session_may_be_active:
                try:
                    self.admin_client.logout()
                    self.admin_session_may_be_active = False
                except FixtureError:
                    admin_logout_unverified = True
                    errors.append("Administrator logout could not be confirmed during cleanup.")
            self.admin_client.clear_cookies()
            self.admin_client = None
        for client in self.api_clients:
            client.clear_cookies()
        self.api_clients.clear()

        remove_state = not self.project_owned
        account_cleanup_verified = True
        if self.project_owned and self.compose is not None:
            possible_unidentified_member = self.identity is not None and any(
                member.creation_unconfirmed for member in self.identity.members
            )
            should_verify_accounts = self.identity is not None and (
                self.identity.user_ids or possible_unidentified_member
            )
            if should_verify_accounts:
                try:
                    self._disable_members_and_verify_signin_denied()
                    self.cleanup_member_accounts = "verified"
                except (FixtureError, ValueError):
                    account_cleanup_verified = False
                    self.cleanup_member_accounts = "not-verified"
                    errors.append(
                        "Synthetic member deactivation or sign-in denial could not be verified."
                    )
            elif self.handoff_published:
                account_cleanup_verified = False
                self.cleanup_member_accounts = "not-verified"
                errors.append("Browser-review members could not be verified for cleanup.")
            else:
                self.cleanup_member_accounts = "not-created"

            # An unverified account must not leave a reachable login behind just
            # because the API/DB denial check failed. This project was checked
            # empty before the first create-capable command; Compose is pinned to
            # that unique name and its private configuration, never a host stack.
            teardown_verified = False
            compose_resources_removed = False
            owned_images_removed = False
            self.cleanup_owned_compose = "not-verified"
            self.cleanup_owned_images = "not-verified"
            for attempt in range(2):
                try:
                    self.compose.down()
                    self.compose.verify_project_resources_removed()
                    compose_resources_removed = True
                    self.compose.remove_owned_images()
                    self.compose.verify_project_images_removed()
                    owned_images_removed = True
                    teardown_verified = True
                    break
                except FixtureError:
                    if attempt == 0:
                        time.sleep(0.5)
            if compose_resources_removed:
                self.cleanup_owned_compose = "removed"
            if owned_images_removed:
                self.cleanup_owned_images = "removed"
            if teardown_verified:
                resources_recorded = self.control_directory is None
                if self.control_directory is not None:
                    try:
                        _update_control_resources_removed(
                            self.control_directory,
                            os.getpid(),
                        )
                        resources_recorded = True
                    except FixtureError:
                        errors.append(
                            "Owned teardown could not be durably recorded for recovery."
                        )
                self.project_owned = False
                remove_state = resources_recorded
                if not resources_recorded:
                    self.cleanup_private_state = "retained-for-recovery"
                self._say(
                    "Owned Compose containers, network, database volume, and run-built images "
                    "were removed; shared Docker cache was not pruned."
                )
            else:
                errors.append("Owned Compose teardown could not be verified.")

        if self.project_owned and self.compose is None:
            self.cleanup_member_accounts = (
                "not-verified" if self.handoff_published else "not-created"
            )
            self.cleanup_owned_compose = "not-verified"
            self.cleanup_owned_images = "not-verified"
            errors.append("Owned Compose teardown could not be verified.")

        if self.state_dir is not None and remove_state:
            try:
                shutil.rmtree(self.state_dir)
                self.state_dir = None
                self.cleanup_private_state = "removed"
            except OSError:
                self.cleanup_private_state = "not-verified"
                errors.append("Private fixture state could not be removed.")
                self._say(f"Private supervisor state remains at: {self.state_dir}")
        elif self.state_dir is not None and self.project_owned:
            self.cleanup_private_state = "retained-for-recovery"
            self._say(
                "Cleanup is incomplete; private supervisor state was retained for manual cleanup "
                "at: "
                f"{self.state_dir}"
            )
            if admin_logout_unverified:
                self._say(
                    "Treat the synthetic administrator session as live until the owned database "
                    "volume is confirmed removed; retry only this run's owned teardown."
                )
            if not account_cleanup_verified:
                self._say(
                    "Treat both generated Member logins and any browser session as live until "
                    "the owned database volume is confirmed removed. Both Member credentials "
                    "remain only in the private recovery file at: "
                    f"{self.state_dir / MEMBER_RECOVERY_FILE}"
                )
            if self.compose is not None:
                command = self.compose.command(
                    ["down", "--volumes", "--remove-orphans", "--timeout", "10"]
                )
                self._say("Retry only this owned project teardown after Docker recovers:")
                self._say(shlex.join(command))
                self._say(
                    "Verify that this project's containers, networks and database volume are gone. "
                    "Remove only this run's uniquely tagged images after checking their project/"
                    "service ownership labels, using docker image rm --no-prune. "
                    "Do not run docker image prune or remove any other project."
                )
        elif self.state_dir is None:
            self.cleanup_private_state = "not-created"

        if self.identity is not None:
            self.identity.admin_password = None
            self.identity.postgres_password = None
            self.identity.app_password = None
            self.identity.rate_limit_key = None
            for member in self.identity.members:
                member.password = None
        return errors

    def run(self) -> int:
        """Run the foreground lifecycle and always attempt owned-resource cleanup."""
        failure: str | None = None
        self._install_signal_handlers()
        try:
            if self.handoff_directory is not None:
                self.handoff_directory = validate_approved_handoff_directory(
                    self.handoff_directory
                )
                initial_status = read_cleanup_status(self.handoff_directory)
                if initial_status is None or initial_status["phase"] != "starting":
                    raise FixtureError("The private fixture launch state is invalid.")
                self.channel_ready = True
                self.channel_status = initial_status
                self._update_channel_status(**self.channel_status)
            self._prepare()
            self._publish_handoff()
            self._wait_for_operator()
        except FixtureError as error:
            failure = str(error)
        except (KeyboardInterrupt, StopRequested):
            if self.handoff_published:
                self._say("Stop requested; cleaning up the disposable fixture.")
            else:
                failure = "Fixture setup was interrupted before browser handoff."
        except Exception:
            failure = "An unexpected fixture error occurred; diagnostic details suppressed."
        finally:
            for signal_number in self._old_signal_handlers:
                try:
                    signal.signal(signal_number, signal.SIG_IGN)
                except (ValueError, OSError):
                    pass
            try:
                cleanup_errors = self._cleanup()
            except BaseException:
                cleanup_errors = ["Fixture cleanup encountered an unexpected error."]
                if self.channel_ready:
                    self.cleanup_member_login = "not-verified"
                    self.cleanup_member_accounts = "not-verified"
                    self.cleanup_owned_compose = "not-verified"
                    self.cleanup_owned_images = "not-verified"
                    self.cleanup_private_state = (
                        "retained-for-recovery" if self.state_dir is not None else "not-verified"
                    )
            self._restore_signal_handlers()

        exit_code = 0 if not failure and not cleanup_errors else 1
        if self.channel_ready and self.handoff_directory is not None:
            final_status = {
                "schema_version": 1,
                "phase": "stopped",
                "exit_code": exit_code,
                "member_login": self.cleanup_member_login,
                "member_accounts": self.cleanup_member_accounts,
                "owned_compose": self.cleanup_owned_compose,
                "owned_images": self.cleanup_owned_images,
                "private_state": self.cleanup_private_state,
                "recovery_status": (
                    "pending"
                    if self.control_directory is not None
                    and (self.project_owned or self.state_dir is not None)
                    else "not-needed"
                ),
            }
            try:
                write_cleanup_status(self.handoff_directory, final_status)
                self.channel_status = final_status
            except FixtureError:
                cleanup_errors.append("Sanitized cleanup status could not be written.")
                exit_code = 1

        if failure:
            self._say(f"Fixture failed closed: {failure}")
        for cleanup_error in cleanup_errors:
            self._say(f"Cleanup warning: {cleanup_error}")
        if exit_code == 0:
            self._say("Disposable browser-review fixture stopped cleanly.")
            return 0
        return 1


def _control_directory_path() -> Path:
    return Path("/tmp") / f"{CONTROL_DIRECTORY_PREFIX}{os.geteuid()}"


def _ensure_control_directory() -> Path:
    directory = _control_directory_path()
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError:
        pass
    except OSError:
        raise FixtureError("A private fixture control directory could not be created.") from None
    return _validate_private_directory(directory, approved_directory=directory)


def _open_control_lock(directory: Path) -> int:
    directory_fd = _open_private_directory(directory)
    descriptor = -1
    try:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(CONTROL_LOCK_FILE, flags, 0o600, dir_fd=directory_fd)
        _require_plain_private_file(os.fstat(descriptor))
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FixtureError("A local browser-review fixture is already active.") from None
        return descriptor
    except FixtureError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        raise FixtureError("A private fixture control lock could not be acquired.") from None
    finally:
        os.close(directory_fd)


def _verify_control_lock_descriptor(directory: Path, descriptor: int) -> None:
    directory_fd = _open_private_directory(directory)
    try:
        descriptor_info = os.fstat(descriptor)
        _require_plain_private_file(descriptor_info)
        path_info = os.stat(CONTROL_LOCK_FILE, dir_fd=directory_fd, follow_symlinks=False)
        _require_plain_private_file(path_info)
        if (descriptor_info.st_dev, descriptor_info.st_ino) != (path_info.st_dev, path_info.st_ino):
            raise FixtureError("The detached fixture guardian received the wrong lock file.")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except FixtureError:
        raise
    except (OSError, ValueError):
        raise FixtureError("The detached fixture guardian lost its private control lock.") from None
    finally:
        os.close(directory_fd)


def _validate_recovery_metadata(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"state_dir", "project_name", "owned", "resources_removed"}
        or not isinstance(value["state_dir"], str)
        or not Path(value["state_dir"]).is_absolute()
        or "\0" in value["state_dir"]
        or (value["project_name"] is not None and not isinstance(value["project_name"], str))
        or type(value["owned"]) is not bool
        or type(value["resources_removed"]) is not bool
        or (value["owned"] and value["project_name"] is None)
        or (value["resources_removed"] and not value["owned"])
    ):
        raise FixtureError("The private fixture recovery registration is malformed.")
    project_name = value["project_name"]
    if project_name is not None:
        review_image_reference(project_name, "db")
    return dict(value)


def _write_control_record(directory: Path, record: Mapping[str, Any]) -> None:
    if (
        set(record) not in (
            {"pid", "start_time"},
            {"pid", "start_time", "recovery"},
        )
        or not isinstance(record["pid"], int)
        or isinstance(record["pid"], bool)
        or record["pid"] <= 0
        or not isinstance(record["start_time"], int)
        or isinstance(record["start_time"], bool)
        or record["start_time"] <= 0
    ):
        raise FixtureError("The private fixture process identity is invalid.")
    safe_record = dict(record)
    if "recovery" in safe_record:
        safe_record["recovery"] = _validate_recovery_metadata(safe_record["recovery"])
    _atomic_write_private_json(
        directory,
        CONTROL_FILE,
        safe_record,
        replace_existing=False,
        maximum_bytes=2048,
    )


def _read_control_record(directory: Path) -> dict[str, Any] | None:
    try:
        record = _read_private_json(directory, CONTROL_FILE, maximum_bytes=2048)
    except FileNotFoundError:
        return None
    if (
        not isinstance(record, dict)
        or set(record)
        not in (
            {"pid", "start_time"},
            {"pid", "start_time", "recovery"},
        )
        or not isinstance(record["pid"], int)
        or isinstance(record["pid"], bool)
        or record["pid"] <= 0
        or not isinstance(record["start_time"], int)
        or isinstance(record["start_time"], bool)
        or record["start_time"] <= 0
    ):
        raise FixtureError("The private fixture process identity is malformed.")
    if "recovery" in record:
        record["recovery"] = _validate_recovery_metadata(record["recovery"])
    return record


def update_control_recovery(
    directory: Path,
    *,
    state_dir: Path,
    project_name: str | None,
    owned: bool,
) -> None:
    """Durably register only nonsecret state/ownership data before Compose writes."""
    deadline = time.monotonic() + 5
    record = None
    while time.monotonic() < deadline:
        record = _read_control_record(directory)
        if record is not None and record["pid"] == os.getpid():
            break
        time.sleep(0.05)
    if record is None or record["pid"] != os.getpid():
        raise FixtureError("The private fixture recovery record is unavailable.")
    if record["start_time"] != _proc_start_time(os.getpid()):
        raise FixtureError("The private fixture recovery process identity changed.")
    new_recovery = _validate_recovery_metadata(
        {
            "state_dir": str(state_dir),
            "project_name": project_name,
            "owned": owned,
            "resources_removed": False,
        }
    )
    previous = record.get("recovery")
    if previous is not None:
        if (
            previous["state_dir"] != new_recovery["state_dir"]
            or (
                previous["project_name"] is not None
                and previous["project_name"] != new_recovery["project_name"]
            )
            or (previous["owned"] and not owned)
            or previous["resources_removed"]
        ):
            raise FixtureError("The private fixture recovery registration changed unexpectedly.")
    record["recovery"] = new_recovery
    _atomic_write_private_json(
        directory,
        CONTROL_FILE,
        record,
        replace_existing=True,
        maximum_bytes=2048,
    )


def _update_control_resources_removed(directory: Path, expected_pid: int) -> None:
    record = _read_control_record(directory)
    if record is None or record["pid"] != expected_pid or "recovery" not in record:
        raise FixtureError("The private fixture recovery registration changed unexpectedly.")
    recovery = dict(record["recovery"])
    recovery["resources_removed"] = True
    record["recovery"] = _validate_recovery_metadata(recovery)
    _atomic_write_private_json(
        directory,
        CONTROL_FILE,
        record,
        replace_existing=True,
        maximum_bytes=2048,
    )


def _validate_recovery_state_directory(path: Path) -> Path:
    expected_parent = Path("/tmp").resolve()
    if path.parent != expected_parent or not path.name.startswith("impostr-browser-review-"):
        raise FixtureError("The private fixture recovery path is outside its temporary root.")
    if path.exists():
        _validate_private_directory(path, approved_directory=path)
    return path


def _require_private_recovery_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise FixtureError("The private fixture recovery files are unavailable.") from None
    _require_plain_private_file(info)


def _private_recovery_result(
    *,
    recovery_status: str,
    owned_compose: str,
    owned_images: str,
    private_state: str,
    member_accounts: str,
) -> dict[str, str]:
    return {
        "recovery_status": recovery_status,
        "owned_compose": owned_compose,
        "owned_images": owned_images,
        "private_state": private_state,
        "member_accounts": member_accounts,
    }


def recover_registered_project(control_directory: Path) -> dict[str, str]:
    """Recover only the project registered after its empty-name ownership check."""
    try:
        record = _read_control_record(control_directory)
    except FixtureError:
        return _private_recovery_result(
            recovery_status="failed",
            owned_compose="not-verified",
            owned_images="not-verified",
            private_state="retained-for-recovery",
            member_accounts="not-verified",
        )
    if record is None:
        return _private_recovery_result(
            recovery_status="manual-required",
            owned_compose="not-verified",
            owned_images="not-verified",
            private_state="retained-for-recovery",
            member_accounts="not-verified",
        )
    if "recovery" not in record:
        return _private_recovery_result(
            recovery_status="manual-required",
            owned_compose="not-created",
            owned_images="not-created",
            private_state="not-verified",
            member_accounts="not-created",
        )

    recovery = record["recovery"]
    state_dir = Path(recovery["state_dir"])
    project_name = recovery["project_name"]
    owned = recovery["owned"]
    resources_removed = recovery["resources_removed"]
    member_accounts = "not-verified" if owned else "not-created"
    compose_removed = "removed" if owned and resources_removed else (
        "not-created" if not owned else "not-verified"
    )
    images_removed = "removed" if owned and resources_removed else (
        "not-created" if not owned else "not-verified"
    )
    if state_dir.exists():
        private_state = "retained-for-recovery"
    elif owned and not resources_removed:
        private_state = "not-verified"
    elif owned:
        private_state = "removed"
    else:
        private_state = "not-created"

    try:
        _validate_recovery_state_directory(state_dir)
        if not owned:
            if state_dir.exists():
                shutil.rmtree(state_dir)
            return _private_recovery_result(
                recovery_status="completed",
                owned_compose="not-created",
                owned_images="not-created",
                private_state="removed" if not state_dir.exists() else "not-verified",
                member_accounts="not-created",
            )

        if resources_removed:
            if state_dir.exists():
                shutil.rmtree(state_dir)
            return _private_recovery_result(
                recovery_status="completed",
                owned_compose="removed",
                owned_images="removed",
                private_state="removed" if not state_dir.exists() else "not-verified",
                member_accounts=member_accounts,
            )

        if project_name is None:
            raise FixtureError("The owned fixture project identity is unavailable.")
        source_dir = state_dir / "source"
        env_file = state_dir / "compose.env"
        if not source_dir.is_dir() or source_dir.is_symlink():
            raise FixtureError("The private fixture Compose snapshot is unavailable.")
        _require_private_recovery_file(env_file)
        compose_file = source_dir / "compose.yaml"
        if not compose_file.is_file() or compose_file.is_symlink():
            raise FixtureError("The private fixture Compose snapshot is unavailable.")
        executable = shutil.which("docker")
        if executable is None:
            raise FixtureError("Docker Compose is unavailable for owned fixture recovery.")
        docker = DockerClient(
            executable=executable,
            docker_socket=LOCAL_DOCKER_SOCKET,
            state_dir=state_dir,
        )
        compose = ComposeController(
            docker=docker,
            source_dir=source_dir,
            env_file=env_file,
            project_name=project_name,
        )

        docker.probe_local_engine()
        compose.verify_project_resources_owned()
        compose.down()
        compose.verify_project_resources_removed()
        compose_removed = "removed"
        compose.remove_owned_images()
        compose.verify_project_images_removed()
        images_removed = "removed"
        _update_control_resources_removed(control_directory, record["pid"])
        shutil.rmtree(state_dir)
        private_state = "removed" if not state_dir.exists() else "not-verified"
        if private_state != "removed":
            raise FixtureError("The private fixture recovery state remains.")
        return _private_recovery_result(
            recovery_status="completed",
            owned_compose=compose_removed,
            owned_images=images_removed,
            private_state=private_state,
            member_accounts=member_accounts,
        )
    except (FixtureError, OSError, ValueError):
        return _private_recovery_result(
            recovery_status="failed",
            owned_compose=compose_removed,
            owned_images=images_removed,
            private_state=private_state,
            member_accounts=member_accounts,
        )


def _remove_control_record(directory: Path, expected_pid: int) -> None:
    record = _read_control_record(directory)
    if record is None:
        return
    if record["pid"] != expected_pid:
        raise FixtureError("The private fixture process identity changed unexpectedly.")
    _unlink_private_file(directory, CONTROL_FILE)


def _proc_start_time(pid: int) -> int:
    try:
        stat_line = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        closing_parenthesis = stat_line.rfind(")")
        fields = stat_line[closing_parenthesis + 1 :].split()
        # The suffix starts at field 3 (state); starttime is field 22.
        if closing_parenthesis < 0 or len(fields) <= 19:
            raise ValueError("invalid process stat")
        start_time = int(fields[19])
        if start_time <= 0:
            raise ValueError("invalid process start time")
        return start_time
    except (OSError, UnicodeError, ValueError):
        raise FixtureError("The fixture process identity could not be verified.") from None


def _open_verified_supervisor_pidfd(record: Mapping[str, int]) -> int | None:
    pid = record["pid"]
    expected_start_time = record["start_time"]
    pidfd_open = getattr(os, "pidfd_open", None)
    pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
    if pidfd_open is None or pidfd_send_signal is None:
        raise FixtureError("This host lacks safe process signaling for fixture stop.")
    try:
        descriptor = pidfd_open(pid, 0)
    except ProcessLookupError:
        return None
    except OSError:
        raise FixtureError("The fixture supervisor process could not be opened safely.") from None

    try:
        process_directory = Path(f"/proc/{pid}")
        if process_directory.stat().st_uid != os.geteuid():
            raise FixtureError("The fixture supervisor process owner changed unexpectedly.")
        if _proc_start_time(pid) != expected_start_time:
            raise FixtureError("The fixture supervisor process identity is stale.")
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        arguments = [os.fsdecode(argument) for argument in arguments if argument]
        expected_script = str(Path(__file__).resolve())
        if (
            len(arguments) != 7
            or Path(arguments[1]) != Path(expected_script)
            or arguments[2] != "_supervise"
            or arguments[3] != "--handoff-dir"
            or arguments[4] != str(APPROVED_HANDOFF_DIRECTORY)
            or arguments[5] != "--lifetime-minutes"
            or re.fullmatch(r"[0-9]{1,3}", arguments[6]) is None
            or not MIN_LIFETIME_MINUTES <= int(arguments[6]) <= MAX_LIFETIME_MINUTES
        ):
            raise FixtureError("The fixture stop record does not identify its supervisor.")
        return descriptor
    except (FixtureError, OSError):
        try:
            exited, _, _ = select.select([descriptor], [], [], 0)
        except (OSError, ValueError):
            exited = []
        os.close(descriptor)
        if exited:
            return None
        raise FixtureError("The fixture supervisor process could not be verified.") from None


def _signal_supervisor(record: Mapping[str, int]) -> bool:
    descriptor = _open_verified_supervisor_pidfd(record)
    if descriptor is None:
        return False
    try:
        try:
            signal.pidfd_send_signal(descriptor, signal.SIGTERM, None, 0)
        except ProcessLookupError:
            return False
        except OSError:
            raise FixtureError("The fixture supervisor could not be stopped safely.") from None
        return True
    finally:
        os.close(descriptor)


def _validated_ready_origin(line: bytes) -> str | None:
    match = PTY_READY_LINE.fullmatch(line.rstrip(b"\r"))
    if match is None:
        return None
    try:
        origin = match.group(1).decode("ascii")
        parsed = urlsplit(origin)
        host = parsed.hostname or ""
        address = ipaddress.ip_address(host)
        if (
            parsed.scheme != "http"
            or address.version != 4
            or not address.is_loopback
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
            or parsed.path
            or parsed.query
            or parsed.fragment
            or origin != f"http://{host}:{parsed.port}"
        ):
            return None
        return origin
    except (UnicodeError, ValueError):
        return None


def run_under_pty(
    command: Sequence[str],
    *,
    on_spawn: Callable[[subprocess.Popen[bytes]], None],
    on_ready: Callable[[str], None],
    stop_requested: Callable[[], bool] = lambda: False,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run one child with a real PTY, discard its output, and forward only its URL."""
    master_fd = -1
    slave_fd = -1
    process: subprocess.Popen[bytes] | None = None
    pending = bytearray()
    pty_closed = False
    ready_forwarded = False
    termination_sent = False
    try:
        master_fd, slave_fd = pty.openpty()
        attributes = termios.tcgetattr(slave_fd)
        attributes[3] &= ~(termios.ECHO | termios.ECHONL)
        termios.tcsetattr(slave_fd, termios.TCSANOW, attributes)
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(environment) if environment is not None else None,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)
        slave_fd = -1
        on_spawn(process)

        while process.poll() is None or not pty_closed:
            if stop_requested() and not termination_sent and process.poll() is None:
                process.send_signal(signal.SIGTERM)
                termination_sent = True
            if pty_closed:
                time.sleep(0.2)
                continue
            readable, _, _ = select.select([master_fd], [], [], 0.2)
            if not readable:
                continue
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                pty_closed = True
                continue
            pending.extend(chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
            while b"\n" in pending:
                line, _, remainder = pending.partition(b"\n")
                pending[:] = remainder
                if not ready_forwarded:
                    origin = _validated_ready_origin(line)
                    if origin is not None:
                        on_ready(origin)
                        ready_forwarded = True
            if len(pending) > MAX_PTY_LINE_BYTES:
                pending.clear()

        return process.wait()
    except BaseException:
        if process is not None and process.poll() is None:
            try:
                process.send_signal(signal.SIGTERM)
            except OSError:
                pass
            try:
                process.wait()
            except subprocess.SubprocessError:
                pass
        raise
    finally:
        if slave_fd >= 0:
            os.close(slave_fd)
        if master_fd >= 0:
            os.close(master_fd)
        pending.clear()


def _safe_runner_environment(control_directory: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(control_directory),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _write_guardian_message(payload: Mapping[str, str]) -> None:
    message = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    try:
        sys.stdout.write(message + "\n")
        sys.stdout.flush()
        sys.stdout.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


def _remove_unexpected_member_handoff(directory: Path) -> str:
    try:
        payload = _read_private_json(
            directory,
            MEMBER_HANDOFF_FILE,
            maximum_bytes=MAX_CHANNEL_JSON_BYTES,
        )
    except FileNotFoundError:
        return "not-created"
    if not _valid_member_login(payload):
        return "not-verified"
    try:
        return (
            "removed"
            if _unlink_private_file(directory, MEMBER_HANDOFF_FILE)
            else "not-verified"
        )
    except FixtureError:
        return "not-verified"


def _write_guardian_failure_status(
    directory: Path,
    *,
    control_directory: Path | None = None,
) -> bool:
    """Recover the registered project before recording an abrupt exit as final."""
    if control_directory is None:
        recovery_result = _private_recovery_result(
            recovery_status="failed",
            owned_compose="not-verified",
            owned_images="not-verified",
            private_state="retained-for-recovery",
            member_accounts="not-verified",
        )
    else:
        recovery_result = recover_registered_project(control_directory)
    try:
        current = read_cleanup_status(directory)
        current_login = current["member_login"] if current is not None else "not-created"
        discovered_login = _remove_unexpected_member_handoff(directory)
        if discovered_login == "not-created" and current_login in {"published", "removed"}:
            member_login = "removed"
        elif discovered_login == "not-created" and current_login == "not-verified":
            member_login = "not-verified"
        else:
            member_login = discovered_login
        member_accounts = recovery_result["member_accounts"]
        if current is not None and current["member_accounts"] in {
            "verified",
            "not-created",
            "not-applicable",
        }:
            member_accounts = current["member_accounts"]
        status = {
            "schema_version": 1,
            "phase": "stopped",
            "exit_code": 1,
            "member_login": member_login,
            "member_accounts": member_accounts,
            "owned_compose": recovery_result["owned_compose"],
            "owned_images": recovery_result["owned_images"],
            "private_state": recovery_result["private_state"],
            "recovery_status": recovery_result["recovery_status"],
        }
        write_cleanup_status(directory, status)
        return _clean_previous_run(status)
    except FixtureError:
        # Inaccessible state is retained; never report an optimistic teardown.
        return False


def _run_guardian(handoff_directory: Path, lifetime_minutes: int, lock_fd: int) -> int:
    control_directory = _ensure_control_directory()
    _verify_control_lock_descriptor(control_directory, lock_fd)

    try:
        validate_approved_handoff_directory(handoff_directory)
        status = read_cleanup_status(handoff_directory)
        if status is None or status["phase"] != "starting":
            raise FixtureError("The private fixture launch state is invalid.")
    except FixtureError:
        _write_guardian_message({"event": "failed"})
        os.close(lock_fd)
        return 1

    child_record: dict[str, int] | None = None
    stop_flag = False
    old_handlers: dict[int, Any] = {}

    def stop_handler(_signum, _frame) -> None:
        nonlocal stop_flag
        stop_flag = True

    for signal_number in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)):
        try:
            old_handlers[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, stop_handler)
        except (ValueError, OSError):
            continue

    ready_sent = False
    result = 1
    try:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "_supervise",
            "--handoff-dir",
            str(handoff_directory),
            "--lifetime-minutes",
            str(lifetime_minutes),
        ]

        def remember_child(process: subprocess.Popen[bytes]) -> None:
            nonlocal child_record
            child_record = {"pid": process.pid, "start_time": _proc_start_time(process.pid)}
            _write_control_record(control_directory, child_record)

        def publish_ready(origin: str) -> None:
            nonlocal ready_sent
            _write_guardian_message({"event": "ready", "origin": origin})
            ready_sent = True

        result = run_under_pty(
            command,
            on_spawn=remember_child,
            on_ready=publish_ready,
            stop_requested=lambda: stop_flag,
            cwd=Path(__file__).resolve().parent.parent,
            environment=_safe_runner_environment(control_directory),
        )
    except BaseException:
        result = 1
        if not ready_sent:
            _write_guardian_message({"event": "failed"})
    finally:
        for signal_number, handler in old_handlers.items():
            try:
                signal.signal(signal_number, handler)
            except (ValueError, OSError):
                pass
        try:
            status = read_cleanup_status(handoff_directory)
        except FixtureError:
            status = None
        cleanup_verified = _clean_previous_run(status)
        if not cleanup_verified:
            cleanup_verified = _write_guardian_failure_status(
                handoff_directory,
                control_directory=control_directory,
            )
        if child_record is not None and cleanup_verified:
            try:
                _remove_control_record(control_directory, child_record["pid"])
            except FixtureError:
                pass
        os.close(lock_fd)
    return result


def _parse_guardian_message(message: bytes) -> dict[str, str] | None:
    if len(message) > 4096 or not message.endswith(b"\n"):
        return None
    try:
        payload = json.loads(message.decode("ascii"), object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("event"), str)
        or payload["event"] not in {"ready", "failed"}
    ):
        return None
    if payload["event"] == "failed":
        return payload if set(payload) == {"event"} else None
    origin = payload.get("origin")
    if (
        set(payload) != {"event", "origin"}
        or not isinstance(origin, str)
        or _validated_ready_origin(f"FIXTURE_HANDOFF_READY {origin}".encode("ascii", "ignore"))
        != origin
    ):
        return None
    return payload


def _read_guardian_message(
    process: subprocess.Popen[bytes],
    *,
    timeout: int,
) -> dict[str, str] | None:
    if process.stdout is None:
        return None
    descriptor = process.stdout.fileno()
    deadline = time.monotonic() + timeout
    pending = bytearray()
    while time.monotonic() < deadline:
        readable, _, _ = select.select([descriptor], [], [], 0.2)
        if not readable:
            if process.poll() is not None:
                return None
            continue
        chunk = os.read(descriptor, 4096)
        if not chunk:
            return None
        pending.extend(chunk)
        if len(pending) > 4096:
            return None
        if b"\n" in pending:
            line, _, _ = pending.partition(b"\n")
            return _parse_guardian_message(line + b"\n")
    return None


def _clean_previous_run(status: Mapping[str, Any] | None) -> bool:
    """Report verified teardown, independently of whether setup/review succeeded."""
    if status is None:
        return False
    return (
        status["phase"] == "stopped"
        and status["member_login"] in {"not-created", "removed"}
        and status["owned_compose"] in {"not-created", "removed"}
        and status["owned_images"] in {"not-created", "removed"}
        and status["private_state"] in {"not-created", "removed"}
        and status["recovery_status"] in {"not-needed", "completed"}
    )


def launch_unattended(handoff_directory: Path, lifetime_minutes: int) -> int:
    """Launch a detached supervisor under a guardian-held PTY and report its URL."""
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        print("This host cannot safely signal the unattended fixture.", file=sys.stderr)
        return 1
    control_directory = _ensure_control_directory()
    lock_fd = _open_control_lock(control_directory)
    guardian: subprocess.Popen[bytes] | None = None
    try:
        validate_approved_handoff_directory(handoff_directory)
        previous_status = read_cleanup_status(handoff_directory)
        prepare_handoff_channel(
            handoff_directory,
            approved_directory=APPROVED_HANDOFF_DIRECTORY,
        )
        prior_control = _read_control_record(control_directory)
        if prior_control is not None:
            if not _clean_previous_run(previous_status):
                raise FixtureError("A prior fixture process has unverified cleanup.")
            _remove_control_record(control_directory, prior_control["pid"])

        write_cleanup_status(handoff_directory, initial_cleanup_status())
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "_guardian",
            "--handoff-dir",
            str(handoff_directory),
            "--lifetime-minutes",
            str(lifetime_minutes),
            "--lock-fd",
            str(lock_fd),
        ]
        try:
            guardian = subprocess.Popen(
                command,
                cwd=Path(__file__).resolve().parent.parent,
                env=_safe_runner_environment(control_directory),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=(lock_fd,),
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError):
            failed_status = initial_cleanup_status()
            failed_status.update(phase="stopped", exit_code=1)
            try:
                write_cleanup_status(handoff_directory, failed_status)
            except FixtureError:
                pass
            raise FixtureError("The private fixture guardian could not be started.") from None

        event = _read_guardian_message(guardian, timeout=STARTUP_TIMEOUT_SECONDS)
        if event is None:
            try:
                guardian.send_signal(signal.SIGTERM)
            except OSError:
                pass
            print(
                "Fixture startup did not produce a safe browser handoff; "
                "read the sanitized cleanup status.",
                file=sys.stderr,
            )
            return 1
        if event["event"] != "ready":
            print(
                "Fixture setup failed closed; read the sanitized cleanup status.",
                file=sys.stderr,
            )
            return 1
        assert guardian.stdout is not None
        guardian.stdout.close()
        print(f"BROWSER_REVIEW_URL={event['origin']}/")
        print(f"Read the generated Member login: {handoff_directory / MEMBER_HANDOFF_FILE}")
        print(
            "Use the normal sign-in form, then leave the same authenticated page open "
            "for the rendered review."
        )
        print("After the rendered review, run: python3 scripts/local_browser_fixture.py stop")
        print(f"Then read sanitized cleanup status: {handoff_directory / CLEANUP_STATUS_FILE}")
        return 0
    except FixtureError as error:
        print(f"Fixture launcher stopped safely: {error}", file=sys.stderr)
        return 1
    finally:
        if guardian is not None and guardian.stdout is not None:
            guardian.stdout.close()
        os.close(lock_fd)


def _attempt_unattended_recovery(handoff_directory: Path) -> int | None:
    """Run recovery only after the supervisor exited and its guardian lock is free."""
    control_directory = _ensure_control_directory()
    try:
        lock_fd = _open_control_lock(control_directory)
    except FixtureError as error:
        if "already active" in str(error):
            return None
        return 1
    try:
        record = _read_control_record(control_directory)
        if record is not None:
            process_fd = _open_verified_supervisor_pidfd(record)
            if process_fd is not None:
                os.close(process_fd)
                return None
        status = read_cleanup_status(handoff_directory)
        if _clean_previous_run(status):
            if record is not None:
                _remove_control_record(control_directory, record["pid"])
            return 0
        cleanup_verified = _write_guardian_failure_status(
            handoff_directory,
            control_directory=control_directory,
        )
        status = read_cleanup_status(handoff_directory)
        if cleanup_verified and _clean_previous_run(status):
            if record is not None:
                _remove_control_record(control_directory, record["pid"])
            return 0
        return 1
    except FixtureError:
        return 1
    finally:
        os.close(lock_fd)


def _finish_clean_run(control_directory: Path, status: Mapping[str, Any] | None) -> bool | None:
    if not _clean_previous_run(status):
        return False
    try:
        lock_fd = _open_control_lock(control_directory)
    except FixtureError as error:
        if "already active" in str(error):
            return None
        raise
    try:
        record = _read_control_record(control_directory)
        if record is not None:
            _remove_control_record(control_directory, record["pid"])
        return True
    finally:
        os.close(lock_fd)


def _stop_exit_code(status: Mapping[str, Any] | None) -> int:
    # A recovered SIGKILL or failed setup can leave no resources behind, but it
    # must not look like a successful browser-review run to the caller of stop.
    if status is not None and status["exit_code"] == 0:
        return 0
    print(
        "Fixture setup or review failed; owned cleanup was verified, but stop cannot "
        "report a successful review.",
        file=sys.stderr,
    )
    return 1


def _print_recovery_action(handoff_directory: Path | None = None) -> None:
    try:
        status = read_cleanup_status(handoff_directory) if handoff_directory is not None else None
    except FixtureError:
        status = None
    if status is not None and status["recovery_status"] == "manual-required":
        print(
            "The fixture has no verifiable owned-project recovery registration. Do not run broad "
            "Docker teardown; preserve this run's private state and request operator-assisted "
            "recovery.",
            file=sys.stderr,
        )
        return
    print(
        "Owned fixture teardown is still unverified. Preserve this run's private recovery state; "
        "after the local Docker engine recovers, retry `python3 scripts/local_browser_fixture.py "
        "recover`. Do not remove resources from another project.",
        file=sys.stderr,
    )


def recover_unattended(handoff_directory: Path) -> int:
    """Retry ownership-verified cleanup for a stopped unattended fixture."""
    try:
        validate_approved_handoff_directory(handoff_directory)
        outcome = _attempt_unattended_recovery(handoff_directory)
        if outcome is None:
            print(
                "The fixture supervisor or guardian is still active; use `stop` first.",
                file=sys.stderr,
            )
            return 1
        if outcome != 0:
            _print_recovery_action(handoff_directory)
        return outcome
    except FixtureError as error:
        print(f"Fixture recovery failed safely: {error}", file=sys.stderr)
        _print_recovery_action(handoff_directory)
        return 1


def stop_unattended(handoff_directory: Path, *, timeout: int = CLEANUP_WAIT_SECONDS) -> int:
    """Stop this supervisor, then recover only its registered owned project if needed."""
    try:
        validate_approved_handoff_directory(handoff_directory)
        control_directory = _ensure_control_directory()
        status = read_cleanup_status(handoff_directory)
        finished = _finish_clean_run(control_directory, status)
        if finished:
            return _stop_exit_code(status)
        if finished is None:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(0.2)
                status = read_cleanup_status(handoff_directory)
                finished = _finish_clean_run(control_directory, status)
                if finished:
                    return _stop_exit_code(status)
            print("The fixture guardian did not release its control lock.", file=sys.stderr)
            return 1
        record = _read_control_record(control_directory)
        if record is None:
            outcome = _attempt_unattended_recovery(handoff_directory)
            if outcome == 0:
                return _stop_exit_code(read_cleanup_status(handoff_directory))
            _print_recovery_action(handoff_directory)
            return 1

        signaled = _signal_supervisor(record)
        deadline = time.monotonic() + timeout
        next_dead_process_check = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(0.2)
            status = read_cleanup_status(handoff_directory)
            finished = _finish_clean_run(control_directory, status)
            if finished:
                return _stop_exit_code(status)
            if status is not None and status["phase"] == "stopped":
                outcome = _attempt_unattended_recovery(handoff_directory)
                if outcome == 0:
                    return _stop_exit_code(read_cleanup_status(handoff_directory))
                if outcome == 1:
                    _print_recovery_action(handoff_directory)
                    return 1

            now = time.monotonic()
            if not signaled or now >= next_dead_process_check:
                next_dead_process_check = now + 1.0
                process_fd = _open_verified_supervisor_pidfd(record)
                if process_fd is None:
                    outcome = _attempt_unattended_recovery(handoff_directory)
                    if outcome == 0:
                        return _stop_exit_code(read_cleanup_status(handoff_directory))
                    if outcome == 1:
                        _print_recovery_action(handoff_directory)
                        return 1
                else:
                    os.close(process_fd)

        print(
            "Fixture cleanup did not reach a verified final status before timeout.",
            file=sys.stderr,
        )
        _print_recovery_action(handoff_directory)
        return 1
    except FixtureError as error:
        print(f"Fixture stop failed safely: {error}", file=sys.stderr)
        _print_recovery_action(handoff_directory)
        return 1


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a disposable authenticated local browser-review fixture from committed HEAD."
        ),
        epilog=(
            "The unattended launcher stores only one generated Member login and a sanitized "
            "cleanup status in the owner-approved private handoff channel."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="build, hand off, supervise, and clean the fixture")
    start.add_argument(
        "--lifetime-minutes",
        type=int,
        default=DEFAULT_LIFETIME_MINUTES,
        help=(
            f"automatic teardown limit ({MIN_LIFETIME_MINUTES}-{MAX_LIFETIME_MINUTES}, "
            f"default {DEFAULT_LIFETIME_MINUTES})"
        ),
    )
    start.add_argument(
        "--docker-socket",
        default=LOCAL_DOCKER_SOCKET,
        help="path to the local Unix Docker socket (TCP/remote engines are not accepted)",
    )
    launch = subparsers.add_parser(
        "launch",
        help="start the detached PTY supervisor and publish a private Member handoff",
    )
    launch.add_argument(
        "--handoff-dir",
        type=Path,
        default=APPROVED_HANDOFF_DIRECTORY,
        help="the owner-approved private coordinator-readable handoff directory",
    )
    launch.add_argument(
        "--lifetime-minutes",
        type=int,
        default=DEFAULT_LIFETIME_MINUTES,
        help=(
            f"automatic teardown limit ({MIN_LIFETIME_MINUTES}-{MAX_LIFETIME_MINUTES}, "
            f"default {DEFAULT_LIFETIME_MINUTES})"
        ),
    )
    stop = subparsers.add_parser(
        "stop",
        help="stop the recorded local fixture and wait for verified cleanup status",
    )
    stop.add_argument(
        "--handoff-dir",
        type=Path,
        default=APPROVED_HANDOFF_DIRECTORY,
        help="the owner-approved private coordinator-readable handoff directory",
    )
    recover = subparsers.add_parser(
        "recover",
        help="retry teardown for this fixture's ownership-verified project only",
    )
    recover.add_argument(
        "--handoff-dir",
        type=Path,
        default=APPROVED_HANDOFF_DIRECTORY,
        help="the owner-approved private coordinator-readable handoff directory",
    )

    guardian = subparsers.add_parser("_guardian", help="internal PTY guardian process")
    guardian.add_argument("--handoff-dir", type=Path, required=True)
    guardian.add_argument("--lifetime-minutes", type=int, required=True)
    guardian.add_argument("--lock-fd", type=int, required=True)

    supervise = subparsers.add_parser("_supervise", help="internal fixture supervisor process")
    supervise.add_argument("--handoff-dir", type=Path, required=True)
    supervise.add_argument("--lifetime-minutes", type=int, required=True)

    parsed = parser.parse_args(arguments)
    if parsed.command in {"start", "launch", "_guardian", "_supervise"} and not (
        MIN_LIFETIME_MINUTES <= parsed.lifetime_minutes <= MAX_LIFETIME_MINUTES
    ):
        parser.error(
            f"--lifetime-minutes must be between {MIN_LIFETIME_MINUTES} and {MAX_LIFETIME_MINUTES}"
        )
    if parsed.command == "start" and not Path(parsed.docker_socket).is_absolute():
        parser.error("--docker-socket must be an absolute path to a local Unix socket")
    return parsed


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _parse_args(arguments)
    root = Path(__file__).resolve().parent.parent
    previous_umask = os.umask(0o077)
    try:
        if parsed.command == "launch":
            return launch_unattended(parsed.handoff_dir, parsed.lifetime_minutes)
        if parsed.command == "stop":
            return stop_unattended(parsed.handoff_dir)
        if parsed.command == "recover":
            return recover_unattended(parsed.handoff_dir)
        if parsed.command == "_guardian":
            return _run_guardian(
                parsed.handoff_dir,
                parsed.lifetime_minutes,
                parsed.lock_fd,
            )
        if parsed.command == "_supervise":
            supervisor = FixtureSupervisor(
                root,
                lifetime_minutes=parsed.lifetime_minutes,
                handoff_directory=parsed.handoff_dir,
                control_directory=_ensure_control_directory(),
            )
            return supervisor.run()
        supervisor = FixtureSupervisor(
            root,
            docker_socket=parsed.docker_socket,
            lifetime_minutes=parsed.lifetime_minutes,
        )
        return supervisor.run()
    except FixtureError as error:
        if parsed.command == "_guardian":
            _write_guardian_message({"event": "failed"})
        else:
            print(f"Fixture stopped safely: {error}", file=sys.stderr)
        return 1
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
