"""Pure harness checks ONLY. No Docker, listener, worker, TLS, provider or DB.

API fixture source is syntax checked, not executed on the host. Runtime checks
remain coordinator-owned after exact-input review.
"""

import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock, patch

import imp025_verify as verify
from test_imp025_inline import context, responses


class InputsTests(unittest.TestCase):
    def capture_git(self, head=verify.CHECKPOINT, *, changed=(), new=(), untracked=(), indexed=(),
                    drift=None, reject_ancestor=False):
        """Synthetic Git replies only; never create commits or alter the checkout."""
        reads = 0
        baseline = {"scripts/imp002_prototype.py"}

        def git(*args):
            nonlocal reads
            if args == ("rev-parse", "HEAD"):
                reads += 1
                return ((drift if reads > 1 and drift else head) + "\n").encode()
            if args[0] == "merge-base":
                if reject_ancestor:
                    raise verify.Unavailable()
                self.assertIn(args[2:], ((verify.BASELINE, verify.CHECKPOINT), (verify.CHECKPOINT, head)))
                return b""
            if args[0] == "diff":
                self.assertEqual(args, ("diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                                       "--name-only", "-z", verify.CHECKPOINT, head))
                return b"\0".join(name.encode() for name in changed)
            if args[0] == "ls-tree":
                paths = baseline | (set(new) if args[-1] != verify.BASELINE else set())
                return b"\0".join(b"100644 blob " + b"0" * 40 + b"\t" + name.encode()
                                   for name in sorted(paths))
            if args == ("ls-files", "--others", "--exclude-standard", "-z"):
                return b"\0".join(name.encode() for name in untracked)
            if args == ("ls-files", "--cached", "-z"):
                return b"\0".join(name.encode() for name in baseline | set(indexed))
            self.fail("unexpected Git command: " + str(args))

        return git

    def test_fingerprint_binds_base_paths_order_and_each_original_native_candidate_byte(self):
        inputs = {name: name.encode() for name in verify.NEW_INPUTS}
        actual, metadata = verify.fingerprint(inputs, verify.CHECKPOINT)
        self.assertEqual(metadata["base"], verify.BASELINE)
        self.assertEqual(metadata["head"], verify.CHECKPOINT)
        self.assertEqual(actual, verify.fingerprint(dict(reversed(list(inputs.items()))), verify.CHECKPOINT)[0])
        self.assertNotEqual(actual, verify.fingerprint(inputs, "a" * 40)[0])
        for name in (
            "api/migrations/versions/20261002_0010_pdf_turn_selections.py",
            "api/migrations/versions/20261014_0011_native_pdf_storage.py",
            "api/migrations/versions/20261014_0012_native_send_authorization.py",
            "api/migrations/versions/20261022_0013_retire_pdf_extraction.py",
            "scripts/imp025_verify.py",
        ):
            with self.subTest(name=name):
                self.assertNotEqual(actual, verify.fingerprint(dict(inputs, **{name: inputs[name] + b"\n"}), verify.CHECKPOINT)[0])
        self.assertNotEqual(actual, verify.fingerprint({"scripts/other.py": b"body"}, verify.CHECKPOINT)[0])

    def test_inventory_selects_runtime_and_never_private_or_runner_state(self):
        for name in ("api/app/chat_broker.py", "scripts/imp002_worker.py", "scripts/imp024_operator_transport.py",
                     "scripts/imp018_receipts.py", "scripts/test_imp018_references.py",
                     "web/nginx.conf", "api/requirements-dev.lock", "compose.chat.yaml"):
            self.assertTrue(verify.source_path(name), name)
        for name in (".env", ".opencode/progress.md", "AGENTS.md", "api/.env", "web/node_modules/x.js",
                      "overnight-agent/opencode.json", "scripts/private.log", "../api/app/main.py",
                      *verify.SUPERSEDED_INPUTS, *verify.RETIRED_INPUTS):
            self.assertFalse(verify.source_path(name), name)

    def test_capture_without_superseded_files_still_requires_native_inputs(self):
        captured = {name: name.encode() for name in verify.NEW_INPUTS}
        captured["scripts/imp002_prototype.py"] = b"baseline launcher"
        with tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="imp025-pure-") as directory:
            source = Path(directory) / "source"
            _, metadata = verify.fingerprint(captured, verify.CHECKPOINT)
            verify.freeze(source, captured, metadata)
            with patch.object(verify, "ROOT", source), \
                    patch.object(verify, "git", side_effect=self.capture_git(untracked=verify.NEW_INPUTS)):
                self.assertEqual(verify.capture(), (captured, verify.CHECKPOINT))
                (source / "scripts/imp018_receipts.py").unlink()
                with self.assertRaises(FileNotFoundError):
                    verify.capture()

    def test_preserved_superseded_files_never_enter_capture_or_fingerprint(self):
        expected = {name: name.encode() for name in (*verify.NEW_INPUTS, "scripts/imp002_prototype.py")}
        for state in ("untracked", "indexed"):
            with self.subTest(state=state), \
                    patch.object(verify, "git", side_effect=self.capture_git(
                        untracked=verify.NEW_INPUTS + (tuple(verify.SUPERSEDED_INPUTS) if state == "untracked" else ()),
                        indexed=tuple(verify.SUPERSEDED_INPUTS) if state == "indexed" else ())), \
                    patch.object(verify, "read_source", side_effect=lambda root, name: name.encode()):
                sources, head = verify.capture()
                self.assertEqual(sources, expected)
                self.assertEqual(verify.fingerprint(sources, head), verify.fingerprint(expected, head))

    def test_freeze_uses_captured_bytes_not_later_worktree_and_rejects_symlink_reads(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="imp025-pure-") as directory:
            root = Path(directory)
            source = root / "source"
            captured = {"api/app/main.py": b"exact candidate\n", "scripts/imp025_verify.py": b"harness\n"}
            _, metadata = verify.fingerprint(captured, verify.CHECKPOINT)
            verify.freeze(source, captured, metadata)
            self.assertEqual((source / "api/app/main.py").read_bytes(), captured["api/app/main.py"])
            self.assertEqual((source / "api/app/main.py").stat().st_mode & 0o777, 0o444)
            (root / "scripts").mkdir()
            (root / "scripts/link.py").symlink_to(source / "scripts/imp025_verify.py")
            with self.assertRaises(verify.Unavailable):
                verify.read_source(root, "scripts/link.py")

    def test_base_mismatch_stops_before_source_reads(self):
        with patch.object(verify, "git", side_effect=self.capture_git(reject_ancestor=True)), \
                patch.object(verify, "read_source") as read:
            with self.assertRaises(verify.Unavailable):
                verify.capture()
            read.assert_not_called()

    def test_checkpoint_and_bounded_repair_descendant_reconcile_tracked_new_inventory(self):
        for head in (verify.CHECKPOINT, "a" * 40):
            with self.subTest(head=head), \
                    patch.object(verify, "git", side_effect=self.capture_git(head,
                        changed=("scripts/imp002_prototype.py", "scripts/imp025_verify.py", "BACKLOG.md",
                                 "scripts/imp024_product_worker.py", "scripts/test_imp025_inline.py",
                                 "docs/agent-history.md"),
                        new=("scripts/imp025_verify.py", "scripts/test_imp025_inline.py", "docs/agent-history.md"),
                        untracked=verify.NEW_INPUTS)), \
                    patch.object(verify, "read_source", side_effect=lambda root, name: name.encode()):
                sources, captured_head = verify.capture()
                self.assertEqual(captured_head, head)
                self.assertEqual(set(sources), set(verify.NEW_INPUTS) | {"scripts/imp002_prototype.py"})
                self.assertEqual(verify.fingerprint(sources, head)[1]["head"], head)

    def test_unapproved_committed_source_drift_rejected_before_reading_candidate(self):
        with patch.object(verify, "git", side_effect=self.capture_git("a" * 40,
                    changed=("scripts/imp024_product_worker.py", "scripts/test_imp025_inline.py",
                             "docs/agent-history.md", "api/app/chat.py"))), \
                patch.object(verify, "read_source") as read:
            with self.assertRaises(verify.Unavailable):
                verify.capture()
            read.assert_not_called()

    def test_head_change_during_capture_fails(self):
        with patch.object(verify, "git", side_effect=self.capture_git(drift="b" * 40)), \
                patch.object(verify, "read_source", side_effect=lambda root, name: name.encode()):
            with self.assertRaises(verify.Unavailable):
                verify.capture()

    def test_unlisted_new_source_rejected_whether_untracked_staged_or_committed(self):
        for state in ("untracked", "indexed", "new"):
            with self.subTest(state=state), \
                    patch.object(verify, "git", side_effect=self.capture_git("a" * 40,
                        **{state: ("scripts/imp018_unlisted.py",)})), \
                    patch.object(verify, "read_source", side_effect=lambda root, name: name.encode()):
                with self.assertRaises(verify.Unavailable):
                    verify.capture()

    def test_frozen_child_revalidates_all_bytes_before_runtime(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="imp025-pure-") as directory:
            source = Path(directory) / "source"
            captured = {name: name.encode() for name in verify.NEW_INPUTS}
            expected, metadata = verify.fingerprint(captured, verify.CHECKPOINT)
            verify.freeze(source, captured, metadata)
            with patch.object(verify, "ROOT", source):
                verify.check_frozen(expected)
                changed = source / "api/migrations/versions/20261014_0012_native_send_authorization.py"
                changed.chmod(0o600)
                changed.write_bytes(b"changed candidate")
                with self.assertRaises(verify.Unavailable):
                    verify.check_frozen(expected)

    def test_frozen_manifest_and_extra_source_cannot_drift(self):
        for mutation in ("head", "row", "extra", "superseded"):
            with self.subTest(mutation=mutation), \
                    tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="imp025-pure-") as directory:
                source = Path(directory) / "source"
                captured = {name: name.encode() for name in verify.NEW_INPUTS}
                expected, metadata = verify.fingerprint(captured, verify.CHECKPOINT)
                verify.freeze(source, captured, metadata)
                if mutation in ("extra", "superseded"):
                    name = "scripts/imp018_verify.py" if mutation == "superseded" else "scripts/unlisted.py"
                    (source / name).write_bytes(b"not captured")
                else:
                    if mutation == "head":
                        metadata["head"] = "a" * 40
                    else:
                        metadata["files"][0]["sha256"] = "f" * 64
                    manifest = source / verify.MANIFEST
                    manifest.chmod(0o600)
                    manifest.write_text(json.dumps(metadata))
                with patch.object(verify, "ROOT", source), self.assertRaises(verify.Unavailable):
                    verify.check_frozen(expected)

    def test_preflight_has_no_owned_runtime_or_command(self):
        sources = {"scripts/imp025_verify.py": b"synthetic source"}
        with patch.object(verify, "capture", return_value=(sources, verify.CHECKPOINT)), \
                patch.object(verify, "Verify") as runtime, patch.object(verify, "report") as report:
            self.assertEqual(verify.main(["--preflight"]), 0)
            runtime.assert_not_called()
            self.assertFalse(report.call_args.kwargs["boundary_executed"])
            self.assertEqual(report.call_args.kwargs["fingerprint"], verify.fingerprint(sources, verify.CHECKPOINT)[0])

    def test_execution_missing_review_or_wrong_fingerprint_never_prepares(self):
        with patch.object(verify, "Verify") as runtime, patch.object(verify, "capture", return_value=({}, verify.CHECKPOINT)), \
                patch.object(verify, "report"), patch("sys.stderr", new=io.StringIO()):
            for argv in (["--synthetic"], ["--api-only", "--fingerprint", "a" * 64],
                         ["--retirement-only"], ["--retirement-only", "--fingerprint", "a" * 64],
                         ["--retirement-only", "--synthetic", "--reviewed-harness", "--fingerprint", "a" * 64],
                         ["--preflight", "--reviewed-harness"], ["--preflight", "--frozen"]):
                with self.assertRaises(SystemExit):
                    verify.main(argv)
            self.assertEqual(verify.main(["--synthetic", "--reviewed-harness", "--fingerprint", "f" * 64]), 1)
            runtime.assert_not_called()

    def test_frozen_retirement_mode_validates_source_before_runner_construction(self):
        argv = ["--retirement-only", "--reviewed-harness", "--fingerprint", "a" * 64, "--frozen"]
        with patch.object(verify, "check_frozen") as frozen, \
                patch.object(verify, "NativeVerify") as runner:
            runner.return_value.run.return_value = 0
            self.assertEqual(verify.main(argv), 0)
            frozen.assert_called_once_with("a" * 64)
            runner.assert_called_once_with(False, retirement_only=True)
        with patch.object(verify, "check_frozen", side_effect=verify.Unavailable), \
                patch.object(verify, "NativeVerify") as runner, patch.object(verify, "report"):
            self.assertEqual(verify.main(argv), 1)
            runner.assert_not_called()

    def test_api_fixture_sources_parse_without_importing_host_dependencies(self):
        for name in ("api/tests/imp025_native_fixture.py", "api/tests/test_imp025_native_integration.py"):
            ast.parse((verify.ROOT / name).read_bytes(), filename=name)
        self.assertTrue(all("test_chat_references.py" not in name and "test_chat_receipts.py" not in name
                            for name in verify.API_TESTS))
        self.assertTrue(any("outage_restart" in name for name in verify.API_TESTS))
        self.assertTrue(any("capture_delete_race" in name for name in verify.PG_TESTS))


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.body = b"%PDF-exact synthetic binary\x00\xff"
        self.payload = context(self.body, history=True)
        self.metadata = self.payload["context"]  # Turn.run's binary-free factory input.
        self.receiver = verify.Receiver()
        self.receiver.originals[hashlib.sha256(self.body).hexdigest()] = self.body
        reporting = patch.object(verify, "report")
        self.report = reporting.start()
        self.addCleanup(reporting.stop)

    def encoded(self, data):
        return json.dumps(dict(data, model="synthetic", stream=True, store=False),
                          separators=(",", ":"), ensure_ascii=True).encode()

    def submission(self, data):
        encoded = self.encoded(data)
        return SimpleNamespace(ledger=SimpleNamespace(native=True), row=dict(turn_id="synthetic-turn", call=1,
            request_sha256=hashlib.sha256(encoded).hexdigest(), request_size=len(encoded)))

    def inspect(self, data):
        return self.receiver.inspect(self.metadata, self.submission(data), self.encoded(data))

    def test_receiver_checks_decoded_exact_bytes_order_final_serialization_and_no_raw_retention(self):
        self.assertFalse(self.inspect(responses(self.payload)))
        observed = self.receiver.observations[0]
        self.assertEqual([row["message_index"] for row in observed["manifest"]], [0, 2])
        self.assertEqual(observed["request_sha256"], hashlib.sha256(self.encoded(responses(self.payload))).hexdigest())
        self.assertNotIn("file_data", json.dumps(observed))
        self.assertNotIn(base64.b64encode(self.body).decode(), json.dumps(observed))

    def test_changed_foreign_missing_reordered_remote_and_extra_parts_fail_without_observation(self):
        for mutate in (
            lambda data: data["input"][0]["content"][1].update(file_data="data:application/pdf;base64," + base64.b64encode(b"%PDF-wrong").decode()),
            lambda data: data["input"][0]["content"][1].update(filename="foreign.pdf"),
            lambda data: data["input"][0]["content"].pop(),
            lambda data: data["input"][0]["content"].reverse(),
            lambda data: data["input"][0]["content"][1].update(file_data="https://example.invalid/file.pdf"),
            lambda data: data["input"][0]["content"][1].update(file_id="provider-file"),
        ):
            with self.subTest(mutate=mutate):
                data = responses(self.payload)
                mutate(data)
                with self.assertRaises(verify.Unavailable):
                    self.inspect(data)
                self.assertEqual(self.receiver.observations, [])

    def test_missing_original_and_final_receipt_hash_size_mismatch_fail(self):
        data = responses(self.payload)
        self.receiver.originals.clear()
        with self.assertRaises(KeyError):
            self.inspect(data)
        self.receiver.originals[hashlib.sha256(self.body).hexdigest()] = self.body
        encoded = self.encoded(data)
        for row in (dict(request_sha256="f" * 64, request_size=len(encoded)),
                    dict(request_sha256=hashlib.sha256(encoded).hexdigest(), request_size=len(encoded) + 1)):
            with self.assertRaises(verify.Unavailable):
                self.receiver.inspect(self.metadata, SimpleNamespace(row=dict(row, turn_id="turn", call=1)), encoded)
        self.assertEqual(self.receiver.observations, [])

    def test_transport_delegates_actual_events_not_consumed_or_normalizer_only(self):
        from imp024_operator_transport import PlanningHTTPSInference

        with patch.object(PlanningHTTPSInference, "__init__") as dns, \
                patch.object(PlanningHTTPSInference, "events", return_value=iter([b"synthetic-frame"])) as actual:
            transport = self.receiver.transport(self.metadata)
            submission = SimpleNamespace(ledger=SimpleNamespace(native=True))
            self.assertEqual(list(transport.events({}, None, 10, submission=submission)), [b"synthetic-frame"])
            dns.assert_not_called()
            actual.assert_called_once_with({}, None, 10, submission=submission)
            self.assertIsInstance(transport.connection(), verify.CapturedConnection)

    def test_metadata_only_factory_observes_request_and_serves_native_tool_followup(self):
        from imp024_inference import parsed_events
        from imp024_operator_transport import PlanningHTTPSInference

        self.metadata["prompt"] = "SYNTHETIC NATIVE TOOL"
        self.assertNotIn("context", self.metadata)
        self.assertNotIn("files", self.metadata)
        self.assertNotIn(base64.b64encode(self.body).decode(), json.dumps(self.metadata))
        transport = self.receiver.transport(self.metadata)
        data = responses(self.payload)
        for followup in (False, True):
            with self.subTest(followup=followup):
                if followup:
                    data["input"].append(dict(type="function_call_output", call_id="call_native_read",
                                              output=self.metadata["documents"]["PROJECT.md"]["content"]))
                submission = self.submission(data)
                with patch.object(PlanningHTTPSInference, "events", return_value=iter(())):
                    list(transport.events(data, None, 10, submission=submission))
                connection = transport.connection()
                connection.request("POST", "/openai/v1/responses", self.encoded(data),
                                   {"api-key": "generated-synthetic-key-not-real"})
                response = connection.getresponse()
                events = list(parsed_events(iter(lambda: response.read1(4096), b"")))
                output = events[-1]["response"]["output"][0]
                if followup:
                    self.assertEqual(output["content"][0]["text"], "Synthetic native assistant quotation.")
                else:
                    self.assertEqual(output["call_id"], "call_native_read")
                    self.assertEqual(json.loads(output["arguments"]), {"filePath": "/project/PROJECT.md"})
                observed = self.receiver.observations[-1]
                self.assertEqual(observed["followup"], followup)
                self.assertEqual(observed["manifest"], [item["manifest"] for item in self.payload["files"]])
        self.assertEqual(len(self.receiver.observations), 2)

    def test_planning_followup_requires_actual_canonical_read_result(self):
        self.metadata["prompt"] = "SYNTHETIC NATIVE TOOL"
        data = responses(self.payload)
        data["input"].append(dict(type="function_call_output", call_id="call_native_read", output="# Draft\n"))
        self.assertTrue(self.inspect(data))
        data["input"][-1]["output"] = "not the actual planning file"
        with self.assertRaises(verify.Unavailable):
            self.inspect(data)

    def test_actual_transport_and_relay_normalizer_finish_ordered_files_and_fresh_followup(self):
        from app.chat_protocol import native_occurrence_manifest
        from imp018_receipts import ReceiptLedger
        from imp024_inference import normalized_events, parsed_events
        from imp024_protocol import fixture_definitions

        second_body = b"%PDF-distinct synthetic original"
        second = context(second_body)
        self.metadata["history"] = []
        first_reference = self.metadata["references"][0]
        second_reference = second["context"]["references"][0]
        self.metadata["references"] = [second_reference, first_reference, second_reference]
        self.metadata["prompt"] = "SYNTHETIC NATIVE TOOL"
        self.receiver.originals[hashlib.sha256(second_body).hexdigest()] = second_body
        urls = {hashlib.sha256(self.body).hexdigest(): self.payload["files"][0]["url"],
                hashlib.sha256(second_body).hexdigest(): second["files"][0]["url"]}
        self.payload["files"] = [dict(manifest=item, url=urls[item["original_sha256"]])
            for item in native_occurrence_manifest(self.metadata)]
        ledger = ReceiptLedger(tuple(str(uuid.uuid4()) for _ in range(3)), str(uuid.uuid4()), self.payload)
        self.addCleanup(ledger.close)
        transport = self.receiver.transport(self.metadata)
        data = responses(self.payload)
        data["tools"] = fixture_definitions()
        grants = []
        for followup in (False, True):
            call = ledger.begin(None)
            output, errors = [], []

            def submit():
                try:
                    # Same two normalizers as PlanningHTTPSInference + host relay;
                    # only the connection is the in-memory receiver. No socket.
                    output.extend(normalized_events(transport.events(data, threading.Event(),
                        time.monotonic() + 3, submission=call), data))
                except Exception as error:
                    errors.append(type(error).__name__)
                finally:
                    call.finish()

            thread = threading.Thread(target=submit)
            thread.start()
            self.addCleanup(thread.join, 4)
            deadline = time.monotonic() + 1
            pending = None
            while thread.is_alive() and time.monotonic() < deadline:
                pending = ledger.pending_authorization()
                if pending is not None:
                    break
                time.sleep(0.002)
            self.assertIsNotNone(pending)
            grant = dict(pending, authorization_id=str(uuid.uuid4()))
            grants.append(grant)
            ledger.grant(grant)
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            events = list(parsed_events(output))
            self.assertEqual(events[-1]["type"], "response.completed")
            self.assertNotIn("error", [item["type"] for item in events])
            terminal = events[-1]["response"]["output"][0]
            if not followup:
                self.assertEqual(terminal["call_id"], "call_native_read")
                data["input"].extend([{key: terminal[key] for key in ("type", "name", "call_id", "arguments")},
                    dict(type="function_call_output",
                    call_id="call_native_read", output=self.metadata["documents"]["PROJECT.md"]["content"])])
            else:
                self.assertEqual(terminal["content"][0]["text"], "Synthetic native assistant quotation.")
        self.assertNotEqual(grants[0]["authorization_id"], grants[1]["authorization_id"])
        rows = ledger.snapshot()
        self.assertEqual([row["status"] for row in rows], ["sent", "sent"])
        self.assertEqual([row["authorization_id"] for row in rows],
                         [grant["authorization_id"] for grant in grants])
        self.assertEqual([row["followup"] for row in self.receiver.observations], [False, True])
        self.assertEqual([row["attachment_id"] for row in self.receiver.observations[0]["manifest"]],
                         [entry["reference"]["attachment_id"] for entry in self.metadata["references"]])
        product = object.__new__(verify.Product)
        product.receiver = self.receiver
        product.base = "unused synthetic route"
        turn = dict(id=ledger.key[2], state="completed", submission=dict(status="sent",
            reference_kind="native-original-v1", rendered_sha256=ledger.rendered_sha256,
            manifest_sha256=ledger.manifest_sha256, calls=rows))
        product.request = Mock(return_value=SimpleNamespace(json=lambda: dict(turns=[turn])))
        self.assertIs(product.wait(turn["id"]), turn)  # Exact Product receipt assertions too.
        self.report.assert_not_called()

    def test_response_close_releases_list_frames_and_remains_idempotent(self):
        connection = verify.CapturedConnection(self.receiver, self.metadata, None)
        response = connection.getresponse()
        self.assertTrue(response.read1(4096))
        response.close()
        self.assertEqual(response.read1(4096), b"")
        response.close()
        self.report.assert_not_called()


