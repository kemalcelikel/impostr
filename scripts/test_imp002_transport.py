"""Synthetic transport tests only: no operator resolver or real network/auth.

Use connected socketpairs for bounded native HTTP/SSE transport integration.
The fixed TLS dialer is tested with mocks; no real services are exposed.
"""

import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import imp002_transport as transport
from imp002_relay import MAX_RESPONSE, ROUTE, SyntheticRelay, stub_response, validate
from imp002_worker import Shim
from http.server import HTTPServer
from test_imp002_prototype import request


KEY = "synthetic-credential-not-real"
ENDPOINT = "https://unit.example.invalid/openai/v1/responses?api-version=v1"


def settings():
    return {"provider": {"azure": {"npm": "@ai-sdk/azure", "options": {
        "baseURL": "https://unit.example.invalid/openai/v1"},
        "models": {"gpt-6.1-sol": {"id": "synthetic-deployment"}}}}}


class ControlledHTTP(http.client.HTTPConnection):
    def __init__(self, sock):
        super().__init__("controlled.invalid", timeout=1)
        self.sock = sock
        self.closed = threading.Event()

    def abort(self):
        self.closed.set()
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class Harness:
    def __init__(self, status="200 OK", body=None, pause=False):
        self.client, self.server = socket.socketpair()
        self.client.settimeout(1)
        self.server.settimeout(1)
        self.connection = ControlledHTTP(self.client)
        self.inference = object.__new__(transport.HTTPSInference)
        self.inference.contract = transport.Contract(ENDPOINT, "synthetic-deployment", KEY)
        self.inference.connection = lambda: self.connection
        self.status = status
        self.body = stub_response().replace(b"IMP002_SYNTHETIC_OK", b"IMP002_SYNTHETIC_OK" * 3) if body is None else body
        self.pause = pause
        self.seen = None
        self.started = threading.Event()
        self.release = threading.Event()
        self.errors = []
        self.thread = threading.Thread(target=self.run)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.release.set()
        self.connection.abort()
        self.connection.close()
        self.thread.join(2)
        self.server.close()
        if self.thread.is_alive() or self.errors:
            raise AssertionError("controlled server cleanup")

    def run(self):
        try:
            with self.server.makefile("rb") as stream:
                line = stream.readline().decode()
                headers = {}
                while True:
                    value = stream.readline()
                    if value == b"\r\n":
                        break
                    name, value = value.decode().strip().split(":", 1)
                    headers[name.lower()] = value.strip()
                body = stream.read(int(headers["content-length"]))
                self.seen = (line, headers, json.loads(body))
            self.server.sendall((f"HTTP/1.1 {self.status}\r\nContent-Type: text/event-stream\r\n"
                                 "Location: https://never-follow.invalid/\r\n"
                                 "Set-Cookie: synthetic-upstream-secret\r\nConnection: close\r\n\r\n").encode())
            if self.pause:
                # Deliver a real delta before final completion, then wait for
                # either test release or cancellation closing the client peer.
                partial = self.body.split(b"event: response.output_text.done")[0]
                self.server.sendall(partial)
                self.started.set()
                while not self.release.wait(0.01):
                    try:
                        self.server.settimeout(0.02)
                        if not self.server.recv(1):
                            return
                    except socket.timeout:
                        pass
                self.server.sendall(self.body[len(partial):])
            else:
                self.server.sendall(self.body)
                self.started.set()
        except OSError:
            pass  # expected client abort/timeout
        except Exception as exc:
            self.errors.append(type(exc).__name__)
        finally:
            self.server.close()


