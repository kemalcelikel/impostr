"""Operator-only, non-serving IMP-002 handoff; synthetic modes by default.

Run: /usr/bin/python3 -I -B scripts/imp002_prototype.py synthetic
Optional failure checks: replace synthetic with probes, outage, or timeout.
No aggregate quotas are claimed (owner deferred them). operator-inspect/live MUST
NOT run before independent review + synthetic checks; never use real project data.
Other runtime pins are host-specific; OpenCode's hash is observational only.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

# -I intentionally excludes scripts/ from sys.path; add only our own code dir.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from imp002_relay import SyntheticRelay

BWRAP = "/usr/bin/bwrap"
OPENCODE = "/home/kemal/.opencode/bin/opencode"
PINS = {BWRAP: "bf6cf3d4456665f5d80c14eb79a76e0ce87b39a0883e614a161658b4ec33492c",
        "/usr/bin/python3.10": "a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae",
        "/usr/bin/dash": "4f291296e89b784cd35479fca606f228126e3641f5bcaee68dee36583d7c9483"}
PINS.update({
    "/lib64/ld-linux-x86-64.so.2": "41daf7836f7fce21a40ca63a00c5caf21b05a35a76ccc075d86f1716212cdf01",
    "/lib/x86_64-linux-gnu/libc.so.6": "b2cf6c33b74d2f22543b7a469a75b538911e690f769d0b238843a49465b83793",
    "/lib/x86_64-linux-gnu/libpthread.so.0": "fbed9505adacada2abb37c6b43be2df6de81e742712c6025694ba48de62c7e78",
    "/lib/x86_64-linux-gnu/libdl.so.2": "3eaaa4aefd9c28f3867c96a427c3cbec9191cb61c4c9d0a2cb4a765d66064499",
    "/lib/x86_64-linux-gnu/libm.so.6": "3dd5511ae94785c9f921429b0f2b2f7aabb461b6f0e6de6dfdbef15f24bdfee6",
    "/lib/x86_64-linux-gnu/libexpat.so.1": "683e2e41db14581194bf1f6616e95a8f02cd4ab599f0fba807e46325ec01d21f",
    "/lib/x86_64-linux-gnu/libz.so.1": "64c206f0146cc58bbddc4f22054436f4ff278f5a554aa3ce6921ddf7e9133370",
    "/lib/x86_64-linux-gnu/libssl.so.3": "51fc92556f11ddce62f3f988d3fe973fab8fb4742032e61a713688581c924262",
    "/lib/x86_64-linux-gnu/libcrypto.so.3": "7cc817ff1841b59516d684f357bc0c3fc2cc52c3fa9b4ffb8ce8bdc215f02915",
    "/usr/lib/python3.10/lib-dynload/_ssl.cpython-310-x86_64-linux-gnu.so": "99aa106038e4ac231b4232733381f98903edba02319363db8a1d12728148c2b6",
    "/usr/lib/python3.10/lib-dynload/_hashlib.cpython-310-x86_64-linux-gnu.so": "aaa7cad4595fb421be5a9206efea579ec852f820d44e1d76a8de9ab46e02200c",
    "/usr/lib/python3.10/lib-dynload/_json.cpython-310-x86_64-linux-gnu.so": "d02668cbf0664d30f194230b767f940d0abf9da851204c54b84640f987bcb145",
})
LIBRARIES = ("libc.so.6", "libpthread.so.0", "libdl.so.2", "libm.so.6",
             "libexpat.so.1", "libz.so.1", "libssl.so.3", "libcrypto.so.3")
SESSION_MODES = ("imp023-startup", "imp023-history", "imp023-reconnect", "imp023-interrupt")
PLANNING_MODES = ("imp024-planning", "imp024-denials", "imp024-cancel", "imp024-error")


class CapabilityError(RuntimeError):
    pass


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _digest(stream)


def _digest(stream):
    value = hashlib.sha256()
    for block in iter(lambda: stream.read(65536), b""):
        value.update(block)
    return value.hexdigest()


def opencode_digest():
    """Validate the fixed public executable without running it or pinning updates.

    This fingerprint describes observed bytes, not API compatibility or a frozen
    launch inode. Actual confined behavior checks remain mandatory.
    """
    fd = os.open(OPENCODE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size == 0
                or info.st_uid not in (0, 1000) or info.st_mode & 0o022
                or not os.access(OPENCODE, os.X_OK)):
            raise CapabilityError("OpenCode executable unavailable or unsafe")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return _digest(stream)
    finally:
        os.close(fd)


def check_runtime():
    if os.getuid() != 1000 or os.getgid() != 1000:
        raise CapabilityError("requires measured non-root UID/GID 1000:1000")
    for path, pin in PINS.items():
        if digest(path) != pin:
            raise CapabilityError("runtime binary changed; remeasure and review")
    return {**{path: digest(path) for path in PINS}, OPENCODE: opencode_digest()}


def command(root, mode, port):
    args = [BWRAP, "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts",
            "--uid", "1000", "--gid", "1000", "--cap-drop", "ALL", "--new-session", "--die-with-parent",
            "--clearenv", "--hostname", "imp002-synthetic"]
    environment = {"PATH": "/bin", "HOME": "/home/worker", "SHELL": "/bin/sh",
                   "XDG_CONFIG_HOME": "/home/worker/config", "XDG_DATA_HOME": "/home/worker/data",
                   "XDG_CACHE_HOME": "/home/worker/cache", "XDG_STATE_HOME": "/home/worker/state",
                   "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
                   "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_PURE": "1",
                   "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1", "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
                   "OPENCODE_DISABLE_CLAUDE_CODE": "1", "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
                   "OPENCODE_CONFIG": "/tmp/generated.json"}
    for key, value in environment.items():
        args += ["--setenv", key, value]
    mounts = [(OPENCODE, "/bin/opencode"), ("/usr/bin/python3.10", "/bin/python3"),
              ("/usr/bin/dash", "/bin/sh"), ("/usr/lib/python3.10", "/usr/lib/python3.10"),
              ("/lib64/ld-linux-x86-64.so.2", "/lib64/ld-linux-x86-64.so.2")]
    mounts += [(f"/lib/x86_64-linux-gnu/{name}", f"/lib/x86_64-linux-gnu/{name}") for name in LIBRARIES]
    for source, destination in mounts:
        args += ["--ro-bind", source, destination]
    # No /usr, /lib, /etc, host HOME, repository, /run or socket-directory bind.
    # Python's fixed public stdlib is the only directory runtime mount.
    args += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
             "--dir", "/home/worker/config/opencode", "--dir", "/home/worker/data",
             "--dir", "/home/worker/cache", "--dir", "/home/worker/state",
             "--bind", str(root / "project"), "/project", "--dir", "/relay",
             "--ro-bind", str(root / "code"), "/prototype", "--chdir", "/project"]
    args += ["--ro-bind", str(root / "config"), "/home/worker/config"]
    # Pinned 1.18.34 executed the project plugin canary despite disable flags.
    # Hide discovery paths at the filesystem boundary; never rely on those flags
    # alone. These empty RO mounts cannot be replaced by project tool writes.
    for directory in (".opencode", ".claude", ".agents"):
        args += ["--ro-bind", str(root / "empty"), f"/project/{directory}"]
    if mode != "outage":
        args += ["--ro-bind", str(root / "relay.sock"), "/relay/inference.sock"]
    # Bootstrap path is explicitly supplied under -I; no project Python modules.
    worker = "imp024_worker" if mode in PLANNING_MODES else "imp023_worker" if mode in SESSION_MODES else "imp002_worker"
    bootstrap = f"import sys; sys.path.insert(0, '/prototype'); import {worker}; raise SystemExit({worker}.main())"
    return args + ["--", "/bin/python3", "-I", "-B", "-c", bootstrap, str(port), mode,
                   str(root / "synthetic-host")]


def bounded_run(args, timeout=20, max_output=65536):
    """Drain bounded output, kill process group on failure; bwrap PID1 kills descendants."""
    process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env={"PATH": "/usr/bin:/bin"}, close_fds=True, start_new_session=True)
    output = bytearray()
    deadline = time.monotonic() + timeout
    reason = "exited"
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            for key, _ in selector.select(0.1):
                block = os.read(key.fileobj.fileno(), min(8192, max_output + 1 - len(output)))
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(block)
                if len(output) > max_output:
                    reason = "output-limit"
                    break
            if reason != "exited":
                break
        if reason != "exited":
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        # A new-session descendant still holding the output pipe would prevent
        # EOF even though the outer bwrap process exited. Require bounded EOF.
        if reason != "exited":
            end = time.monotonic() + 2
            while selector.get_map() and time.monotonic() < end:
                for key, _ in selector.select(0.1):
                    if not os.read(key.fileobj.fileno(), 8192):
                        selector.unregister(key.fileobj)
            if selector.get_map():
                raise CapabilityError("worker descendant output remained open")
        return process.returncode, reason, bytes(output[:max_output])
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
        selector.close()
        process.stdout.close()


def run(mode, transport=None):
    if mode in SESSION_MODES + PLANNING_MODES and transport is not None:
        raise CapabilityError("session scenarios require the unchanged synthetic relay")
    pins = check_runtime()
    parent = Path("/tmp/opencode")
    if not parent.is_dir():
        raise CapabilityError("approved scratch parent missing")
    with tempfile.TemporaryDirectory(prefix="imp002-", dir=parent) as name:
        root = Path(name)
        root.chmod(0o700)
        (root / "project").mkdir(mode=0o700)
        (root / "code").mkdir(mode=0o700)
        (root / "empty").mkdir(mode=0o700)
        (root / "config").mkdir(mode=0o700)
        (root / "config" / "opencode").mkdir(mode=0o700)
        (root / "config" / "opencode" / ".gitignore").write_text("node_modules\n")
        filenames = ("imp002_worker.py", "imp002_relay.py", "imp024_protocol.py")
        if mode in SESSION_MODES + PLANNING_MODES:
            filenames += ("imp023_worker.py",)
        if mode in PLANNING_MODES:
            filenames += ("imp024_worker.py",)
        for filename in filenames:
            (root / "code" / filename).write_bytes(Path(__file__).with_name(filename).read_bytes())
        # Synthetic canaries are outside the mounted project. Never actual host data.
        (root / "synthetic-host").mkdir()
        (root / "synthetic-host" / "home").mkdir()
        (root / "synthetic-host" / "home" / "secret").write_text("synthetic-not-a-secret")
        (root / "synthetic-host" / "sibling").mkdir()
        (root / "synthetic-host" / "sibling" / "PROJECT.md").write_text("synthetic sibling")
        (root / "project" / "escape").symlink_to(root / "synthetic-host" / "home" / "secret")
        (root / "project" / "PROJECT.md").write_text("# Synthetic IMP002 project\n")
        if mode in PLANNING_MODES:
            (root / "project" / "AGENTS.md").write_text("# Synthetic planning rules\nOnly plan; no execution.\n")
            (root / "project" / "BACKLOG.md").write_text("# Synthetic backlog\n\n## [-] TASK-001 — Synthetic plan\n")
        # Invalid local config + executable plugin/skill canaries must never be
        # loaded. All content is generated; no installed host definitions enter.
        (root / "project" / "opencode.json").write_text("INVALID SYNTHETIC CONFIG")
        (root / "project" / ".opencode" / "plugins").mkdir(parents=True)
        (root / "project" / ".opencode" / "plugins" / "canary.ts").write_text(
            "await Bun.write('/project/injection-executed', 'synthetic'); throw Error('synthetic plugin');\n")
        (root / "project" / ".opencode" / "skills" / "canary").mkdir(parents=True)
        (root / "project" / ".opencode" / "skills" / "canary" / "SKILL.md").write_text(
            "---\nname: canary\ndescription: synthetic only\n---\nNever load this synthetic skill.\n")
        for directory in (".claude", ".agents"):
            (root / "project" / directory).mkdir()
        listeners = []
        try:
            for filename in ("docker.sock", "db.sock"):
                listener = socket.socket(socket.AF_UNIX)
                listeners.append(listener)
                listener.bind(str(root / "synthetic-host" / filename))
                listener.listen(1)
            listener = socket.socket(socket.AF_UNIX)
            listeners.append(listener)
            listener.bind("\0impostr-imp002-synthetic-canary")
            listener.listen(1)
            listener = socket.socket(socket.AF_INET)
            listeners.append(listener)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            if mode in PLANNING_MODES:
                from imp024_session import SyntheticPlanning
                transport = SyntheticPlanning(mode.removeprefix("imp024-"))
            with SyntheticRelay(root / "relay.sock", lifetime=45 if mode in PLANNING_MODES else 30,
                                transport=transport, planning=mode in PLANNING_MODES) as relay:
                code, reason, output = bounded_run(command(root, mode, port),
                                                 timeout=2 if mode == "timeout" else 45 if mode in SESSION_MODES + PLANNING_MODES else 20)
                results = []
                response_text = False
                runtime_error = False
                for line in output.splitlines():
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict) and ("containment" in value or "relay_outage_denied" in value):
                            results.append(value)
                        if isinstance(value, dict) and value.get("type") == "text":
                            response_text |= value.get("part", {}).get("text") == "IMP002_SYNTHETIC_OK"
                        if isinstance(value, dict) and value.get("type") == "error":
                            runtime_error = True
                    except (ValueError, UnicodeError):
                        pass
                contained = any(all(result.get("containment", {}).values())
                                for result in results if "containment" in result)
                injection_denied = not (root / "project" / "injection-executed").exists()
                success = (code == 0 and reason == "exited" and contained and injection_denied)
                if mode in SESSION_MODES + PLANNING_MODES:
                    session_results = []
                    for line in output.splitlines():
                        try:
                            value = json.loads(line)
                            # Only exact fixed boolean assertions leave the worker.
                            if isinstance(value, dict) and set(value) == {"session_checks"}:
                                checks = value["session_checks"]
                                if mode in PLANNING_MODES:
                                    from imp024_worker import CHECKS
                                else:
                                    from imp023_worker import CHECKS
                                if (isinstance(checks, dict) and set(checks) == set(CHECKS[mode])
                                        and all(type(item) is bool for item in checks.values())):
                                    session_results.append(checks)
                        except (ValueError, UnicodeError):
                            pass
                    expected_calls = {"imp023-startup": 0, "imp023-history": 3,
                                      "imp023-reconnect": 2, "imp023-interrupt": 2,
                                      "imp024-planning": 4, "imp024-cancel": 2,
                                      "imp024-denials": 1, "imp024-error": 1}[mode]
                    expected_denials = 1 if mode in ("imp024-denials", "imp024-error") else 0
                    success = (success and len(session_results) == 1 and all(session_results[0].values())
                               and relay.calls == expected_calls and relay.denied == expected_denials)
                    if mode == "imp024-planning":
                        success = success and transport.validated
                    results += [{"session_checks": checks} for checks in session_results]
                if mode in ("synthetic", "synthetic-stream", "operator-live"):
                    success = success and relay.calls > 0 and relay.denied == 0 and response_text and not runtime_error
                if mode == "outage":
                    success = success and {"relay_outage_denied": True} in results
                if mode == "timeout":
                    success = contained and reason == "timeout" and not (root / "project" / "late").exists()
                summary = {"success": success, "mode": mode, "worker_exit": code, "stop": reason,
                           "checks": results, "relay_calls": relay.calls, "relay_denied": relay.denied,
                           "observed": relay.observed, "runtime_sha256": pins,
                           "project_configuration_injection_denied": injection_denied,
                           "aggregate_containment": "owner-deferred; not proved"}
                if mode in ("synthetic", "synthetic-stream") and not success:
                    # This output is from an isolated, entirely synthetic runtime;
                    # never enable this diagnostic for a credential-bearing mode.
                    summary["synthetic_diagnostic"] = output.decode("utf-8", errors="replace")[-6000:]
        finally:
            for listener in listeners:
                listener.close()
    summary["owned_state_removed"] = not root.exists()
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["success"] and summary["owned_state_removed"] else 1


def operator_inspect():
    """Human-only offline inspection; fixed diagnostics, never exception details."""
    from imp002_transport import Unavailable, inspection_file_details, inspection_reason, resolve_operator_contract
    try:
        try:
            check_runtime()
        except CapabilityError as exc:
            raise Unavailable("runtime mismatch", reason="runtime_mismatch") from exc
        except OSError as exc:
            raise Unavailable("runtime unavailable", reason="runtime_unavailable") from exc
        contract = resolve_operator_contract()
        print(json.dumps({"operator_contract_resolved": True,
                          "contract_sha256": contract.fingerprint,
                          "network_used": False, "credentials_disclosed": False}))
        return 0
    except Exception as exc:
        # The offline call graph has no network transport or worker launch. Render
        # only allowlisted categories, never messages, types or chained errors.
        print(json.dumps({"success": False, "operator_capability_unavailable": True,
                          "reason_code": inspection_reason(exc), "network_used": False,
                          **inspection_file_details(exc)}))
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("synthetic", "synthetic-stream", "probes", "outage", "timeout", "operator-inspect", "operator-live"))
    parser.add_argument("--contract-sha256", help="nonsecret fingerprint from reviewed operator-inspect")
    args = parser.parse_args()
    try:
        if args.mode == "operator-inspect":
            return operator_inspect()
        if args.mode == "synthetic-stream":
            from imp002_transport import SyntheticStream
            return run(args.mode, SyntheticStream())
        if args.mode.startswith("operator-"):
            # This branch is for a human operator AFTER independent review, never
            # unattended agent execution. No host CLI/config loader is executed.
            check_runtime()
            from imp002_transport import HTTPSInference, Unavailable, resolve_operator_contract
            try:
                contract = resolve_operator_contract()
                if args.contract_sha256 != contract.fingerprint:
                    raise Unavailable("contract pin absent/changed")
                return run(args.mode, HTTPSInference(contract))
            except Exception:
                # No paths/settings/credentials/chained errors or runtime text.
                print(json.dumps({"success": False, "operator_capability_unavailable": True}))
                return 1
        return run(args.mode)
    except (CapabilityError, OSError) as exc:
        # No raw runtime output or private configuration in the operator report.
        print(json.dumps({"success": False, "capability_error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
