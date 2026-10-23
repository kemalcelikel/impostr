"""Pure IMP-026 profile/CLI checks; no Docker, worker, browser, or provider run."""

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import imp026_browser as guardian
import imp026_browser_fixture as fixture
import imp005_connection as ordinary
import imp024_verify as verifier
import local_browser_fixture as browser


class NativeCandidateProfileTests(unittest.TestCase):
    def test_profile_uses_native_baseline_and_only_explicit_ui_runtime_overlays(self):
        policy = browser.IMP026_CANDIDATE_PREVIEW_POLICY
        self.assertEqual(policy.base_commit, "bd6454c77f819d106c56c599f46602cb1f01c9fe")
        self.assertEqual(browser.IMP026_NATIVE_ANCESTOR,
                         "a966d7775567860fb5943fb9db080f241aadc27d")
        self.assertTrue(policy.strict_scope and policy.fingerprint_test_changes
                        and policy.fingerprint_harness_changes)
        self.assertEqual(set(path for path, _status in policy.reviewed_inputs), {
            "web/src/AttachmentComposer.tsx", "web/src/ProjectChat.tsx", "web/src/chat.ts",
            "web/src/api.ts", "scripts/imp026_browser.py",
        })
        self.assertEqual(policy.nonruntime_test_changes,
                         (("web/src/ProjectChat.test.tsx", "modified"),))
        self.assertNotIn("api/tests/conftest.py", policy.status_paths)
        self.assertNotIn("scripts/imp018_verify.py", policy.status_paths)
        self.assertIn("api/migrations/versions/20261014_0012_native_send_authorization.py",
                      policy.required_snapshot_paths)
        self.assertIn("scripts/imp025_verify.py", policy.committed_support_paths)
        valid_rules = ("\n".join(browser.IMP026_CANDIDATE_DOCKERIGNORE_RULES) + "\n").encode()
        with patch.object(browser, "_read_candidate_file", return_value=valid_rules):
            browser.validate_candidate_dockerignore(fixture.ROOT, imp026=True)
        with patch.object(browser, "_read_candidate_file", return_value=b"**\n!api/\n"):
            with self.assertRaises(browser.FixtureError):
                browser.validate_candidate_dockerignore(fixture.ROOT, imp026=True)

    def test_readonly_preflight_fingerprints_exact_candidate_and_emits_no_source_paths(self):
        records = (browser.CandidateInputRecord(
            "web/src/ProjectChat.tsx", "modified", 3, 0o644, hashlib.sha256(b"ui\n").hexdigest()),)
        with patch.object(browser, "imp026_verified_head", return_value=("d" * 40, {})) as ancestry, \
                patch.object(browser, "_resolve_head_commit", return_value="d" * 40), \
                patch.object(browser, "_collect_candidate_worktree_inputs", return_value=(records, {})) as collect, \
                patch.object(browser, "_candidate_records_fingerprint", return_value="a" * 64), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(fixture.candidate_preflight(), 0)
        ancestry.assert_called_once_with(fixture.ROOT, private_home=Path("/tmp/opencode"))
        collect.assert_called_once_with(
            fixture.ROOT, private_home=Path("/tmp/opencode"),
            policy=browser.IMP026_CANDIDATE_PREVIEW_POLICY,
        )
        report = json.loads(output.getvalue())
        self.assertEqual(report["fingerprint"], "a" * 64)
        self.assertEqual(report["head"], "d" * 40)
        self.assertFalse(report["boundary_executed"])
        self.assertEqual(report["synthetic_pdf_path"],
                          "/tmp/opencode/impostr-imp026-review-aaaaaaaaaaaaaaaaaaaa/native-review.pdf")
        self.assertNotIn("ProjectChat", output.getvalue())

    def test_preflight_denies_wrong_head_and_unrelated_dirty_runtime_input(self):
        with patch.object(browser, "imp026_verified_head", side_effect=browser.FixtureError("denied")), \
                patch("sys.stderr", new_callable=io.StringIO) as output:
            self.assertEqual(fixture.candidate_preflight(), 1)
        self.assertEqual(json.loads(output.getvalue()), {
            "boundary_executed": False, "check": "imp026_preflight", "status": "failed",
        })

        changes = {"web/src/ProjectChat.tsx": "modified", "api/tests/conftest.py": "modified"}
        with patch.object(browser, "_candidate_status", return_value=changes), \
                self.assertRaises(browser.FixtureError):
            browser._collect_candidate_worktree_inputs(
                fixture.ROOT, private_home=Path("/tmp/opencode"),
                policy=browser.IMP026_CANDIDATE_PREVIEW_POLICY,
            )

    def test_exact_current_overlay_inventory_excludes_unrelated_dirty_inputs(self):
        records, _contents = browser._collect_candidate_worktree_inputs(
            fixture.ROOT, private_home=Path("/tmp/opencode"),
            policy=browser.IMP026_CANDIDATE_PREVIEW_POLICY,
        )
        expected = (set(path for path, _ in browser.IMP026_RUNTIME_INPUTS)
                    | set(path for path, _ in browser.IMP026_TEST_INPUTS)
                    | set(path for path, _ in browser.IMP026_HARNESS_INPUTS))
        self.assertEqual({row.path for row in records}, expected)
        self.assertFalse(expected.intersection({
            "api/tests/conftest.py", "api/tests/test_chat_postgres.py",
            "scripts/imp018_verify.py", "scripts/test_imp018_verify.py",
        }))

    def test_native_profile_archives_only_its_committed_support_and_overlays_added_ui(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "snapshot"
            candidate = browser.archive_candidate_snapshot(
                fixture.ROOT,
                snapshot,
                private_home=Path("/tmp/opencode"),
                policy=browser.IMP026_CANDIDATE_PREVIEW_POLICY,
            )

            self.assertEqual(candidate.base_commit,
                             browser._resolve_head_commit(fixture.ROOT, private_home=Path("/tmp/opencode")))
            self.assertEqual(
                (snapshot / "web/src/AttachmentComposer.tsx").read_bytes(),
                (fixture.ROOT / "web/src/AttachmentComposer.tsx").read_bytes(),
            )
            self.assertTrue((snapshot / "scripts/imp025_verify.py").is_file())
            browser.validate_candidate_snapshot_tree(snapshot, candidate)
            browser.validate_candidate_worktree_snapshot(
                fixture.ROOT, candidate, private_home=Path("/tmp/opencode"),
                policy=browser.IMP026_CANDIDATE_PREVIEW_POLICY,
            )
            archive = browser.archive_head_snapshot

            def archive_with_committed_guardian(*args, **kwargs):
                head = archive(*args, **kwargs)
                (args[1] / "scripts/imp026_browser.py").write_bytes(
                    (fixture.ROOT / "scripts/imp026_browser.py").read_bytes())
                (args[1] / "scripts/imp026_browser.py").chmod(0o644)
                return head

            # Simulate a declared added guardian already in a recovery commit;
            # the exact reviewed overlay must still archive and validate.
            with patch.object(browser, "archive_head_snapshot", side_effect=archive_with_committed_guardian):
                committed = browser.archive_candidate_snapshot(
                    fixture.ROOT, Path(temporary) / "committed-repair",
                    private_home=Path("/tmp/opencode"), policy=browser.IMP026_CANDIDATE_PREVIEW_POLICY)
            self.assertEqual(committed.fingerprint, candidate.fingerprint)

            with self.assertRaises(browser.FixtureError):
                browser.archive_head_snapshot(
                    fixture.ROOT,
                    Path(temporary) / "unapproved-support",
                    private_home=Path("/tmp/opencode"),
                    expected_commit=browser.IMP026_BASE_COMMIT,
                    additional_paths=("scripts/imp026_browser.py",),
                )

    def test_head_admission_allows_only_declared_repairs_and_bookkeeping(self):
        for changed, admitted in (
            (b"M\0BACKLOG.md\0M\0scripts/local_browser_fixture.py\0A\0scripts/imp026_browser.py\0", True),
            (b"M\0scripts/imp024_broker.py\0", False),
            (b"D\0web/src/ProjectChat.tsx\0", False),
            (b"M\0api/.env\0", False),
            (b"M\0unknown.md\0", False),
        ):
            with self.subTest(admitted=admitted, changed=changed), \
                    patch.object(browser, "_resolve_head_commit", return_value="d" * 40), \
                    patch.object(browser.subprocess, "run", side_effect=(
                        subprocess.CompletedProcess([], 0, stdout=b""),
                        subprocess.CompletedProcess([], 0, stdout=b""),
                        subprocess.CompletedProcess([], 0, stdout=changed),
                    )) as run:
                if admitted:
                    head, changes = browser.imp026_verified_head(fixture.ROOT, private_home=Path("/tmp/opencode"))
                    self.assertEqual(head, "d" * 40)
                    self.assertEqual(changes["scripts/imp026_browser.py"], "added")
                else:
                    with self.assertRaises(browser.FixtureError):
                        browser.imp026_verified_head(fixture.ROOT, private_home=Path("/tmp/opencode"))
                self.assertEqual(run.call_args.args[0][1:4], ["diff", "--no-ext-diff", "--no-textconv"])
        with patch.object(browser, "_resolve_head_commit", return_value="d" * 40), \
                patch.object(browser.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stdout=b"")), \
                self.assertRaises(browser.FixtureError):
            browser.imp026_verified_head(fixture.ROOT, private_home=Path("/tmp/opencode"))

    def test_committed_harness_is_still_fingerprinted_and_staged_changes_denied(self):
        policy = browser.IMP026_CANDIDATE_PREVIEW_POLICY
        changes = dict((*policy.reviewed_inputs, *policy.nonruntime_test_changes, *policy.harness_changes))
        committed = {"scripts/imp026_browser.py": changes.pop("scripts/imp026_browser.py")}
        with patch.object(browser, "_candidate_status", return_value=changes), \
                patch.object(browser, "imp026_verified_head", return_value=("d" * 40, committed)):
            records, _contents = browser._collect_candidate_worktree_inputs(
                fixture.ROOT, private_home=Path("/tmp/opencode"), policy=policy)
        self.assertEqual(next(row.status for row in records if row.path == "scripts/imp026_browser.py"), "added")
        changes["scripts/imp026_browser.py"] = "unexpected"
        with patch.object(browser, "_candidate_status", return_value=changes), \
                patch.object(browser, "imp026_verified_head", return_value=("d" * 40, committed)), \
                self.assertRaises(browser.FixtureError):
            browser._collect_candidate_worktree_inputs(
                fixture.ROOT, private_home=Path("/tmp/opencode"), policy=policy)


