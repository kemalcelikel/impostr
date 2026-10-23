"""HUMAN ONLY local PostgreSQL backup/restore, using the existing Compose DB.

Stop the source API/frontdoor AND the human planning connection before backup.
Restore ONLY an operator-trusted own archive: PostgreSQL restoration executes SQL.
Use a different, fresh Compose project and explicit private target dotenv. Only DB
may be started; this helper never stops/destroys stacks, starts apps, or uses --clean.
Recreate API/workspace caches after restoration. Old backups can resurrect deleted
PDFs, accounts and revoked sessions; scratch/channels/native processes are not backed up.

64 GiB archive / 1800 second PostgreSQL limits are engineering safeguards, not product
quotas. No host PostgreSQL, ambient Docker settings, auth discovery or secret output.
The explicit dotenv is passed to Compose, never parsed or copied by this helper.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import re
import secrets
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DOCKER = "/usr/bin/docker"
MAX_ARCHIVE = 64 * 1024**3
PG_SECONDS = 1800
CHUNK = 64 * 1024
MAGIC = b"PGDMP"


class Refused(Exception):
    """Only fixed public messages; never wrap private subprocess/OS exceptions."""


def require(value, message="Local data operation refused."):
    if not value:
        raise Refused(message)


def project_name(value):
    require(re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", value) is not None,
            "Use a lowercase Compose project identifier (1–63 characters).")
    return value


def identity(info):
    return info.st_dev, info.st_ino, info.st_uid, info.st_mode


class PrivatePath:
    """Pin every ancestor without following links; final parent is private 0700.

    Root-owned sticky /tmp is allowed as an ancestor. Other ancestors must be
    root/operator owned and not writable by another identity. No permission repair.
    Operations on archive names use the held parent directory, not path traversal.
    """

    def __init__(self, value):
        self.path = Path(value)
        self.fds = []
        self.fd = None
        require(self.path.is_absolute() and str(self.path) == value
                and ".." not in self.path.parts and self.path.name not in {"", "."},
                "Use an explicit absolute, normalized private file path.")
        try:
            fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.fds.append((Path("/"), fd))
            for part in self.path.parent.parts[1:]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=fd)
                parent = self.fds[-1][0] / part
                self.fds.append((parent, fd))
                info = os.fstat(fd)
                sticky_tmp = (parent == Path("/tmp") and info.st_uid == 0
                              and bool(info.st_mode & stat.S_ISVTX))
                require(info.st_uid in {0, os.getuid()}
                        and (not info.st_mode & 0o022 or sticky_tmp),
                        "Private path has an unsafe ancestor.")
            self.parent_fd = fd
            info = os.fstat(fd)
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                    "Existing private parent must be operator-owned mode 0700.")
        except BaseException:
            self.close()
            raise

    def check(self):
        for path, fd in self.fds:
            require(identity(path.lstat()) == identity(os.fstat(fd)),
                    "Private path changed during operation.")
        if self.fd is not None:
            held = os.fstat(self.fd)
            current = os.stat(self.path.name, dir_fd=self.parent_fd, follow_symlinks=False)
            require(identity(current) == identity(held) and held.st_nlink == 1
                    and stat.S_ISREG(held.st_mode) and held.st_uid == os.getuid()
                    and stat.S_IMODE(held.st_mode) == 0o600,
                    "Private input changed during operation.")
            require((held.st_size, held.st_mtime_ns, held.st_ctime_ns) == self.version,
                    "Private input changed during operation.")

    def open_input(self, *, archive=False):
        self.fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                          dir_fd=self.parent_fd)
        info = os.fstat(self.fd)
        self.version = info.st_size, info.st_mtime_ns, info.st_ctime_ns
        self.check()
        require(0 < info.st_size <= (MAX_ARCHIVE if archive else 64 * 1024),
                "Private input size is outside the engineering bound.")
        if archive:
            require(os.pread(self.fd, len(MAGIC), 0) == MAGIC,
                    "Input is not a PostgreSQL custom archive.")
        return self

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        for _, fd in reversed(self.fds):
            os.close(fd)
        self.fds.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class ArchiveOutput:
    """Exclusive partial inode; atomic link publication never overwrites a name."""

    def __init__(self, path):
        self.path = path
        self.fd = None
        self.size = 0
        self.partial = ".local-data-" + secrets.token_hex(16) + ".partial"
        path.check()
        try:
            os.stat(path.path.name, dir_fd=path.parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise Refused("Backup output must be a new, absent file.")
        self.fd = os.open(self.partial, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=path.parent_fd)
        os.fchmod(self.fd, 0o600)  # Our newly created inode only; independent of umask.

    def write(self, block):
        self.size += len(block)
        require(self.size <= MAX_ARCHIVE, "Backup exceeded the engineering size bound.")
        view = memoryview(block)
        while view:
            written = os.write(self.fd, view)
            require(written > 0)
            view = view[written:]

    def owned_partial(self):
        current = os.stat(self.partial, dir_fd=self.path.parent_fd, follow_symlinks=False)
        held = os.fstat(self.fd)
        require(identity(current) == identity(held) and held.st_nlink == 1
                and held.st_uid == os.getuid() and stat.S_IMODE(held.st_mode) == 0o600,
                "Backup partial changed during operation.")

    def publish(self):
        self.path.check()
        self.owned_partial()
        require(self.size >= len(MAGIC) and os.pread(self.fd, len(MAGIC), 0) == MAGIC,
                "DB did not produce a PostgreSQL custom archive.")
        os.fsync(self.fd)
        os.link(self.partial, self.path.path.name, src_dir_fd=self.path.parent_fd,
                dst_dir_fd=self.path.parent_fd, follow_symlinks=False)
        # The temporary second link exists only during no-overwrite publication.
        os.unlink(self.partial, dir_fd=self.path.parent_fd)
        os.fsync(self.path.parent_fd)

    def close(self):
        if self.fd is not None:
            try:
                try:
                    self.owned_partial()
                except FileNotFoundError:
                    pass  # Already published.
                else:
                    os.unlink(self.partial, dir_fd=self.path.parent_fd)
            finally:
                os.close(self.fd)
                self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def run_child(args, environment, *, receive=None, source=None, seconds=30,
              failure_message="Docker/PostgreSQL operation failed; private diagnostics suppressed."):
    """Bounded binary pipes; discard stderr, expose only fixed failure categories.

    Kill/wait only this owned CLI process group on failure, never a target service.
    Container timeout separately bounds the owned PostgreSQL invocation.
    """
    process = subprocess.Popen(args, cwd=ROOT, env=environment, start_new_session=True,
                               stdin=subprocess.PIPE if source else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    collected = bytearray()
    output_size = error_size = sent = 0
    pending = b""
    deadline = time.monotonic() + seconds
    try:
        with selectors.DefaultSelector() as selector:
            for pipe in (process.stdout, process.stderr):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ)
            if source:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE)
            while selector.get_map():
                require(time.monotonic() < deadline, "Local data subprocess timed out.")
                for key, _ in selector.select(0.1):
                    pipe = key.fileobj
                    if pipe is process.stdin:
                        if not pending and sent < source.version[0]:
                            pending = os.read(source.fd, min(CHUNK, source.version[0] - sent))
                            require(pending, "Archive ended before its held size.")
                        if pending:
                            try:
                                count = os.write(pipe.fileno(), pending)
                            except BrokenPipeError:
                                # PostgreSQL may reject an archive before consuming
                                # stdin. Drain its bounded pipes and collect the real
                                # exit status instead of losing it to a host pipe error.
                                selector.unregister(pipe)
                                pipe.close()
                                continue
                            pending = pending[count:]
                            sent += count
                        else:
                            source.check()
                            selector.unregister(pipe)
                            pipe.close()
                        continue
                    block = os.read(pipe.fileno(), CHUNK)
                    if not block:
                        selector.unregister(pipe)
                    elif pipe is process.stderr:
                        error_size += len(block)
                        require(error_size <= 1024 * 1024, "Subprocess diagnostics exceeded bound.")
                    else:
                        output_size += len(block)
                        if receive:
                            receive(block)
                        else:
                            require(output_size <= 64 * 1024, "Subprocess output exceeded bound.")
                            collected.extend(block)
            status = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            require(status == 0, failure_message)
            if source:
                source.check()
                require(sent == source.version[0], "Archive transport was incomplete.")
            return bytes(collected)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()


# Variables expand only INSIDE the existing DB container, never into host argv.
# Local initdb trust socket; clean libpq environment avoids password/config discovery.
PG_ENV = "env -i PATH=/usr/bin:/bin PGCONNECT_TIMEOUT=10 PGPASSFILE=/dev/null "
# libpq interprets a dbname containing '=' or a URI as connection settings that
# override --host. Check only inside the container; never retrieve these values.
PG_GUARD = 'case "$POSTGRES_DB" in ""|*[!a-zA-Z0-9_-]*) exit 1;; esac; '
PG_CONNECTION = ('--host=/var/run/postgresql --port=5432 --no-password '
                 '--username="$POSTGRES_USER" --dbname="$POSTGRES_DB"')
DUMP = (PG_GUARD + f'exec timeout --signal=TERM --kill-after=5s {PG_SECONDS}s ' + PG_ENV
        + 'pg_dump --format=custom ' + PG_CONNECTION)
RESTORE = (PG_GUARD + f'exec timeout --signal=TERM --kill-after=5s {PG_SECONDS}s ' + PG_ENV
           + 'pg_restore --exit-on-error --single-transaction --no-owner --no-privileges '
           + '--no-comments --role="$IMPOSTR_APP_DB_USER" ' + PG_CONNECTION)
FRESH = (PG_GUARD + PG_ENV + 'IMPOSTR_APP_DB_USER="$IMPOSTR_APP_DB_USER" '
         + 'psql -X -qAt --set=ON_ERROR_STOP=1 ' + PG_CONNECTION + " <<'SQL'\n" + r"""
