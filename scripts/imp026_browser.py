"""Owned EOF/lifetime guardian for the native IMP-026 browser fixture.

Runs only from the reviewed frozen candidate. Ordinary OwnedRuntime/Connection
is retained; only PlanningHTTPSInference's connection callable is synthetic.
No network/provider connection, Docker access, or credential source is present.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import sys
import threading
import time


PARENT = Path("/tmp/opencode")
REVIEW_PARENT = PARENT
DIRECTORY_RE = re.compile(r"impostr-browser-chat-[0-9a-f]{20}")


def _require(value: bool) -> None:
    if not value:
        raise RuntimeError("fixture unavailable")


def _create_review_file(parent_fd: int, fingerprint: str, content: bytes):
    name = "impostr-imp026-review-" + fingerprint[:20]
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    directory_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    directory_fd = -1
    file_fd = -1
    try:
        directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        info = os.fstat(directory_fd)
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == info.st_gid == 1000
                 and stat.S_IMODE(info.st_mode) == 0o700
                 and (info.st_dev, info.st_ino) == (directory_info.st_dev, directory_info.st_ino))
        file_fd = os.open("native-review.pdf", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o644, dir_fd=directory_fd)
        os.fchmod(file_fd, 0o644)
        remaining = memoryview(content)
        while remaining:
            written = os.write(file_fd, remaining)
            _require(written > 0)
            remaining = remaining[written:]
        os.fsync(file_fd)
        file_info = os.fstat(file_fd)
        _require(stat.S_ISREG(file_info.st_mode) and file_info.st_uid == file_info.st_gid == 1000
                 and file_info.st_nlink == 1 and stat.S_IMODE(file_info.st_mode) == 0o644
                 and file_info.st_size == len(content))
        os.fsync(directory_fd)
        return name, directory_fd, file_fd, info, hashlib.sha256(content).hexdigest()
    except BaseException:
        try:
            if directory_fd >= 0:
                if file_fd >= 0:
                    current_file = os.stat("native-review.pdf", dir_fd=directory_fd, follow_symlinks=False)
                    pinned_file = os.fstat(file_fd)
                    if ((current_file.st_dev, current_file.st_ino) == (pinned_file.st_dev, pinned_file.st_ino)
                            and stat.S_ISREG(current_file.st_mode) and current_file.st_uid == current_file.st_gid == 1000
                            and current_file.st_nlink == 1):
                        os.unlink("native-review.pdf", dir_fd=directory_fd)
                pinned_directory = os.fstat(directory_fd)
                current_directory = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if (not os.listdir(directory_fd)
                        and (current_directory.st_dev, current_directory.st_ino)
                            == (pinned_directory.st_dev, pinned_directory.st_ino)
                        and (pinned_directory.st_dev, pinned_directory.st_ino)
                            == (directory_info.st_dev, directory_info.st_ino)):
                    os.rmdir(name, dir_fd=parent_fd)
            else:
                current_directory = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if ((current_directory.st_dev, current_directory.st_ino)
                        == (directory_info.st_dev, directory_info.st_ino)):
                    os.rmdir(name, dir_fd=parent_fd)
        except OSError:
            pass
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)
        raise


def _remove_review_file(parent_fd: int, review) -> None:
    if review is None:
        return
    name, directory_fd, file_fd, directory_info, digest = review
    current_directory = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    pinned_directory = os.fstat(directory_fd)
    _require(stat.S_ISDIR(current_directory.st_mode)
             and (current_directory.st_dev, current_directory.st_ino)
                 == (pinned_directory.st_dev, pinned_directory.st_ino)
             and (pinned_directory.st_dev, pinned_directory.st_ino)
                 == (directory_info.st_dev, directory_info.st_ino)
             and pinned_directory.st_uid == pinned_directory.st_gid == 1000
             and stat.S_IMODE(pinned_directory.st_mode) == 0o700)
    current_file = os.stat("native-review.pdf", dir_fd=directory_fd, follow_symlinks=False)
    pinned_file = os.fstat(file_fd)
    _require(stat.S_ISREG(current_file.st_mode) and current_file.st_uid == current_file.st_gid == 1000
             and current_file.st_nlink == 1 and stat.S_IMODE(current_file.st_mode) == 0o644
             and (current_file.st_dev, current_file.st_ino) == (pinned_file.st_dev, pinned_file.st_ino)
             and hashlib.sha256(os.pread(file_fd, pinned_file.st_size + 1, 0)).hexdigest() == digest)
    os.unlink("native-review.pdf", dir_fd=directory_fd)
    _require(not os.listdir(directory_fd))
    os.rmdir(name, dir_fd=parent_fd)
    os.close(file_fd)
    os.close(directory_fd)


def _remove_runtime(runtime, held: dict[Path, int], parent_info: os.stat_result) -> None:
    runtime.check()
    runtime.close(clean=True)
    root_fd, channel_fd, private_fd, parent_fd = (
        held[runtime.root], held[runtime.channel], held[runtime.scratch], held[runtime.root.parent]
    )
    _require(not os.listdir(channel_fd) and not os.listdir(private_fd))
    _require(set(os.listdir(root_fd)) == {"channel", "private"})
    current_parent = os.fstat(parent_fd)
    _require((current_parent.st_dev, current_parent.st_ino) == (parent_info.st_dev, parent_info.st_ino))
    for name, descriptor in (("channel", channel_fd), ("private", private_fd)):
        current = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        pinned = os.fstat(descriptor)
        _require(stat.S_ISDIR(current.st_mode)
                 and (current.st_dev, current.st_ino) == (pinned.st_dev, pinned.st_ino))
        os.rmdir(name, dir_fd=root_fd)
    current = os.stat(runtime.root.name, dir_fd=parent_fd, follow_symlinks=False)
    pinned = os.fstat(root_fd)
    _require(stat.S_ISDIR(current.st_mode)
             and (current.st_dev, current.st_ino) == (pinned.st_dev, pinned.st_ino))
    os.rmdir(runtime.root.name, dir_fd=parent_fd)


def _remove_empty_owned_parent(parent_fd: int, name: str, descriptor: int,
                               parent_info: os.stat_result) -> None:
    """Remove only our pinned, empty private parent, including failed startup."""
    current_parent = os.fstat(parent_fd)
    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    pinned = os.fstat(descriptor)
    _require((current_parent.st_dev, current_parent.st_ino)
                 == (parent_info.st_dev, parent_info.st_ino)
             and stat.S_ISDIR(current.st_mode) and current.st_uid == current.st_gid == 1000
             and stat.S_IMODE(current.st_mode) == 0o700
             and (current.st_dev, current.st_ino) == (pinned.st_dev, pinned.st_ino)
             and not os.listdir(descriptor))
    os.rmdir(name, dir_fd=parent_fd)


def run(directory: Path, lifetime: int, fingerprint: str) -> int:
    if ((os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (1000, 1000, 1000, 1000)
            or directory.parent != PARENT or DIRECTORY_RE.fullmatch(directory.name) is None
            or not 300 <= lifetime <= 18000
            or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None):
        raise RuntimeError("fixture identity")
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError("subreaper unavailable")
    parent_fd = os.open(PARENT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parent_info = os.fstat(parent_fd)
    if parent_info.st_uid != 1000 or parent_info.st_gid != 1000 or parent_info.st_mode & 0o002:
        os.close(parent_fd)
        raise RuntimeError("unsafe parent")
    review_parent_fd = os.dup(parent_fd)
    try:
        os.stat(directory.name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        os.close(review_parent_fd)
        os.close(parent_fd)
        raise RuntimeError("runtime collision")

    # The imported ordinary runtime pins all three directories and exclusive lock.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
    from imp005_connection import Connection, OwnedRuntime
    from imp024_verify import reap_children
    from imp025_verify import Receiver
    from imp025_fixtures import text_pdf

    class BoundedReceiver(Receiver):
        def __init__(self):
            super().__init__()
            self.lock = threading.RLock()

        def inspect(self, metadata, submission, encoded):
            with self.lock:
                _require(len(self.observations) < 512)
                return super().inspect(metadata, submission, encoded)

    runtime = connection = None
    review = None
    held: dict[Path, int] = {}
    created_root_fd = -1
    selector = selectors.DefaultSelector()
    stop = False

    def request_stop(*_args) -> None:
        nonlocal stop
        stop = True

    prior = {}
    try:
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            prior[number] = signal.signal(number, request_stop)
        # OwnedRuntime requires a private mode0700 parent, not the shared
        # /tmp/opencode scratch root. Keep "r" short for the relay socket limit.
        os.mkdir(directory.name, 0o700, dir_fd=parent_fd)
        created_root_fd = os.open(directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=parent_fd)
        os.fchmod(created_root_fd, 0o700)
        runtime = OwnedRuntime(directory / "r")
        created = os.fstat(created_root_fd)
        owned = os.fstat(runtime.fds[runtime.root.parent])
        _require((created.st_dev, created.st_ino) == (owned.st_dev, owned.st_ino))
        for path in (runtime.root.parent, runtime.root, runtime.channel, runtime.scratch):
            held[path] = os.dup(runtime.fds[path])
        receiver = BoundedReceiver()
        review_pdf = text_pdf((b"IMP-026 synthetic original PDF; no private content.",))
        review = _create_review_file(review_parent_fd, fingerprint, review_pdf)
        receiver.originals[review[4]] = review_pdf
        connection = Connection(runtime, receiver.transport, mode="planning")
        connection.start()
        _require(connection.thread.is_alive() and not connection.failed.is_set())
        selector.register(sys.stdin, selectors.EVENT_READ)
        print("READY", flush=True)
        deadline = time.monotonic() + lifetime
        while not stop and time.monotonic() < deadline:
            runtime.check()
            _require(connection.thread.is_alive() and not connection.failed.is_set())
            for _key, _mask in selector.select(0.1):
                if not os.read(0, 1):
                    stop = True
        if time.monotonic() >= deadline:
            stop = True
        return 0
    finally:
        cleanup_failed = False
        # These owned steps must all be attempted. In particular a changed
        # synthetic PDF must not strand the independent private runtime.
        # Each removal retains its own fd/inode/content checks; a failure
        # still fails the guardian even when the later steps succeed.
        cleanups = [
            selector.close,
            lambda: connection.close() if connection is not None else None,
            lambda: reap_children() if runtime is not None else None,
            lambda: _remove_review_file(review_parent_fd, review),
            lambda: _remove_runtime(runtime, held, os.fstat(created_root_fd))
                if runtime is not None else None,
            lambda: _remove_empty_owned_parent(parent_fd, directory.name, created_root_fd, parent_info)
                if created_root_fd >= 0 else None,
        ]
        descriptors = [*held.values(), review_parent_fd, parent_fd]
        if created_root_fd >= 0:
            descriptors.append(created_root_fd)
        cleanups.extend(lambda fd=fd: os.close(fd) for fd in descriptors)
        cleanups.extend(lambda number=number, handler=handler: signal.signal(number, handler)
                        for number, handler in prior.items())
        for cleanup in cleanups:
            try:
                cleanup()
            except BaseException:
                cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError("fixture cleanup unverified") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--lifetime", type=int, required=True)
    parser.add_argument("--fingerprint", required=True)
    args = parser.parse_args()
    try:
        return run(args.directory, args.lifetime, args.fingerprint)
    except Exception:
        print("Native browser Connection stopped without verified cleanup.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