class NativeFixtureCommandTests(unittest.TestCase):
    def test_status_projects_fixed_codes_without_mutations_or_private_values(self):
        record = dict(pid=4321, start_time=7654, recovery=dict(
            state_dir="/tmp/impostr-browser-review-synthetic-private-id",
            project_name="impostr-review-" + "a" * 20, owned=False, resources_removed=False))
        with patch.object(browser, "read_cleanup_status", return_value=browser.initial_cleanup_status()), \
                patch.object(browser, "_open_private_directory", return_value=20), \
                patch.object(fixture.os, "open", return_value=21) as open_file, \
                patch.object(fixture.os, "fstat"), patch.object(fixture.os, "close"), \
                patch.object(browser, "_require_plain_private_file"), \
                patch.object(fixture.fcntl, "flock"), \
                patch.object(browser, "_read_control_record", return_value=record), \
                patch.object(browser, "_open_verified_supervisor_pidfd", return_value=None), \
                patch.object(browser, "_validate_recovery_state_directory", return_value=Path(record["recovery"]["state_dir"])), \
                patch.object(browser, "inspect_registered_watchdog_layout", return_value={
                    "watchdog_root_layout": "absent", "watchdog_scratch_layout": "absent"}), \
                patch.object(Path, "exists", return_value=False), \
                patch.object(Path, "is_symlink", return_value=False), \
                patch.object(browser, "main") as mutate, \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(fixture.main(["status"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["guardian"], "idle")
        self.assertEqual(report["supervisor"], "exited")
        self.assertEqual(report["watchdog_paths"], "absent")
        self.assertEqual(report["watchdog_root_layout"], "absent")
        self.assertEqual(report["watchdog_scratch_layout"], "absent")
        self.assertEqual(report["native_input"], "unregistered")
        self.assertEqual(report["compose_ownership"], "never-acquired")
        self.assertFalse(open_file.call_args.args[1] & (os.O_CREAT | os.O_RDWR | os.O_TRUNC))
        self.assertTrue(open_file.call_args.args[1] & os.O_NOFOLLOW)
        mutate.assert_not_called()
        for private in ("4321", "7654", "synthetic-private-id", "a" * 20, "state_dir", "project_name"):
            self.assertNotIn(private, output.getvalue())

    def test_status_failure_suppresses_private_exception_and_partial_results(self):
        with patch.object(browser, "read_cleanup_status", side_effect=PermissionError("synthetic-private-value")), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(fixture.cleanup_status(), 1)
        self.assertEqual(json.loads(output.getvalue()), {
            "check": "imp026_cleanup_status", "status": "unavailable",
        })

    def test_launch_requires_exact_fingerprint_and_delegates_only_native_profile(self):
        with patch.object(browser, "main", return_value=0) as run:
            result = fixture.main(["launch", "--fingerprint", "b" * 64])
        self.assertEqual(result, 0)
        run.assert_called_once_with([
            "launch", "--handoff-dir", str(browser.APPROVED_HANDOFF_DIRECTORY),
            "--lifetime-minutes", str(browser.DEFAULT_LIFETIME_MINUTES),
            "--imp026-candidate-fingerprint", "b" * 64,
        ])
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            fixture.main(["launch", "--fingerprint", "not-a-fingerprint"])
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            fixture.main(["stop", "--handoff-dir", "/other/path"])

    def test_profile_and_guardian_sources_are_syntax_valid_without_execution(self):
        for name in ("scripts/local_browser_fixture.py", "scripts/imp026_browser_fixture.py",
                     "scripts/imp026_browser.py"):
            ast.parse((fixture.ROOT / name).read_bytes(), filename=name)
        self.assertIn("imp026", browser._candidate_selection(SimpleNamespace(
            imp026_candidate_fingerprint="c" * 64)))


class NativeStartupRecoveryTests(unittest.TestCase):
    def test_guardian_uses_private_parent_and_cleans_pre_connection_failure(self):
        directory = guardian.PARENT / ("impostr-browser-chat-" + "a" * 20)
        parent_info = SimpleNamespace(st_dev=1, st_ino=10, st_uid=1000, st_gid=1000,
                                    st_mode=stat.S_IFDIR | 0o775)
        owned_info = SimpleNamespace(st_dev=1, st_ino=12, st_uid=1000, st_gid=1000,
                                   st_mode=stat.S_IFDIR | 0o700)
        for failure in (None, "construct", "review_create", "review_cleanup", "connection_cleanup", "runtime_cleanup"):
            with self.subTest(failure=failure):
                modes = {}
                runtime = Mock(root=directory / "r", channel=directory / "r/channel",
                               scratch=directory / "r/private")
                runtime.fds = {directory: 12, runtime.root: 14,
                               runtime.channel: 15, runtime.scratch: 16}

                def construct(root):
                    # This is the unchanged ordinary OwnedRuntime parent contract.
                    self.assertEqual(root.parent, directory)
                    self.assertEqual(modes[12], 0o700)
                    if failure == "construct":
                        raise RuntimeError("synthetic constructor failure")
                    return runtime

                with patch.multiple(guardian.os,
                        getuid=Mock(return_value=1000), geteuid=Mock(return_value=1000),
                        getgid=Mock(return_value=1000), getegid=Mock(return_value=1000),
                        open=Mock(side_effect=(10, 12)),
                        fstat=Mock(side_effect=lambda fd: {
                            10: parent_info, 12: owned_info,
                        }[fd]),
                        stat=Mock(side_effect=FileNotFoundError), mkdir=Mock(),
                        fchmod=Mock(side_effect=lambda fd, mode: modes.update({fd: mode})),
                        dup=Mock(side_effect=(11, 20, 21, 22, 23)), close=Mock(),
                        read=Mock(return_value=b"")), \
                        patch.object(guardian.ctypes, "CDLL") as libc, \
                        patch.object(guardian.selectors, "DefaultSelector") as selector, \
                        patch.object(ordinary, "OwnedRuntime", side_effect=construct), \
                        patch.object(ordinary, "Connection") as connection, \
                        patch.object(verifier, "reap_children"), \
                        patch.object(guardian, "_create_review_file", return_value=("review", 30, 31, owned_info, "b" * 64)) as create_review, \
                        patch.object(guardian, "_remove_review_file") as remove_review, \
                        patch.object(guardian, "_remove_runtime") as remove_runtime, \
                        patch.object(guardian, "_remove_empty_owned_parent") as remove_parent, \
                        patch("sys.stdout", new_callable=io.StringIO):
                    libc.return_value.prctl.return_value = 0
                    selector.return_value.select.return_value = [(None, None)]
                    connection.return_value.failed.is_set.return_value = False
                    if failure in {"review_cleanup", "connection_cleanup", "runtime_cleanup"}:
                        failed_step = {"review_cleanup": remove_review,
                                       "connection_cleanup": connection.return_value.close,
                                       "runtime_cleanup": remove_runtime}[failure]
                        failed_step.side_effect = RuntimeError("synthetic private detail")
                        with self.assertRaisesRegex(RuntimeError, "fixture cleanup unverified"):
                            guardian.run(directory, 300, "c" * 64)
                        connection.return_value.close.assert_called_once()
                        remove_review.assert_called_once()
                        remove_runtime.assert_called_once()
                        remove_parent.assert_called_once()
                        continue
                    if failure == "review_create":
                        create_review.side_effect = RuntimeError("synthetic input collision")
                        with self.assertRaisesRegex(RuntimeError, "synthetic input collision"):
                            guardian.run(directory, 300, "c" * 64)
                        connection.assert_not_called()
                        remove_runtime.assert_called_once()
                        remove_parent.assert_called_once()
                        continue
                    if failure == "construct":
                        with self.assertRaisesRegex(RuntimeError, "synthetic constructor failure"):
                            guardian.run(directory, 300, "c" * 64)
                        connection.assert_not_called()
                        remove_runtime.assert_not_called()
                    else:
                        self.assertEqual(guardian.run(directory, 300, "c" * 64), 0)
                        remove_runtime.assert_called_once()
                        self.assertEqual(remove_runtime.call_args.args[2], owned_info)
                    remove_parent.assert_called_once_with(10, directory.name, 12, parent_info)

    def test_synthetic_review_file_uses_pinned_private_directory_and_refuses_tampering(self):
        self.assertEqual(guardian.REVIEW_PARENT, Path("/tmp/opencode"))
        with tempfile.TemporaryDirectory(dir=guardian.REVIEW_PARENT) as temporary:
            parent_fd = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            review = None
            try:
                content = b"%PDF-1.4\nsynthetic only\n%%EOF\n"
                review = guardian._create_review_file(parent_fd, "b" * 64, content)
                with self.assertRaises(FileExistsError):
                    guardian._create_review_file(parent_fd, "b" * 64, content)
                self.assertEqual(stat.S_IMODE(os.fstat(review[1]).st_mode), 0o700)
                os.pwrite(review[2], b"changed", 0)
                with self.assertRaises(RuntimeError):
                    guardian._remove_review_file(parent_fd, review)
                self.assertTrue((Path(temporary) / review[0] / "native-review.pdf").is_file())
                os.pwrite(review[2], content, 0)
                guardian._remove_review_file(parent_fd, review)
                review = None
                self.assertEqual(os.listdir(parent_fd), [])
            finally:
                if review is not None:
                    os.close(review[2])
                    os.close(review[1])
                os.close(parent_fd)

    def test_native_recovery_keeps_private_state_if_registered_input_lingers(self):
        recovery = dict(state_dir="/tmp/impostr-browser-review-synthetic", project_name="impostr-review-" + "a" * 20,
                        owned=False, resources_removed=False, native_fingerprint="b" * 64)
        with patch.object(browser, "_read_control_record", return_value={"recovery": recovery}), \
                patch.object(browser, "_validate_recovery_state_directory"), \
                patch.object(Path, "exists", return_value=False), \
                patch.object(browser.time, "monotonic", side_effect=(0, 91)), \
                patch.object(browser.shutil, "rmtree") as remove:
            # A symlink at the exact registered input is also lingering state,
            # never followed/deleted by recovery.
            with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path:
                              path.name == "impostr-imp026-review-" + "b" * 20):
                result = browser.recover_registered_project(Path("/unused"))
        self.assertEqual(result["recovery_status"], "failed")
        remove.assert_not_called()

    def test_native_recovery_fingerprint_is_preserved_when_ownership_advances(self):
        recovery = dict(state_dir="/tmp/impostr-browser-review-synthetic", project_name="impostr-review-" + "a" * 20,
                        owned=False, resources_removed=False, native_fingerprint="b" * 64)
        record = dict(pid=os.getpid(), start_time=55, recovery=recovery)
        with patch.object(browser, "_read_control_record", return_value=record), \
                patch.object(browser, "_proc_start_time", return_value=55), \
                patch.object(browser, "_atomic_write_private_json") as write:
            browser.update_control_recovery(Path("/unused"), state_dir=Path(recovery["state_dir"]),
                                            project_name=recovery["project_name"], owned=True,
                                            native_fingerprint="b" * 64)
            self.assertEqual(write.call_args.args[2]["recovery"]["native_fingerprint"], "b" * 64)
            write.reset_mock()
            for replacement in (None, "c" * 64):
                with self.subTest(replacement=replacement), self.assertRaises(browser.FixtureError):
                    browser.update_control_recovery(Path("/unused"), state_dir=Path(recovery["state_dir"]),
                                                    project_name=recovery["project_name"], owned=True,
                                                    native_fingerprint=replacement)
            write.assert_not_called()

    def test_private_parent_removal_refuses_replaced_or_nonempty_directory(self):
        parent = SimpleNamespace(st_dev=1, st_ino=10)
        owned = SimpleNamespace(st_dev=1, st_ino=12, st_uid=1000, st_gid=1000,
                                st_mode=stat.S_IFDIR | 0o700)
        replaced = SimpleNamespace(**{**vars(owned), "st_ino": 99})
        for current, children in ((owned, []), (replaced, []), (owned, ["unexpected"])):
            with self.subTest(replaced=current is replaced, children=children), \
                    patch.object(guardian.os, "fstat", side_effect=(parent, owned)), \
                    patch.object(guardian.os, "stat", return_value=current), \
                    patch.object(guardian.os, "listdir", return_value=children), \
                    patch.object(guardian.os, "rmdir") as remove:
                if current is owned and not children:
                    guardian._remove_empty_owned_parent(10, "owned", 12, parent)
                    remove.assert_called_once_with("owned", dir_fd=10)
                else:
                    with self.assertRaises(RuntimeError):
                        guardian._remove_empty_owned_parent(10, "owned", 12, parent)
                    remove.assert_not_called()

    def test_native_bind_accepts_only_its_exact_channel_and_readonly_mount(self):
        identity = SimpleNamespace(run_id="a" * 20)
        directory = Path("/tmp/opencode") / ("impostr-browser-chat-" + identity.run_id) / "r/channel"
        config = {"services": {"api": {
            "environment": {"IMPOSTR_CHAT_ENABLED": "1"},
            "volumes": [{"type": "bind", "source": str(directory),
                         "target": "/run/impostr-broker", "read_only": True,
                         "bind": {"create_host_path": False}}],
        }}}
        directory_info = SimpleNamespace(st_mode=stat.S_IFDIR | 0o711, st_uid=1000, st_gid=1000)
        socket_info = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=1000)
        with patch.object(Path, "lstat", side_effect=(directory_info, socket_info)):
            browser.validate_chat_bind(config, identity, directory, native=True)
        with self.assertRaises(browser.FixtureError):
            browser.validate_chat_bind(config, identity, directory)
        with self.assertRaises(browser.FixtureError):
            browser.validate_chat_bind(config, identity, directory.parent, native=True)
        for option, value in (("read_only", False), ("bind", {"create_host_path": True})):
            with self.subTest(option=option):
                changed = json.loads(json.dumps(config))
                changed["services"]["api"]["volumes"][0][option] = value
                with patch.object(Path, "lstat", side_effect=(directory_info, socket_info)), \
                        self.assertRaises(browser.FixtureError):
                    browser.validate_chat_bind(changed, identity, directory, native=True)

        relay = directory.parent / "private/imp024-turn-12345678/relay.sock"
        self.assertLess(len(str(relay).encode()), 108)

    def test_prebuild_recovery_message_does_not_assert_an_engine_failure(self):
        status = browser.initial_cleanup_status()
        status.update(phase="stopped", exit_code=1, private_state="retained-for-recovery",
                      recovery_status="failed")
        with patch.object(browser, "read_cleanup_status", return_value=status), \
                patch("sys.stderr", new_callable=io.StringIO) as output:
            browser._print_recovery_action(browser.APPROVED_HANDOFF_DIRECTORY)
        self.assertIn("No owned Compose resources were created", output.getvalue())
        self.assertIn("operator-assisted diagnosis", output.getvalue())
        self.assertNotIn("after the local Docker engine recovers", output.getvalue())


