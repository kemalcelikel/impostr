"""Synthetic browser broker guardian; no Docker/private inputs/operator mode.

The fixture owns stdin. EOF (including supervisor death) stops the broker and
reaps only our adopted worker children. The channel is exclusively created and
inode-pinned, never borrowed from another run. Review before runtime execution.
"""
import argparse
import ctypes
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time


def run(directory, lifetime):
    if (os.getuid(), os.geteuid(), os.getgid()) != (1000, 1000, 1000):
        raise RuntimeError("identity")
    if directory.parent != Path("/tmp/opencode") or re.fullmatch(r"impostr-browser-chat-[0-9a-f]{20}", directory.name) is None:
        raise RuntimeError("directory")
    if ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError("subreaper")
    parent = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parent_info = os.fstat(parent)
    if parent_info.st_uid != 1000 or parent_info.st_gid != 1000 or parent_info.st_mode & 0o002:
        os.close(parent)
        raise RuntimeError("scratch parent")
    # Never chmod the shared approved scratch parent. Only our exclusive child.
    try:
        os.mkdir(directory.name, 0o711, dir_fd=parent)
    except BaseException:
        os.close(parent)
        raise
    held = os.open(directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    os.fchmod(held, 0o711)
    # A separate mode0700 sibling contains only this broker's turn scratch;
    # it is never bind-mounted into the API. Its inode is owned before startup.
    scratch = directory.with_name(directory.name + "-scratch")
    try:
        os.mkdir(scratch.name, 0o700, dir_fd=parent)
    except BaseException:
        # Do not adopt a colliding scratch sibling; remove only our empty channel.
        os.rmdir(directory.name, dir_fd=parent)
        os.close(held)
        os.close(parent)
        raise
    scratch_fd = os.open(scratch.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    os.fchmod(scratch_fd, 0o700)
    broker = None
    stopped = False
    selector = selectors.DefaultSelector()
    def stop(*_):
        nonlocal stopped
        stopped = True
    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, stop)
    try:
        broker = subprocess.Popen([
            "/usr/bin/python3", "-I", "-B", str(Path(__file__).resolve()), "_broker",
            "--directory", str(directory), "--scratch", str(scratch), "--lifetime", str(lifetime),
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
           env={"PATH": "/usr/bin:/bin"}, start_new_session=True)
        selector.register(sys.stdin, selectors.EVENT_READ)
        deadline = time.monotonic() + lifetime
        ready_deadline = time.monotonic() + 15
        ready = False
        while not stopped and time.monotonic() < deadline:
            current_parent = directory.parent.lstat()
            if (current_parent.st_dev, current_parent.st_ino) != (parent_info.st_dev, parent_info.st_ino):
                raise RuntimeError("scratch parent replaced")
            if broker.poll() is not None:
                raise RuntimeError("broker exit")
            if not ready:
                try:
                    info = (directory / "channel.sock").lstat()
                    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 1000:
                        raise RuntimeError("socket")
                    print("READY", flush=True)
                    ready = True
                except FileNotFoundError:
                    if time.monotonic() > ready_deadline:
                        raise RuntimeError("startup")
            for _, _ in selector.select(0.1):
                if not os.read(0, 1):
                    stopped = True
    finally:
        selector.close()
        if broker is not None:
            if broker.poll() is None:
                os.killpg(broker.pid, signal.SIGTERM)
                try:
                    broker.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(broker.pid, signal.SIGKILL)
                    broker.wait(timeout=5)
            deadline = time.monotonic() + 5
            children_path = Path(f"/proc/self/task/{os.getpid()}/children")
            while time.monotonic() < deadline:
                children = [int(value) for value in children_path.read_text().split()]
                if not children:
                    break
                for pid in children:
                    try:
                        fd = os.pidfd_open(pid)
                        try:
                            signal.pidfd_send_signal(fd, signal.SIGKILL)
                        finally:
                            os.close(fd)
                        os.waitpid(pid, os.WNOHANG)
                    except (ProcessLookupError, ChildProcessError):
                        pass
                time.sleep(0.05)
            if children_path.read_text().strip():
                raise RuntimeError("children remain")
        current = os.stat(directory.name, dir_fd=parent, follow_symlinks=False)
        pinned = os.fstat(held)
        if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
            raise RuntimeError("directory replaced")
        # After all owned children are reaped, forced broker shutdown may leave
        # just its owned socket. Validate exact type/owner before unlinking it;
        # unknown files remain a cleanup failure, never recursive deletion.
        try:
            info = os.stat("channel.sock", dir_fd=held, follow_symlinks=False)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 1000:
                raise RuntimeError("unexpected cleanup socket")
            os.unlink("channel.sock", dir_fd=held)
        except FileNotFoundError:
            pass
        scratch_current = os.stat(scratch.name, dir_fd=parent, follow_symlinks=False)
        scratch_pinned = os.fstat(scratch_fd)
        if (scratch_current.st_dev, scratch_current.st_ino) != (scratch_pinned.st_dev, scratch_pinned.st_ino):
            raise RuntimeError("scratch replaced")
        if not shutil.rmtree.avoids_symlink_attacks:
            raise RuntimeError("unsafe scratch removal")
        # Anchor recursive cleanup in the retained scratch fd, not its pathname
        # in the shared parent. The root must still match before final rmdir.
        for name in os.listdir(scratch_fd):
            child = os.stat(name, dir_fd=scratch_fd, follow_symlinks=False)
            if stat.S_ISDIR(child.st_mode):
                shutil.rmtree(f"/proc/self/fd/{scratch_fd}/{name}")
            elif stat.S_ISREG(child.st_mode) or stat.S_ISLNK(child.st_mode) or stat.S_ISSOCK(child.st_mode):
                os.unlink(name, dir_fd=scratch_fd)
            else:
                raise RuntimeError("unexpected scratch file")
        scratch_current = os.stat(scratch.name, dir_fd=parent, follow_symlinks=False)
        if (scratch_current.st_dev, scratch_current.st_ino) != (scratch_pinned.st_dev, scratch_pinned.st_ino):
            raise RuntimeError("scratch replaced during cleanup")
        os.rmdir(scratch.name, dir_fd=parent)
        os.close(scratch_fd)
        os.rmdir(directory.name, dir_fd=parent)
        os.close(held)
        os.close(parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--lifetime", type=int, required=True)
    parser.add_argument("mode", nargs="?", choices=("_broker",))
    parser.add_argument("--scratch", type=Path)
    args = parser.parse_args()
    if not 300 <= args.lifetime <= 16200:
        return 1
    try:
        if args.mode == "_broker":
            return broker_child(args.directory, args.scratch)
        if args.scratch is not None:
            return 1
        run(args.directory, args.lifetime)
        return 0
    except Exception:
        print("Synthetic browser broker failed closed.", file=sys.stderr)
        return 1


def broker_child(directory, scratch):
    # Fixed adapter for the unchanged delivered broker's one tempfile call. No
    # arbitrary directory/prefix or private input is accepted, and no provider
    # credential source is loaded. Original worker/relay boundary is unchanged.
    if (scratch != directory.with_name(directory.name + "-scratch") or directory.parent != Path("/tmp/opencode")
            or re.fullmatch(r"impostr-browser-chat-[0-9a-f]{20}", directory.name) is None
            or (os.getuid(), os.geteuid(), os.getgid()) != (1000, 1000, 1000)):
        raise RuntimeError("scratch scope")
    info = scratch.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 1000 or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError("scratch owner")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import imp024_broker as broker
    original = broker.tempfile.TemporaryDirectory
    def temporary(*args, **kwargs):
        if args or kwargs != {"prefix": "imp024-turn-", "dir": "/tmp/opencode"}:
            raise RuntimeError("unexpected scratch request")
        return original(prefix="imp024-turn-", dir=str(scratch))
    broker.tempfile.TemporaryDirectory = temporary
    sys.argv = ["imp024_broker.py", "synthetic", "--directory", str(directory), "--persistent-directory"]
    return broker.main()


if __name__ == "__main__":
    raise SystemExit(main())
