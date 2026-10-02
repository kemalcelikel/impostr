"""Pure tests only: no sockets/processes/Docker/parsers/private inputs executed."""

import ast
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from app import pdf_protocol as protocol
sys.modules["pdf_protocol"] = protocol
sys.path.insert(0, str(ROOT / "pdf-extractor"))
from bounded_json import parse
import bounded_json
import process as runner_module
from process import StartupFailure, command, probe_command, startup_category
from structure import pages
from imp017_fixtures import compressed_active, expansion, fixtures, near_cap
import imp017_verify as verifier
import imp017_mount_probe as mount_probe
import bootstrap
import build as pdf_build
import probe as sandbox_probe


def tree():
    return {"version": 2, "encrypt": {"encrypted": False}, "qpdf": [
        {"jsonversion": 2, "calledgetallpages": False, "pushedinheritedpageresources": False}, {
            "trailer": {"value": {"/Root": "1 0 R"}},
            "obj:1 0 R": {"value": {"/Type": "/Catalog", "/Pages": "2 0 R"}},
            "obj:2 0 R": {"value": {"/Type": "/Pages", "/Count": 1, "/Kids": ["3 0 R"]}},
            "obj:3 0 R": {"value": {"/Type": "/Page", "/Parent": "2 0 R"}},
            "obj:4 0 R": {"stream": {"dict": {"/Filter": "/FlateDecode"}}}
        }]}


def ready(text="Unicode café ١\f", count=1):
    return {"v": 1, "status": "ready", "size": 7, "sha256": "a" * 64,
        "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "pages": count, "missing_pages": protocol.coverage(text, count), "label": protocol.LABEL,
        "provenance": {"policy": protocol.POLICY, "qpdf": "11.3.0", "pdftotext": "22.12.0",
                       "build_sha256": "b" * 64}}


class Pipe:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.requested = []
    def recv(self, size):
        self.requested.append(size)
        return self.stream.read(min(size, 3))
    def settimeout(self, _):
        pass


