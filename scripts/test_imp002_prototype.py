"""Focused synthetic inference/launcher failures; no credentials or live provider.

Run: /usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp002_*.py'
Namespace integration is an explicit operator command, not an automatic test gate.
"""

import copy
import http.client
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import imp002_prototype as prototype
from imp002_relay import Denied, MAX_CALLS, MAX_REQUEST, MODEL, ROUTE, SyntheticRelay, read_request, validate


def request():
    return {"model": MODEL, "stream": True, "store": False, "max_output_tokens": 256,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "synthetic"}]}]}


class RelayTests(unittest.TestCase):
    def test_measured_text_shapes_and_session_cache_hint(self):
        data = request()
        data["input"].insert(0, {"role": "system", "content": "synthetic system"})
        data["prompt_cache_key"] = "synthetic-session"
        normalized = validate("POST", ROUTE, json.dumps(data).encode())
        self.assertNotIn("prompt_cache_key", normalized)
        self.assertEqual(normalized["input"][0]["content"], "synthetic system")

    def test_reject_remote_fetch_tools_state_and_foreign_model(self):
        changes = [
            {"tools": [{"type": "web_search_preview"}]},
            {"tools": [{"type": "function", "name": "synthetic"}]},
            {"previous_response_id": "foreign"}, {"background": True},
            {"store": True}, {"model": "foreign"}, {"max_output_tokens": 100000},
            {"max_output_tokens": True}, {"stream": False},
            {"input": [{"role": "user", "content": [{"type": "input_image", "image_url": "https://example.invalid"}]}]},
            {"input": [{"role": "user", "content": [{"type": "input_file", "file_id": "foreign"}]}]},
        ]
        for change in changes:
            with self.subTest(change=list(change)):
                data = copy.deepcopy(request())
                data.update(change)
                with self.assertRaises(Denied):
                    validate("POST", ROUTE, json.dumps(data).encode())
        for method, route in [("CONNECT", ROUTE), ("GET", ROUTE), ("POST", ROUTE + "/resp_foreign"),
                              ("POST", "http://example.invalid/responses"), ("POST", "/session"),
                              ("POST", ROUTE + "?api-version=arbitrary")]:
            with self.subTest(method=method, route=route), self.assertRaises(Denied):
                validate(method, route, json.dumps(request()).encode())

    def test_duplicate_json_nonfinite_and_request_size(self):
        for body in [b'{"model":"one","model":"two"}', b'{"number":NaN}', b"[", b"x" * (MAX_REQUEST + 1)]:
            with self.assertRaises(Denied):
                validate("POST", ROUTE, body)

    def test_framing_denies_auth_chunked_and_duplicate_lengths(self):
        import io
        for headers in ["Authorization: synthetic\r\n", "api-key: synthetic\r\n",
                        "Transfer-Encoding: chunked\r\n", "Content-Length: 2\r\n",
                        "Content-Length: -1\r\n"]:
            data = (f"POST {ROUTE} HTTP/1.1\r\nContent-Type: application/json\r\n"
                    f"Content-Length: 2\r\n{headers}\r\n{{}}").encode()
            with self.assertRaises(Denied):
                read_request(io.BytesIO(data))

    def test_real_unix_socket_stream_call_bound_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="imp002-test-", dir="/tmp/opencode") as directory:
            path = Path(directory) / "inference.sock"
            with SyntheticRelay(path, lifetime=10) as relay:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                for index in range(MAX_CALLS + 1):
                    body = json.dumps(request()).encode()
                    with socket.socket(socket.AF_UNIX) as connection:
                        connection.settimeout(4)
                        connection.connect(str(path))
                        connection.sendall((f"POST {ROUTE} HTTP/1.1\r\nContent-Type: application/json\r\n"
                                            f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
                        response = http.client.HTTPResponse(connection)
                        response.begin()
                        output = response.read()
                        self.assertEqual(response.status, 200 if index < MAX_CALLS else 403)
                        if index < MAX_CALLS:
                            self.assertIn(b"response.completed", output)
                self.assertEqual(relay.denied, 1)
            self.assertFalse(path.exists())
            self.assertFalse(relay.thread.is_alive())


class LauncherTests(unittest.TestCase):
    def test_main_capability_failure_reports_sanitized_json_without_launch(self):
        output = io.StringIO()
        with patch.object(prototype.sys, "argv", ["imp002_prototype.py", "synthetic"]), \
                patch.object(prototype, "check_runtime", side_effect=prototype.CapabilityError("synthetic-private-detail")), \
                patch.object(prototype.subprocess, "Popen") as child, \
                patch.object(prototype.sys, "stdout", output):
            self.assertEqual(prototype.main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {"success": False, "capability_error": "CapabilityError"})
        self.assertNotIn("synthetic-private-detail", output.getvalue())
        child.assert_not_called()

    def test_mandatory_namespace_and_narrow_mounts(self):
        args = prototype.command(Path("/tmp/opencode/synthetic"), "probes", 12345)
        for flag in ["--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts",
                     "--clearenv", "--die-with-parent", "--new-session"]:
            self.assertIn(flag, args)
        for flag in ["--unshare-user-try", "--share-net", "--dev-bind", "--bind-try"]:
            self.assertNotIn(flag, args)
        self.assertNotIn("/home/kemal", args)
        self.assertNotIn("/run", args)
        self.assertNotIn("/usr", args)
        for directory in (".opencode", ".claude", ".agents"):
            index = args.index(f"/project/{directory}")
            self.assertEqual(args[index - 2], "--ro-bind")
            self.assertTrue(args[index - 1].endswith("/empty"))

    def test_bad_pin_never_launches(self):
        with patch.object(prototype, "digest", return_value="changed"), patch.object(prototype.subprocess, "Popen") as child:
            with self.assertRaises(prototype.CapabilityError):
                prototype.check_runtime()
            child.assert_not_called()

    def test_launcher_failure_no_host_fallback(self):
        with self.assertRaises(FileNotFoundError):
            prototype.bounded_run(["/synthetic-missing-bwrap"])

    def test_output_and_time_bounds_kill_child(self):
        code, reason, output = prototype.bounded_run(
            ["/usr/bin/python3", "-I", "-B", "-c", "import os; os.write(1,b'x'*4096)"], max_output=100)
        self.assertEqual(reason, "output-limit")
        self.assertLessEqual(len(output), 100)
        code, reason, _ = prototype.bounded_run(
            ["/usr/bin/python3", "-I", "-B", "-c", "import time; time.sleep(2)"], timeout=0.1)
        self.assertEqual(reason, "timeout")
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
