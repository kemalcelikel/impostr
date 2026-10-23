"""Credential-free child; launched BEFORE provider key acquisition.

Owns generated Docker inputs/stack/Member and product acceptance. Fixed pipe
messages only; no key/config/endpoint transport or post-key orchestration forks in
the credential-bearing parent. EOF/SIGTERM/failures invoke owned cleanup.
"""

import json
import os
from pathlib import Path
import selectors
import signal
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imp024_operator_product import ProductAcceptance
from imp024_verify import ROOT, Verify, require


class MemberOutput:
    stdout_only = True

    def __init__(self):
        self.raw = bytearray()
        self.login = None

    def feed(self, block):
        require(len(self.raw) + len(block) <= 4096)
        self.raw.extend(block)

    def finish(self):
        try:
            value = json.loads(self.raw)
            require(type(value) is dict and set(value) == {"username", "password"}
                    and type(value["username"]) is str and value["username"].startswith("model-check-")
                    and type(value["password"]) is str and 32 <= len(value["password"]) <= 128)
            self.login = value
        finally:
            self.raw.clear()


class OperatorFixture(Verify):
    def __init__(self):
        super().__init__()
        self.product = None

    def prepare(self):
        super().prepare()
        # Choose a loopback-only disposable port before the provider exists.
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.url = "http://127.0.0.1:" + str(port)
        # Rewrite only our generated synthetic env, never checkout/private input.
        env = self.inputs / "fixture.env"
        text = env.read_text().replace("APP_PORT=8080\n", f"APP_PORT={port}\n").replace(
            "IMPOSTR_PUBLIC_ORIGIN=http://127.0.0.1:8080\n",
            "IMPOSTR_PUBLIC_ORIGIN=" + self.url + "\n")
        env.write_text(text)
        self.compose("build", "db", "api", "frontdoor", "api-integration-check", seconds=600)
        self.compose("up", "-d", "--wait", "db")
        self.compose("run", "--rm", "api", "alembic", "upgrade", "head")
        member = MemberOutput()
        self.compose("run", "--rm", "api-integration-check", "python", "-B",
                     "tests/imp024_operator_member.py", output=member)
        self.product = ProductAcceptance(self.url, member.login)
        # API starts before broker, which is valid default fail-closed behavior.
        self.compose("up", "-d", "--wait", "api", "frontdoor", seconds=180)

    def stop_broker(self):
        # Parent owns in-process credential-bearing broker. Never signal it or
        # assert its socket gone until the fixed STOPPED/EOF cleanup handshake.
        pass

    def cleanup(self):
        if self.product is not None:
            self.product.close()
        return super().cleanup()


def control(expected, timeout):
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin, selectors.EVENT_READ)
    try:
        deadline = time.monotonic() + timeout
        message = bytearray()
        while time.monotonic() < deadline:
            require(bool(selector.select(max(0, deadline - time.monotonic()))))
            block = os.read(sys.stdin.fileno(), 1)
            require(bool(block) and len(message) < 64)
            message.extend(block)
            if block == b"\n":
                require(bytes(message) == expected)
                return
        require(False)
    finally:
        selector.close()


def main():
    require(Path.cwd() == ROOT)
    fixture = OperatorFixture()
    status = 1
    try:
        fixture.prepare()
        print("PREPARED " + str(fixture.channel), flush=True)
        control(b"ACCEPT\n", 600)  # No provider facts/key may cross this pipe.
        fixture.product.run()
        print("ACCEPTED", flush=True)
        control(b"STOPPED\n", 16200)
        status = 0
    except (Exception, KeyboardInterrupt):
        print("UNAVAILABLE", flush=True)
        # Parent stops broker first; only then may helper delete mounted channel.
        try:
            control(b"STOPPED\n", 20)
        except Exception:
            pass  # EOF also triggers owned teardown; unknown socket fails cleanup.
    finally:
        if not fixture.cleanup():
            status = 1
    return status


if __name__ == "__main__":
    def interrupted(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        raise SystemExit(main())
    except Exception:
        print("UNAVAILABLE", flush=True)
        raise SystemExit(1) from None