class ProtocolTests(unittest.TestCase):
    def test_fixed_metadata_rejects_paths_options_bool_and_size(self):
        value = {"v": 1, "size": protocol.MAX_ORIGINAL, "sha256": "a" * 64}
        self.assertEqual(protocol.metadata(value), value)
        for bad in ({**value, "filename": "secret.pdf"}, {**value, "path": "/etc/passwd"},
                    {**value, "options": []}, {**value, "size": True},
                    {**value, "size": protocol.MAX_ORIGINAL + 1}, {**value, "sha256": "A" * 64}):
            with self.subTest(bad=bad), self.assertRaises(protocol.PDFError):
                protocol.metadata(bad)

    def test_counts_and_hashes_actual_bytes_without_clipping(self):
        data = b"%PDF-test"
        expected = {"v": 1, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        sink = io.BytesIO()
        protocol.counted([data[:3], data[3:]], sink.write, expected)
        self.assertEqual(sink.getvalue(), data)
        for chunks in ([data, b"extra"], [data[:-1]], [b"x" * len(data)]):
            with self.assertRaises(protocol.PDFError):
                protocol.counted(chunks, lambda _: None, expected)
        with patch.object(protocol, "MAX_ORIGINAL", 4), self.assertRaises(protocol.PDFError):
            protocol.counted([data], sink.write, expected)

    def test_reply_text_coverage_hash_and_provenance(self):
        value = ready("Readable\f\n\f١٢٣\f", 3)
        self.assertEqual(protocol.result(value)["missing_pages"], [2])
        for key, bad in (("missing_pages", []), ("text_sha256", "c" * 64),
                         ("label", "All images read"), ("pages", True),
                         ("provenance", {"policy": "other"})):
            with self.subTest(key=key), self.assertRaises(protocol.PDFError):
                protocol.result({**value, key: bad})
        with self.assertRaises(protocol.PDFError):
            protocol.result(value, {"size": 8, "sha256": "a" * 64})

    def test_zero_text_page_disagreement_invalid_utf8_and_overbounds(self):
        for text, count in (("...\f", 1), ("\f", 1), ("Readable", 1),
                            ("Readable\f\f", 1), ("A\r\f", 1), ("\ud800\f", 1),
                            ("a" * protocol.MAX_TEXT + "\f", 1), ("A\f" * 501, 501)):
            with self.subTest(count=count), self.assertRaises(protocol.PDFError):
                protocol.coverage(text, count)
        self.assertEqual(protocol.coverage("圖١\f", 1), [])

    def test_framing_fragmentation_nested_or_duplicate_rejection(self):
        value = ready()
        self.assertEqual(protocol.receive(Pipe(protocol.encode(value)), time.monotonic() + 1), value)
        for data in (b'{"v":1,"v":2}', b'{"v":NaN}', b'{"x":' + b"[" * 6 + b"0" + b"]" * 6 + b"}"):
            with self.assertRaises(protocol.PDFError):
                protocol.receive(Pipe(struct.pack("!I", len(data)) + data), time.monotonic() + 1)
        pipe = Pipe(struct.pack("!I", protocol.MAX_REPLY + 1))
        with self.assertRaises(protocol.PDFError):
            protocol.receive(pipe, time.monotonic() + 1)
        self.assertEqual(pipe.requested, [4, 1])  # No attempted body read.

    def test_peer_requires_exact_uid_gid_without_real_channel_execution(self):
        class Peer:
            def getsockopt(self, *_):
                return struct.pack("3i", 123, 10001, 10001)
        protocol.peer(Peer(), 10001)
        with self.assertRaises(protocol.PDFError):
            protocol.peer(Peer(), 10002)
        for code in protocol.ERRORS:
            self.assertEqual(protocol.result(protocol.rejected(code))["code"], code)
        with self.assertRaises(protocol.PDFError):
            protocol.result({"v": 1, "status": "rejected", "code": "invalid", "diagnostics": "secret"})


class StructuralTests(unittest.TestCase):
    def check(self, value):
        return pages(json.dumps(value).encode())

    def test_actual_page_tree_not_count_and_resolved_semantics(self):
        self.assertEqual(self.check(tree()), 1)
        value = tree()
        value["qpdf"][1]["obj:5 0 R"] = {"value": "/Pages"}
        value["qpdf"][1]["obj:2 0 R"]["value"]["/Type"] = "5 0 R"
        self.assertEqual(self.check(value), 1)
        for change in (lambda o: o["obj:2 0 R"]["value"].update({"/Count": 2}),
                       lambda o: o["obj:2 0 R"]["value"].update({"/Kids": ["3 0 R", "3 0 R"]}),
                       lambda o: o["obj:3 0 R"]["value"].update({"/Parent": "1 0 R"}),
                       lambda o: o["obj:2 0 R"]["value"].update({"/Kids": ["2 0 R"]}),
                       lambda o: o["obj:2 0 R"]["value"].update({"/Kids": [{"/Type": "/Page"}]}),
                       lambda o: o.update({"obj:6 0 R": {"value": {"/Type": "/Page"}}})):
            value = tree()
            change(value["qpdf"][1])
            with self.assertRaises(protocol.PDFError):
                self.check(value)

    def test_all_objects_nested_unreferenced_actions_and_external_streams(self):
        for dictionary in ({"/S": "/JavaScript"}, {"/JS": "u:alert"}, {"/Type": "/EmbeddedFile"},
                           {"/XFA": "u:payload"}, {"/Subtype": "/RichMedia"},
                           {"/Nested": [{"/AA": "9 0 R"}]}, {"/S": "6 0 R"}):
            value = tree()
            value["qpdf"][1]["obj:5 0 R"] = {"value": dictionary}
            value["qpdf"][1]["obj:6 0 R"] = {"value": "/Launch"}
            with self.subTest(dictionary=dictionary), self.assertRaises(protocol.PDFError):
                self.check(value)
        value = tree()
        value["qpdf"][1]["obj:4 0 R"]["stream"]["dict"]["/F"] = "u:external"
        with self.assertRaises(protocol.PDFError):
            self.check(value)
        # Plain PDF strings are NOT actions/names. qpdf canonical names aren't
        # unescaped a second time (/Java#53cript is a literal '#' name in JSON).
        value = tree()
        value["qpdf"][1]["obj:5 0 R"] = {"value": {"/Note": "u:/JavaScript", "/Custom": "/Java#53cript"}}
        self.assertEqual(self.check(value), 1)

    def test_encryption_repair_dangling_reference_or_stream_data_reject(self):
        for change in (lambda v: v["encrypt"].update({"encrypted": True}),
                       lambda v: v["qpdf"][0].update({"calledgetallpages": True}),
                       lambda v: v["qpdf"][1]["obj:1 0 R"]["value"].update({"/Note": "9 0 R"}),
                       lambda v: v["qpdf"][1]["obj:4 0 R"]["stream"].update({"data": "huge"})):
            value = tree()
            change(value)
            with self.assertRaises(protocol.PDFError):
                self.check(value)

    def test_json_budgets_before_tree_allocation(self):
        self.assertEqual(parse(b'{"a":[1,true,null,"x"]}'), {"a": [1, True, None, "x"]})
        for data in (b'{"a":0,"a":1}', b"[1,]", b"NaN", b"1e9999", b'"\ud800"',
                     b"[" * 34 + b"0" + b"]" * 34, b'"' + b"a" * 16385 + b'"'):
            with self.subTest(data=data[:20]), self.assertRaises(protocol.PDFError):
                parse(data)
        for constant, data in (("MAX_NODES", b"[0,0,0,0]"),
                               ("MAX_DICTIONARIES", b"[{},{},{},{}]"), ("MAX_JSON", b"[0,0]")):
            with patch.object(bounded_json, constant, 3), self.assertRaises(protocol.PDFError):
                parse(data)


class PackagingTests(unittest.TestCase):
    def test_extractor_copy_sources_have_exact_build_context_allowances(self):
        rules = (ROOT / ".dockerignore").read_text().splitlines()
        allowed = {line[1:] for line in rules if line.startswith("!pdf-extractor/")}
        self.assertEqual(allowed, {"pdf-extractor/", "pdf-extractor/Dockerfile",
            "pdf-extractor/dependencies.lock.json", "pdf-extractor/build.py",
            "pdf-extractor/worker.py", "pdf-extractor/structure.py",
            "pdf-extractor/bounded_json.py", "pdf-extractor/process.py",
            "pdf-extractor/supervisor.py", "pdf-extractor/bootstrap.py", "pdf-extractor/probe.py"})
        dockerfile = (ROOT / "pdf-extractor/Dockerfile").read_text()
        for line in dockerfile.splitlines():
            if line.startswith("COPY "):
                for source in line.split()[1:-1]:
                    if source.startswith("pdf-extractor/"):
                        self.assertIn(source, allowed)

    def test_candidate_and_embedded_verifier_code_syntax_without_execution(self):
        files = [ROOT / "api/app/pdf_protocol.py", ROOT / "api/app/pdf_extractor.py",
                 ROOT / "scripts/imp017_fixtures.py", ROOT / "scripts/imp017_verify.py",
                 ROOT / "scripts/imp017_mount_probe.py"]
        files.extend(sorted((ROOT / "pdf-extractor").glob("*.py")))
        for path in files:
            with self.subTest(path=path.name):
                ast.parse(path.read_text(), filename=str(path))
                self.assertFalse(any(line.rstrip() != line for line in path.read_text().splitlines()))
        module = ast.parse((ROOT / "scripts/imp017_verify.py").read_text())
        for node in ast.walk(module):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                    ("CLIENT", "PROBE", "DEADLINE_TRIGGER", "DEADLINE_RECOVERY", "SOCKET_SNAPSHOT",
                     "NEW_LISTENER", "generation") for t in node.targets):
                code = ast.literal_eval(node.value)
                ast.parse(code)

    def test_confined_command_no_channel_or_supervisor_mounts(self):
        args = command("/scratch/tmpabcdefgh")
        self.assertEqual(args, ["/usr/local/bin/python3", "-I", "-B", "/worker/bootstrap.py",
                                "launch", "/scratch/tmpabcdefgh", "worker"])
        self.assertEqual(probe_command("/scratch/tmpabcdefgh", "denial"), args[:-1] + ["denial"])

    def test_only_internal_generated_job_paths_and_fixed_modes(self):
        for path in ("/scratch", "/scratch/tmpabcdefgh/../sibling", "/tmp/tmpabcdefgh", "/scratch/secret",
                     "/scratch/tmpabcdefgh;evil", None):
            with self.assertRaises(protocol.PDFError):
                command(path)
        with self.assertRaises(protocol.PDFError):
            probe_command("/scratch/tmpabcdefgh", "arbitrary-source")

    def test_pins_build_only_and_runtime_defaults(self):
        lock = json.loads((ROOT / "pdf-extractor/dependencies.lock.json").read_text())
        dockerfile = (ROOT / "pdf-extractor/Dockerfile").read_text()
        compose = (ROOT / "compose.pdf.yaml").read_text()
        self.assertIn(lock["base"], dockerfile)
        self.assertEqual(lock["snapshot"], "20261001T000000Z")
        for token in ("network_mode: none", "read_only: true", "mem_limit: 512m",
                      "memswap_limit: 512m", "pids_limit: 16", "cpus: 1.0", "size=128m",
                      "no-new-privileges:true", "restart: \"no\""):
            self.assertIn(token, compose)
        self.assertNotIn("privileged:", compose)
        self.assertNotIn("docker.sock", compose)
        seccomp = json.loads((ROOT / "pdf-extractor/seccomp.json").read_text())
        self.assertEqual(seccomp["defaultAction"], "SCMP_ACT_ERRNO")
        self.assertEqual(seccomp["defaultErrnoRet"], 1)
        self.assertFalse(any("ptrace" in rule["names"] for rule in seccomp["syscalls"]))
        # All three netlink arguments are conjunctive and exact. This is inherited,
        # not a launcher-only exception: child containment also needs fresh netns,
        # zero capabilities, disabled further userns and closed outer descriptors.
        socket_rules = [rule for rule in seccomp["syscalls"] if "socket" in rule["names"]]
        self.assertEqual(socket_rules, [{"names": ["socket"], "action": "SCMP_ACT_ALLOW",
            "args": [{"index": 0, "value": 1, "op": "SCMP_CMP_EQ"}]},
            {"names": ["socket"], "action": "SCMP_ACT_ALLOW", "args": [
                {"index": 0, "value": 16, "op": "SCMP_CMP_EQ"},
                {"index": 1, "value": 524291, "op": "SCMP_CMP_EQ"},
                 {"index": 2, "value": 0, "op": "SCMP_CMP_EQ"}]}])
        self.assertEqual(lock["existing_launcher"]["package"], "util-linux")
        self.assertNotIn("util-linux", lock["packages"])
        self.assertNotIn("bubblewrap", lock["packages"])
        self.assertTrue(any(rule["names"] == ["landlock_create_ruleset", "landlock_add_rule",
            "landlock_restrict_self"] and rule["action"] == "SCMP_ACT_ALLOW" for rule in seccomp["syscalls"]))

    def test_owned_synthetic_fixture_inventory_and_xref(self):
        values = fixtures()
        self.assertEqual(len(values), 14)
        self.assertIn(b"/Subtype /Image", values["scanned"])
        valid = values["valid"]
        xref = int(valid.split(b"startxref\n")[1].splitlines()[0])
        self.assertEqual(valid[xref:xref + 4], b"xref")
        compressed = compressed_active()
        self.assertNotIn(b"/Java#53cript", compressed)
        self.assertIn(b"/ObjStm", compressed)
        self.assertIn(b"/XRef", compressed)
        self.assertIn(b"/Open#41ction", values["escaped_action"])

    def test_near_cap_fixture_is_exact_size_with_referenced_raster_and_valid_xref(self):
        value = near_cap()
        self.assertEqual(len(value), 50_000_000)
        self.assertIn(b"/XObject << /Im1 6 0 R >>", value[:2048])
        self.assertIn(b"/Subtype /Image", value[:2048])
        xref = int(value.rsplit(b"startxref\n", 1)[1].splitlines()[0])
        self.assertEqual(value[xref:xref + 4], b"xref")

    def test_expansion_fixture_has_bounded_visible_text_and_exact_references(self):
        """Inspect known generated objects, not a host PDF/structural parser."""
        value = expansion()
        self.assertLess(len(value), 1_000_000)
        xref = int(value.rsplit(b"startxref\n", 1)[1].splitlines()[0])
        entries = value[xref:].splitlines()
        self.assertEqual(entries[:3], [b"xref", b"0 68", b"0000000000 65535 f "])
        offsets = [int(entry[:10]) for entry in entries[3:70]]
        boundaries = offsets[1:] + [xref]
        objects = {}
        for number, (start, end) in enumerate(zip(offsets, boundaries), 1):
            chunk = value[start:end]
            header = str(number).encode() + b" 0 obj\n"
            self.assertTrue(chunk.startswith(header) and chunk.endswith(b"\nendobj\n"))
            objects[number] = chunk[len(header):-len(b"\nendobj\n")]
        kids = b" ".join(f"{4 + index * 2} 0 R".encode() for index in range(32))
        self.assertEqual(objects[1], b"<< /Type /Catalog /Pages 2 0 R >>")
        self.assertEqual(objects[2], b"<< /Type /Pages /Count 32 /Kids [" + kids + b"] >>")
        self.assertIn(b"/BaseFont /Courier /Encoding /WinAnsiEncoding", objects[3])
        self.assertLess(32, protocol.MAX_PAGES)
        expected_line = b"Expansion reference 017 " * 4
        total_text = total_inflated = 0
        for index in range(32):
            number = 4 + index * 2
            self.assertEqual(objects[number], b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 3 0 R >> >> /Contents " + str(number + 1).encode() + b" 0 R >>")
            header, raw = objects[number + 1].split(b"\nstream\n", 1)
            compressed = raw[:-len(b"\nendstream")]
            self.assertEqual(header, b"<< /Length " + str(len(compressed)).encode() + b" /Filter /FlateDecode >>")
            # Only our small deterministic synthetic stream is inflated here.
            content = zlib.decompress(compressed)
            self.assertEqual(content, b"BT /F1 8 Tf 36 756 Td 14 TL\n"
                + (b"(" + expected_line + b") Tj T*\n") * 48 + b"ET\n")
            self.assertLess(len(content), 8192)
            # Courier glyphs are 0.6 em: all 48 lines fit ordinary page bounds.
            self.assertLess(36 + len(expected_line) * 8 * 0.6, 612 - 36)
            self.assertGreater(756 - 47 * 14, 36)
            total_text += len(expected_line.rstrip()) * 48
            total_inflated += len(content)
        self.assertGreater(total_text, protocol.MAX_TEXT)
        self.assertLess(total_inflated, 256 * 1024)


class VerifierDiagnosticTests(unittest.TestCase):
    def deadline(self, source, *, received=None, eof=b"", failure=None, recovered=None, elapsed=3,
                 validate_eof_timeout=False):
        """Embedded deadline code, fake sockets/extractor/fixture; no waiting or OS work."""
        socket = Mock(AF_UNIX=1)
        channel = Mock()
        socket.socket.return_value.__enter__ = Mock(return_value=channel)
        socket.socket.return_value.__exit__ = Mock(return_value=False)
        def read_eof(_):
            if validate_eof_timeout and channel.settimeout.call_args.args != (35 - elapsed,):
                raise TimeoutError("synthetic acceptance-frame timeout not restored")
            if failure is not None:
                raise failure
            return eof
        channel.recv.side_effect = read_eof
        clock = Mock(side_effect=[100, 100, 100, 100 + elapsed])
        def remaining(deadline):
            seconds = deadline - clock()
            if seconds <= 0:
                raise protocol.PDFError("timeout")
            return seconds
        extractor = Mock(side_effect=recovered if isinstance(recovered, Exception) else None,
            return_value=recovered if recovered is not None else {"status": "ready"})
        def accept(connection, deadline):
            # Real protocol.exact updates the socket timeout to its remaining
            # acceptance-frame deadline. Retain this observable fixture behavior.
            connection.settimeout(1.9)
            return received if received is not None else {"status": "accepted"}
        receive = Mock(side_effect=accept)
        modules = {"socket": socket, "time": SimpleNamespace(monotonic=clock),
            "app.pdf_protocol": SimpleNamespace(PDFError=protocol.PDFError, SOCKET_PATH="synthetic-socket",
                JOB_SECONDS=30, remaining=remaining, MAX_CONTROL=1024,
                encode=Mock(return_value=b"fake-control"), receive=receive),
            "app.pdf_extractor": SimpleNamespace(UnixPDFExtractor=lambda: SimpleNamespace(extract=extractor))}
        import imp017_fixtures as fixtures_module
        output = io.StringIO()
        with patch.dict(sys.modules, modules), patch.object(sys, "path", list(sys.path)), \
                patch.object(fixtures_module, "text_pdf", return_value=b"fake-pdf"), \
                patch.object(sys, "stdout", output):
            try:
                exec(compile(source, "<synthetic-deadline>", "exec"), {})
            except SystemExit as exc:
                return exc.code, output.getvalue(), channel
        return 0, output.getvalue(), channel

    def test_deadline_trigger_diagnostic_retains_eof_assertion_and_fixed_error_types(self):
        code, output, channel = self.deadline(verifier.DEADLINE_TRIGGER)
        self.assertEqual((code, output), (0, ""))
        self.assertEqual([call.args for call in channel.settimeout.call_args_list], [(35,), (1.9,), (32,)])
        channel.recv.assert_called_once_with(1)
        channel.sendall.assert_called_once_with(b"fake-control")
        for kwargs, stage, error in (({"eof": b"private-nonempty"}, "deadline-eof", "assertion"),
                ({"failure": ConnectionResetError("synthetic private")}, "deadline-eof", "connection-error"),
                ({"failure": TimeoutError("synthetic private")}, "deadline-eof", "timeout"),
                ({"received": {"status": "rejected", "code": "timeout"}}, "status-check", "assertion")):
            code, output, _ = self.deadline(verifier.DEADLINE_TRIGGER, **kwargs)
            self.assertEqual(code, 1)
            detail = verifier.client_detail(output.encode())
            self.assertEqual((detail["fixture"], detail["stage"], detail["error"]),
                ("deadline-trigger", stage, error))
            self.assertNotIn("private", output)

    def test_deadline_eof_restores_original_absolute_wait_after_receive_shortens_timeout(self):
        for elapsed in (3, 6):
            code, output, channel = self.deadline(verifier.DEADLINE_TRIGGER, elapsed=elapsed,
                validate_eof_timeout=True)
            self.assertEqual((code, output), (0, ""))
            self.assertEqual([call.args for call in channel.settimeout.call_args_list],
                [(35,), (1.9,), (35 - elapsed,)])
            channel.recv.assert_called_once_with(1)

    def test_deadline_eof_does_not_extend_expired_absolute_wait(self):
        code, output, channel = self.deadline(verifier.DEADLINE_TRIGGER, elapsed=36)
        self.assertEqual(code, 1)
        self.assertEqual(verifier.client_detail(output.encode()), {"fixture": "deadline-trigger",
            "stage": "deadline-eof", "error": "pdf-error", "status": "accepted", "code": "timeout"})
        channel.recv.assert_not_called()
        self.assertEqual([call.args for call in channel.settimeout.call_args_list], [(35,), (1.9,)])

    def test_deadline_recovery_diagnostic_retains_ready_assertion_and_pdf_error_code(self):
        self.assertEqual(self.deadline(verifier.DEADLINE_RECOVERY)[:2], (0, ""))
        for result, stage, error, status, code in (
                (protocol.rejected("busy"), "status-check", "assertion", "rejected", "busy"),
                (protocol.PDFError("invalid"), "extract", "pdf-error", "unknown", "invalid"),
                (ConnectionError("synthetic private"), "extract", "connection-error", "unknown", "unknown")):
            exitcode, output, _ = self.deadline(verifier.DEADLINE_RECOVERY, recovered=result)
            self.assertEqual(exitcode, 1)
            self.assertEqual(verifier.client_detail(output.encode()), {"fixture": "deadline-recovery",
                "stage": stage, "error": error, "status": status, "code": code})
            self.assertNotIn("private", output)

    def test_main_deadline_diagnostics_locate_trigger_state_readiness_and_recovery_with_cleanup(self):
        import imp017_fixtures as fixtures_module
        for failed in ("trigger", "stopped-state", "restart", "readiness", "recovery"):
            record = fixtures_module.client_error_record(ConnectionResetError("synthetic private"),
                "deadline-trigger" if failed == "trigger" else "deadline-recovery",
                "deadline-eof" if failed == "trigger" else "extract")
            error = subprocess.CalledProcessError(1, ["synthetic private"], output=record.encode(),
                stderr=b"synthetic private traceback")
            triggered = False
            restarted = False
            def fake_docker(args, **kwargs):
                nonlocal triggered, restarted
                if args[-1] == verifier.SOCKET_SNAPSHOT:
                    return b"[1,2]\n"
                if verifier.NEW_LISTENER in args:
                    if failed == "readiness":
                        raise subprocess.CalledProcessError(1, ["private"], output=b"private", stderr=b"private")
                    return b"new-listener: PASS\n"
                if args[-1] == verifier.DEADLINE_TRIGGER:
                    triggered = True
                    if failed == "trigger":
                        raise error
                    return b""
                if args[-1] == verifier.DEADLINE_RECOVERY:
                    if failed == "recovery":
                        raise error
                    return b""
                if args[-1] == verifier.PROBE:
                    return b"namespace-denial-timeout-descendant-output-cleanup: PASS\n"
                if args[-1] == verifier.CLIENT:
                    return ("\n".join(verifier.CLIENT_PASSES) + "\n").encode()
                if args[-3:] == ["ps", "-q", "pdf-extractor"]:
                    return b"synthetic-container"
                if "{{.State.Running}}" in args:
                    return b"true" if not triggered or restarted or failed == "stopped-state" else b"false"
                if args == verifier.COMPOSE + ["up", "-d"] and triggered:
                    if failed == "restart":
                        raise subprocess.CalledProcessError(1, ["private"], output=b"private", stderr=b"private")
                    restarted = True
                    return b""
                if "run" in args:
                    return b"%PDF-fake-encrypted"
                if "exec" in args:
                    if args[-1].endswith("print('peer-denial: PASS')"):
                        return b"peer-denial: PASS"
                    if args[-1].endswith("print('peer-credential-denial: PASS')"):
                        return b"peer-credential-denial: PASS"
                    return b"True"
                return b""
            output = io.StringIO()
            with patch.object(verifier, "docker", side_effect=fake_docker) as docker, \
                    patch.object(verifier, "archive", return_value=b"fake-archive"), \
                    patch.object(verifier.subprocess, "run", return_value=SimpleNamespace(
                        returncode=1 if failed == "readiness" else 0, stdout=b"private", stderr=b"private")), \
                    patch.object(verifier.time, "sleep"), \
                    patch.object(sys, "argv", ["synthetic", "--reviewed-runtime"]), \
                    patch.object(sys, "stdout", output), self.assertRaises(SystemExit) as raised:
                verifier.main()
            self.assertIn("failed at whole-job-deadline-restart", str(raised.exception))
            self.assertIn("no acceptance", str(raised.exception))
            self.assertIn("deadline_step=" + failed + "\n", output.getvalue())
            if failed in ("trigger", "recovery"):
                self.assertIn("client_fixture=deadline-", output.getvalue())
                self.assertIn("client_error=connection-error", output.getvalue())
            else:
                self.assertIn("client_fixture=unknown client_stage=unknown", output.getvalue())
            self.assertNotIn("private", output.getvalue() + str(raised.exception))
            self.assertNotIn("whole-job-deadline-restart: PASS", output.getvalue())
            self.assertTrue(output.getvalue().endswith("owned-cleanup: PASS\n"))
            docker.assert_any_call(verifier.COMPOSE + ["down", "--volumes", "--remove-orphans"])
            recovery_calls = [call for call in docker.call_args_list if call.args[0][-1] == verifier.DEADLINE_RECOVERY]
            self.assertEqual(len(recovery_calls), 1 if failed == "recovery" else 0)
            if failed == "recovery":
                self.assertIn("new-listener: PASS\n", output.getvalue())

    def listener(self, stats, *, reply=b"", connect_errors=(), uid=10002):
        """Fake exact channel metadata and a denied peer; no host socket or file use."""
        namespace = {}
        definitions = ast.parse(verifier.NEW_LISTENER)
        definitions.body = definitions.body[:next(index for index, node in enumerate(definitions.body)
            if isinstance(node, ast.Try))]
        exec(compile(definitions, "<synthetic-listener>", "exec"), namespace)
        current = SimpleNamespace(st_dev=1, st_ino=3, st_mode=stat.S_IFSOCK | 0o660,
            st_uid=10002, st_gid=10001)
        channel = Mock()
        channel.connect.side_effect = list(connect_errors) + [None] if connect_errors else None
        channel.recv.side_effect = reply if isinstance(reply, Exception) else None
        channel.recv.return_value = reply
        context = Mock()
        context.__enter__ = Mock(return_value=channel)
        context.__exit__ = Mock(return_value=False)
        ticks = iter([0, 0, 0.6, 0.6, 1.2, 1.2, 2.1, 2.1])
        peer = Mock()
        with patch.dict(namespace, {"channel_stat": Mock(side_effect=stats), "peer": peer,
                "remaining": lambda deadline: 0.5}), \
                patch.object(os, "geteuid", return_value=uid), \
                patch.object(os, "getegid", return_value=10001), \
                patch.object(os, "open", return_value=7) as opened, \
                patch.object(os, "fstat", return_value=current), \
                patch.object(os, "close") as closed, \
                patch.object(namespace["socket"], "socket", return_value=context), \
                patch.object(time, "monotonic", side_effect=lambda: next(ticks, 2.1)), \
                patch.object(time, "sleep"):
            try:
                namespace["new_listener"]((1, 2), 2)
                code = "ready"
            except namespace["PDFError"] as exc:
                code = exc.code
        return code, channel, opened, closed, peer

    def test_new_listener_waits_for_replacement_and_actual_denied_peer_response_without_job(self):
        current = SimpleNamespace(st_dev=1, st_ino=3)
        stale = SimpleNamespace(st_dev=1, st_ino=2)
        for stats, errors in (([stale, current, current], ()),
                ([current, current, current], (ConnectionRefusedError("private"),))):
            code, channel, opened, closed, peer = self.listener(stats, connect_errors=errors)
            self.assertEqual(code, "ready")
            channel.sendall.assert_not_called()
            channel.shutdown.assert_not_called()
            peer.assert_called_with(channel, 10002)
            self.assertEqual(opened.call_count, closed.call_count)
            for call in opened.call_args_list:
                self.assertEqual(call.args[1], os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
        code, _, _, _, _ = self.listener([current, current], reply=ConnectionResetError("private"))
        self.assertEqual(code, "ready")

    def test_new_listener_rejects_stale_replaced_missing_nonresponsive_and_wrong_identity(self):
        stale = SimpleNamespace(st_dev=1, st_ino=2)
        current = SimpleNamespace(st_dev=1, st_ino=3)
        other = SimpleNamespace(st_dev=1, st_ino=4)
        for stats, reply in (([stale] * 6, b""),
                ([current, other, current, other, current, other], b""),
                ([FileNotFoundError("private")] * 6, b""),
                ([current] * 6, b"nonempty"), ([current] * 6, TimeoutError("private"))):
            code, channel, opened, closed, _ = self.listener(stats, reply=reply)
            self.assertEqual(code, "unavailable")
            self.assertEqual(opened.call_count, closed.call_count)
            channel.sendall.assert_not_called()
        code, channel, opened, _, _ = self.listener([], uid=10001)
        self.assertEqual(code, "unavailable")
        opened.assert_not_called()
        channel.connect.assert_not_called()

    def test_new_listener_inline_has_only_fixed_stdlib_dependencies_and_no_private_import_or_output(self):
        parsed = ast.parse(verifier.NEW_LISTENER)
        imports = [alias.name for node in ast.walk(parsed) if isinstance(node, ast.Import)
            for alias in node.names]
        self.assertEqual(set(imports), {"json", "os", "socket", "stat", "struct", "sys", "time"})
        self.assertFalse(any(isinstance(node, ast.ImportFrom) for node in ast.walk(parsed)))
        self.assertNotIn("sys.path", verifier.NEW_LISTENER)
        self.assertFalse(any(isinstance(node, ast.Constant) and isinstance(node.value, str)
            and "/fixture" in node.value for node in ast.walk(parsed)))
        output = io.StringIO()
        with patch.object(os, "geteuid", side_effect=OSError("synthetic secret /fixture/private")), \
                patch.object(sys, "argv", ["synthetic", "[1,2]"]), \
                patch.object(sys, "stdout", output), self.assertRaises(SystemExit):
            exec(compile(parsed, "<synthetic-listener>", "exec"), {})
        self.assertEqual(verifier.client_detail(output.getvalue().encode()), {
            "fixture": "restart-readiness", "stage": "listener-check", "error": "os-error",
            "status": "unknown", "code": "unknown"})
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("/fixture", output.getvalue())

    def test_channel_identity_requires_exact_existing_metadata_and_strict_snapshot(self):
        import imp017_fixtures as fixtures_module
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o711, st_uid=10002)
        info = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=10002, st_gid=10001,
            st_dev=1, st_ino=2)
        with patch.object(fixtures_module.os, "lstat", side_effect=[directory, info]):
            self.assertEqual(fixtures_module.socket_identity(fixtures_module.channel_stat()), (1, 2))
        for field, bad in (("st_uid", 10001), ("st_gid", 10002), ("st_mode", stat.S_IFLNK | 0o660),
                ("st_mode", stat.S_IFSOCK | 0o666)):
            wrong = SimpleNamespace(**{**vars(info), field: bad})
            with patch.object(fixtures_module.os, "lstat", side_effect=[directory, wrong]), \
                    self.assertRaises(protocol.PDFError):
                fixtures_module.channel_stat()
        self.assertEqual(verifier.old_socket_record(b"[1,2]\n"), "[1,2]")
        for raw in (b"private", b"[true,2]\n", b"[1,0]\n", b"[1,2,3]\n",
                b"[1, 2]\n", b"[1,2]\nprivate", b"x" * 129):
            with self.assertRaises(AssertionError):
                verifier.old_socket_record(raw)

    def client(self, extracted, *, values=None, connect_error=None):
        """Embedded CLIENT control flow with fake parser/channel/filesystem seams."""
        extractor = Mock(side_effect=extracted)
        channel = Mock()
        channel.connect.side_effect = connect_error
        socket = SimpleNamespace(AF_UNIX=1, SOCK_STREAM=1, SHUT_WR=1,
            socket=Mock())
        context = Mock()
        context.__enter__ = Mock(return_value=channel)
        context.__exit__ = Mock(return_value=False)
        socket.socket.return_value = context
        import imp017_fixtures as fixtures_module
        modules = {
            "socket": socket,
            "app.pdf_extractor": SimpleNamespace(UnixPDFExtractor=lambda: SimpleNamespace(extract=extractor)),
            "app.pdf_protocol": SimpleNamespace(PDFError=protocol.PDFError, MAX_ORIGINAL=7,
                JOB_SECONDS=30, SOCKET_PATH="synthetic-socket", MAX_CONTROL=1024,
                encode=Mock(return_value=b"fake-control"), rejected=protocol.rejected,
                receive=Mock(side_effect=[{"status": "accepted"}, {"status": "rejected"},
                    {"status": "accepted"}, {"status": "rejected"}]))}
        source = Mock()
        source.__enter__ = Mock(return_value=SimpleNamespace(read=lambda: b"fake-encrypted"))
        source.__exit__ = Mock(return_value=False)
        output = io.StringIO()
        with patch.dict(sys.modules, modules), patch.object(sys, "path", list(sys.path)), \
                patch.object(fixtures_module, "fixtures", return_value=values or {"valid": b"fake"}), \
                patch.object(fixtures_module, "near_cap", return_value=b"fakecap"), \
                patch.object(fixtures_module, "expansion", return_value=b"fake-expansion"), \
                patch("builtins.open", return_value=source), patch.object(sys, "stdout", output):
            try:
                exec(compile(verifier.CLIENT, "<synthetic-client>", "exec"), {})
            except SystemExit as exc:
                return exc.code, output.getvalue(), extractor
        return 0, output.getvalue(), extractor

    def test_client_reports_fixed_fixture_stage_and_processor_code_without_raw_data(self):
        private = "synthetic private text/path/settings/auth"
        cases = (
            ({"status": "rejected", "code": "unavailable", "text": private},
                "status-check", "assertion", "rejected", "unavailable"),
            ({"status": "ready", "text": private}, "text-check", "assertion", "ready", "unknown"),
            (protocol.PDFError("timeout"), "extract", "pdf-error", "unknown", "timeout"),
            (TimeoutError(private), "extract", "timeout", "unknown", "unknown"),
            (OSError(private), "extract", "os-error", "unknown", "unknown"),
            (RuntimeError(private), "extract", "client-unknown", "unknown", "unknown"),
        )
        for result, stage, error, status, reason in cases:
            with self.subTest(error=error, stage=stage):
                code, output, extractor = self.client([result])
                self.assertEqual(code, 1)
                self.assertEqual(verifier.client_detail(output.encode()), {"fixture": "valid",
                    "stage": stage, "error": error, "status": status, "code": reason})
                self.assertNotIn(private, output)
                extractor.assert_called_once()

    def test_client_preserves_workflow_assertions_and_partial_pass_prefix(self):
        valid = {"status": "ready", "text": "Synthetic PDF reference 017\f"}
        code, output, extractor = self.client([valid, {"status": "ready", "missing_pages": [2]},
            protocol.rejected("invalid"), valid, protocol.rejected("limit"), protocol.rejected("encrypted"),
            protocol.rejected("busy"), valid, valid], values={"valid": b"fake", "mixed": b"fake",
                "spoof": b"fake"})
        self.assertEqual(code, 0)
        self.assertEqual(output, "\n".join(verifier.CLIENT_PASSES) + "\n")
        self.assertEqual(extractor.call_count, 9)
        code, output, _ = self.client([valid, protocol.rejected("limit")])
        self.assertEqual(code, 1)
        self.assertTrue(output.startswith("representative-rejections: PASS\n"))
        self.assertEqual(verifier.client_detail(output.encode()), {"fixture": "decimal50MB",
            "stage": "status-check", "error": "assertion", "status": "rejected", "code": "limit"})
        # A genuine channel failure remains a failure at its fixed stage, not PASS.
        code, output, _ = self.client([valid, valid, protocol.rejected("limit"),
            protocol.rejected("encrypted")], connect_error=PermissionError("synthetic private"))
        self.assertEqual(code, 1)
        self.assertEqual(verifier.client_detail(output.encode()), {"fixture": "busy-short-body",
            "stage": "channel-connect", "error": "os-error", "status": "unknown", "code": "unknown"})

    def test_expansion_requires_limit_not_arbitrary_rejection_or_channel_failure(self):
        valid = {"status": "ready", "text": "Synthetic PDF reference 017\f"}
        for result, stage, error, status, reason in (
                (protocol.rejected("invalid"), "status-check", "assertion", "rejected", "invalid"),
                (protocol.rejected("timeout"), "status-check", "assertion", "rejected", "timeout"),
                (protocol.PDFError("invalid"), "extract", "pdf-error", "unknown", "invalid")):
            code, output, _ = self.client([valid, valid, result])
            self.assertEqual(code, 1)
            self.assertEqual(verifier.client_detail(output.encode()), {"fixture": "expansion",
                "stage": stage, "error": error, "status": status, "code": reason})
            self.assertEqual(verifier.client_projection(output.encode())[1], verifier.CLIENT_PASSES[:2])
            self.assertNotIn("expansion: PASS", output)

    def test_client_projection_uses_only_fixed_enums_and_exact_canonical_schema(self):
        import imp017_fixtures as fixtures_module
        unknown = {"fixture": "unknown", "stage": "unknown", "error": "client-unknown",
            "status": "unknown", "code": "unknown"}
        record = fixtures_module.client_record("valid", "status-check", "assertion",
            {"status": "rejected", "code": "unavailable", "text": "synthetic private", "path": "private"})
        self.assertNotIn("private", record)
        self.assertEqual(verifier.client_detail(record.encode())["code"], "unavailable")
        self.assertEqual(fixtures_module.client_record([], {}, "private", {"status": [], "code": {}}, {}),
                         fixtures_module.client_record())
        for field in unknown:
            detail = {"fixture": "valid", "stage": "extract", "error": "pdf-error",
                "status": "unknown", "code": "invalid"}
            detail[field] = "synthetic-private"
            output = fixtures_module.CLIENT_PREFIX + json.dumps(detail, separators=(",", ":")) + "\n"
            self.assertEqual(verifier.client_detail(output.encode()), unknown)
        invalid = [b"private traceback", b"\xff", b"x" * 1025, None, record,
            record.encode().replace(b'"stage":"status-check"', b'"stage":true'),
            record.encode().replace(b'"code":"unavailable"', b'"code":"unavailable","text":"private"'),
            record.encode().replace(b'"code":"unavailable"', b'"code":"invalid","code":"unavailable"'),
            record.encode().replace(b'"code":"unavailable"', b'"code":[[]]'),
            b"private\n" + record.encode(), record.encode() + b"private\n",
            record.encode().rstrip(b"\n"), record.encode().replace(b"\n", b"\r\n"),
            b"decimal50MB: PASS\n" + record.encode()]
        for output in invalid:
            with self.subTest(output_type=type(output).__name__):
                self.assertEqual(verifier.client_detail(output), unknown)
                self.assertEqual(verifier.client_projection(output)[1], ())
        self.assertEqual(verifier.fixed("private-stage", verifier.VERIFIER_STAGES), "unknown")
        self.assertEqual(verifier.fixed([], verifier.VERIFIER_STAGES), "unknown")

    def test_main_projects_same_captured_client_error_and_preserves_cleanup(self):
        import imp017_fixtures as fixtures_module
        record = fixtures_module.client_record("valid", "status-check", "assertion",
            protocol.rejected("unavailable"))
        for captured, expected in ((record.encode(), "client_fixture=valid client_stage=status-check "
                "client_error=assertion result_status=rejected result_code=unavailable\n"),
                (("\n".join(verifier.CLIENT_PASSES[:2]) + "\n" + fixtures_module.client_record(
                    "expansion", "extract", "pdf-error", code="invalid")).encode(),
                    "representative-rejections: PASS\ndecimal50MB: PASS\n"
                    "client_fixture=expansion client_stage=extract "
                    "client_error=pdf-error result_status=unknown result_code=invalid\n"),
                (b"synthetic private traceback", "client_fixture=unknown client_stage=unknown "
                "client_error=client-unknown result_status=unknown result_code=unknown\n")):
            error = subprocess.CalledProcessError(1, ["synthetic private command"],
                output=captured, stderr=b"synthetic private stderr")
            def fake_docker(args, **kwargs):
                if args[-1] == verifier.CLIENT:
                    raise error
                if args[-1] == verifier.PROBE:
                    return b"namespace-denial-timeout-descendant-output-cleanup: PASS\n"
                if args[-3:] == ["ps", "-q", "pdf-extractor"]:
                    return b"synthetic-container"
                if "run" in args:
                    return b"%PDF-fake-encrypted"
                if "{{.State.Running}}" in args:
                    return b"true"
                if "exec" in args and "os.path.exists" in args[-1]:
                    return b"True"
                return b""
            output = io.StringIO()
            with patch.object(verifier, "docker", side_effect=fake_docker) as docker, \
                    patch.object(verifier, "archive", return_value=b"fake-archive"), \
                    patch.object(sys, "argv", ["synthetic", "--reviewed-runtime"]), \
                    patch.object(sys, "stdout", output), self.assertRaises(SystemExit) as raised:
                verifier.main()
            self.assertEqual(str(raised.exception),
                "phase-one runtime verification failed at representative-channel-workflow; "
                "failure_category=client-workflow-failure probe_step=verifier; no acceptance")
            self.assertEqual(output.getvalue(), "dedicated-pinned-build: PASS\n"
                "namespace-denial-timeout-descendant-output-cleanup: PASS\n" + expected + "owned-cleanup: PASS\n")
            docker.assert_any_call(verifier.COMPOSE + ["down", "--volumes", "--remove-orphans"])
            self.assertEqual(sum(call.args[0][-1] == verifier.CLIENT for call in docker.call_args_list), 1)

    def test_bwrap_startup_fixed_categories_without_policy_attribution(self):
        cases = (
            (b"bwrap: Creating new namespace failed: Operation not permitted\n", "namespace-denied"),
            (b"bwrap: No permissions to create new namespace, likely because the kernel "
             b"does not allow non-privileged user namespaces. See <https://synthetic.invalid>.\n",
             "usernamespace-denied"),
            (b"bwrap: setting up uid map: Permission denied\n", "namespace-mapping-denied"),
            (b"bwrap: write to /proc/self/gid_map: Operation not permitted\n", "namespace-mapping-denied"),
            (b"bwrap: Unknown option --synthetic-invalid\n", "launcher-arguments-invalid"),
            (b"bwrap: --ro-bind takes two arguments\n", "launcher-arguments-invalid"),
            (b"bwrap: --uid takes an argument\n", "launcher-arguments-invalid"),
             (b"bwrap: --disable-userns requires --unshare-user\n", "launcher-arguments-invalid"),
            (b"bwrap: Failed to make / slave: Permission denied\n", "mount-propagation-denied"),
            (b"bwrap: Failed to make / slave: Operation not permitted\n", "mount-propagation-denied"),
            (b"imp017-bootstrap:unavailable\n", "sandbox-unavailable"),
            (b"imp017-bootstrap:landlock:unavailable\n", "sandbox-landlock-unavailable"),
            (b"unshare: unshare failed: Operation not permitted\n", "namespace-denied"),
            (b"bwrap: execvp /synthetic/missing-runtime: No such file or directory\n",
             "executable-runtime-missing"),
        )
        for diagnostic, expected in cases:
            with self.subTest(category=expected):
                self.assertEqual(startup_category(diagnostic), expected)
                error = StartupFailure(diagnostic)
                self.assertEqual(str(error), "invalid")
                self.assertEqual(error.category, expected)
                code, output, runner = self.probe([error])
                self.assertEqual(code, 1)
                self.assertEqual(output, "imp017-probe-failure:" + expected + ":namespace-start\n")
                self.assertEqual(runner.call_count, 1)
                self.assertTrue(runner.call_args.kwargs["diagnose_startup"])
                record = subprocess.CalledProcessError(1, ["synthetic"], output=output.encode())
                self.assertEqual(verifier.failure_detail(record, "containment"),
                                 (expected, "namespace-start"))

    def test_startup_unknown_and_missing_executable_do_not_leak_values(self):
        for diagnostic in (b"private diagnostic", b"Operation not permitted",
                b"bwrap: Creating new namespace failed: Invalid argument\n",
                b"bwrap: execvp /synthetic/private: Permission denied\n",
                b"prefix bwrap: Unknown option --synthetic-invalid\n",
                b"bwrap: Unknown option --synthetic-invalid\nprivate diagnostic",
                b"bwrap: --disable-userns requires --unshare-user\nprivate diagnostic",
                 b"bwrap: --disable-userns requires --unshare-user-try\n",
                b"bwrap: Failed to make / slave: Permission denied\nprivate diagnostic",
                b"bwrap: Unknown option --synthetic-invalid\x00", b"\xff", b"x" * 8193, None):
            self.assertEqual(startup_category(diagnostic), "namespace-runtime-unknown")
        for error, expected in ((StartupFailure(b"private diagnostic"), "namespace-runtime-unknown"),
                                (FileNotFoundError("private path"), "executable-runtime-missing")):
            code, output, runner = self.probe([error])
            self.assertEqual(code, 1)
            self.assertEqual(output, "imp017-probe-failure:" + expected + ":namespace-start\n")
            self.assertEqual(runner.call_count, 1)

    def test_runner_classifies_only_opt_in_nonzero_after_bounded_capture_and_cleans_up(self):
        """Fake process, pipes and OS seams; no runtime or host input is used."""
        diagnostic = b"bwrap: Unknown option --synthetic-invalid\n"
        for diagnose, returncode, limit in ((False, 1, 8192), (True, 1, 8192),
                                           (True, 0, 8192), (True, 1, 8)):
            child = Mock(pid=123, returncode=returncode)
            stdout, stderr = child.stdout, child.stderr
            stdout.fileno.return_value, stderr.fileno.return_value = 10, 11
            registered = {}
            selector = Mock()
            selector.register.side_effect = lambda pipe, events, index: registered.update({pipe: index})
            selector.get_map.side_effect = lambda: registered
            selector.select.side_effect = lambda _: [
                (SimpleNamespace(fileobj=pipe, data=index), 0) for pipe, index in list(registered.items())]
            selector.unregister.side_effect = registered.pop
            reads = {10: [b""], 11: [diagnostic, b""]}
            with patch.object(runner_module.subprocess, "Popen", return_value=child), \
                    patch.object(runner_module.os, "open", return_value=9) as opened, \
                    patch.object(runner_module.os, "close") as closed, \
                    patch.object(runner_module.selectors, "DefaultSelector", return_value=selector), \
                    patch.object(runner_module.os, "read", side_effect=lambda fd, count: reads[fd].pop(0)), \
                    patch.object(runner_module.os, "killpg") as kill, \
                    patch.object(runner_module.os, "waitpid", side_effect=ChildProcessError) as reap:
                if returncode:
                    with self.assertRaises(protocol.PDFError) as raised:
                        runner_module.run(["synthetic"], time.monotonic()+2, 8192, reap=True,
                                          diagnostics_limit=limit, diagnose_startup=diagnose)
                    classified = diagnose and limit == 8192
                    self.assertEqual(type(raised.exception), StartupFailure if classified else protocol.PDFError)
                    self.assertEqual(str(raised.exception), "invalid" if limit == 8192 else "limit")
                    if classified:
                        self.assertEqual(raised.exception.category, "launcher-arguments-invalid")
                else:
                    self.assertEqual(runner_module.run(["synthetic"], time.monotonic()+2, 8192,
                        reap=True, diagnose_startup=True), (b"", diagnostic))
                kill.assert_called_once_with(123, runner_module.signal.SIGKILL)
                self.assertTrue(runner_module.subprocess.Popen.call_args.kwargs["close_fds"])
                self.assertEqual(runner_module.subprocess.Popen.call_args.kwargs["stdin"], 9)
                opened.assert_called_once_with("/dev/null", runner_module.os.O_RDONLY | runner_module.os.O_CLOEXEC)
                closed.assert_called_once_with(9)
                reap.assert_called_once_with(-1, runner_module.os.WNOHANG)
                selector.close.assert_called_once_with()
                stdout.close.assert_called_once_with()
                stderr.close.assert_called_once_with()

    def test_ro_default_stdin_launch_failure_closes_only_owned_fd_without_fallback(self):
        for source in (None, Mock(name="owned-ro-spool-or-pipe")):
            with patch.object(runner_module.os, "open", return_value=9) as opened, \
                    patch.object(runner_module.os, "close") as closed, \
                    patch.object(runner_module.subprocess, "Popen", side_effect=FileNotFoundError("synthetic")) as launch, \
                    self.assertRaises(FileNotFoundError):
                runner_module.run(["synthetic"], time.monotonic()+1, 8192, source=source)
            if source is None:
                self.assertEqual(launch.call_args.kwargs["stdin"], 9)
                opened.assert_called_once_with("/dev/null", runner_module.os.O_RDONLY | runner_module.os.O_CLOEXEC)
                closed.assert_called_once_with(9)
            else:
                self.assertIs(launch.call_args.kwargs["stdin"], source)
                opened.assert_not_called()
                closed.assert_not_called()
                source.close.assert_not_called()
        with patch.object(runner_module.os, "open", side_effect=PermissionError("synthetic")) as opened, \
                patch.object(runner_module.subprocess, "Popen") as launch, \
                patch.object(runner_module.os, "close") as closed, self.assertRaises(PermissionError):
            runner_module.run(["synthetic"], time.monotonic()+1, 8192)
        opened.assert_called_once()
        launch.assert_not_called()
        closed.assert_not_called()

    def test_fixed_failure_record_and_unknown_output_never_escape(self):
        error = subprocess.CalledProcessError(1, ["private command"],
            output=b"imp017-probe-failure:namespace-runtime:namespace-start\n",
            stderr=b"private diagnostic")
        self.assertEqual(verifier.failure_detail(error, "containment"),
                         ("namespace-runtime", "namespace-start"))
        for output in (b"private text", b"imp017-probe-failure:private:namespace-start\n",
                       b"imp017-probe-failure:namespace-runtime:private\n",
                       b"imp017-probe-failure:namespace-runtime:namespace-start\nprivate",
                       b"x" * 257, b"\xff", None):
            error.output = output
            self.assertEqual(verifier.failure_detail(error, "containment"),
                             ("probe-runtime", "probe-launch"))

    def test_launch_policy_categories_are_not_guessed_from_namespace_failure(self):
        for stderr, expected in ((b"could not apply AppArmor profile private", "apparmor-runtime"),
                                 (b"failed loading seccomp private", "seccomp-runtime"),
                                 (b"operation not permitted private", "container-runtime")):
            error = subprocess.CalledProcessError(125, ["private"], stderr=stderr)
            self.assertEqual(verifier.failure_detail(error, "containment"),
                             (expected, "container-start"))
            error.returncode = 1
            self.assertEqual(verifier.failure_detail(error, "containment"),
                             ("probe-runtime", "probe-launch"))
        for error, expected in ((subprocess.TimeoutExpired(["private"], 1),
                                ("runtime-timeout", "probe-launch")),
                               (AssertionError("private"), ("harness-assertion", "probe-report")),
                               (FileNotFoundError("private"), ("runtime-unavailable", "verifier")),
                               (RuntimeError("private"), ("runtime-failure", "verifier"))):
            self.assertEqual(verifier.failure_detail(error, "containment"), expected)

    def test_main_reports_fixed_failure_without_acceptance_and_keeps_owned_cleanup(self):
        error = subprocess.CalledProcessError(1, ["private command"],
            output=b"imp017-probe-failure:launcher-arguments-invalid:namespace-start\n",
            stderr=b"private diagnostic")
        def fake_docker(args, **kwargs):
            if "run" in args:
                raise error
            return b""
        output = io.StringIO()
        with patch.object(verifier, "docker", side_effect=fake_docker) as docker, \
                patch.object(sys, "argv", ["synthetic", "--reviewed-runtime"]), \
                patch.object(sys, "stdout", output), self.assertRaises(SystemExit) as raised:
            verifier.main()
        self.assertEqual(str(raised.exception),
            "phase-one runtime verification failed at containment; "
            "failure_category=launcher-arguments-invalid probe_step=namespace-start; no acceptance")
        self.assertEqual(output.getvalue(), "dedicated-pinned-build: PASS\nowned-cleanup: PASS\n")
        docker.assert_any_call(verifier.COMPOSE + ["down", "--volumes", "--remove-orphans"])

    def test_exact_mount_failure_runs_diagnostic_but_never_accepts_startup(self):
        error = subprocess.CalledProcessError(1, ["synthetic"], output=
            b"imp017-probe-failure:mount-propagation-denied:namespace-start\n")
        def fake_docker(args, **kwargs):
            if "run" in args:
                raise error
            return b""
        output = io.StringIO()
        with patch.object(verifier, "docker", side_effect=fake_docker) as docker, \
                patch.object(verifier, "mount_diagnostic", return_value="root-slave-recursive:eacces") as diagnostic, \
                patch.object(sys, "argv", ["synthetic", "--reviewed-runtime"]), \
                patch.object(sys, "stdout", output), self.assertRaises(SystemExit) as raised:
            verifier.main()
        self.assertIn("failure_category=mount-propagation-denied", str(raised.exception))
        self.assertIn("no acceptance", str(raised.exception))
        self.assertEqual(output.getvalue(), "dedicated-pinned-build: PASS\n"
            "root-propagation-diagnostic=root-slave-recursive:eacces\n"
            "root-propagation-policy=unattributed\nowned-cleanup: PASS\n")
        diagnostic.assert_called_once()
        settings, name = diagnostic.call_args.args
        self.assertIn("ALL", settings)
        self.assertIn("no-new-privileges", settings)
        self.assertIn("none", settings)
        self.assertEqual(name, verifier.PROJECT + "-probe")
        docker.assert_any_call(verifier.COMPOSE + ["down", "--volumes", "--remove-orphans"])

    def test_mount_diagnostic_accepts_only_canonical_fixed_records(self):
        for output, expected in ((b"imp017-mount-probe:root-slave-recursive:eacces\n",
                "root-slave-recursive:eacces"),
                (b"imp017-mount-probe:root-slave-recursive:ok\n", "root-slave-recursive:ok"),
                (b"imp017-mount-probe:root-slave-recursive:eacces\nprivate", "unavailable"),
                (b"imp017-mount-probe:private:eacces\n", "unavailable"),
                (b"private", "unavailable")):
            with patch.object(verifier, "docker", return_value=output) as docker:
                self.assertEqual(verifier.mount_diagnostic(["synthetic-settings"], "synthetic-name"), expected)
                args = docker.call_args.args[0]
                self.assertIn("synthetic-settings", args)
                self.assertNotIn("--privileged", args)
                self.assertNotIn("-v", args)
        with patch.object(verifier, "docker", side_effect=PermissionError("private")):
            self.assertEqual(verifier.mount_diagnostic([], "synthetic-name"), "unavailable")
        with patch.object(Path, "read_text", side_effect=PermissionError("private")), \
                patch.object(verifier, "docker") as docker:
            self.assertEqual(verifier.mount_diagnostic([], "synthetic-name"), "unavailable")
        docker.assert_not_called()

    def probe(self, results, *, canary_connected=False):
        """Execute only verifier control flow; fake every runtime/filesystem seam."""
        path = Mock()
        path.__str__ = Mock(return_value="/scratch/sibling")
        path.read_text.return_value = "owned synthetic sibling canary"
        path.iterdir.return_value = []
        directory = Mock()
        directory.__enter__ = Mock(return_value="/scratch/tmpabcdefgh")
        directory.__exit__ = Mock(return_value=False)
        handle = Mock()
        handle.fileno.return_value = 40
        path.open.return_value.__enter__ = Mock(return_value=handle)
        path.open.return_value.__exit__ = Mock(return_value=False)
        canary = Mock()
        canary.fileno.return_value = 41
        canary.accept.side_effect = None if canary_connected else BlockingIOError
        canary.accept.return_value = (Mock(), "synthetic")
        socket = Mock()
        socket.socket.return_value.__enter__ = Mock(return_value=canary)
        socket.socket.return_value.__exit__ = Mock(return_value=False)
        runner = Mock(side_effect=results)
        modules = {"ctypes": SimpleNamespace(CDLL=lambda _: SimpleNamespace(prctl=lambda *args: 0)),
                    "pathlib": SimpleNamespace(Path=Mock(return_value=path)),
                    "tempfile": SimpleNamespace(TemporaryDirectory=Mock(return_value=directory)),
                    "socket": socket,
                    "os": SimpleNamespace(getpid=lambda: 123, set_inheritable=Mock(),
                                          readlink=lambda _: "net:[outer]"),
                      "process": SimpleNamespace(StartupFailure=StartupFailure, probe_command=probe_command, run=runner)}
        output = io.StringIO()
        with patch.dict(sys.modules, modules), patch.object(sys, "path", list(sys.path)), \
                patch.object(sys, "stdout", output):
            try:
                exec(compile(verifier.PROBE, "<synthetic-probe>", "exec"), {})
            except SystemExit as exc:
                return exc.code, output.getvalue(), runner
        return 0, output.getvalue(), runner

    def test_probe_separates_namespace_start_from_assertions_without_raw_details(self):
        code, output, runner = self.probe([protocol.PDFError("invalid")])
        self.assertEqual(code, 1)
        self.assertEqual(output, "imp017-probe-failure:namespace-runtime:namespace-start\n")
        self.assertEqual(runner.call_count, 1)
        code, output, _ = self.probe([(b"private unexpected output", b"private stderr")])
        self.assertEqual(code, 1)
        self.assertEqual(output, "imp017-probe-failure:harness-assertion:namespace-start\n")
        code, output, _ = self.probe([(b"namespace-ready\n", b""),
            (b"imp017-probe-failure:boundary-assertion:denial-network\n", b"")])
        self.assertEqual(code, 1)
        self.assertEqual(output, "imp017-probe-failure:boundary-assertion:denial-network\n")
        for step in ("denial-capabilities", "denial-usernamespace", "denial-handles", "denial-outer-socket"):
            record = "imp017-probe-failure:boundary-assertion:" + step + "\n"
            code, output, _ = self.probe([(b"namespace-ready\n", b""), (record.encode(), b"")])
            self.assertEqual((code, output), (1, record))

    def test_probe_keeps_expected_failures_and_rejects_invalid_child_exit(self):
        code, output, runner = self.probe([(b"namespace-ready\n", b""), (b"denied\n", b""),
            protocol.PDFError("timeout"), (b"", b""), protocol.PDFError("limit")])
        self.assertEqual(code, 0)
        self.assertEqual(output, "namespace-denial-timeout-descendant-output-cleanup: PASS\n")
        self.assertEqual(runner.call_count, 5)
        self.assertEqual([call.kwargs.get("diagnose_startup", False) for call in runner.call_args_list],
                          [True, False, False, False, False])
        # Actual containment calls exercise the shared RO no-input default,
        # not a probe-only descriptor workaround that production never uses.
        self.assertTrue(all(call.kwargs.get("source") is None for call in runner.call_args_list))
        args = runner.call_args_list[1].args[0]
        self.assertEqual(args[-3:], ["launch", "/scratch/tmpabcdefgh", "denial"])
        self.assertTrue(all("\x00" not in arg for arg in args))
        code, output, _ = self.probe([(b"namespace-ready\n", b""), (b"denied\n", b""),
            protocol.PDFError("invalid")])
        self.assertEqual(code, 1)
        self.assertEqual(output, "imp017-probe-failure:probe-runtime:timeout\n")
        code, output, runner = self.probe([(b"namespace-ready\n", b""), (b"denied\n", b"")],
                                          canary_connected=True)
        self.assertEqual(code, 1)
        self.assertEqual(output, "imp017-probe-failure:boundary-assertion:denial-outer-socket\n")
        self.assertEqual(runner.call_count, 2)
        code, output, _ = self.probe([(b"namespace-ready\n", b""), (b"denied\n", b""),
            protocol.PDFError("timeout"), protocol.PDFError("timeout")])
        self.assertEqual((code, output), (1, "imp017-probe-failure:runtime-timeout:descendants\n"))

