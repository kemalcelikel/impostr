"""Internal synthetic server/driver/fixture; invoked only by mandatory bwrap.

Selected v1.18.34 public source: cli/network.ts, server/auth.ts, and
server/routes/instance/httpapi/{groups/session,handlers/{session,event,global}}.ts.
No shell, tool, auth/config API, file, general proxy or prompt override route.
The fixture controls are Python events, not externally accessible HTTP endpoints.
"""

import base64
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import queue
import re
import secrets
import select
import socket
import subprocess
import sys
import threading
import time

from imp002_relay import MAX_CALLS, MAX_REQUEST, MAX_RESPONSE, ROUTE, stub_response, validate
from imp002_worker import probes

VERSION = "1.18.34"
MODEL = {"providerID": "azure", "modelID": "synthetic-deployment"}
PROMPTS = {"seed": "IMP023_SEED", "recall": "IMP023_RECALL", "fresh": "IMP023_FRESH",
           "abort": "IMP023_ABORT", "failure": "IMP023_FAILURE"}
TEXTS = {"seed": "IMP023_SEEDED", "recall": "IMP023_HISTORY_OK", "fresh": "IMP023_FRESH_OK",
         "abort": "IMP023_PARTIAL_ABORT", "failure": "IMP023_PARTIAL_FAILURE"}
COMMON = ("authenticated_health_version", "unauthenticated_denied", "event_connected",
          "session_created_read", "server_child_stopped", "private_listener_closed", "fixture_stopped")
CHECKS = {
    "imp023-startup": COMMON,
    "imp023-history": COMMON + ("delta_before_completion", "distinct_sessions", "second_turn_history",
                                "fresh_session_no_history", "successful_history"),
    "imp023-reconnect": COMMON + ("delta_before_completion", "reconnected_event", "reconnected_history_status",
                                  "no_prompt_resubmission", "restart_history_preserved", "restart_continuation"),
    "imp023-interrupt": COMMON + ("delta_before_completion", "abort_not_success", "abort_upstream_cancelled",
                                  "failure_not_success", "failure_observed", "bounded_inference_calls"),
}
MAX_API_BODY = 128 * 1024
MAX_EVENT_BYTES = 256 * 1024


class Failed(RuntimeError):
    """Never render exception details; checkpoint contains fixed assertions only."""


def require(condition):
    if not condition:
        raise Failed()


def fixture_text(data):
    """History-sensitive oracle uses conversation roles, not flattened system text."""
    turns = []
    for message in data["input"]:
        if message["role"] not in ("user", "assistant"):
            continue
        content = message["content"]
        text = content if isinstance(content, str) else "".join(part["text"] for part in content)
        turns.append((message["role"], text))
    for action, prompt in PROMPTS.items():
        if turns and turns[-1] == ("user", prompt):
            expected = [("user", prompt)]
            if action == "recall":
                expected = [("user", PROMPTS["seed"]), ("assistant", TEXTS["seed"]), ("user", prompt)]
            require(turns == expected)
            return action, TEXTS[action]
    raise Failed()


def response_events(text):
    # Reuse the approved native Responses stub shape; only synthetic text differs.
    return stub_response().replace(b"IMP002_SYNTHETIC_OK", text.encode()).split(b"\n\n")[:-1]


def relay_check(body):
    """Every fixture inference crosses the unchanged inference-only host validator.

    No server request/auth/control reaches this socket, no transport is supplied,
    and its constant synthetic answer is discarded locally. Limit remains four.
    """
    with socket.socket(socket.AF_UNIX) as upstream:
        upstream.settimeout(3)
        upstream.connect("/relay/inference.sock")
        upstream.sendall((f"POST {ROUTE} HTTP/1.1\r\nHost: synthetic\r\n"
                          f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                          "Connection: close\r\n\r\n").encode() + body)
        response = http.client.HTTPResponse(upstream)
        response.begin()
        require(response.status == 200)
        result = response.read(MAX_RESPONSE + 1)
        require(len(result) <= MAX_RESPONSE and b"response.completed" in result)


