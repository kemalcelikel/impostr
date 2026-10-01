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
from test_imp002_diagnostic import synthetic_ancestor

import imp002_prototype as prototype
import imp002_transport as transport
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


class InspectionTests(unittest.TestCase):
    """Drive the real report path with injected synthetic failures, NEVER the resolver."""
    def inspect(self, *, failure=None, effect=None, contract=None, runtime=None):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(prototype.sys, "argv", ["imp002_prototype.py", "operator-inspect",
                                                  "--contract-sha256", "0" * 64]), \
                patch.object(prototype, "check_runtime", side_effect=runtime) as check, \
                patch.object(transport, "resolve_operator_contract", side_effect=failure or effect,
                             return_value=contract) as resolver, \
                patch.object(transport, "HTTPSInference") as inference, \
                patch.object(prototype, "run") as worker, \
                patch.object(prototype.sys, "stdout", output), \
                patch.object(prototype.sys, "stderr", errors):
            code = prototype.main()
        check.assert_called_once_with()
        worker.assert_not_called()
        inference.assert_not_called()
        self.assertEqual(errors.getvalue(), "")
        if runtime is not None:
            resolver.assert_not_called()
        else:
            resolver.assert_called_once_with()
        return code, json.loads(output.getvalue())

    def assert_failure(self, reason, **kwargs):
        self.assertEqual(self.inspect(**kwargs), (1, {
            "success": False, "operator_capability_unavailable": True,
            "reason_code": reason, "network_used": False,
        }))

    def test_model_and_configuration_shape_categories_without_resolver(self):
        from test_imp002_transport import KEY, settings
        configs = [(None, "configuration_unsupported"),
                   ({"provider": []}, "configuration_unsupported"),
                   ({"provider": {"azure": []}}, "configuration_unsupported"),
                   ({"provider": {"azure": {"options": []}}}, "configuration_unsupported"),
                   ({"disabled_providers": None}, "configuration_unsupported"),
                   ({"enabled_providers": 1}, "configuration_unsupported")]
        for models in ({}, [], {transport.TARGET: []}, {transport.TARGET: {"id": "synthetic unsupported"}}):
            config = settings()
            config["provider"]["azure"]["models"] = models
            configs.append((config, "model_unsupported"))
        for config, reason in configs:
            with self.subTest(reason=reason, config=config):
                self.assert_failure(reason, effect=lambda: transport.contract_from_settings(
                    config, {"type": "api", "key": KEY}))

    def test_ssh_session_metadata_passes_guard_without_private_discovery(self):
        environment = {"SSH_CONNECTION": "192.0.2.1 1234 192.0.2.2 22",
                       "SSH_CLIENT": "192.0.2.1 1234 22", "SSH_TTY": "/dev/pts/1",
                       "TERM": "xterm-256color", "XDG_SESSION_ID": "synthetic-session",
                       "XDG_SESSION_TYPE": "tty", "XDG_SESSION_CLASS": "user",
                       "XDG_SESSION_DESKTOP": "synthetic-desktop", "XDG_CURRENT_DESKTOP": "synthetic-desktop",
                       "XDG_SEAT": "seat0", "XDG_VTNR": "1"}
        original = environment.copy()
        with patch.object(transport.os, "environ", environment), \
                patch.object(transport.os, "getuid", return_value=1000), \
                patch.object(transport.os, "getgid", return_value=1000), \
                patch.object(transport, "private_json") as private, \
                patch.object(transport.Path, "exists") as discovery, \
                patch.object(transport, "HTTPSInference") as inference:
            transport.check_operator_context()
        self.assertEqual(environment, original)
        private.assert_not_called()
        discovery.assert_not_called()
        inference.assert_not_called()

    def test_environment_override_offline_guard_without_private_discovery(self):
        overrides = ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT",
                     "OPENCODE_AUTH_CONTENT", "OPENCODE_TEST_HOME", "OPENCODE_TEST_MANAGED_CONFIG_DIR",
                     "AZURE_API_KEY", "AZURE_COGNITIVE_SERVICES_RESOURCE_NAME",
                     "OPENCODE_SYNTHETIC_SECRET_NAME", "AZURE_SYNTHETIC_SECRET_NAME", "XDG_SYNTHETIC_SECRET_NAME",
                     "XDG_SESSION_CONFIG_HOME")
        for name in overrides:
            environment = {"SSH_TTY": "/dev/pts/1", "XDG_SESSION_ID": "synthetic-session",
                           name: "synthetic-secret-value"}
            with self.subTest(name=name), \
                    patch.object(transport.os, "environ", environment), \
                    patch.object(transport.os, "getuid", return_value=1000), \
                    patch.object(transport.os, "getgid", return_value=1000), \
                    patch.object(transport, "private_json") as private, \
                    patch.object(transport.Path, "exists") as discovery:
                self.assert_failure("environment_override", effect=transport.check_operator_context)
                private.assert_not_called()
                discovery.assert_not_called()

    def test_synthetic_file_parse_permissions_and_unavailable_categories(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="imp002-inspect-test-") as name, synthetic_ancestor():
            path = Path(name) / "synthetic-private-name.json"
            for body, reason in [("{synthetic-secret-value", "file_parse"),
                                 ('{"synthetic-secret-key":1,"synthetic-secret-key":2}', "file_parse"),
                                 ("[]", "configuration_unsupported")]:
                path.write_text(body)
                path.chmod(0o600)
                with self.subTest(reason=reason):
                    self.assert_failure(reason, effect=lambda: transport.private_json(path))
            path.chmod(0o666)
            self.assert_failure("file_permissions", effect=lambda: transport.private_json(path))
            for error, reason in [(PermissionError("synthetic-secret-value"), "file_permissions"),
                                  (FileNotFoundError("synthetic-private-name"), "file_unavailable")]:
                with patch.object(transport.os, "open", side_effect=error):
                    self.assert_failure(reason, effect=lambda: transport.private_json(path))

    def test_runtime_mismatch_and_unavailable_stop_before_resolver(self):
        # Keep the real runtime check but inject every identity/digest operation.
        with patch.object(prototype.os, "getuid", return_value=1000), \
                patch.object(prototype.os, "getgid", return_value=1000), \
                patch.object(prototype, "digest", return_value="synthetic-drift"):
            self.assert_failure("runtime_mismatch", runtime=prototype.check_runtime)
        with patch.object(prototype.os, "getuid", return_value=0):
            self.assert_failure("runtime_mismatch", runtime=prototype.check_runtime)
        with patch.object(prototype.os, "getuid", return_value=1000), \
                patch.object(prototype.os, "getgid", return_value=1000), \
                patch.object(prototype, "digest", side_effect=PermissionError("synthetic-private-name")):
            self.assert_failure("runtime_unavailable", runtime=prototype.check_runtime)

    def test_unknown_exception_messages_types_chains_and_reason_never_rendered(self):
        secret = "synthetic-secret-value /synthetic/private-name SYNTHETIC_SECRET_ENV=https://secret.invalid"
        categorized = transport.Unavailable(secret, reason="file_parse")
        categorized.__cause__ = ValueError(secret)
        self.assert_failure("file_parse", failure=categorized)
        altered = transport.Unavailable(secret, reason="file_parse")
        altered.reason = secret  # Output rechecks allowlist even after mutation.
        for error in (ValueError(secret), KeyError(secret), type("SyntheticSecretException", (Exception,), {})(secret),
                      transport.Unavailable(secret), transport.Unavailable(secret, reason=secret), altered):
            self.assert_failure("unknown", failure=error)
        self.assert_failure("unknown", runtime=ValueError(secret))

    def test_inspection_success_and_live_failure_contracts_unchanged(self):
        contract = transport.Contract("https://unit.example.invalid/openai/v1/responses",
                                      "synthetic-deployment", "synthetic-not-a-secret")
        self.assertEqual(self.inspect(contract=contract), (0, {
            "operator_contract_resolved": True, "contract_sha256": contract.fingerprint,
            "network_used": False, "credentials_disclosed": False,
        }))
        for failure in (transport.Unavailable("synthetic-secret", reason="file_parse"), None):
            output = io.StringIO()
            with patch.object(prototype.sys, "argv", ["imp002_prototype.py", "operator-live"]), \
                    patch.object(prototype, "check_runtime"), \
                    patch.object(transport, "resolve_operator_contract", side_effect=failure, return_value=contract), \
                    patch.object(transport, "HTTPSInference") as inference, \
                    patch.object(prototype, "run") as worker, \
                    patch.object(prototype.sys, "stdout", output):
                self.assertEqual(prototype.main(), 1)
            self.assertEqual(json.loads(output.getvalue()), {
                "success": False, "operator_capability_unavailable": True,
            })
            inference.assert_not_called()
            worker.assert_not_called()

    def test_selected_input_success_and_refusal_reports_are_nonsecret(self):
        from test_imp002_transport import KEY, settings
        config = settings()
        config["provider"]["azure"]["options"] = {}
        environment = {"XDG_CONFIG_HOME": "/synthetic-private/config", "XDG_DATA_HOME": "/synthetic-private/data",
                       "AZURE_RESOURCE_NAME": "synthetic-resource"}
        files = {"opencode.json": config, "auth.json": {"azure": {"type": "api", "key": KEY}}}
        effect = lambda: transport.contract_from_inputs(environment, lambda path, **_: files.get(path.name))
        code, report = self.inspect(effect=effect)
        self.assertEqual(code, 0)
        self.assertEqual(set(report), {"operator_contract_resolved", "contract_sha256", "network_used", "credentials_disclosed"})
        self.assertFalse(report["network_used"])
        self.assertFalse(report["credentials_disclosed"])
        for private in (KEY, "synthetic-private", "synthetic-resource", "openai.azure.com"):
            self.assertNotIn(private, json.dumps(report))
        config["provider"]["azure"]["options"]["baseURL"] = KEY
        self.assert_failure("configuration_unsupported", effect=effect)
        environment["AZURE_OTHER"] = KEY
        self.assert_failure("environment_override", effect=effect)


if __name__ == "__main__":
    unittest.main()
