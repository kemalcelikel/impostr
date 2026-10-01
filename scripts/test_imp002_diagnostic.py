"""Synthetic inputs ONLY. Never run operator_report or the private CLI diagnostic."""

import copy
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch

import imp002_diagnostic as diagnostic

PRIVATE = "synthetic-private-marker /never/read https://never.example.invalid secret-value"


def absent(_):
    return "absent", None


def synthetic_ancestor():
    """Emulate a secure scratch ancestor; never chmod the existing shared directory.

    /tmp/opencode is group-writable here, intentionally denied by the reader. Only
    that approved scratch inode's metadata is injected; fixture descendants and all
    NOFOLLOW/open checks remain real. Unsafe fixture-directory tests remain unmocked.
    """
    scratch = os.stat("/tmp/opencode")
    original = os.fstat

    def info(fd):
        value = original(fd)
        if (value.st_dev, value.st_ino) == (scratch.st_dev, scratch.st_ino):
            fields = list(value)
            fields[0] = stat.S_IFDIR | 0o755
            return os.stat_result(fields)
        return value

    return patch.object(diagnostic.os, "fstat", side_effect=info)


class DiagnosticTests(unittest.TestCase):
    def test_environment_categories_without_reading_values_or_changing_mapping(self):
        class NamesOnly(dict):
            def __getitem__(self, key):
                raise AssertionError("must not read environment values")

        environment = NamesOnly({name: PRIVATE for name in (
            "XDG_CONFIG_HOME", "XDG_SESSION_ID", "XDG_UNRECOGNIZED_PRIVATE_NAME",
            "OPENCODE_CONFIG_CONTENT", "OPENCODE_CONFIG_DIR", "OPENCODE_AUTH_CONTENT",
            "OPENCODE_UNRECOGNIZED_PRIVATE_NAME", "AZURE_API_KEY", "AZURE_RESOURCE_NAME",
            "AZURE_UNRECOGNIZED_PRIVATE_NAME", "SSH_TTY", "TERM",
        )})
        before = dict(environment)
        self.assertEqual(diagnostic.environment_categories(environment),
                         dict.fromkeys(diagnostic.ENV_FIELDS, True))
        self.assertEqual(dict(environment), before)
        with self.assertRaises(ValueError):
            diagnostic.environment_categories(dict.fromkeys(
                [f"OTHER_{index}" for index in range(diagnostic.MAX_ENV_NAMES + 1)]))

    def test_path_and_unknown_xdg_overrides_never_call_reader_or_read_path_values(self):
        class NoValues(dict):
            def __getitem__(self, key):
                raise AssertionError("override path must not be read")

        for name in (*diagnostic.XDG_DIRECTORIES, *diagnostic.CONFIG_PATHS, "XDG_UNKNOWN"):
            reader = Mock(side_effect=AssertionError("must not inspect any default files"))
            report = diagnostic.collect(NoValues({name: PRIVATE}), reader)
            self.assertEqual(set(report["sources"].values()), {"absent", "uninspected_override"})
            self.assertEqual(report["ambiguity"], {"endpoint": "potential", "model": "potential"})
            reader.assert_not_called()
            self.assertNotIn(PRIVATE, diagnostic.render_report(report))

    def test_inline_config_and_auth_classification_without_precedence_claim(self):
        config = {"plugin": [PRIVATE], "model": PRIVATE, "provider": {PRIVATE: {
            "api": PRIVATE, "options": {"baseURL": PRIVATE, "apiKey": PRIVATE,
                "headers": {"Authorization": "Bearer " + PRIVATE}, "tokenProvider": PRIVATE},
            "models": {PRIVATE: {"id": PRIVATE}},
        }}}
        auth = {PRIVATE: {"type": "oauth", "access": PRIVATE, "refresh": PRIVATE, "expires": 1},
                "another-private-provider": {"type": "api", "key": PRIVATE},
                "private-url": {"type": "wellknown", "key": PRIVATE, "token": PRIVATE}}
        environment = {"OPENCODE_CONFIG_CONTENT": json.dumps(config),
                       "OPENCODE_AUTH_CONTENT": json.dumps(auth), "AZURE_API_KEY": PRIVATE}
        original = copy.deepcopy(environment)
        reader = Mock(side_effect=absent)
        report = diagnostic.collect(environment, reader)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["sources"]["inline_config"], "literal_json")
        self.assertEqual(report["sources"]["inline_auth"], "literal_json")
        self.assertEqual(report["sources"]["default_auth"], "uninspected_override")
        self.assertEqual(report["authentication_observed"], dict.fromkeys(diagnostic.AUTH_FIELDS, True))
        self.assertEqual(report["effective_configuration"], "unestablished")
        self.assertEqual(report["other_sources"], "uninspected")
        self.assertNotIn("default_auth", [call.args[0] for call in reader.call_args_list])
        self.assertEqual(environment, original)
        self.assertNotIn(PRIVATE, diagnostic.render_report(report))

    def test_unsupported_auth_does_not_infer_mechanism_from_names_or_partial_records(self):
        for entry in (None, [], PRIVATE, {"type": PRIVATE, "key": PRIVATE},
                      {"type": "api", "key": []}, {"type": "oauth", "access": PRIVATE},
                      {"type": "oauth", "access": PRIVATE, "refresh": PRIVATE, "expires": True},
                      {"type": "wellknown", "key": PRIVATE}):
            report = diagnostic.collect({"OPENCODE_AUTH_CONTENT": json.dumps({PRIVATE: entry})}, absent)
            observed = report["authentication_observed"]
            self.assertTrue(observed["unsupported"])
            self.assertFalse(any(value for key, value in observed.items() if key != "unsupported"))
            self.assertNotIn(PRIVATE, diagnostic.render_report(report))
        report = diagnostic.collect({"AZURE_API_KEY": PRIVATE}, absent)
        self.assertTrue(report["environment"]["azure_auth"])
        self.assertFalse(report["authentication_observed"]["api_key"])

    def test_auth_metadata_multiple_configs_and_model_override_ambiguity_stay_coarse(self):
        def sources(source):
            if source == "global_json":
                return "literal_json", {"provider": {PRIVATE: {"models": {
                    PRIVATE: {"options": {"baseURL": PRIVATE}},
                }}}}
            if source == "global_named_json":
                return "literal_json", {}
            return "absent", None

        report = diagnostic.collect({}, sources)
        self.assertEqual(report["ambiguity"], {"endpoint": "potential", "model": "potential"})
        report = diagnostic.collect({"OPENCODE_AUTH_CONTENT": json.dumps({PRIVATE: {
            "type": "api", "key": PRIVATE, "metadata": {PRIVATE: PRIVATE},
        }})}, absent)
        self.assertEqual(report["ambiguity"], {"endpoint": "potential", "model": "unknown"})
        self.assertEqual(report["effective_configuration"], "unestablished")
        self.assertNotIn(PRIVATE, diagnostic.render_report(report))

    def test_unsupported_jsonc_duplicates_nonfinite_shape_and_size_are_sanitized(self):
        bodies = ("// " + PRIVATE + "\n{}", '{"key":1,"key":2}', '{"key":NaN}',
                  '["' + PRIVATE + '"]', "{broken " + PRIVATE,
                  "{\"nested\":" + "[" * 100 + "0" + "]" * 100 + "}")
        for body in bodies:
            state, value = diagnostic.parse_literal(body)
            self.assertEqual((state, value), ("unsupported", None))
            report = diagnostic.collect({"OPENCODE_CONFIG_CONTENT": body}, absent)
            self.assertNotIn(PRIVATE, diagnostic.render_report(report))
        self.assertEqual(diagnostic.parse_literal("x" * (diagnostic.MAX_INPUT + 1)), ("too_large", None))

    def test_references_plugins_remote_inputs_have_no_execution_or_expansion(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("no subprocess")), \
                patch.object(socket, "socket", side_effect=AssertionError("no network")), \
                patch.object(diagnostic.os, "open", side_effect=AssertionError("no reference read")):
            for reference in ("{env:PRIVATE_NAME}", "{file:/never/read}"):
                report = diagnostic.collect({"OPENCODE_CONFIG_CONTENT": json.dumps({
                    "provider": {PRIVATE: {"options": {"apiKey": reference}}},
                    "plugin": [PRIVATE], "instructions": [PRIVATE],
                })}, absent)
                self.assertEqual(report["sources"]["inline_config"], "expansion_required")
                self.assertFalse(report["authentication_observed"]["api_key"])
            report = diagnostic.collect({"OPENCODE_CONFIG_CONTENT": json.dumps({
                "plugin": [PRIVATE], "instructions": [PRIVATE],
            }), "OPENCODE_AUTH_CONTENT": json.dumps({PRIVATE: {
                "type": "wellknown", "key": PRIVATE, "token": PRIVATE,
            }})}, absent)
            self.assertTrue(report["authentication_observed"]["wellknown_remote"])
            self.assertNotIn(PRIVATE, diagnostic.render_report(report))

    def test_synthetic_fixed_sources_presence_format_and_auth(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="imp002-diag-test-") as name, \
                synthetic_ancestor():
            root = Path(name)
            paths = {source: root / source for source in diagnostic.SOURCE_FIELDS[2:]}
            paths["global_json"].write_text(json.dumps({"provider": {PRIVATE: {
                "options": {"resourceName": PRIVATE}, "models": {PRIVATE: {"id": PRIVATE}},
            }}}))
            paths["global_json"].chmod(0o600)
            paths["global_jsonc"].write_text("// " + PRIVATE + "\n{}")
            paths["global_jsonc"].chmod(0o600)
            paths["default_auth"].write_text(json.dumps({PRIVATE: {"type": "api", "key": PRIVATE}}))
            paths["default_auth"].chmod(0o600)

            def reader(source):
                return diagnostic.read_fixed_file(paths[source], literal=source not in (
                    "global_jsonc", "global_legacy"))

            report = diagnostic.collect({}, reader)
            self.assertEqual(report["sources"]["global_json"], "literal_json")
            self.assertEqual(report["sources"]["global_named_json"], "absent")
            self.assertEqual(report["sources"]["global_jsonc"], "unsupported_format")
            self.assertEqual(report["sources"]["global_legacy"], "absent")
            self.assertTrue(report["authentication_observed"]["api_key"])
            self.assertNotIn(PRIVATE, diagnostic.render_report(report))

    def test_synthetic_reader_nofollow_owner_permissions_special_files_and_bound(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="imp002-diag-test-") as name, \
                synthetic_ancestor():
            root = Path(name)
            path = root / "fake.json"
            path.write_text(json.dumps({"synthetic": True}))
            path.chmod(0o600)
            self.assertEqual(diagnostic.read_fixed_file(path), ("literal_json", {"synthetic": True}))
            link = root / "link.json"
            link.symlink_to(path)
            self.assertEqual(diagnostic.read_fixed_file(link), ("unsafe", None))
            directory_link = root / "directory-link"
            directory_link.symlink_to(root, target_is_directory=True)
            self.assertEqual(diagnostic.read_fixed_file(directory_link / "fake.json"), ("unsafe", None))
            path.chmod(0o666)
            self.assertEqual(diagnostic.read_fixed_file(path), ("unsafe", None))
            path.chmod(0o600)
            root.chmod(0o777)
            self.assertEqual(diagnostic.read_fixed_file(path), ("unsafe", None))
            root.chmod(0o700)
            with patch.object(diagnostic.os, "getuid", return_value=98765):
                self.assertEqual(diagnostic.read_fixed_file(path), ("unsafe", None))
            fifo = root / "fifo"
            os.mkfifo(fifo, 0o600)
            self.assertEqual(diagnostic.read_fixed_file(fifo), ("unsafe", None))
            path.write_bytes(b"x" * (diagnostic.MAX_INPUT + 1))
            self.assertEqual(diagnostic.read_fixed_file(path), ("too_large", None))
            with patch.object(diagnostic.os, "open", side_effect=PermissionError(PRIVATE)):
                self.assertEqual(diagnostic.read_fixed_file(path), ("unreadable", None))

    def test_report_projection_strips_extra_private_fields_and_rejects_bad_values(self):
        report = diagnostic.empty_report()
        report[PRIVATE] = PRIVATE
        report["sources"][PRIVATE] = PRIVATE
        report["environment"][PRIVATE] = PRIVATE
        self.assertEqual(json.loads(diagnostic.render_report(report)), diagnostic.empty_report())
        for field in ("schema", "status", "network_used", "effective_configuration"):
            tampered = copy.deepcopy(report)
            tampered[field] = PRIVATE
            self.assertEqual(json.loads(diagnostic.render_report(tampered)), diagnostic.empty_report())
        for group, key in (("sources", "inline_config"), ("environment", "xdg_session"),
                           ("authentication_observed", "oauth"), ("ambiguity", "endpoint")):
            tampered = copy.deepcopy(report)
            tampered[group][key] = PRIVATE
            self.assertEqual(json.loads(diagnostic.render_report(tampered)), diagnostic.empty_report())
        report["environment"]["xdg_session"] = 1
        self.assertEqual(json.loads(diagnostic.render_report(report)), diagnostic.empty_report())

    def test_main_injected_report_and_private_error_paths_never_render_details(self):
        # operator_report is ALWAYS mocked; neither resolver nor real diagnostic runs.
        complete = diagnostic.collect({}, absent)
        error = ValueError(PRIVATE)
        error.__cause__ = RuntimeError(PRIVATE)
        for value, failure, expected in ((complete, None, 0), (None, error, 1),
                                         ({"status": PRIVATE}, None, 1)):
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(diagnostic.sys, "argv", ["synthetic-program"]), \
                    patch.object(diagnostic, "operator_report", return_value=value, side_effect=failure), \
                    patch.object(diagnostic.sys, "stdout", output), \
                    patch.object(diagnostic.sys, "stderr", errors):
                self.assertEqual(diagnostic.main(), expected)
            self.assertEqual(errors.getvalue(), "")
            self.assertNotIn(PRIVATE, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["status"],
                             "complete" if expected == 0 else "unavailable")
        output = io.StringIO()
        with patch.object(diagnostic.sys, "argv", ["synthetic-program", PRIVATE]), \
                patch.object(diagnostic, "operator_report") as private, \
                patch.object(diagnostic.sys, "stdout", output):
            self.assertEqual(diagnostic.main(), 1)
        private.assert_not_called()
        self.assertNotIn(PRIVATE, output.getvalue())


if __name__ == "__main__":
    unittest.main()