class Fixture:
    def __init__(self):
        self.calls = 0
        self.action = None
        self.history_valid = False
        self.release = threading.Event()
        self.delta_sent = threading.Event()
        self.completed = threading.Event()
        self.cancelled = threading.Event()
        self.failed = threading.Event()
        self.stop = threading.Event()
        self.server = HTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.server.fixture = self
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.05}, daemon=True)

    def reset(self):
        for event in (self.release, self.delta_sent, self.completed, self.cancelled, self.failed):
            event.clear()
        self.action = None
        self.history_valid = False

    def close(self):
        self.stop.set()
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        require(not self.thread.is_alive())


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def do_POST(self):
        fixture = self.server.fixture
        self.close_connection = True
        self.connection.settimeout(2)
        try:
            lengths = self.headers.get_all("Content-Length", [])
            require(self.path == ROUTE and len(lengths) == 1 and not self.headers.get("Transfer-Encoding"))
            require(lengths[0].isascii() and lengths[0].isdecimal() and len(lengths[0]) <= 7)
            length = int(lengths[0])
            require(1 <= length <= MAX_REQUEST)
            body = self.rfile.read(length)
            require(len(body) == length)
            fixture.calls += 1
            require(fixture.calls <= MAX_CALLS)
            data = validate("POST", ROUTE, body)
            action, text = fixture_text(data)
            relay_check(body)
            fixture.action, fixture.history_valid = action, True
            events = response_events(text)
            self.connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                                    b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n")

            def send(block):
                self.connection.sendall(f"{len(block):x}\r\n".encode() + block + b"\r\n")

            for event in events[:4]:
                send(event + b"\n\n")
            fixture.delta_sent.set()
            deadline = time.monotonic() + 5
            while not fixture.release.wait(0.02):
                if fixture.stop.is_set() or select.select([self.connection], [], [], 0)[0]:
                    fixture.cancelled.set()
                    return
                require(time.monotonic() < deadline)
            require(not fixture.stop.is_set() and action != "abort")
            if action == "failure":
                # @ai-sdk/openai 3.0.88 requires sequence_number or falls through
                # to unknown_chunk. After output, OpenCode provider/error.ts reads
                # nested error.code; invalid_prompt is explicitly non-retryable.
                # Top-level codes default to retryable even with SDK maxRetries=0.
                send(b'event: error\ndata: {"type":"error","sequence_number":4,"error":{"type":"invalid_request_error","code":"invalid_prompt","message":"synthetic terminal rejection","param":null}}\n\n')
                fixture.failed.set()
            else:
                fixture.completed.set()
                for event in events[4:]:
                    send(event + b"\n\n")
            self.connection.sendall(b"0\r\n\r\n")
        except Exception:
            fixture.failed.set()
            # Fixed error only; don't leak SDK headers, generated auth or bodies.
            try:
                self.connection.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass

    def do_GET(self):
        self.send_error(403)


def generated_config(port):
    return {"username": "synthetic", "enabled_providers": ["azure"],
            "model": "azure/synthetic-deployment", "small_model": "azure/synthetic-deployment",
            "default_agent": "tech-lead", "share": "disabled", "autoupdate": False,
            "snapshot": False, "plugin": [], "mcp": {}, "lsp": False, "formatter": False,
            "permission": {"*": "deny"}, "compaction": {"auto": False, "prune": False},
            "agent": {"tech-lead": {"mode": "primary", "prompt": "Synthetic text only. Never use tools.",
                                    "permission": {"*": "deny"}}},
            "provider": {"azure": {"npm": "@ai-sdk/azure", "options": {
                "baseURL": f"http://127.0.0.1:{port}/openai/v1", "apiKey": "synthetic-not-a-secret",
                "useDeploymentBasedUrls": False, "timeout": 8000, "headerTimeout": 3000,
                "chunkTimeout": 6000, "maxRetries": 0},
                "models": {"synthetic-deployment": {"name": "Synthetic", "toolcall": False,
                           "limit": {"context": 64000, "output": 256},
                           "options": {"store": False, "maxOutputTokens": 256}}}}}}