class ProductDiagnosticTests(unittest.TestCase):
    def product(self, turn):
        product = object.__new__(verify.Product)
        product.base = "/synthetic"
        product.receiver = verify.Receiver()
        product.request = Mock(return_value=SimpleNamespace(json=lambda: dict(turns=[turn] if turn else [])))
        return product

    def test_wait_separates_missing_failed_unsent_and_timeout_without_private_data(self):
        for state, operation, category in ((None, "wait_turn", "missing_turn"),
                ("failed", "wait_terminal", "turn_failed"),
                ("cancelled", "wait_terminal", "turn_cancelled"),
                ("interrupted", "wait_terminal", "turn_interrupted"),
                ("completed", "wait_submission", "submission_not_sent"),
                ("queued", "wait_deadline", "timeout")):
            with self.subTest(state=state), patch.object(verify, "report") as report:
                turn = None if state is None else dict(id="private-turn-id", state=state,
                    submission=dict(status="failed-before-send"))
                product = self.product(turn)
                if state in ("failed", "cancelled", "interrupted"):
                    events = dict(events=[dict(turn_id="private-other-turn", type="failed", data=dict(reason="worker_error")),
                        dict(turn_id="private-turn-id", type="failed", data=dict(reason="private credential")),
                        dict(turn_id="private-turn-id", type="failed", data=dict(reason="worker_error"))], after=3)
                    product.request.side_effect = [product.request.return_value, SimpleNamespace(json=lambda: events)]
                with patch.object(verify.time, "monotonic", side_effect=[0, 1, 121]), \
                        patch.object(verify.time, "sleep"), self.assertRaises(verify.Unavailable):
                    product.wait("private-turn-id")
                fields = dict(operation=operation, category=category)
                self.assertEqual(report.call_args_list[0].args, ("native_diagnostic", "failed"))
                self.assertEqual(report.call_args_list[0].kwargs, fields)
                if state in ("failed", "cancelled", "interrupted"):
                    self.assertEqual(report.call_args_list[1].kwargs,
                                     dict(operation="wait_failure_events", category=category, reason="worker_error"))
                else:
                    self.assertEqual(report.call_count, 1)
                self.assertNotIn("private", str(report.call_args_list))

    def test_failure_reason_read_uses_bounded_pagination_and_never_resubmits(self):
        product = self.product(dict(id="synthetic-turn", state="failed", submission=dict(status="sent")))
        history = product.request.return_value
        page = dict(events=[dict(turn_id="other-turn", type="failed", data=dict(reason="worker_error"))], after=1)
        failed = dict(events=[dict(turn_id="synthetic-turn", type="failed", data=dict(reason="native_session_error"))], after=2)
        product.request.side_effect = [history, SimpleNamespace(json=lambda: page), SimpleNamespace(json=lambda: failed)]
        with patch.object(verify, "report") as report, self.assertRaises(verify.Unavailable):
            product.wait("synthetic-turn")
        self.assertEqual(product.request.call_args_list[-1].args, ("GET", "/synthetic/events?after=1"))
        self.assertEqual(report.call_args.kwargs["reason"], "native_session_error")
        product.request.reset_mock(side_effect=True)
        product.request.side_effect = [history] + [SimpleNamespace(json=lambda index=index: dict(page, after=index))
                                                  for index in range(1, 6)]
        with patch.object(verify, "report"), self.assertRaises(verify.Unavailable):
            product.wait("synthetic-turn")
        self.assertEqual(product.request.call_count, 6)  # History plus at most five event pages.
        self.assertTrue(all(call.args[0] == "GET" for call in product.request.call_args_list))

    def test_receipt_failure_identifies_count_and_binding_without_hashes_or_ids(self):
        from app.chat_protocol import NATIVE_PDF_REFERENCE
        turn = dict(id="private-turn-id", submission=dict(reference_kind=NATIVE_PDF_REFERENCE, calls=[]))
        product = self.product(turn)
        with patch.object(verify, "report") as report, self.assertRaises(verify.Unavailable):
            product.receipt(turn)
        report.assert_called_once_with("native_diagnostic", "failed", operation="receipt_count", category="count")
        product.receiver.observations = [dict(turn_id=turn["id"], call=1)]
        turn["submission"]["calls"] = [dict(status="failed-before-send")]
        with patch.object(verify, "report") as report, self.assertRaises(verify.Unavailable):
            product.receipt(turn)
        self.assertEqual(report.call_args_list[0].kwargs, dict(operation="receipt_call", category="binding"))
        self.assertNotIn("private", str(report.call_args_list))

    def test_request_status_is_projected_without_route_response_or_exception_text(self):
        product = object.__new__(verify.Product)
        product.client = SimpleNamespace(base_url="private origin", cookies={},
            request=Mock(return_value=SimpleNamespace(status_code=503, text="private response")))
        with patch.object(verify, "report") as report, self.assertRaises(verify.Unavailable):
            product.request("GET", "/private/path")
        report.assert_called_once_with("native_diagnostic", "failed", operation="product_request", category="http_status")
        product.client.request.side_effect = TimeoutError("private credential in exception")
        with patch.object(verify, "report") as report, self.assertRaises(TimeoutError):
            product.request("GET", "/private/path")
        report.assert_called_once_with("native_diagnostic", "failed", operation="product_request", category="timeout")

    def test_probe_classifies_receiver_cleanup_failure_without_exception_text(self):
        with patch.object(verify, "report") as report, self.assertRaises(AttributeError):
            with verify.native_probe("receiver_close"):
                raise AttributeError("private binary or credential")
        report.assert_called_once_with("native_diagnostic", "failed", operation="receiver_close", category="shape")


