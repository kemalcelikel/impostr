"""Trusted single-thread mountless bootstrap. REVIEW before container execution.

No wire options. Only supervisor-owned /scratch/tmpXXXXXXXX jobs and fixed worker
or disposable probe modes. Requires existing pinned unshare, Landlock ABI>=3,
no-new-privileges, new user/net/PID namespaces; never mounts or changes roots.
"""

import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import sys

sys.path.insert(0, "/worker")  # Immutable image code only, even with Python -I.

READ = (1 << 2) | (1 << 3)
EXEC = 1
WRITE = (1 << 1) | (1 << 4) | (1 << 5) | (1 << 7) | (1 << 8) | (1 << 14)
HANDLED = (1 << 15) - 1  # ALL ABI3 FS rights, including REFER and TRUNCATE.
MODES = frozenset({"worker", "startup", "denial", "timeout", "descendants", "output", "encrypt"})
# x86_64-only fixed allowlist, complementary to unchanged outer filter. No socket
# calls, fd reception/stealing, chmod/chown/utime/xattr, mount/ns, ptrace, capset,
# credential changes, prctl (after setup), or general namespace-capable clone.
ALLOWED = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 28, 32, 33, 35, 39, 57, 58, 59,
    60, 61, 62, 63, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 86, 87,
    89, 95, 96, 97, 98, 99, 100, 102, 104, 107, 108, 110, 111, 112, 121,
    124, 125, 127, 128, 129, 130, 131, 137, 138, 186, 202, 204, 217, 218,
    219, 228, 230, 231, 232, 233, 234, 257, 262, 267, 269, 270, 271, 273,
    281, 291, 292, 293, 302, 318, 334, 436})
STAGE = "entry"


class Unavailable(Exception):
    pass


def need(value):
    if not value:
        raise Unavailable()


def libc_signatures(libc):
    # glibc prctl reads EVERY variadic argument as unsigned long (including
    # unused zeros). ctypes' default c_int is not that ABI; specify all five.
    # Pinned x86_64 glibc has close_range; NOT Python os.close_range/closerange.
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    libc.close_range.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_int]
    libc.close_range.restype = ctypes.c_int


class Header(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class Caps(ctypes.Structure):
    _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32), ("inheritable", ctypes.c_uint32)]


class Rule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed", ctypes.c_uint64), ("fd", ctypes.c_int32)]


class Instruction(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8), ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]


class Program(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint16), ("filter", ctypes.POINTER(Instruction))]


def capabilities(libc):
    header, data = Header(0x20080522, 0), (Caps * 2)()
    need(libc.capget(ctypes.byref(header), data) == 0)
    return tuple(getattr(data[0], key) | (getattr(data[1], key) << 32)
                 for key in ("effective", "permitted", "inheritable"))


def namespaces():
    # Self only, container proc. Unavailable facts STOP, never another reader.
    return [str(os.stat("/proc/self/ns/" + name).st_ino) for name in ("user", "net", "mnt")]


def job_directory(job):
    need(re.fullmatch(r"/scratch/tmp[a-z0-9_]{8}", job))
    info = os.lstat(job)
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == 10002 and
         stat.S_IMODE(info.st_mode) == 0o700 and os.path.realpath(job) == job)
    parent = os.lstat("/scratch")
    need(stat.S_ISDIR(parent.st_mode) and parent.st_uid == 10002 and
         stat.S_IMODE(parent.st_mode) == 0o700)


def landlock(libc, job):
    global STAGE
    STAGE = "landlock"
    syscall = libc.syscall
    syscall.restype = ctypes.c_long
    need(syscall(444, None, 0, 1) >= 3)  # VERSION; no graceful degradation.
    handled = ctypes.c_uint64(HANDLED)
    fd = syscall(444, ctypes.byref(handled), ctypes.sizeof(handled), 0)
    need(fd >= 0)
    try:
        grants = [("/usr", READ), ("/worker", READ), ("/lib", READ), ("/lib64", READ), ("/etc/fonts", READ),
            ("/lib64/ld-linux-x86-64.so.2", EXEC | (1 << 2)),
            ("/usr/bin/qpdf", EXEC | (1 << 2)), ("/usr/bin/pdftotext", EXEC | (1 << 2)),
            ("/dev/null", (1 << 2) | (1 << 1)), ("/dev/urandom", 1 << 2), (job, READ | WRITE)]
        for path, rights in grants:
            parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = Rule(rights, parent)
                need(syscall(445, fd, 1, ctypes.byref(rule), 0) == 0)
            finally:
                os.close(parent)
        need(libc.prctl(38, 1, 0, 0, 0) == 0)
        need(syscall(446, fd, 0) == 0)
    finally:
        os.close(fd)