def server_command(port):
    return ["/bin/opencode", "--log-level", "ERROR", "serve", "--hostname", "127.0.0.1",
            "--port", str(port), "--mdns=false"]


def route(method, operation, session=None):
    fixed = {("GET", "health"): "/global/health", ("GET", "event"): "/event",
             ("GET", "status"): "/session/status", ("POST", "create"): "/session"}
    scoped = {("GET", "read"): "", ("GET", "history"): "/message?limit=16",
              ("POST", "prompt"): "/prompt_async", ("POST", "abort"): "/abort"}
    if (method, operation) in fixed and session is None:
        return fixed[method, operation]
    require((method, operation) in scoped and isinstance(session, str)
            and re.fullmatch(r"ses_[A-Za-z0-9_-]{1,128}", session) is not None)
    return "/session/" + session + scoped[method, operation]


class Driver:
    route = staticmethod(route)
    max_request = MAX_REQUEST
    max_body = MAX_API_BODY

    def __init__(self, port, password):
        self.port = port
        self.auth = "Basic " + base64.b64encode(("synthetic:" + password).encode()).decode()
        self.requests = 0
        self.prompts = 0

    def open(self, method, operation, session=None, body=None, authenticated=True):
        path = self.route(method, operation, session)
        self.requests += 1
        require(self.requests <= 200)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        headers = {"x-opencode-directory": "/project", "Accept-Encoding": "identity"}
        if authenticated:
            headers["Authorization"] = self.auth
        payload = None if body is None else json.dumps(body).encode()
        require(payload is None or len(payload) <= self.max_request)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, payload, headers)
            # HTTPResponse can detach HTTPConnection.sock for Connection: close.
            # Retain the owned socket solely to interrupt the SSE reader on cleanup.
            connection._imp023_socket = connection.sock
            return connection, connection.getresponse()
        except Exception:
            connection.close()
            raise

    def request(self, method, operation, session=None, body=None, authenticated=True):
        connection, response = self.open(method, operation, session, body, authenticated)
        try:
            raw = response.read(self.max_body + 1)
            require(len(raw) <= self.max_body)
            if not authenticated:
                return response.status
            require(response.status == (204 if operation == "prompt" else 200))
            require(not raw or response.getheader("Content-Type", "").startswith("application/json"))
            return json.loads(raw) if raw else None
        finally:
            response.close()
            connection.close()

    def create(self, title):
        value = self.request("POST", "create", body={"title": title})
        require(isinstance(value, dict) and value.get("title") == title)
        session = value.get("id")
        route("GET", "read", session)
        require(self.request("GET", "read", session) == value)
        return session

    def prompt(self, session, action):
        require(action in PROMPTS)
        self.prompts += 1
        require(self.prompts <= MAX_CALLS)
        return self.request("POST", "prompt", session, {
            "model": MODEL, "agent": "tech-lead", "parts": [{"type": "text", "text": PROMPTS[action]}]})

    def history(self, session):
        value = self.request("GET", "history", session)
        require(isinstance(value, list) and len(value) <= 16)
        for message in value:
            require(isinstance(message, dict) and message.get("info", {}).get("sessionID") == session)
            require(all(part.get("type") != "tool" for part in message.get("parts", [])))
        return value

    def idle(self, session):
        status = self.request("GET", "status")
        require(isinstance(status, dict))
        return status.get(session, {"type": "idle"}).get("type") == "idle"


def parse_event(stream, *, max_line=8192, max_event=32768):
    data = []
    total = 0
    while True:
        line = stream.readline(max_line + 1)
        require(line and len(line) <= max_line)
        total += len(line)
        require(total <= max_event)
        if line in (b"\n", b"\r\n"):
            if not data:
                continue
            value = json.loads(b"\n".join(data))
            require(isinstance(value, dict) and isinstance(value.get("type"), str))
            return value, total
        if line.startswith(b"data:"):
            data.append(line[5:].strip())


