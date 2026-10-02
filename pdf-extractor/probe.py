"""Owned synthetic checks ONLY after the same bootstrap as real parsing."""

import ctypes
import errno
import os
from pathlib import Path
import sys
import time


def denied(function):
    try:
        function()
    except OSError as exc:
        assert exc.errno in (errno.EPERM, errno.EACCES, errno.ENOENT, errno.EROFS, errno.EBADF)
    else:
        raise AssertionError()


def main(mode):
    if mode == "startup":
        print("namespace-ready")
    elif mode == "timeout":
        time.sleep(10)
    elif mode == "output":
        sys.stdout.write("x" * 20000)
    elif mode == "descendants":
        read, write = os.pipe()
        if os.fork() == 0:
            os.close(read)
            os.setsid()
            if os.fork() == 0:
                os.write(write, b"ready")
                os.close(write)
                time.sleep(10)
            os._exit(0)
        os.close(write)
        assert os.read(read, 5) == b"ready"
        os.close(read)
        # Returning from job PID1 must kill the now escaped grandchild without
        # waiting ten seconds or relying on process-group membership.
    elif mode == "encrypt":
        from process import run
        Path("valid.pdf").write_bytes(sys.stdin.buffer.read())
        run(["/usr/bin/qpdf", "--encrypt", "synthetic", "synthetic", "256", "--",
             "valid.pdf", "encrypted.pdf"], time.monotonic() + 10, 8192)
        sys.stdout.buffer.write(Path("encrypted.pdf").read_bytes())
    else:
        step = "denial-handles"
        try:
            for fd in range(3, 256):
                try:
                    os.fstat(fd)
                except OSError as exc:
                    assert exc.errno == errno.EBADF
                else:
                    raise AssertionError()
            # RO inherited stdin: preopened descriptor rights aren't revoked.
            denied(lambda: os.write(0, b"x"))
            step = "denial-capabilities"
            from bootstrap import capabilities
            libc = ctypes.CDLL(None, use_errno=True)
            assert capabilities(libc) == (0, 0, 0)
            step = "denial-usernamespace"
            for flags in (0x10000000, 0x50000000):
                assert libc.unshare(flags) == -1 and ctypes.get_errno() == errno.EPERM
            step = "denial-filesystem"
            for path in ("/run/impostr-pdf/channel.sock", "/supervisor/build.json", "/scratch/sibling", "/etc/passwd",
                         "/proc/self/status", "/sys/fs/cgroup/memory.max"):
                denied(lambda: open(path, "rb"))
                denied(lambda: os.open(path, os.O_WRONLY))
                denied(lambda: os.chmod(path, 0o777))
                denied(lambda: os.utime(path, None))
            # A granted own job is usable; parent scratch and sibling are NOT.
            Path("owned-canary").write_text("owned")
            assert Path("owned-canary").read_text() == "owned"
            denied(lambda: os.link("/scratch/sibling", "sibling-link"))
            denied(lambda: os.truncate("/scratch/sibling", 0))
            denied(lambda: os.chown("/scratch/sibling", 10002, 10002))
            denied(lambda: os.setxattr("/scratch/sibling", "user.imp017", b"x"))
            Path("owned-canary").unlink()
            step = "denial-network"
            for family, kind, protocol in ((1,1,0),(2,1,0),(10,1,0),(16,524291,0),(17,3,0)):
                ctypes.set_errno(0)
                fd = libc.socket(family, kind, protocol)
                if fd >= 0:
                    os.close(fd)
                    raise AssertionError()
                assert ctypes.get_errno() == errno.EPERM
            step = "denial-outer-socket"
            # connect itself must be blocked even with no valid socket descriptor.
            assert libc.connect(-1, None, 0) == -1 and ctypes.get_errno() == errno.EPERM
            assert libc.recvmsg(-1, None, 0) == -1 and ctypes.get_errno() == errno.EPERM
            assert libc.syscall(438, -1, -1, 0) == -1 and ctypes.get_errno() == errno.EPERM
            step = "denial-proc"
            denied(lambda: open("/proc/1/root/scratch/sibling", "rb"))
            print("denied")
        except AssertionError:
            print("imp017-probe-failure:boundary-assertion:" + step)
        except Exception:
            print("imp017-probe-failure:probe-runtime:" + step)
    return 0