def instructions():
    # arch mismatch and x32 ABI fail closed. Default EPERM, clone3 ENOSYS for
    # glibc fallback. clone allowed ONLY plain fork/thread flags, never namespaces.
    # x86_64 glibc TLS needs arch_prctl ARCH_SET_FS/ARCH_GET_FS. All other
    # arch_prctl operations remain denied, as does general prctl after setup.
    result = [(0x20, 0, 0, 4), (0x15, 1, 0, 0xc000003e), (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0), (0x35, 0, 1, 0x40000000), (0x06, 0, 0, 0x80000000),
        (0x15, 0, 1, 435), (0x06, 0, 0, 0x50000 | 38),
        (0x15, 0, 4, 56), (0x20, 0, 0, 16),
        (0x45, 0, 1, 0x7e020080), (0x06, 0, 0, 0x50001), (0x06, 0, 0, 0x7fff0000),
        (0x15, 0, 5, 158), (0x20, 0, 0, 16), (0x15, 2, 0, 0x1002),
        (0x15, 1, 0, 0x1003), (0x06, 0, 0, 0x50001), (0x06, 0, 0, 0x7fff0000)]
    for number in sorted(ALLOWED):
        result.extend([(0x15, 0, 1, number), (0x06, 0, 0, 0x7fff0000)])
    result.append((0x06, 0, 0, 0x50001))
    return result


def enforce(libc, job):
    global STAGE
    libc_signatures(libc)
    STAGE = "identity"
    need(os.uname().machine == "x86_64" and os.getuid() == os.getgid() == 10002)
    need(os.getpid() == 1 and os.getppid() == 0)  # Fresh PID namespace init.
    STAGE = "no-new-privileges"
    need(libc.prctl(39, 0, 0, 0, 0) == 1)  # Already no-new-privileges.
    STAGE = "stdin"
    need(fcntl.fcntl(0, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY)
    STAGE = "outputs"
    need(all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (1, 2)))
    STAGE = "limits"
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    STAGE = "capabilities"
    # No privileged caps survive exec; explicitly zero any remaining caps too.
    header, zeros = Header(0x20080522, 0), (Caps * 2)()
    need(libc.capset(ctypes.byref(header), zeros) == 0)
    need(capabilities(libc) == (0, 0, 0))
    need(libc.prctl(4, 0, 0, 0, 0) == 0)
    need(libc.prctl(1, signal.SIGKILL, 0, 0, 0) == 0)  # reset PDEATH after cap changes.
    landlock(libc, job)
    # Landlock never revokes preopened handles. Keep ONLY RO stdin and output
    # pipes. No preopened channel, supervisor directory, proc or rule FD survives.
    STAGE = "close-fds"
    # Close ALL high descriptors, even above the now-lowered hard NOFILE limit.
    # No /proc enumeration, bounded partial close loop, or alternate denied call.
    need(libc.close_range(3, 0xffffffff, 0) == 0)
    values = instructions()
    filters = (Instruction * len(values))(*(Instruction(*value) for value in values))
    program = Program(len(values), filters)
    STAGE = "seccomp"
    need(libc.prctl(22, 2, ctypes.cast(ctypes.byref(program), ctypes.c_void_p).value, 0, 0) == 0)


def main():
    global STAGE
    # Entrypoints are trusted image code, not user-selected paths/options.
    need(len(sys.argv) >= 4 and sys.argv[1] in ("launch", "child") and sys.argv[3] in MODES)
    phase, job, mode = sys.argv[1:4]
    need(len(sys.argv) == (4 if phase == "launch" else 7))
    job_directory(job)
    libc = ctypes.CDLL(None, use_errno=True)
    libc_signatures(libc)
    if phase == "launch":
        STAGE = "launcher"
        need(os.getuid() == os.getgid() == 10002 and capabilities(libc) == (0, 0, 0))
        build = json.loads(Path("/worker/build.json").read_text())
        need(hashlib.sha256(Path("/usr/bin/unshare").read_bytes()).hexdigest() == build["launcher"]["sha256"])
        STAGE = "namespaces"
        before = namespaces()
        os.chdir(job)
        need(libc.prctl(1, signal.SIGKILL, 0, 0, 0) == 0)
        args = ["/usr/bin/unshare", "--user", "--map-current-user", "--pid", "--net", "--ipc",
            "--fork", "--kill-child=KILL", "--", "/usr/local/bin/python3", "-I", "-B",
            "/worker/bootstrap.py", "child", job, mode, *before, *sys.argv[4:]]
        os.execve(args[0], args, {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    need(os.getcwd() == job)
    STAGE = "namespaces"
    after = namespaces()
    before = sys.argv[4:7]
    need(all(re.fullmatch(r"[0-9]{1,20}", value) for value in before))
    need(after[0] != before[0] and after[1] != before[1] and after[2] == before[2])
    enforce(libc, job)
    STAGE = "worker"
    if mode == "worker":
        from worker import main as convert
        return convert()
    from probe import main as check
    return check(mode)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Fixed startup failure only, no traceback/private details or parser start.
        sys.stderr.write("imp017-bootstrap:" + STAGE + ":unavailable\n")
        raise SystemExit(70)