class BootstrapTests(unittest.TestCase):
    def evaluate(self, number, argument=0, arch=0xc000003e):
        # Small interpreter for the emitted classic BPF; no kernel execution.
        accumulator, pc = 0, 0
        code = bootstrap.instructions()
        while True:
            op, yes, no, value = code[pc]
            if op == 0x20:
                accumulator = {0: number, 4: arch, 16: argument & 0xffffffff}[value]
            elif op == 0x15:
                pc += yes if accumulator == value else no
            elif op == 0x35:
                pc += yes if accumulator >= value else no
            elif op == 0x45:
                pc += yes if accumulator & value else no
            elif op == 0x06:
                return value
            else:
                self.fail("unrecognized BPF")
            pc += 1

    def test_child_filter_denies_comms_metadata_namespace_and_cap_reacquisition(self):
        for number in (41, 42, 43, 44, 45, 46, 47, 49, 50, 53, 54, 55,
                       90, 91, 92, 93, 94, 101, 105, 106, 113, 114, 116, 126,
                       132, 133, 155, 157, 161, 165, 166, 188, 190, 192,
                       260, 263, 272, 280, 299, 303, 304, 308, 310, 311, 321,
                       425, 426, 427, 434, 438, 444, 445, 446):
            self.assertEqual(self.evaluate(number), 0x50001, number)
        for flag in (0x10000000, 0x40000000, 0x20000000, 0x20000, 0x80):
            self.assertEqual(self.evaluate(56, 17 | flag), 0x50001)
        self.assertEqual(self.evaluate(56, 17), 0x7fff0000)
        self.assertEqual(self.evaluate(435), 0x50000 | 38)
        self.assertEqual(self.evaluate(59 | 0x40000000), 0x80000000)
        self.assertEqual(self.evaluate(59, arch=0x40000003), 0x80000000)
        for number in (0, 1, 59, 61, 262):
            self.assertEqual(self.evaluate(number), 0x7fff0000)

    def test_glibc_tls_arch_prctl_only_fs_set_get(self):
        for operation in (0x1002, 0x1003):  # ARCH_SET_FS, ARCH_GET_FS
            self.assertEqual(self.evaluate(158, operation), 0x7fff0000)
        for operation in (0, 0x1001, 0x1004, 0x1011, 0x1012, 0x1013, 0x1021, 0x1022, 0xffffffff):
            self.assertEqual(self.evaluate(158, operation), 0x50001)
        self.assertEqual(self.evaluate(157, 0x1002), 0x50001)
        self.assertEqual(self.evaluate(158, 0x1002, arch=0x40000003), 0x80000000)
        self.assertEqual(self.evaluate(158 | 0x40000000, 0x1002), 0x80000000)

    def test_landlock_requires_abi3_and_grants_exact_job_not_parent_or_channel(self):
        calls, grants = [], []
        libc = Mock()
        def syscall(number, *args):
            calls.append((number, args))
            if number == 444:
                if args[-1] == 1:
                    return 3
                self.assertEqual(args[0]._obj.value, (1 << 15) - 1)
                return 30
            if number == 445:
                rule = args[2]._obj
                grants.append((rule.fd, rule.allowed))
            return 0
        libc.syscall.side_effect = syscall
        libc.prctl.return_value = 0
        paths = []
        def opened(path, flags):
            paths.append(path)
            return 100 + len(paths)
        with patch.object(bootstrap.os, "open", side_effect=opened), patch.object(bootstrap.os, "close"):
            bootstrap.landlock(libc, "/scratch/tmpabcdefgh")
        self.assertEqual(paths[-1], "/scratch/tmpabcdefgh")
        self.assertTrue(all(path not in paths for path in ("/scratch", "/run", "/proc", "/sys", "/supervisor")))
        self.assertEqual(grants[-1][1], bootstrap.READ | bootstrap.WRITE)
        self.assertEqual(grants[-1][1] & ((1 << 13) | 1 | (1 << 6) | (1 << 9) | (1 << 10) | (1 << 11) | (1 << 12)), 0)
        self.assertEqual(calls[-1][0], 446)
        libc.syscall.side_effect = None
        libc.syscall.return_value = 2
        with patch.object(bootstrap.os, "open") as opened, self.assertRaises(bootstrap.Unavailable):
            bootstrap.landlock(libc, "/scratch/tmpabcdefgh")
        opened.assert_not_called()

    def test_bootstrap_stops_before_enforcement_for_rw_stdin_or_non_pipe_output(self):
        libc = Mock()
        libc.prctl.return_value = 1
        for flags, mode in ((2, 0o010000), (0, 0o100000)):
            with patch.object(bootstrap.os, "uname", return_value=SimpleNamespace(machine="x86_64")), \
                    patch.object(bootstrap.os, "getuid", return_value=10002), \
                    patch.object(bootstrap.os, "getgid", return_value=10002), \
                    patch.object(bootstrap.os, "getpid", return_value=1), \
                    patch.object(bootstrap.os, "getppid", return_value=0), \
                    patch.object(bootstrap.fcntl, "fcntl", return_value=flags), \
                    patch.object(bootstrap.os, "fstat", return_value=SimpleNamespace(st_mode=mode)), \
                    patch.object(bootstrap, "landlock") as landlock, self.assertRaises(bootstrap.Unavailable):
                bootstrap.enforce(libc, "/scratch/tmpabcdefgh")
            landlock.assert_not_called()
            self.assertEqual(bootstrap.STAGE, "stdin" if flags == 2 else "outputs")
        libc.capset.assert_not_called()

    def test_native_seams_have_explicit_word_width_and_full_close_range(self):
        libc = Mock()
        bootstrap.libc_signatures(libc)
        self.assertEqual(libc.prctl.argtypes, [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                                             ctypes.c_ulong, ctypes.c_ulong])
        self.assertEqual(libc.prctl.restype, ctypes.c_int)
        self.assertEqual(libc.close_range.argtypes, [ctypes.c_uint, ctypes.c_uint, ctypes.c_int])
        self.assertEqual(libc.close_range.restype, ctypes.c_int)

    def test_disambiguated_no_new_privs_or_close_failure_never_installs_filter(self):
        for failure in ("no-new-privileges", "close-fds"):
            libc = Mock()
            libc.prctl.side_effect = lambda option, *args: (0 if failure == "no-new-privileges" else 1) if option == 39 else 0
            libc.capset.return_value = 0
            libc.close_range.return_value = -1
            with patch.object(bootstrap.os, "uname", return_value=SimpleNamespace(machine="x86_64")), \
                    patch.object(bootstrap.os, "getuid", return_value=10002), \
                    patch.object(bootstrap.os, "getgid", return_value=10002), \
                    patch.object(bootstrap.os, "getpid", return_value=1), \
                    patch.object(bootstrap.os, "getppid", return_value=0), \
                    patch.object(bootstrap.fcntl, "fcntl", return_value=0), \
                    patch.object(bootstrap.os, "fstat", return_value=SimpleNamespace(st_mode=0o010000)), \
                    patch.object(bootstrap.resource, "setrlimit"), \
                    patch.object(bootstrap, "capabilities", return_value=(0,0,0)), \
                    patch.object(bootstrap, "landlock") as landlock, self.assertRaises(bootstrap.Unavailable):
                bootstrap.enforce(libc, "/scratch/tmpabcdefgh")
            self.assertEqual(bootstrap.STAGE, failure)
            self.assertFalse(any(call.args[0] == 22 for call in libc.prctl.call_args_list))
            if failure == "no-new-privileges":
                libc.close_range.assert_not_called()
                landlock.assert_not_called()
            else:
                libc.close_range.assert_called_once_with(3, 0xffffffff, 0)
            record = ("imp017-bootstrap:" + failure + ":unavailable\n").encode()
            category = startup_category(record)
            self.assertEqual(category, "sandbox-" + failure + "-unavailable")
            self.assertIn(category, verifier.FAILURE_CATEGORIES)

    def test_bootstrap_enforcement_order_and_failed_landlock_never_installs_filter(self):
        for unavailable in (False, True):
            order = []
            libc = Mock()
            def prctl(option, *args):
                order.append(option)
                return 1 if option == 39 else 0
            libc.prctl.side_effect = prctl
            libc.capset.return_value = 0
            libc.close_range.side_effect = lambda *args: order.append("close-fds") or 0
            def landlock(*args):
                order.append("landlock")
                if unavailable:
                    raise bootstrap.Unavailable()
            with patch.object(bootstrap.os, "uname", return_value=SimpleNamespace(machine="x86_64")), \
                    patch.object(bootstrap.os, "getuid", return_value=10002), \
                    patch.object(bootstrap.os, "getgid", return_value=10002), \
                    patch.object(bootstrap.os, "getpid", return_value=1), \
                    patch.object(bootstrap.os, "getppid", return_value=0), \
                    patch.object(bootstrap.fcntl, "fcntl", return_value=0), \
                    patch.object(bootstrap.os, "fstat", return_value=SimpleNamespace(st_mode=0o010000)), \
                    patch.object(bootstrap.resource, "setrlimit"), \
                    patch.object(bootstrap, "capabilities", return_value=(0,0,0)), \
                    patch.object(bootstrap, "landlock", side_effect=landlock):
                if unavailable:
                    with self.assertRaises(bootstrap.Unavailable):
                        bootstrap.enforce(libc, "/scratch/tmpabcdefgh")
                    self.assertNotIn(22, order)
                    libc.close_range.assert_not_called()
                else:
                    bootstrap.enforce(libc, "/scratch/tmpabcdefgh")
                    self.assertEqual(order[-3:], ["landlock", "close-fds", 22])
                    libc.close_range.assert_called_once_with(3, 0xffffffff, 0)
                    # Typed prctl accepts a full-width pointer value, not a
                    # byref object accidentally converted/truncated to c_int.
                    self.assertIsInstance(libc.prctl.call_args.args[2], int)

    def test_existing_launcher_checked_without_install_fallback(self):
        lock = json.loads((ROOT / "pdf-extractor/dependencies.lock.json").read_text())
        path = Mock()
        path.is_file.return_value = True
        path.is_symlink.return_value = False
        path.stat.return_value.st_mode = 0o100755
        path.read_bytes.return_value = b"owned synthetic executable bytes"
        for version in (lock["existing_launcher"]["version"], "drift"):
            with patch.object(pdf_build, "Path", return_value=path), \
                    patch.object(pdf_build, "call", side_effect=[version, "unshare from util-linux 2.38.1"]) as call:
                if version == "drift":
                    with self.assertRaises(SystemExit):
                        pdf_build.launcher(lock)
                else:
                    self.assertEqual(pdf_build.launcher(lock)["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertFalse(any("apt-get" in item.args[0] for item in call.call_args_list))

    def test_actual_probe_failures_remain_failed_not_denied_success(self):
        for leaked, expected in ((True, "denial-handles"), (False, "denial-capabilities")):
            libc = Mock()
            def fstat(fd):
                if leaked:
                    return object()
                raise OSError(9, "synthetic")
            output = io.StringIO()
            with patch.object(sandbox_probe.os, "fstat", side_effect=fstat), \
                    patch.object(sandbox_probe.os, "write", side_effect=OSError(9, "synthetic")), \
                    patch.object(sandbox_probe.ctypes, "CDLL", return_value=libc), \
                    patch.object(bootstrap, "capabilities", return_value=(1, 0, 0)), \
                    patch.object(sys, "stdout", output):
                sandbox_probe.main("denial")
            self.assertEqual(output.getvalue(), "imp017-probe-failure:boundary-assertion:" + expected + "\n")

    def test_same_bootstrap_launch_has_no_mount_root_or_persistent_namespace_option(self):
        path = Mock()
        path.read_bytes.return_value = b"owned launcher"
        path.read_text.return_value = json.dumps({"launcher": {"sha256": hashlib.sha256(b"owned launcher").hexdigest()}})
        class Launched(Exception):
            pass
        with patch.object(sys, "argv", ["synthetic", "launch", "/scratch/tmpabcdefgh", "worker"]), \
                patch.object(bootstrap, "job_directory"), patch.object(bootstrap, "capabilities", return_value=(0,0,0)), \
                patch.object(bootstrap.os, "getuid", return_value=10002), \
                patch.object(bootstrap.os, "getgid", return_value=10002), \
                patch.object(bootstrap, "Path", return_value=path), \
                patch.object(bootstrap, "namespaces", return_value=["1", "2", "3"]), \
                patch.object(bootstrap.os, "chdir"), patch.object(bootstrap.ctypes, "CDLL", return_value=Mock(prctl=Mock(return_value=0))), \
                patch.object(bootstrap.os, "execve", side_effect=Launched) as execute, self.assertRaises(Launched):
            bootstrap.main()
        args = execute.call_args.args[1]
        self.assertEqual(args[:9], ["/usr/bin/unshare", "--user", "--map-current-user", "--pid", "--net",
                                    "--ipc", "--fork", "--kill-child=KILL", "--"])
        self.assertEqual(args[-6:], ["child", "/scratch/tmpabcdefgh", "worker", "1", "2", "3"])


class MountProbeTests(unittest.TestCase):
    def invoke(self, *, unshare_errno=None, changed=True, caps=True, map_errno=None,
               fact_errno=None, mount_errno=13):
        """Fake ALL namespace, map, capability and mount operations; no runtime."""
        libc = Mock()
        libc.unshare.return_value = -1 if unshare_errno else 0
        libc.mount.return_value = -1 if mount_errno else 0
        before, after = ((1, 10), (1, 20)), ((1, 11), (1, 21))
        facts = Mock(side_effect=PermissionError(13, "private") if fact_errno else
                     [after if changed else before, after])
        write = Mock(side_effect=PermissionError(map_errno, "private") if map_errno else None)
        with patch.object(mount_probe.ctypes, "CDLL", return_value=libc), \
                patch.object(mount_probe.ctypes, "get_errno", return_value=unshare_errno or mount_errno), \
                patch.object(mount_probe, "outer_guard", return_value=before), \
                patch.object(mount_probe, "namespaces", facts), \
                patch.object(mount_probe, "write_map", write), \
                patch.object(mount_probe, "effective", return_value=mount_probe.SYS_ADMIN if caps else 0), \
                patch.object(mount_probe.os, "getuid", return_value=10002), \
                patch.object(mount_probe.os, "getgid", return_value=10002):
            result = mount_probe.probe()
        return result, libc, write, facts

    def test_exact_operation_only_in_verified_new_namespaces_with_local_capability(self):
        for number, expected in ((13, "eacces"), (1, "eperm"), (0, "ok")):
            result, libc, write, facts = self.invoke(mount_errno=number)
            self.assertEqual(result, ("root-slave-recursive", expected))
            libc.unshare.assert_called_once_with(0x10020000)
            libc.mount.assert_called_once_with(None, b"/", None, 0x8c000, None)
            self.assertEqual([call.args for call in write.call_args_list], [
                ("/proc/self/uid_map", "10002 10002 1\n"),
                ("/proc/self/setgroups", "deny\n"),
                ("/proc/self/gid_map", "10002 10002 1\n")])
            self.assertEqual(facts.call_count, 2)

    def test_unavailable_namespace_or_mapping_never_mounts_or_uses_another_reader(self):
        for kwargs, expected in (({"unshare_errno": 1}, ("unshare-user-mount", "eperm")),
                ({"changed": False}, ("namespace-guard", "unavailable")),
                ({"caps": False}, ("namespace-guard", "unavailable")),
                ({"map_errno": 13}, ("uid-map", "eacces")),
                ({"fact_errno": 13}, ("namespace-guard", "eacces"))):
            with self.subTest(kwargs=kwargs):
                result, libc, write, facts = self.invoke(**kwargs)
                self.assertEqual(result, expected)
                libc.mount.assert_not_called()
                if "caps" not in kwargs and "map_errno" not in kwargs:
                    write.assert_not_called()
                if "fact_errno" in kwargs:
                    self.assertEqual(facts.call_count, 1)

    def test_outer_guard_stops_wrong_identity_caps_or_unreadable_status(self):
        for uid, caps in ((0, 0), (10002, mount_probe.SYS_ADMIN)):
            with patch.object(mount_probe.os, "getuid", return_value=uid), \
                    patch.object(mount_probe.os, "getgid", return_value=10002), \
                    patch.object(mount_probe, "effective", return_value=caps), \
                    patch("builtins.open") as read, self.assertRaises(mount_probe.Stop):
                mount_probe.outer_guard(Mock())
            read.assert_not_called()
        with patch.object(mount_probe.os, "getuid", return_value=10002), \
                patch.object(mount_probe.os, "getgid", return_value=10002), \
                patch.object(mount_probe, "effective", return_value=0), \
                patch("builtins.open", side_effect=PermissionError(13, "private")) as read, \
                patch.object(mount_probe, "namespaces") as facts, self.assertRaises(PermissionError):
            mount_probe.outer_guard(Mock())
        read.assert_called_once_with("/proc/self/status", "rb")
        facts.assert_not_called()


if __name__ == "__main__":
    unittest.main()
