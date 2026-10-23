"""HUMAN ONLY: explicit model setup + disposable real-product acceptance.

Agents must NEVER execute setup-accept. No parked resolver/private input/file auth,
environment credential, secret argument, persisted activation or automatic runner.
API/worker model stays the fixed alias. Only public HTTPS:443 Responses/API-key is
supported. Key enters trusted foreground memory through verified no-echo terminal.
Memory-only does NOT protect against host swap/dumps/debuggers or Python copies.
"""

import argparse
import ctypes
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import termios
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imp024_broker import Broker
from imp024_operator_transport import PlanningHTTPSInference, explicit_contract, require
from imp024_verify import ROOT, reap_children, stop_process


def terminal_input(label, *, secret=False):
    """No /dev/tty fallback/getpass warning mode. Fail if echo cannot be disabled."""
    require(sys.stdin.isatty() and sys.stdout.isatty())
    fd = sys.stdin.fileno()
    before = termios.tcgetattr(fd)
    changed = list(before)
    changed[3] &= ~(termios.ECHO | termios.ECHONL)
    try:
        if secret:
            termios.tcsetattr(fd, termios.TCSAFLUSH, changed)
            require(not termios.tcgetattr(fd)[3] & (termios.ECHO | termios.ECHONL))
        sys.stdout.write(label)
        sys.stdout.flush()
        value = sys.stdin.readline(4098)
        require(value.endswith("\n") and len(value) <= 4097)
        return value[:-1]
    finally:
        if secret:
            termios.tcsetattr(fd, termios.TCSAFLUSH, before)
            sys.stdout.write("\n")
            sys.stdout.flush()


def helper_message(process, expected, timeout):
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    buffer = bytearray()
    try:
        while time.monotonic() < deadline:
            if not selector.select(0.1):
                require(process.poll() is None)
                continue
            block = os.read(process.stdout.fileno(), 1)
            require(bool(block) and len(buffer) < 4096)
            buffer.extend(block)
            if block == b"\n":
                line = bytes(buffer).strip()
                buffer.clear()
                if line == b"UNAVAILABLE" and expected.startswith(b'{"check":'):
                    continue  # Preserve/await cleanup after the original failure.
                require(line != b"UNAVAILABLE")
                if line.startswith(expected):
                    return line
                # Ignore credential-free helper's fixed sanitized Docker status.
                require(line.startswith(b'{"check":'))
        require(False)
    finally:
        selector.close()


def run_broker(broker, failed):
    # Suppress thread exception details in the only credential-bearing process.
    try:
        broker.run()
    except BaseException:
        failed.set()


def shutdown(broker, thread, inference, helper, passed):
    """Disable trusted memory first; independently attempt every owned teardown."""
    stopped = True
    # Ignore repeated terminal signals while bounded cleanup runs. A later SIGKILL
    # or daemon/host loss still cannot guarantee cleanup (documented limitation).
    previous = {number: signal.getsignal(number) for number in
                (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    for number in previous:
        signal.signal(number, signal.SIG_IGN)
    try:
        try:
            if broker is not None:
                broker.stop.set()
                if thread is not None:
                    thread.join(20)
                    require(not thread.is_alive())
                else:
                    broker.listener.close()
                    broker.path.unlink()
            reap_children(exclude={helper.pid})
        except Exception:
            stopped = False
        finally:
            inference.clear()
        if stopped:
            helper.stdin.write(b"STOPPED\n")
            helper.stdin.flush()
            helper_message(helper, b'{"check": "owned_cleanup", "status": "passed"', 600)
            status = helper.wait(timeout=5)
            require(status == 0 or not passed)
        else:
            require(False)
    finally:
        try:
            if helper.poll() is None:
                os.killpg(helper.pid, signal.SIGTERM)
                try:
                    helper.wait(timeout=240)  # Allow helper's bounded owned cleanup, not ten seconds.
                except subprocess.TimeoutExpired:
                    stop_process(helper)
            helper.stdin.close()
            helper.stdout.close()
            reap_children()
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)


def setup_accept():
    require(Path.cwd() == ROOT and sys.stdin.isatty() and sys.stdout.isatty())
    require(ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0)
    authority = terminal_input("Exact HTTPS authority (no path; public port 443): ")
    route = terminal_input("Exact Responses route: ")
    version = terminal_input("Exact api-version, or literal none: ")
    deployment = terminal_input("Exact model deployment: ")
    contract = explicit_contract(authority, route, version, deployment)
    # DNS child, CA/TLS setup and ALL orchestration child creation precede key input.
    inference = PlanningHTTPSInference(contract)
    helper = subprocess.Popen([
        "/usr/bin/python3", "-I", "-B", str(ROOT / "scripts/imp024_operator_helper.py"),
    ], cwd=ROOT, env={"PATH": "/usr/local/bin:/usr/bin:/bin"}, close_fds=True,
       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
       start_new_session=True)
    broker = thread = None
    passed = False
    try:
        line = helper_message(helper, b"PREPARED ", 900)
        directory = Path(line[9:].decode("ascii"))
        require(directory.parent == Path("/tmp/opencode")
                and re.fullmatch(r"imp024-verify-[0-9a-f]{12}", directory.name))
        # Validate runtime/directory and bind in trusted process before key input.
        broker = Broker(directory, persistent_directory=True,
                        transport_factory=lambda _: inference.for_turn(), mode="operator")
        confirmation = terminal_input(
            "Only synthetic project data will reach this explicit provider. Type ACCEPT: ")
        require(confirmation == "ACCEPT")
        inference.acquire(terminal_input("API key (no echo): ", secret=True))
        # After acquisition: no orchestration fork, no DNS process; worker launches
        # use existing clean exec env/close_fds, never preexec_fn/pass_fds or Python fork.
        failed = threading.Event()
        thread = threading.Thread(target=run_broker, args=(broker, failed), daemon=True)
        thread.start()
        helper.stdin.write(b"ACCEPT\n")
        helper.stdin.flush()
        helper_message(helper, b"ACCEPTED", 240)
        require(thread.is_alive() and not failed.is_set())
        passed = True
        print("Model product acceptance passed; connection remains foreground until Ctrl-C.", flush=True)
        # No URL/login/provider facts/key forwarded, no flag/file enables later use.
        while thread.is_alive() and not failed.is_set() and helper.poll() is None:
            time.sleep(0.25)
        require(False)
    except KeyboardInterrupt:
        return 0 if passed else 1
    finally:
        shutdown(broker, thread, inference, helper, passed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup-accept",))
    parser.parse_args()
    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        return setup_accept()
    except (Exception, KeyboardInterrupt):
        print("Model setup/acceptance unavailable; no verified connection retained.", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