class ContractTests(unittest.TestCase):
    def test_dns_nonpublic_address_and_dns_timeout_are_fail_closed(self):
        import subprocess
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:8.8.8.8"):
            result = subprocess.CompletedProcess([], 0, json.dumps([[socket.AF_INET6 if ":" in address else socket.AF_INET, address]]).encode(), b"")
            with self.subTest(address=address), patch.object(transport.subprocess, "run", return_value=result), self.assertRaises(transport.Unavailable):
                transport.resolve_addresses("unit.example.invalid")
        with patch.object(transport.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic", 3)), self.assertRaises(transport.Unavailable):
            transport.resolve_addresses("unit.example.invalid")

    def test_literal_sdk_route_and_model_mapping_without_private_resolver(self):
        config = settings()
        contract = transport.contract_from_settings(config, {"type": "api", "key": KEY})
        self.assertEqual(contract.host, "unit.example.invalid")
        self.assertEqual(contract.route, "/openai/v1/responses")
        self.assertEqual(contract.deployment, "synthetic-deployment")
        self.assertNotIn(KEY, repr(contract))
        config["provider"]["azure"]["options"] = {"resourceName": "synthetic", "useDeploymentBasedUrls": True,
                                                       "apiVersion": "2025-01-01-preview"}
        contract = transport.contract_from_settings(config, {"type": "api", "key": KEY})
        self.assertEqual(contract.route, "/openai/deployments/synthetic-deployment/responses?api-version=2025-01-01-preview")

    def test_unsupported_existing_auth_or_endpoint_fails_closed(self):
        for auth in [None, {"type": "oauth", "access": KEY}, {"type": "api", "key": KEY, "metadata": {"resourceName": "other"}}]:
            with self.subTest(auth=auth and auth["type"]), self.assertRaises(transport.Unavailable):
                transport.contract_from_settings(settings(), auth)
        for option in [{"headers": {"Authorization": KEY}}, {"apiKey": "{env:AZURE_API_KEY}"},
                       {"baseURL": "http://localhost/openai/v1"}, {"baseURL": "https://unit.example.invalid/admin"},
                       {"baseURL": "https://unit.example.invalid/openai/v1?secret=synthetic"}]:
            config = settings()
            config["provider"]["azure"]["options"].update(option)
            with self.subTest(fields=list(option)), self.assertRaises(transport.Unavailable):
                transport.contract_from_settings(config, {"type": "api", "key": KEY})

    def test_provider_api_override_cannot_be_ignored_for_resource_endpoint(self):
        config = settings()
        provider = config["provider"]["azure"]
        provider["api"] = "https://override.example.invalid/openai/v1"
        provider["options"] = {"resourceName": "synthetic"}
        with self.assertRaises(transport.Unavailable):
            transport.contract_from_settings(config, {"type": "api", "key": KEY})

    def test_direct_tls_pinned_address_sni_and_explicit_ca_no_proxy(self):
        with patch.object(transport, "resolve_addresses", return_value=[(socket.AF_INET, "203.0.113.1")]), \
                patch.object(transport.ssl, "SSLContext") as context_factory, \
                patch.dict(transport.os.environ, {"HTTPS_PROXY": "http://never.invalid", "SSL_CERT_FILE": "/never"}):
            inference = transport.HTTPSInference(transport.Contract(ENDPOINT, "synthetic-deployment", KEY))
            context_factory.return_value.load_verify_locations.assert_called_once_with(cafile=transport.CA_FILE)
            connection = inference.connection()
            with patch.object(transport.socket, "socket") as socket_factory:
                connection.connect()
                socket_factory.return_value.connect.assert_called_once_with(("203.0.113.1", 443))
                context_factory.return_value.wrap_socket.assert_called_once_with(
                    socket_factory.return_value, server_hostname="unit.example.invalid", do_handshake_on_connect=False)
                connection.abort()

    def test_private_file_reader_only_synthetic_regular_bounded_nonsymlink(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="imp002-auth-test-") as name:
            path = Path(name) / "fake.json"
            path.write_text(json.dumps({"synthetic": True}))
            path.chmod(0o600)
            self.assertEqual(transport.private_json(path), {"synthetic": True})
            link = Path(name) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                transport.private_json(link)
            path.chmod(0o666)
            with self.assertRaises(transport.Unavailable):
                transport.private_json(path)


class StreamingTests(unittest.TestCase):
    def test_real_relay_sanitizes_transport_failure_and_shutdown_cancels(self):
        for shutdown in (False, True):
            with self.subTest(shutdown=shutdown), tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="imp002-relay-test-") as name, Harness("200 OK" if shutdown else "401 Unauthorized", pause=shutdown) as harness:
                path = Path(name) / "relay.sock"
                relay = SyntheticRelay(path, lifetime=5, transport=harness.inference)
                connection = socket.socket(socket.AF_UNIX)
                connection.settimeout(2)
                try:
                    with relay:
                        connection.connect(str(path))
                        body = json.dumps(request()).encode()
                        connection.sendall((f"POST {ROUTE} HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body)
                        response = http.client.HTTPResponse(connection)
                        response.begin()
                        if not shutdown:
                            self.assertEqual(response.status, 503)
                            self.assertEqual(response.read(), b'{"error":"relay unavailable"}')
                        else:
                            self.assertEqual(response.status, 200)
                            self.assertTrue(harness.started.wait(1))
                    self.assertTrue(harness.connection.closed.wait(1))
                    self.assertFalse(relay.thread.is_alive())
                    self.assertFalse(path.exists())
                finally:
                    connection.close()

    def test_native_incremental_normalization_fixed_headers_and_no_metadata(self):
        with Harness(pause=True) as harness:
            data = request()
            data["prompt_cache_key"] = "synthetic-session"
            normalized = validate("POST", ROUTE, json.dumps(data).encode())
            events = harness.inference.events(normalized, threading.Event(), time.monotonic() + 2)
            output = b""
            first_delta = True
            for event in events:
                output += event
                if first_delta and b"response.output_text.delta" in event:
                    first_delta = False
                    self.assertTrue(harness.started.wait(1))
                    self.assertFalse(harness.release.is_set())
                    harness.release.set()
            self.assertIn(b"response.completed", output)
            self.assertNotIn(b"Set-Cookie", output)
            self.assertNotIn(b"resp_synthetic", output)
            line, headers, sent = harness.seen
            self.assertEqual(line, "POST /openai/v1/responses?api-version=v1 HTTP/1.1\r\n")
            self.assertEqual(headers["api-key"], KEY)
            self.assertEqual(sent["model"], "synthetic-deployment")
            self.assertFalse(sent["store"])
            self.assertNotIn("prompt_cache_key", sent)
            self.assertTrue(harness.connection.closed.is_set())

    def test_redirect_error_malformed_truncated_and_oversize_never_complete(self):
        cases = [("302 Found", KEY.encode()), ("401 Unauthorized", KEY.encode()),
                 ("200 OK", b"event: error\ndata: {\"type\":\"error\",\"message\":\"" + KEY.encode() + b"\"}\n\n"),
                 ("200 OK", stub_response().split(b"event: response.completed")[0]),
                 ("200 OK", b"x" * (MAX_RESPONSE + 1))]
        for status, body in cases:
            with self.subTest(status=status, size=len(body)), Harness(status, body) as harness:
                output = b""
                with self.assertRaises(transport.Unavailable):
                    for event in harness.inference.events(request(), threading.Event(), time.monotonic() + 2):
                        output += event
                self.assertNotIn(KEY.encode(), output)
                self.assertNotIn(b"response.completed", output)
                self.assertTrue(harness.connection.closed.is_set())

    def test_echoed_credential_split_deltas_is_redacted(self):
        redactor = transport.SecretFilter(KEY)
        output = "".join(redactor.feed(piece) for piece in ["hello ", KEY[:9], KEY[9:20], KEY[20:], " done"])
        output += redactor.feed("", final=True)
        self.assertEqual(output, "hello [redacted] done")

    def test_cancel_and_total_deadline_abort_stalled_native_stream(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel), Harness(pause=True) as harness:
                cancelled = threading.Event()
                events = harness.inference.events(request(), cancelled, time.monotonic() + 0.2)
                next(events)
                if cancel:
                    cancelled.set()
                with self.assertRaises(transport.Unavailable):
                    list(events)
                self.assertTrue(harness.connection.closed.is_set())

    def test_real_relay_shim_incremental_stream_disconnect_cleanup(self):
        # HTTPServer is never bound/listening: drive a handler over a socketpair
        # to exercise the real shim without exposing a host service.
        class LocalShim(Shim):
            def __init__(self, sock, server):
                super().__init__(sock, ("127.0.0.1", 0), server)

        with tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="imp002-stream-test-") as name, Harness(pause=True) as harness:
            relay_path = Path(name) / "relay.sock"
            with SyntheticRelay(relay_path, lifetime=5, transport=harness.inference) as relay:
                original_connect = socket.socket.connect

                def connect(sock, address):
                    return original_connect(sock, str(relay_path) if address == "/relay/inference.sock" else address)

                caller, handler = socket.socketpair()
                caller.settimeout(2)
                server = HTTPServer(("127.0.0.1", 0), LocalShim, bind_and_activate=False)
                with patch.object(socket.socket, "connect", connect):
                    child = threading.Thread(target=LocalShim, args=(handler, server))
                    child.start()
                    try:
                        body = json.dumps(request()).encode()
                        caller.sendall((f"POST {ROUTE} HTTP/1.1\r\nHost: fixed\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body)
                        response = http.client.HTTPResponse(caller)
                        response.begin()
                        output = b""
                        while b"response.output_text.delta" not in output:
                            block = response.read1(4096)
                            self.assertTrue(block, "shim stream ended before text delta")
                            output += block
                        self.assertFalse(harness.release.is_set())
                        caller.shutdown(socket.SHUT_RDWR)
                        self.assertTrue(harness.connection.closed.wait(1))
                    finally:
                        caller.close()
                        child.join(2)
                        handler.close()
                        server.server_close()
                    self.assertFalse(child.is_alive())
                self.assertEqual(relay.calls, 1)
            self.assertFalse(relay.thread.is_alive())
            self.assertFalse(relay_path.exists())


if __name__ == "__main__":
    unittest.main()