class Events:
    parse_event = staticmethod(parse_event)
    stream_timeout = 8

    def __init__(self, driver):
        self.connection, self.response = driver.open("GET", "event")
        try:
            require(self.response.status == 200)
            require(self.response.getheader("Content-Type", "").startswith("text/event-stream"))
            owned_socket = getattr(self.connection, "_imp023_socket", None)
            if owned_socket is not None:
                owned_socket.settimeout(self.stream_timeout)
            event, size = self.parse_event(self.response)
            require(event["type"] == "server.connected")
        except Exception:
            self.close()
            raise
        self.queue = queue.Queue(maxsize=256)
        self.stopped = threading.Event()
        self.bytes = size
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            while not self.stopped.is_set():
                event, size = self.parse_event(self.response)
                self.bytes += size
                require(self.bytes <= MAX_EVENT_BYTES)
                self.queue.put_nowait(event)
        except Exception:
            if not self.stopped.is_set():
                try:
                    self.queue.put_nowait({"type": "driver.stream.failed"})
                except queue.Full:
                    pass

    def delta(self, session, text):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                event = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            fields = event.get("properties", {})
            require(event["type"] != "driver.stream.failed")
            require(event["type"] != "session.error" or fields.get("sessionID") != session)
            if (event["type"] == "message.part.delta" and fields.get("sessionID") == session
                    and fields.get("field") == "text" and fields.get("delta") == text):
                return
        raise Failed()

    def close(self):
        if hasattr(self, "stopped"):
            self.stopped.set()
        # Interrupt a blocking SSE read before closing its buffered reader.
        owned_socket = getattr(self.connection, "_imp023_socket", None)
        if owned_socket is not None:
            try:
                owned_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.connection.close()
        if hasattr(self, "thread"):
            self.thread.join(3)
            require(not self.thread.is_alive())
        self.response.close()


def assistant(history, action):
    users = [item for item in history if item["info"].get("role") == "user"]
    require(users)
    require("".join(part.get("text", "") for part in users[-1].get("parts", [])
                    if part.get("type") == "text") == PROMPTS[action])
    latest = users[-1]["info"]["id"]
    candidates = [item for item in history if item["info"].get("role") == "assistant"
                  and item["info"].get("parentID") == latest]
    return candidates[-1] if candidates else None


def successful(message, action):
    if not message:
        return False
    info = message["info"]
    text = "".join(part.get("text", "") for part in message.get("parts", []) if part.get("type") == "text")
    return (not info.get("error") and info.get("finish") == "stop"
            and bool(info.get("time", {}).get("completed")) and text == TEXTS[action])


def wait_history(driver, session, action, success=True):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        history = driver.history(session)
        message = assistant(history, action) if history else None
        if message and driver.idle(session):
            if success and successful(message, action):
                return history
            if not success and message["info"].get("error") and not successful(message, action):
                return history
        time.sleep(0.05)
    raise Failed()


class Server:
    def __init__(self, driver, password):
        self.driver = driver
        self.password = password
        self.process = None

    def start(self):
        require(self.process is None)
        # This environment comes from bwrap --clearenv, never host env/config.
        environment = dict(os.environ)
        environment.update(OPENCODE_SERVER_USERNAME="synthetic", OPENCODE_SERVER_PASSWORD=self.password)
        self.process = subprocess.Popen(server_command(self.driver.port), cwd="/project", env=environment,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            require(self.process.poll() is None)
            try:
                value = self.driver.request("GET", "health")
                require(value == {"healthy": True, "version": VERSION})
                return
            except (OSError, http.client.HTTPException):
                time.sleep(0.05)
        raise Failed()

    def close(self):
        if self.process is not None:
            process, self.process = self.process, None
            if process.poll() is None:
                os.killpg(process.pid, 15)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, 9)
                    process.wait(timeout=2)
            require(process.poll() is not None)
        with socket.socket(socket.AF_INET) as peer:
            peer.settimeout(0.2)
            require(peer.connect_ex(("127.0.0.1", self.driver.port)) != 0)


