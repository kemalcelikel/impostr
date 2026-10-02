"""Bounded pipe runner. Mountless per-job PID1 teardown kills parser descendants."""

import os
import re
import selectors
import signal
import subprocess
import time

from pdf_protocol import PDFError, remaining, require


def startup_category(diagnostics):
    """Offline, fixed categories for an owned synthetic bwrap startup only.

    No raw diagnostics are retained or returned. Unknown, oversized, multiline or
    ambiguous messages stay unattributed; namespace denial does not identify the
    responsible kernel, AppArmor or seccomp policy.
    """
    unknown = "namespace-runtime-unknown"
    if not isinstance(diagnostics, bytes) or len(diagnostics) > 8192:
        return unknown
    message = diagnostics.strip()
    denied = rb"(?:Operation not permitted|Permission denied)"
    if re.fullmatch(rb"bwrap: Creating new namespace failed: " + denied, message):
        return "namespace-denied"
    if re.fullmatch(
            rb"bwrap: No permissions to create new namespace, likely because the kernel "
            rb"does not allow non-privileged user namespaces\."
            rb"(?: See <[^\r\n\x00]{1,512}>\.)?", message):
        return "usernamespace-denied"
    if re.fullmatch(rb"bwrap: (?:setting up (?:uid|gid) map|"
            rb"write to /proc/self/(?:uid|gid)_map): " + denied, message):
        return "namespace-mapping-denied"
    if re.fullmatch(rb"bwrap: (?:Unknown option --[a-z0-9-]{1,64}|"
            rb"--[a-z0-9-]{1,64} takes (?:an argument|two arguments))", message):
        return "launcher-arguments-invalid"
    if message == b"bwrap: --disable-userns requires --unshare-user":
        return "launcher-arguments-invalid"
    if re.fullmatch(rb"bwrap: Failed to make / slave: " + denied, message):
        # v0.8.0 bubblewrap.c: mount(NULL, "/", NULL,
        # MS_SILENT | MS_SLAVE | MS_REC, NULL). Identifies the operation ONLY.
        return "mount-propagation-denied"
    if message == b"imp017-bootstrap:unavailable":
        return "sandbox-unavailable"
    for stage in ("entry", "launcher", "namespaces", "landlock", "descriptors", "capabilities", "seccomp", "worker",
                  "identity", "no-new-privileges", "stdin", "outputs", "limits", "close-fds"):
        if message == b"imp017-bootstrap:" + stage.encode("ascii") + b":unavailable":
            return "sandbox-" + stage + "-unavailable"
    if re.fullmatch(rb"unshare: unshare failed: " + denied, message):
        return "namespace-denied"
    if re.fullmatch(rb"bwrap: execvp [^\r\n\x00]{1,512}: "
            rb"(?:No such file or directory|Exec format error)", message):
        return "executable-runtime-missing"
    return unknown


class StartupFailure(PDFError):
    """Probe-only detail. Public error remains fixed; never attach child stderr."""

    def __init__(self, diagnostics):
        self.category = startup_category(diagnostics)
        super().__init__()


def run(args, deadline, output_limit, diagnostics_limit=8192, source=None, reap=False,
        *, diagnose_startup=False):
    # CPython 3.12.11 Popen._get_devnull opens O_RDWR even for stdin. The
    # sandbox correctly rejects that writable inherited capability. Supply an
    # explicit RO fd instead; production's RO spool and probe pipes are unchanged.
    null = None
    try:
        if source is None:
            null = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
        process = subprocess.Popen(args, stdin=null if source is None else source,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
            start_new_session=True, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    finally:
        # Popen has duplicated fd0 into the child; parent owns only this default
        # handle. Close it even if startup fails; never close caller-owned source.
        if null is not None:
            os.close(null)
    selector = selectors.DefaultSelector()
    outputs = [bytearray(), bytearray()]
    try:
        for index, pipe in enumerate((process.stdout, process.stderr)):
            selector.register(pipe, selectors.EVENT_READ, index)
        while selector.get_map():
            remaining(deadline)
            for key, _ in selector.select(min(0.05, remaining(deadline))):
                index = key.data
                limit = output_limit if index == 0 else diagnostics_limit
                block = os.read(key.fileobj.fileno(), min(65536, limit + 1 - len(outputs[index])))
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                require(len(outputs[index]) + len(block) <= limit, "limit")
                outputs[index].extend(block)
        process.wait(timeout=remaining(deadline))
        if process.returncode != 0 and diagnose_startup:
            # Opt-in ONLY for the verifier's synthetic namespace-start command.
            # Existing pipe/deadline bounds and finally kill/reap remain intact.
            raise StartupFailure(bytes(outputs[1]))
        require(process.returncode == 0)
        return bytes(outputs[0]), bytes(outputs[1])
    except subprocess.TimeoutExpired as exc:
        raise PDFError("timeout") from exc
    finally:
        # Always kill launcher process group even after early EOF. unshare's
        # kill-child/PDEATHSIG + job PID1 teardown cover escaped descendants.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            # Never accept a subsequent job after unproved cleanup.
            os._exit(70)
        if reap:
            # Supervisor is a subreaper. Even if unshare's monitor returned before
            # its namespace init, wait for every adopted descendant before reuse.
            end = time.monotonic() + 1
            while True:
                try:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    break
                if pid == 0:
                    if time.monotonic() >= end:
                        os._exit(70)
                    time.sleep(0.01)
        selector.close()
        process.stdout.close()
        process.stderr.close()


def command(job):
    # Internal supervisor-generated job only, never a wire/caller path or command.
    require(isinstance(job, (str, os.PathLike)) and
            re.fullmatch(r"/scratch/tmp[a-z0-9_]{8}", str(job)), "unavailable")
    return ["/usr/local/bin/python3", "-I", "-B", "/worker/bootstrap.py", "launch", str(job), "worker"]


def probe_command(job, mode):
    # Disposable image verification only. No arbitrary source/command/path API.
    require(mode in ("startup", "denial", "timeout", "descendants", "output", "encrypt"), "unavailable")
    return command(job)[:-1] + [mode]
