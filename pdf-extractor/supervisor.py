"""UID10002 networkless extractor supervisor; REVIEW before any execution.

Only private Unix API UID10001 peers. Single job/no in-process queue. Bounded
upload is spooled outside the child's Landlock grant, then fed read-only on stdin. Parent parses only
the bounded result contract (never PDF/qpdf objects). No logs of input/results.
"""

import hashlib
import io
import ctypes
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import time

sys.path.insert(0, "/supervisor")
from pdf_protocol import (API_UID, EXTRACTOR_UID, JOB_SECONDS, MAX_CONTROL, MAX_REPLY,
    PDFError, SOCKET_PATH, counted, encode, metadata, peer, receive, rejected,
    remaining, require, result)
from process import command, run

SCRATCH = Path("/scratch")


def guards():
    require(os.getuid() == EXTRACTOR_UID and os.getgid() == EXTRACTOR_UID, "unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    require(libc.prctl(36, 1, 0, 0, 0) == 0, "unavailable")  # PR_SET_CHILD_SUBREAPER
    require(libc.prctl(4, 0, 0, 0, 0) == 0, "unavailable")   # PR_SET_DUMPABLE
    # Container-only cgroup/proc facts. Never host config, fallback or provisioning.
    root = Path("/sys/fs/cgroup")
    require((root / "memory.max").read_text().strip() == "536870912", "unavailable")
    require((root / "memory.swap.max").read_text().strip() == "0", "unavailable")
    require((root / "pids.max").read_text().strip() == "16", "unavailable")
    quota, period = (root / "cpu.max").read_text().split()
    require(int(quota) > 0 and int(quota) <= int(period), "unavailable")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines()
                  if ":" in line)
    require(status["NoNewPrivs"].strip() == "1" and int(status["CapEff"].strip(), 16) == 0,
            "unavailable")
    require(set(os.listdir("/sys/class/net")) == {"lo"}, "unavailable")
    mounts = [line.split() for line in Path("/proc/mounts").read_text().splitlines()]
    require(any(m[1] == "/" and "ro" in m[3].split(",") for m in mounts), "unavailable")
    require(any(m[1] == "/scratch" and m[2] == "tmpfs"
        and {"noexec", "nosuid", "nodev"} <= set(m[3].split(",")) for m in mounts), "unavailable")
    space = os.statvfs(SCRATCH)
    require(space.f_blocks * space.f_frsize <= 128 * 1024 * 1024, "unavailable")
    require(not any(SCRATCH.iterdir()), "unavailable")


def convert(connection, deadline):
    original = metadata(receive(connection, deadline, MAX_CONTROL))
    connection.settimeout(remaining(deadline))
    connection.sendall(encode({"v": 1, "status": "accepted"}, MAX_CONTROL))
    with tempfile.TemporaryFile(dir=SCRATCH) as spool:
        def chunks():
            while True:
                connection.settimeout(remaining(deadline))
                block = connection.recv(65536)
                if not block:
                    return
                yield block
        counted(chunks(), spool.write, original)
        spool.seek(0)
        # Reopen this OWNED anonymous spool read-only before passing fd0. Landlock
        # cannot revoke rights of preopened descriptors. No arbitrary proc paths.
        readonly = os.open(f"/proc/self/fd/{spool.fileno()}", os.O_RDONLY | os.O_CLOEXEC)
        with os.fdopen(readonly, "rb") as source, tempfile.TemporaryDirectory(dir=SCRATCH) as job:
            raw, diagnostics = run(command(job), deadline, MAX_REPLY + 4, source=source, reap=True)
            require(not diagnostics, "unavailable")
            # Same bounded wire decoder over in-memory pipe bytes, no child paths.
            class Pipe:
                def __init__(self):
                    self.stream = io.BytesIO(raw)
                def recv(self, size):
                    return self.stream.read(size)
                def settimeout(self, _):
                    pass
            pipe = Pipe()
            value = result(receive(pipe, deadline), original)
            require(not pipe.recv(1))
            if value["status"] == "ready":
                expected = hashlib.sha256(Path("/supervisor/build.json").read_bytes()).hexdigest()
                require(value["provenance"]["build_sha256"] == expected)
            return value


def main():
    os.umask(0o077)
    guards()
    directory = Path(SOCKET_PATH).parent
    info = directory.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == EXTRACTOR_UID
            and stat.S_IMODE(info.st_mode) == 0o711, "unavailable")
    # Stale socket is safe only in this UID-owned, not API-writable directory.
    if Path(SOCKET_PATH).exists():
        info = Path(SOCKET_PATH).lstat()
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == EXTRACTOR_UID, "unavailable")
        Path(SOCKET_PATH).unlink()
    busy = threading.Lock()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(SOCKET_PATH)
        os.chown(SOCKET_PATH, EXTRACTOR_UID, API_UID)  # Image supplementary group10001.
        os.chmod(SOCKET_PATH, 0o660)
        server.listen(1)

        def job(connection):
            deadline = time.monotonic() + JOB_SECONDS
            # Hard whole-job backstop: container PID1 exit kills all children,
            # Docker discards tmpfs; no next job after unproved reap/cleanup.
            guard = threading.Timer(JOB_SECONDS, lambda: os._exit(70))
            guard.daemon = True
            guard.start()
            try:
                try:
                    value = convert(connection, deadline)
                except PDFError as exc:
                    value = rejected(exc.code)
                except socket.timeout:
                    value = rejected("timeout")
                except Exception:
                    value = rejected("unavailable")
                connection.settimeout(remaining(deadline))
                connection.sendall(encode(value))
            except Exception:
                pass
            finally:
                connection.close()
                guard.cancel()
                busy.release()

        try:
            while True:
                connection, _ = server.accept()
                acquired = False
                try:
                    peer(connection, API_UID)
                    acquired = busy.acquire(blocking=False)
                    if not acquired:
                        connection.settimeout(0.1)
                        connection.sendall(encode(rejected("busy"), MAX_CONTROL))
                        connection.close()
                    else:
                        threading.Thread(target=job, args=(connection,), daemon=True).start()
                except Exception:
                    connection.close()
                    if acquired:
                        busy.release()
        finally:
            Path(SOCKET_PATH).unlink(missing_ok=True)


if __name__ == "__main__":
    # No traceback on capability failure; no automatic unsafe fallback.
    try:
        main()
    except Exception:
        raise SystemExit(70)
