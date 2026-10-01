"""Pure joined-fixture client regressions: in-memory wire bytes, no listeners/DB."""

import importlib.util
import io
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPResponse
from pathlib import Path
from unittest.mock import Mock, patch

PATH = Path(__file__).resolve().parents[1] / "api/tests/imp024_http.py"
SPEC = importlib.util.spec_from_file_location("imp024_http_test", PATH)
client_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client_module)


def wire(status=200, data=None, cookies=()):
    body = json.dumps(data or {}).encode()
    return (
        f"HTTP/1.1 {status} Fixture\r\nContent-Length: {len(body)}\r\n".encode()
        + b"".join(f"Set-Cookie: {cookie}\r\n".encode() for cookie in cookies)
        + b"\r\n" + body
    )


class Connection:
    def __init__(self, raw, entered=None, release=None):
        self.sock = Mock()
        self.sock.makefile.return_value = io.BufferedReader(io.BytesIO(raw))
        self.response = HTTPResponse(self.sock)
        self.entered, self.release = entered, release
        self.closed = False

    def connect(self):
        pass

    def request(self, method, path, body, headers):
        self.sent = (method, path, body, {key.lower(): value for key, value in headers.items()})
        if self.entered is not None:
            self.entered.set()
            if not self.release.wait(2):
                raise AssertionError("test concurrent request did not release")

    def getresponse(self):
        self.response.begin()
        return self.response

    def close(self):
        self.closed = True


class ClientTests(unittest.TestCase):
    def test_real_cookiejar_login_rotation_error_status_and_json_requests(self):
        connections = [
            Connection(wire(data={"csrf_token": "preauth"}, cookies=("impostr_csrf=preauth; Path=/",))),
            Connection(wire(cookies=("impostr_session=first; Path=/; HttpOnly", "impostr_csrf=active; Path=/"))),
            Connection(wire(status=202, data={"state": "queued"})),
            Connection(wire(status=401, data={"detail": "Authentication required"})),
            Connection(wire(cookies=("impostr_session=second; Path=/; HttpOnly", "impostr_csrf=rotated; Path=/"))),
            Connection(wire(cookies=("impostr_session=; Path=/; Max-Age=0",))),
        ]
        client = client_module.Client("http://127.0.0.1:12345")
        with patch.object(client_module.http.client, "HTTPConnection", side_effect=connections):
            self.assertEqual(client.get("/api/auth/csrf").json()["csrf_token"], "preauth")
            self.assertEqual(client.cookies.get("impostr_csrf"), "preauth")
            client.post("/api/auth/login", json={"username": "synthetic", "password": "fake"}, headers={"X-CSRF-Token": "preauth"})
            result = client.put("/api/draft", json={"content": "café\r\n"})
            self.assertEqual((result.status_code, result.json()), (202, {"state": "queued"}))
            result = client.get("/api/denied")
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.json(), {"detail": "Authentication required"})
            client.post("/api/auth/login", json={})
            self.assertEqual(client.cookies.get("impostr_session"), "second")
            self.assertEqual(client.cookies.get("impostr_csrf"), "rotated")
            client.get("/api/clear")
            self.assertIsNone(client.cookies.get("impostr_session"))
        self.assertIn("impostr_csrf=preauth", connections[1].sent[3]["cookie"])
        self.assertEqual(connections[1].sent[3]["x-csrf-token"], "preauth")
        self.assertIn("impostr_session=first", connections[2].sent[3]["cookie"])
        self.assertEqual(json.loads(connections[2].sent[2]), {"content": "café\r\n"})
        self.assertEqual(connections[2].sent[3]["content-type"], "application/json")
        self.assertTrue(all(connection.closed for connection in connections))
        client.close()

    def test_chunked_sse_is_incremental_and_does_not_lock_concurrent_http(self):
        first = b": heartbeat\n\n"
        second = "event: chat\ndata: café\n\n".encode()
        raw = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + b"".join(
            f"{len(piece):x}\r\n".encode() + piece + b"\r\n" for piece in (first, second)
        ) + b"0\r\n\r\n"
        stream_connection = Connection(raw)
        entered, release = threading.Event(), threading.Event()
        save_connection = Connection(wire(data={"saved": True}), entered, release)
        client = client_module.Client("http://127.0.0.1:12345")
        with patch.object(client_module.http.client, "HTTPConnection", side_effect=(stream_connection, save_connection)):
            with client.stream("GET", "/api/stream") as response:
                self.assertEqual(response.status_code, 200)
                lines = response.iter_lines()
                self.assertEqual(next(lines), ": heartbeat")
                # Not prebuffered into a complete body before yielding the first line.
                self.assertIsNotNone(stream_connection.response.fp)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    saved = pool.submit(client.put, "/api/save", json={"text": "synthetic"})
                    self.assertTrue(entered.wait(1))
                    self.assertIsNone(client.cookies.get("missing"))  # HTTP does not hold jar lock.
                    self.assertEqual(list(lines), ["", "event: chat", "data: café", ""])
                    release.set()
                    self.assertEqual(saved.result(timeout=2).json(), {"saved": True})
        self.assertTrue(stream_connection.closed and save_connection.closed)
        client.close()

    def test_timeout_and_early_stream_exit_close_owned_connections(self):
        client = client_module.Client("http://127.0.0.1:12345")
        failing = Connection(wire())
        failing.request = Mock(side_effect=TimeoutError("not retained"))
        with patch.object(client_module.http.client, "HTTPConnection", return_value=failing):
            with self.assertRaises(client_module.TransportError) as failure:
                client.post("/api/turn", json={})
        self.assertNotIn("not retained", str(failure.exception))
        self.assertEqual(failing.request.call_count, 1)  # Never retry uncertain mutations.
        self.assertTrue(failing.closed)
        self.assertEqual(client.connections, set())
        active = Connection(wire(data={"unused": True}))
        with patch.object(client_module.http.client, "HTTPConnection", return_value=active):
            with client.stream("GET", "/api/stream"):
                pass
        self.assertTrue(active.closed)
        stalled = Connection(wire())
        with patch.object(client_module.http.client, "HTTPConnection", return_value=stalled), \
                patch.object(client_module, "Timer") as timer:
            with client.stream("GET", "/api/stream") as stream:
                self.assertEqual(timer.call_args.args[0], 35)
                timer.call_args.args[1]()  # Hard deadline closes the owned socket.
                stalled.sock.shutdown.assert_called_once()
                stream.response.readline = Mock(side_effect=TimeoutError("private detail"))
                with self.assertRaises(client_module.TransportError):
                    next(stream.iter_lines())
            timer.return_value.cancel.assert_called_once()
        self.assertTrue(stalled.closed)
        client.close()

    def test_no_httpx_import_or_external_redirect_proxy_transport(self):
        client = client_module.Client("http://127.0.0.1:12345")
        for path in ("https://example.invalid/", "//example.invalid/", "/api#fragment"):
            with self.assertRaises(ValueError):
                client.get(path) if path.startswith("/") else client.request("GET", path)
        redirect = Connection(b"HTTP/1.1 302 Found\r\nLocation: https://example.invalid/\r\nContent-Length: 0\r\n\r\n")
        with patch.object(client_module.http.client, "HTTPConnection", return_value=redirect) as create:
            self.assertEqual(client.get("/api/redirect").status_code, 302)
            self.assertEqual(create.call_count, 1)
        client.close()
        self.assertNotIn("httpx", client_module.__dict__)


if __name__ == "__main__":
    unittest.main()