\getenv app_role IMPOSTR_APP_DB_USER
SELECT CASE WHEN
  NOT EXISTS (SELECT 1 FROM pg_depend d JOIN pg_namespace n ON n.oid=d.refobjid
              WHERE d.refclassid='pg_namespace'::regclass AND n.nspname='public')
  AND NOT EXISTS (SELECT 1 FROM pg_namespace
                  WHERE nspname <> 'public' AND nspname <> 'information_schema'
                    AND nspname NOT LIKE 'pg\_%')
  AND NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname <> 'plpgsql')
  AND NOT EXISTS (SELECT 1 FROM pg_largeobject_metadata)
  AND NOT EXISTS (SELECT 1 FROM pg_default_acl)
  AND NOT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database()
                  AND pid<>pg_backend_pid() AND backend_type='client backend')
  AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:'app_role' AND NOT rolsuper
               AND rolname<>current_user)
  AND has_schema_privilege(:'app_role', 'public', 'USAGE')
  AND has_schema_privilege(:'app_role', 'public', 'CREATE')
THEN 'fresh' ELSE 'not-fresh' END;
SQL
""")


class LocalDB:
    def __init__(self, project, dotenv, config):
        self.project = project_name(project)
        self.dotenv = dotenv
        self.environment = {"PATH": "/usr/bin:/bin", "HOME": str(config),
                            "DOCKER_CONFIG": str(config), "DOCKER_HOST": "unix:///var/run/docker.sock",
                            "COMPOSE_DISABLE_ENV_FILE": "1"}
        self.docker = [DOCKER, "--config", str(config), "--host", "unix:///var/run/docker.sock"]
        self.compose = self.docker + ["compose", "--project-directory", str(ROOT),
                                     "--env-file", str(dotenv.path), "-p", self.project,
                                     "-f", str(ROOT / "compose.yaml")]

    def run(self, args, **kwargs):
        self.dotenv.check()
        result = run_child(args, self.environment, **kwargs)
        self.dotenv.check()
        return result

    def quiescent(self, *, backup=False):
        services = self.run(self.docker + ["ps", "--filter",
                            "label=com.docker.compose.project=" + self.project,
                            "--format", '{{.Label "com.docker.compose.service"}}']).splitlines()
        require(all(service == b"db" for service in services),
                "Stop all non-DB services in this project and the human planning connection first.")
        if backup:
            require(services == [b"db"], "Backup requires exactly one running source DB.")

    def pg(self, command, **kwargs):
        if command == FRESH:
            kwargs["failure_message"] = "Restore freshness query failed; private diagnostics suppressed."
        elif command == RESTORE:
            kwargs["failure_message"] = "Restore PostgreSQL transaction failed; private diagnostics suppressed."
        return self.run(self.compose + ["exec", "-T", "db", "sh", "-ec", command], **kwargs)

    def backup(self, output):
        self.quiescent(backup=True)
        with ArchiveOutput(output) as archive:
            self.pg(DUMP, receive=archive.write, seconds=PG_SECONDS + 30)
            self.quiescent(backup=True)
            archive.publish()

    def restore(self, archive):
        self.quiescent()
        self.run(self.compose + ["up", "-d", "--no-deps", "--no-build", "--no-recreate", "--pull", "never",
                                  "--wait", "--wait-timeout", "120", "db"], seconds=150)
        self.quiescent(backup=True)
        require(self.pg(FRESH).strip() == b"fresh",
                "Restore requires a fresh empty DB, initialized app role, and no other DB clients.")
        self.pg(RESTORE, source=archive, seconds=PG_SECONDS + 30)
        self.quiescent(backup=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, option in (("backup", "--output"), ("restore", "--input")):
        command = commands.add_parser(name)
        command.add_argument("--project", required=True)
        command.add_argument("--env-file", required=True)
        command.add_argument(option, required=True)
    args = parser.parse_args(argv)
    try:
        require(os.getuid() == os.geteuid() and os.getgid() == os.getegid(),
                "Do not run this helper setuid/setgid.")
        project_name(args.project)
        with ExitStack() as stack:
            dotenv = stack.enter_context(PrivatePath(args.env_file)).open_input()
            path = stack.enter_context(PrivatePath(args.output if args.command == "backup" else args.input))
            if args.command == "restore":
                path.open_input(archive=True)
            config = stack.enter_context(tempfile.TemporaryDirectory(prefix="impostr-local-data-", dir="/tmp"))
            db = LocalDB(args.project, dotenv, config)
            if args.command == "backup":
                db.backup(path)
            else:
                db.restore(path)
        print("Backup published." if args.command == "backup" else
              "Restore completed. Keep apps stopped until manual migration/cache recovery.")
        return 0
    except Refused as error:
        print(str(error), file=sys.stderr)
    except KeyboardInterrupt:
        print("Local data operation interrupted; no readiness is claimed.", file=sys.stderr)
    except Exception:
        print("Local data operation failed; private diagnostics suppressed. No readiness is claimed.",
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(main())
