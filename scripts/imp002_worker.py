"""Runs ONLY inside the mandatory bwrap boundary; synthetic shim and probes."""

import http.client
import json
import os
import select
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from imp002_relay import CALL_TIMEOUT, IO_TIMEOUT, MAX_REQUEST, MAX_RESPONSE, ROUTE, respond


class Shim(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def do_POST(self):
        self.connection.settimeout(IO_TIMEOUT)
        started = False
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if self.path != ROUTE or len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                raise ValueError("framing")
            if not lengths[0].isascii() or not lengths[0].isdecimal() or len(lengths[0]) > 7:
                raise ValueError("length")
            length = int(lengths[0])
            if not 1 <= length <= MAX_REQUEST:
                raise ValueError("bound")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("truncated")
            with socket.socket(socket.AF_UNIX) as upstream:
                upstream.settimeout(CALL_TIMEOUT)
                upstream.connect("/relay/inference.sock")
                # No worker-supplied host, auth, cookies, query, or proxy headers.
                request = (f"POST {ROUTE} HTTP/1.1\r\nHost: synthetic\r\n"
                           f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                           "Connection: close\r\n\r\n").encode() + body
                upstream.sendall(request)
                finished = threading.Event()
                deadline = time.monotonic() + CALL_TIMEOUT

                def guard():
                    while not finished.wait(0.025):
                        try:
                            if (time.monotonic() >= deadline
                                    or select.select([self.connection], [], [], 0)[0]):
                                # Caller EOF/pipelining or timeout closes the
                                # Unix peer, cancelling the host inference/TLS.
                                upstream.shutdown(socket.SHUT_RDWR)
                                return
                        except OSError:
                            return

                watcher = threading.Thread(target=guard, daemon=True)
                watcher.start()
                try:
                    response = http.client.HTTPResponse(upstream)
                    response.begin()
                    if response.status not in (200, 403, 503):
                        raise ValueError("upstream")
                    if response.status != 200:
                        # Never trust error bodies even from the trusted relay.
                        respond(self.connection, "403 Forbidden" if response.status == 403 else "503 Service Unavailable",
                                b'{"error":"relay unavailable"}')
                    else:
                        if response.getheader("Content-Type") != "text/event-stream":
                            raise ValueError("stream type")
                        self.connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                                                b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
                        started = True
                        total = 0
                        while True:
                            block = response.read1(4096)
                            if not block:
                                break
                            total += len(block)
                            if total > MAX_RESPONSE or time.monotonic() >= deadline:
                                raise ValueError("stream bound")
                            self.connection.sendall(f"{len(block):x}\r\n".encode() + block + b"\r\n")
                        self.connection.sendall(b"0\r\n\r\n")
                finally:
                    finished.set()
                    watcher.join(1)
        except (ValueError, OSError, http.client.HTTPException):
            try:
                if not started:
                    respond(self.connection, "503 Service Unavailable", b'{"error":"relay unavailable"}')
            except OSError:
                pass
        self.close_connection = True

    def do_GET(self):
        respond(self.connection, "403 Forbidden", b'{"error":"inference only"}')
        self.close_connection = True


def denied_connect(family, target):
    with socket.socket(family) as connection:
        connection.settimeout(0.2)
        try:
            connection.connect(target)
            return False
        except OSError:
            return True


def probes():
    # All paths/addresses are synthetic. Never test real host secrets or services.
    canaries = sys.argv[3]
    targets = [canaries + "/home/secret", canaries + "/sibling/PROJECT.md",
               canaries + "/docker.sock", canaries + "/db.sock",
               "/project/escape", "/home/kemal", "/etc/opencode", "/sys"]
    absent = all(not os.path.exists(path) for path in targets)
    escaped = subprocess.run(["/bin/sh", "-c", "test ! -r /project/escape && test ! -e /synthetic-host/home/secret"],
                             timeout=2, capture_output=True).returncode == 0
    sockets = all(denied_connect(socket.AF_UNIX, path) for path in targets[2:4])
    abstract = denied_connect(socket.AF_UNIX, "\0impostr-imp002-synthetic-canary")
    external = denied_connect(socket.AF_INET, ("192.0.2.1", 9))
    external6 = denied_connect(socket.AF_INET6, ("2001:db8::1", 9))
    host_loopback = denied_connect(socket.AF_INET, ("127.0.0.1", int(sys.argv[1])))
    # bwrap's one-ID user mapping renders supplementary host groups unmapped
    # (overflow GID 65534), not their privileged host group IDs.
    clean = (os.getuid() == 1000 and os.getgid() == 1000 and set(os.getgroups()) <= {1000, 65534}
             and "IMPOSTR_SYNTHETIC_SECRET" not in os.environ
             and os.environ.get("HOME") == "/home/worker")
    try:
        with open("/bin/opencode", "ab"):
            pass
        readonly = False
    except OSError:
        readonly = True
    try:
        with open("/home/worker/config/opencode/untrusted.json", "w"):
            pass
        config_readonly = False
    except OSError:
        config_readonly = True
    try:
        with open("/project/.opencode/canary.ts", "w"):
            pass
        discovery_readonly = False
    except OSError:
        discovery_readonly = True
    return {"synthetic_files_denied": absent and escaped, "synthetic_sockets_denied": sockets and abstract,
            "network_denied": external and external6 and host_loopback, "clean_identity_env": clean,
            "runtime_readonly": readonly, "config_readonly": config_readonly,
            "project_discovery_readonly": discovery_readonly}


def main():
    results = probes()
    print(json.dumps({"containment": results, "identity": {"uid": os.getuid(), "gid": os.getgid(),
                                                         "groups": os.getgroups()}}), flush=True)
    if not all(results.values()):
        return 1
    mode = sys.argv[2]
    if mode == "probes":
        return 0
    if mode == "timeout":
        # Synthetic descendant deliberately outlives its parent. The launcher
        # timeout kills the namespace, including new-session descendants.
        subprocess.Popen(["/bin/python3", "-I", "-B", "-c",
                          "import time; time.sleep(20); open('/project/late','w').write('escaped')"],
                         start_new_session=True)
        time.sleep(20)
        return 1
    server = HTTPServer(("127.0.0.1", 0), Shim)
    server.timeout = 0.1
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        if mode == "outage":
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
            conn.request("POST", ROUTE, b"{}", {"Content-Type": "application/json"})
            response = conn.getresponse()
            ok = response.status == 503
            response.read()
            conn.close()
            print(json.dumps({"relay_outage_denied": ok}), flush=True)
            return 0 if ok else 1
        # Private generated configuration, never the installed host tech-lead.
        config = {"$schema": "https://opencode.ai/config.json", "username": "synthetic",
                  "enabled_providers": ["azure"], "model": "azure/synthetic-deployment",
                  "small_model": "azure/synthetic-deployment", "default_agent": "tech-lead",
                  "share": "disabled", "autoupdate": False, "snapshot": False,
                  "plugin": [], "mcp": {}, "lsp": False, "formatter": False,
                  "permission": {"*": "deny"}, "compaction": {"auto": False, "prune": False},
                  "agent": {"tech-lead": {"mode": "primary", "prompt": "Reply with the synthetic stub text.",
                                          "permission": {"*": "deny"}}},
                  "provider": {"azure": {"npm": "@ai-sdk/azure", "options": {
                      "baseURL": f"http://127.0.0.1:{port}/openai/v1", "apiKey": "synthetic-not-a-secret",
                      "useDeploymentBasedUrls": False,
                      "timeout": 12000 if mode == "operator-live" else 3000,
                      "headerTimeout": 12000 if mode == "operator-live" else 3000,
                      "chunkTimeout": 3000, "maxRetries": 0},
                      "models": {"synthetic-deployment": {"name": "Synthetic", "toolcall": False,
                                 "limit": {"context": 64000, "output": 256},
                                 "options": {"store": False, "maxOutputTokens": 256}}}}}}
        with open("/tmp/generated.json", "w") as stream:
            json.dump(config, stream)
        # exec is supervised by the host launcher; never buffer unlimited output
        # here. Keep the shim alive while OpenCode runs; no live provider exists.
        process = subprocess.Popen(["/bin/opencode", "--print-logs", "--log-level", "ERROR", "run", "--dir", "/project", "--agent", "tech-lead",
                                    "--model", "azure/synthetic-deployment", "--format", "json",
                                    "Return IMP002_SYNTHETIC_OK"], stdin=subprocess.DEVNULL)
        return process.wait(timeout=15)
    finally:
        server.shutdown()
        thread.join(4)
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
