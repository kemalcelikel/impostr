"""COORDINATOR-ONLY disposable-image diagnostic, never a host command.

The verifier passes this source to a fresh dedicated extractor container under
the unchanged runtime policy, ONLY after bwrap's exact root-propagation denial.
No parser, host mounts/configuration, policy changes or capability grants.
Reproduce the v0.8.0 bubblewrap.c operation: mount(NULL, "/", NULL,
MS_SILENT | MS_SLAVE | MS_REC, NULL). This Python syscall probe is not bwrap
execution and cannot identify an executable-specific policy or the denying layer.
"""

import ctypes
import errno
import os

NEW_USER_MOUNT = 0x10000000 | 0x00020000
ROOT_SLAVE_FLAGS = 0x8000 | 0x80000 | 0x4000
SYS_ADMIN = 1 << 21
PREFIX = "imp017-mount-probe:"
STAGES = frozenset({"outer-guard", "unshare-user-mount", "uid-map",
    "setgroups", "gid-map", "namespace-guard", "root-slave-recursive"})
OUTCOMES = frozenset({"unavailable", "eacces", "eperm", "einval", "enosys", "other", "ok"})


class Stop(Exception):
    pass


class Header(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class Capabilities(ctypes.Structure):
    _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32),
                ("inheritable", ctypes.c_uint32)]


def effective(libc):
    header = Header(0x20080522, 0)  # _LINUX_CAPABILITY_VERSION_3, self only.
    data = (Capabilities * 2)()
    if libc.capget(ctypes.byref(header), data) != 0:
        raise Stop()
    return data[0].effective | (data[1].effective << 32)


def namespaces():
    # Self only, inside the disposable container. On denial STOP; no alternate
    # transport, /proc/1, host proc, namespace-owner traversal or policy lookup.
    return tuple((value.st_dev, value.st_ino) for value in
                 (os.stat("/proc/self/ns/user"), os.stat("/proc/self/ns/mnt")))


def outer_guard(libc):
    if os.getuid() != 10002 or os.getgid() != 10002 or effective(libc) != 0:
        raise Stop()
    with open("/proc/self/status", "rb") as file:
        raw = file.read(8193)
    if len(raw) > 8192:
        raise Stop()
    status = dict(line.split(b":", 1) for line in raw.splitlines() if b":" in line)
    if status.get(b"NoNewPrivs", b"").strip() != b"1" or status.get(b"Seccomp", b"").strip() != b"2":
        raise Stop()
    return namespaces()


def write_map(path, value):
    # These are fixed SELF namespace setup files, written ONLY after successful
    # atomic NEWUSER|NEWNS. Never write maps in an existing/ancestor namespace.
    with open(path, "w", encoding="ascii") as file:
        if file.write(value) != len(value):
            raise Stop()


def outcome(number):
    return {errno.EACCES: "eacces", errno.EPERM: "eperm", errno.EINVAL: "einval",
            errno.ENOSYS: "enosys"}.get(number, "other")


def probe():
    stage = "outer-guard"
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                               ctypes.c_ulong, ctypes.c_void_p]
        before = outer_guard(libc)
        stage = "unshare-user-mount"
        if libc.unshare(NEW_USER_MOUNT) != 0:
            return stage, outcome(ctypes.get_errno())
        # Kernel creates the mount namespace owned by the simultaneously created
        # user namespace. Verify BOTH changed before any map write or mount.
        stage = "namespace-guard"
        after = namespaces()
        if any(old == new for old, new in zip(before, after)):
            raise Stop()
        stage = "uid-map"
        write_map("/proc/self/uid_map", "10002 10002 1\n")
        stage = "setgroups"
        write_map("/proc/self/setgroups", "deny\n")
        stage = "gid-map"
        write_map("/proc/self/gid_map", "10002 10002 1\n")
        stage = "namespace-guard"
        if (namespaces() != after or os.getuid() != 10002 or os.getgid() != 10002
                or not effective(libc) & SYS_ADMIN):
            raise Stop()
        stage = "root-slave-recursive"
        if libc.mount(None, b"/", None, ROOT_SLAVE_FLAGS, None) != 0:
            return stage, outcome(ctypes.get_errno())
        return stage, "ok"
    except OSError as exc:
        return stage, outcome(exc.errno)
    except Exception:
        return stage, "unavailable"


def main():
    stage, result = probe()
    # No exception strings, IDs, paths, mount tables, kernel/profile names or
    # capability masks escape. A diagnostic success is NOT containment PASS.
    print(PREFIX + stage + ":" + result)


if __name__ == "__main__":
    main()