class OutputAndOrchestrationTests(unittest.TestCase):
    def test_retirement_only_runs_two_preservation_cases_and_cleans_on_failure(self):
        runner = verify.NativeVerify(False, retirement_only=True)
        runner.base = ["owned-compose"]
        runner.owner_overlay = Path("/owned/native-owner.yaml")
        for failed in (False, True):
            with self.subTest(failed=failed), patch.object(runner, "prepare"), \
                    patch.object(runner, "compose") as compose, \
                    patch.object(runner, "command", side_effect=verify.Unavailable if failed else None) as command, \
                    patch.object(runner, "check") as check, \
                    patch.object(runner, "cleanup", return_value=True) as cleanup, \
                    patch.object(runner, "run_native") as native, patch.object(verify, "report"):
                self.assertEqual(runner.run(), 1 if failed else 0)
                self.assertEqual([call.args for call in compose.call_args_list], [
                    ("build", "db"), ("up", "-d", "--wait", "db"),
                ])
                command.assert_called_once()
                self.assertEqual(command.call_args.args[0], [
                    "owned-compose", "-f", "/owned/native-owner.yaml", "run", "--build", "--rm",
                    "api-integration-owner-check", "python", "-m", "pytest", "-p", "no:cacheprovider",
                    "--tb=no", "--show-capture=no", "--color=no", "-s", verify.RETIREMENT_TEST,
                ])
                self.assertEqual(command.call_args.kwargs["output"].expected, 2)
                check.assert_not_called()
                native.assert_not_called()
                cleanup.assert_called_once()

    def test_pytest_requires_execution_no_skips_and_exact_pg_count(self):
        output = verify.ResultOutput(expected=2)
        output.feed(b"private arbitrary output\n2 passed in 0.1s\n")
        output.finish()
        for raw in (b"", b"2 passed, 1 skipped\n", b"1 passed\n", b"2 passed, 1 failed\n"):
            with self.subTest(raw=raw), self.assertRaises(verify.Unavailable):
                output = verify.ResultOutput(expected=2)
                output.feed(raw)
                output.finish()

    def test_child_output_projects_only_fixed_metadata_and_requires_success(self):
        output = verify.SafeOutput()
        with patch.object(verify, "report") as report:
            with self.assertRaises(verify.Unavailable):
                output.feed(b'{"username":"private-login","password":"private-password"}\n')
            # Unknown JSON shapes fail closed rather than being printed.
            self.assertFalse(report.called)

    def test_child_success_drops_raw_metadata(self):
        output = verify.SafeOutput()
        with patch.object(verify, "report") as report:
            output.feed(b'{"check":"imp025_verification","status":"passed","body":"private","password":"secret"}\n')
            output.finish()
            report.assert_called_once_with("imp025_verification", "passed")

    def test_native_diagnostics_survive_child_projection_with_only_fixed_fields(self):
        output = verify.SafeOutput()
        row = dict(check="native_diagnostic", status="failed", operation="receiver_close", category="shape",
                   reason="worker_error", path="private path", body="private binary", traceback="private exception")
        with patch.object(verify, "report") as report:
            output.feed(json.dumps(row).encode() + b"\n")
            report.assert_called_once_with("native_diagnostic", "failed", operation="receiver_close",
                                          category="shape", reason="worker_error")
            report.reset_mock()
            row["reason"] = "private credential"
            output.feed(json.dumps(row).encode() + b"\n")
            report.assert_called_once_with("native_diagnostic", "failed", operation="receiver_close", category="shape")
            for field in ("operation", "category"):
                report.reset_mock()
                bad = dict(row, **{field: "private arbitrary label"})
                with self.assertRaises(verify.Unavailable):
                    output.feed(json.dumps(bad).encode() + b"\n")
                report.assert_not_called()

    def test_static_diagnostic_accepts_only_fixed_owned_paths_codes_and_locations(self):
        output = verify.SafeOutput()
        row = dict(check="api_lint", status="failed", file="app/chat.py", code="F401", line=10,
                   message="private arbitrary output")
        with patch.object(verify, "report") as report:
            output.feed(json.dumps(row).encode() + b"\n")
            report.assert_called_once_with("api_lint", "failed", file="app/chat.py", code="F401", line=10)
            row["file"] = "/private/unknown.py"
            with self.assertRaises(verify.Unavailable):
                output.feed(json.dumps(row).encode() + b"\n")

    def test_api_only_never_starts_native_or_builds_extractor_and_failure_still_cleans(self):
        runner = verify.NativeVerify(False)
        runner.base = ["owned-compose"]
        runner.owner_overlay = Path("/owned/native-owner.yaml")
        with patch.object(runner, "prepare"), patch.object(runner, "compose") as compose, \
                patch.object(runner, "command"), patch.object(runner, "check"), \
                patch.object(runner, "cleanup", return_value=True) as cleanup, \
                patch.object(runner, "run_native") as native, patch.object(verify, "report"):
            self.assertEqual(runner.run(), 0)
            native.assert_not_called()
            cleanup.assert_called_once()
            build = compose.call_args_list[0].args
            self.assertEqual(build, ("build", "db", "api", "api-check", "api-integration-check"))
            self.assertFalse(any("extractor" in str(call) for call in compose.call_args_list))
        with patch.object(runner, "prepare", side_effect=verify.Unavailable), \
                patch.object(runner, "cleanup", return_value=False) as cleanup, patch.object(verify, "report"):
            self.assertEqual(runner.run(), 1)
            cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
