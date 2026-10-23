"""HUMAN ONLY foreground ordinary-stack planning connection; default application off.

No Docker, fixture orchestration, host auth/config discovery, background service or
credential files/env/arguments. Explicit public Responses facts and verified noecho
key input only. Run from repository root; clean stop retains channel directory inode
for the API bind mount. Crash state is NEVER adopted or automatically cleaned.
"""

import argparse
import ctypes
import os
from pathlib import Path
import signal
import stat
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imp002_prototype import check_runtime
from imp024_broker import Broker
from imp024_operator import terminal_input
from imp024_operator_transport import PlanningHTTPSInference, explicit_contract, require
from imp024_verify import reap_children

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path("/tmp/impostr-chat-1000")


class OwnedRuntime:
    """Separate retained channel inode from exclusive private lock/turn scratch.

    Parent must be safe against rename by other identities (root sticky /tmp or
    coordinator-created private synthetic directory). Hold/check every inode;
    create lock exclusively, including against another launcher of the same UID.
    """
    def __init__(self, root=RUNTIME):
        self.root = root
        self.channel = root / "channel"
        self.scratch = root / "private"
        self.fds = {}
        self.lock = None
        require(os.getuid() == os.geteuid() == os.getgid() == os.getegid() == 1000)
        try:
            parent = root.parent.lstat()
            require(stat.S_ISDIR(parent.st_mode) and (
                root.parent == Path("/tmp") and parent.st_uid == 0 and parent.st_mode & stat.S_ISVTX
                or parent.st_uid == parent.st_gid == 1000 and stat.S_IMODE(parent.st_mode) == 0o700))
            self.pin(root.parent, None)
            self.directory(root, 0o711)
            self.directory(self.channel, 0o711)
            self.directory(self.scratch, 0o700)
            require(set(root.iterdir()) == {self.channel, self.scratch})
            require(not any(self.channel.iterdir()) and not any(self.scratch.iterdir()))
            self.lock = os.open("connection.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                0o600, dir_fd=self.fds[self.scratch])
            self.check()
        except BaseException:
            self.close()
            raise

    def pin(self, path, mode):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.fds[path] = fd
        info = os.fstat(fd)
        require(stat.S_ISDIR(info.st_mode))
        if mode is not None:
            require(info.st_uid == info.st_gid == 1000 and stat.S_IMODE(info.st_mode) == mode)

    def directory(self, path, mode):
        try:
            os.mkdir(path.name, mode, dir_fd=self.fds[path.parent])
            # Newly created paths only, never repair adopted permissions.
            fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         dir_fd=self.fds[path.parent])
            try:
                os.fchmod(fd, mode)
            finally:
                os.close(fd)
        except FileExistsError:
            pass
        self.pin(path, mode)

    def check(self):
        for path, fd in self.fds.items():
            current, held = path.lstat(), os.fstat(fd)
            require(stat.S_ISDIR(current.st_mode) and
                    (current.st_dev, current.st_ino, current.st_uid, current.st_gid, current.st_mode) ==
                    (held.st_dev, held.st_ino, held.st_uid, held.st_gid, held.st_mode))
        if self.lock is not None:
            current = (self.scratch / "connection.lock").lstat()
            held = os.fstat(self.lock)
            require(stat.S_ISREG(current.st_mode) and current.st_nlink == 1 and
                    (current.st_dev, current.st_ino) == (held.st_dev, held.st_ino))

    def close(self, *, clean=False):
        try:
            if clean:
                self.check()
                require(not any(self.channel.iterdir()) and
                        set(self.scratch.iterdir()) == {self.scratch / "connection.lock"})
                os.unlink("connection.lock", dir_fd=self.fds[self.scratch])
        finally:
            if self.lock is not None:
                os.close(self.lock)
                self.lock = None
            for fd in self.fds.values():
                os.close(fd)
            self.fds.clear()


class Connection:
    """Ordinary setup core. Controlled verifier injects DATA, never public live mode."""
    def __init__(self, runtime, transport_factory, *, mode="planning"):
        runtime.check()
        self.runtime = runtime
        self.broker = Broker(runtime.channel, persistent_directory=True, mode=mode,
                             transport_factory=transport_factory, scratch_parent=runtime.scratch,
                             owned_runtime=True)
        self.failed = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.started = False

    def run(self):
        try:
            self.broker.run()
        except BaseException:
            self.failed.set()  # No credential-bearing exception detail.

    def start(self):
        self.runtime.check()
        self.thread.start()
        self.started = True

    def close(self):
        self.broker.stop.set()
        if self.started:
            self.thread.join(20)
            require(not self.thread.is_alive() and not self.failed.is_set())
        else:
            self.broker.listener.close()
            self.broker.path.unlink()


def connect():
    require(Path.cwd() == ROOT and sys.stdin.isatty() and sys.stdout.isatty())
    check_runtime()
    require(ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0)
    runtime = OwnedRuntime()
    inference = connection = None
    clean = False
    try:
        contract = explicit_contract(
            terminal_input("Exact HTTPS authority (public port 443, no path): "),
            terminal_input("Exact Responses route: "),
            terminal_input("Exact api-version, or literal none: "),
            terminal_input("Exact deployment: "))
        # DNS child and CA/TLS pinning + runtime/socket ownership BEFORE key.
        inference = PlanningHTTPSInference(contract)
        connection = Connection(runtime, lambda _: inference.for_turn())
        runtime.check()
        require(terminal_input("Project text reaches this explicit provider. Type CONNECT: ") == "CONNECT")
        inference.acquire(terminal_input("API key (no echo): ", secret=True))
        connection.start()
        print("Planning connection foreground; channel /tmp/impostr-chat-1000/channel. "
              "Enable the optional Compose overlay explicitly. Ctrl-C stops. "
              "248 admitted turns per connection; capacity requires clean human restart.", flush=True)
        while connection.thread.is_alive() and not connection.failed.wait(0.25):
            runtime.check()
        require(False)
    except KeyboardInterrupt:
        return 0 if connection is not None and connection.started else 1
    finally:
        handlers = {number: signal.getsignal(number) for number in
                    (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        for number in handlers:
            signal.signal(number, signal.SIG_IGN)
        try:
            try:
                if inference is not None:
                    inference.clear()
                try:
                    if connection is not None:
                        connection.close()
                finally:
                    reap_children()
                clean = True
            finally:
                runtime.close(clean=clean)
        finally:
            for number, handler in handlers.items():
                signal.signal(number, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("connect",))
    parser.parse_args()
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        return connect()
    except (Exception, KeyboardInterrupt):
        print("Planning connection unavailable; no verified connection retained.", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