class EmptyWatchdogRecoveryTests(unittest.TestCase):
    def setUp(self):
        # Owned synthetic test directories only; never the registered incident.
        self.temporary = tempfile.TemporaryDirectory(dir=browser.WATCHDOG_PARENT)
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        overrides = {"WATCHDOG_PARENT": self.parent,
                     "_verify_control_lock_descriptor": Mock(),
                     "_read_control_record": Mock(),
                     "_open_verified_supervisor_pidfd": Mock(return_value=None),
                     "read_cleanup_status": Mock(return_value=browser.initial_cleanup_status())}
        for name, value in overrides.items():
            override = patch.object(browser, name, value)
            override.start()
            self.addCleanup(override.stop)
        self.recovery = dict(state_dir="/tmp/impostr-browser-review-synthetic",
                             project_name="impostr-review-" + "a" * 20,
                             owned=False, resources_removed=False)
        self.record = dict(pid=4321, start_time=55, recovery=self.recovery)
        names = browser._registered_watchdog_names(self.recovery)
        self.root, self.scratch = (self.parent / name for name in names)
        self.root.mkdir(mode=0o700)
        self.scratch.mkdir(mode=0o700)
        browser._read_control_record.return_value = self.record

    def test_empty_native_or_legacy_dirs_are_pinned_and_rmdir_only(self):
        for mode in (0o700, 0o711):
            with self.subTest(mode=mode), patch.object(browser.os, "rmdir") as remove:
                self.root.chmod(mode)
                self.assertEqual(browser.inspect_registered_watchdog_layout(self.recovery), {
                    "watchdog_root_layout": "owned-empty", "watchdog_scratch_layout": "owned-empty",
                })
                browser._remove_empty_registered_watchdog_dirs(Path("/unused"), 77, self.record)
                self.assertEqual([call.args[0] for call in remove.call_args_list],
                                 [self.root.name, self.scratch.name])
                self.assertTrue(all("dir_fd" in call.kwargs for call in remove.call_args_list))
                browser._verify_control_lock_descriptor.assert_called_with(Path("/unused"), 77)
                browser._open_verified_supervisor_pidfd.assert_called_with(self.record)
        with patch.object(browser.os, "rmdir", side_effect=(OSError("private detail"), None)) as remove, \
                self.assertRaisesRegex(browser.FixtureError, "Empty watchdog cleanup remains unverified"):
            browser._remove_empty_registered_watchdog_dirs(Path("/unused"), 77, self.record)
        self.assertEqual(remove.call_count, 2)

    def test_native_shape_with_unknown_lock_is_readonly_and_never_reclaimed(self):
        runtime = self.root / "r"
        runtime.mkdir(mode=0o711)
        runtime.chmod(0o711)
        channel, private = runtime / "channel", runtime / "private"
        channel.mkdir(mode=0o711)
        channel.chmod(0o711)
        private.mkdir(mode=0o700)
        (private / "connection.lock").write_bytes(b"synthetic unread content")
        self.assertEqual(browser.inspect_registered_watchdog_layout(self.recovery), {
            "watchdog_root_layout": "known-native-shape", "watchdog_scratch_layout": "owned-empty",
            "native_channel_layout": "owned-empty", "native_private_layout": "nonempty",
        })
        with patch.object(browser.os, "rmdir") as remove, self.assertRaises(browser.FixtureError):
            browser._remove_empty_registered_watchdog_dirs(Path("/unused"), 77, self.record)
        remove.assert_not_called()
        self.assertTrue((private / "connection.lock").is_file())

    def test_unsafe_mode_and_symlink_are_not_listed_or_reclaimed(self):
        self.root.chmod(0o777)
        with patch.object(browser.os, "listdir", wraps=os.listdir) as listing:
            layout = browser.inspect_registered_watchdog_layout(self.recovery)
        self.assertEqual(layout["watchdog_root_layout"], "unsafe")
        # Only the safe scratch descriptor was listed, not the unsafe root.
        self.assertEqual(listing.call_count, 1)
        self.root.chmod(0o700)
        # Replace only this test's empty root with a link to its owned scratch.
        self.root.rmdir()
        self.root.symlink_to(self.scratch, target_is_directory=True)
        with patch.object(browser.os, "listdir", wraps=os.listdir) as listing, \
                patch.object(browser.os, "rmdir") as remove:
            self.assertEqual(browser.inspect_registered_watchdog_layout(self.recovery)["watchdog_root_layout"], "unsafe")
            self.assertEqual(listing.call_count, 1)
            with self.assertRaises(browser.FixtureError):
                browser._remove_empty_registered_watchdog_dirs(Path("/unused"), 77, self.record)
        remove.assert_not_called()

    def test_replacement_inode_prevents_rmdir_and_other_directory_removal(self):
        real_stat = os.stat
        root_stats = 0

        def replaced_stat(name, **kwargs):
            nonlocal root_stats
            info = real_stat(name, **kwargs)
            if name == self.root.name:
                root_stats += 1
                if root_stats == 2:
                    return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino + 1,
                                           st_uid=info.st_uid, st_gid=info.st_gid, st_mode=info.st_mode)
            return info

        with patch.object(browser.os, "stat", side_effect=replaced_stat), \
                patch.object(browser.os, "rmdir") as remove, self.assertRaises(browser.FixtureError):
            browser._remove_empty_registered_watchdog_dirs(Path("/unused"), 77, self.record)
        remove.assert_not_called()

    def test_registration_and_exclusive_lock_fences_block_before_directory_access(self):
        with patch.object(browser, "_pin_watchdog_directory") as pin:
            browser._verify_control_lock_descriptor.side_effect = browser.FixtureError("lock held")
            with self.assertRaises(browser.FixtureError):
                browser._remove_empty_registered_watchdog_dirs(Path("/unused"), 77, self.record)
            browser._verify_control_lock_descriptor.side_effect = None
            browser._read_control_record.return_value = None
            with self.assertRaises(browser.FixtureError):
                browser._remove_empty_registered_watchdog_dirs(Path("/unused"), 77, self.record)
            browser._read_control_record.return_value = self.record
            browser._open_verified_supervisor_pidfd.return_value = 88
            with patch.object(browser.os, "close") as close, self.assertRaises(browser.FixtureError):
                browser._remove_empty_registered_watchdog_dirs(Path("/unused"), 77, self.record)
            close.assert_called_once_with(88)
            browser._open_verified_supervisor_pidfd.return_value = None
            self.recovery["owned"] = True
            with self.assertRaises(browser.FixtureError):
                browser._remove_empty_registered_watchdog_dirs(Path("/unused"), 77, self.record)
            pin.assert_not_called()

    def test_recovery_attempt_does_not_certify_cleanup_after_rmdir_failure(self):
        with patch.object(browser, "_ensure_control_directory", return_value=Path("/unused")), \
                patch.object(browser, "_open_control_lock", return_value=77), \
                patch.object(browser.os, "close"), \
                patch.object(browser, "_remove_empty_registered_watchdog_dirs", side_effect=OSError("private detail")) as remove, \
                patch.object(browser, "_write_guardian_failure_status") as finish:
            self.assertEqual(browser._attempt_unattended_recovery(browser.APPROVED_HANDOFF_DIRECTORY), 1)
        remove.assert_called_once_with(Path("/unused"), 77, self.record)
        finish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