def scenario(mode, checks):
    fixture = Fixture()
    fixture.thread.start()
    # Port reserved only inside the namespace, no host listener or ingress.
    with socket.socket(socket.AF_INET) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    password = secrets.token_hex(32)
    driver = Driver(port, password)
    server = Server(driver, password)
    events = None
    try:
        with open("/tmp/generated.json", "w") as stream:
            json.dump(generated_config(fixture.server.server_address[1]), stream)
        server.start()
        checks["authenticated_health_version"] = True
        checks["unauthenticated_denied"] = driver.request("GET", "health", authenticated=False) == 401
        require(checks["unauthenticated_denied"])
        events = Events(driver)
        checks["event_connected"] = True
        first = driver.create("IMP023 explicit synthetic A")
        checks["session_created_read"] = True
        if mode == "imp023-startup":
            return

        def begin(session, action):
            fixture.reset()
            driver.prompt(session, action)
            events.delta(session, TEXTS[action])
            require(fixture.delta_sent.wait(0.5) and fixture.history_valid
                    and fixture.action == action and not fixture.completed.is_set() and not fixture.release.is_set())
            checks["delta_before_completion"] = True

        def complete(session, action):
            fixture.release.set()
            history = wait_history(driver, session, action)
            require(fixture.completed.is_set() and not fixture.failed.is_set())
            return history

        if mode == "imp023-history":
            second = driver.create("IMP023 explicit synthetic B")
            require(first != second and driver.history(second) == [])
            checks["distinct_sessions"] = True
            begin(first, "seed")
            complete(first, "seed")
            begin(first, "recall")
            checks["second_turn_history"] = True
            saved = complete(first, "recall")
            begin(second, "fresh")
            checks["fresh_session_no_history"] = True
            complete(second, "fresh")
            require(driver.history(first) == saved)
            checks["successful_history"] = True
        elif mode == "imp023-reconnect":
            begin(first, "seed")
            events.close()
            events = Events(driver)
            checks["reconnected_event"] = True
            # Reconnect while inference is held: saved partial history + busy status.
            partial = driver.history(first)
            require(assistant(partial, "seed") is not None and not driver.idle(first))
            history = complete(first, "seed")
            require(driver.history(first) == history and driver.idle(first))
            checks["reconnected_history_status"] = True
            require(driver.prompts == 1 and fixture.calls == 1)
            checks["no_prompt_resubmission"] = True
            events.close()
            events = None
            server.close()
            server.start()
            require(driver.history(first) == history and driver.idle(first)
                    and driver.request("GET", "read", first)["id"] == first)
            checks["restart_history_preserved"] = True
            events = Events(driver)
            begin(first, "recall")
            complete(first, "recall")
            checks["restart_continuation"] = True
        elif mode == "imp023-interrupt":
            begin(first, "abort")
            require(driver.request("POST", "abort", first) is True)
            history = wait_history(driver, first, "abort", success=False)
            require(not successful(assistant(history, "abort"), "abort") and not fixture.completed.is_set())
            checks["abort_not_success"] = True
            require(fixture.cancelled.wait(2))
            checks["abort_upstream_cancelled"] = True
            second = driver.create("IMP023 explicit synthetic failure")
            begin(second, "failure")
            fixture.release.set()
            history = wait_history(driver, second, "failure", success=False)
            checks["failure_not_success"] = not successful(assistant(history, "failure"), "failure")
            checks["failure_observed"] = fixture.failed.is_set() and not fixture.completed.is_set()
            checks["bounded_inference_calls"] = fixture.calls == driver.prompts == 2
        else:
            raise Failed()
    finally:
        try:
            if events is not None:
                events.close()
        finally:
            try:
                server.close()
                checks["server_child_stopped"] = True
                checks["private_listener_closed"] = True
            finally:
                fixture.close()
                checks["fixture_stopped"] = True


def main():
    mode = sys.argv[2]
    require(mode in CHECKS)
    # Same argv, containment canaries, mandatory identity and masks as IMP-002.
    containment = probes()
    print(json.dumps({"containment": containment}), flush=True)
    checks = dict.fromkeys(CHECKS[mode], False)
    try:
        require(all(containment.values()))
        scenario(mode, checks)
    except Exception:
        pass
    print(json.dumps({"session_checks": checks}), flush=True)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
