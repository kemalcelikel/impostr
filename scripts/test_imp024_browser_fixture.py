"""Pure mocked phase-three profile/bind/lifecycle tests; no worker/Docker runs."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import local_browser_fixture as fixture


class ChatFixtureTests(unittest.TestCase):
    def setUp(self):
        self.identity = fixture.generate_identity(18001)
        self.directory = Path("/tmp/opencode") / ("impostr-browser-chat-" + self.identity.run_id)
        self.mount = {"type": "bind", "source": str(self.directory), "target": "/run/impostr-broker", "read_only": True, "bind": {"create_host_path": False}}
        self.config = {"services": {"api": {"environment": {"IMPOSTR_CHAT_ENABLED": "1"}, "volumes": [self.mount]}, "frontdoor": {}, "db": {}}}

    def owned_stat(self, path):
        return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o666 if path.name == "channel.sock" else stat.S_IFDIR | 0o711, st_uid=1000, st_gid=1000)

    def test_bind_exception_is_exact_readonly_api_only(self):
        with patch.object(Path, "lstat", autospec=True, side_effect=self.owned_stat):
            fixture.validate_chat_bind(self.config, self.identity, self.directory)
            for change in ("writable", "foreign", "extra", "frontdoor"):
                config = copy.deepcopy(self.config)
                if change == "writable": config["services"]["api"]["volumes"][0]["read_only"] = False
                if change == "foreign": config["services"]["api"]["volumes"][0]["source"] = "/var/run/docker.sock"
                if change == "extra": config["services"]["api"]["volumes"].append(dict(self.mount))
                if change == "frontdoor": config["services"]["frontdoor"]["volumes"] = [dict(self.mount)]
                with self.subTest(change=change), self.assertRaises(fixture.FixtureError):
                    fixture.validate_chat_bind(config, self.identity, self.directory)

    def test_profile_pins_delivered_base_and_fingerprints_host_helpers(self):
        policy = fixture.IMP024_CANDIDATE_PREVIEW_POLICY
        self.assertEqual(policy.base_commit, "1121bb3314c7f298a16854f2f21ac084b13b44ae")
        self.assertTrue(policy.strict_scope and policy.fingerprint_harness_changes)
        self.assertIn("api/migrations/versions/20261001_0007_durable_chat.py", policy.required_snapshot_paths)
        self.assertEqual(policy.host_inputs, fixture.IMP024_HOST_INPUTS)
        record = fixture.CandidateInputRecord("scripts/imp024_broker.py", "committed", 1, 0o644, hashlib.sha256(b"a").hexdigest())
        self.assertNotEqual(fixture._candidate_records_fingerprint(policy.base_commit, [record]), fixture._candidate_records_fingerprint(policy.base_commit, [fixture.CandidateInputRecord(record.path, record.status, 1, record.mode, hashlib.sha256(b"b").hexdigest())]))

    def test_opt_in_cli_and_cleanup_waits_for_owned_watchdog(self):
        self.assertEqual(fixture._parse_args(["imp024-candidate-preflight"]).command, "imp024-candidate-preflight")
        parsed = fixture._parse_args([
            "launch", "--handoff-dir", str(fixture.APPROVED_HANDOFF_DIRECTORY),
            "--lifetime-minutes", "30", "--imp024-candidate-fingerprint", "a" * 64,
        ])
        self.assertEqual(fixture._candidate_selection(parsed), ("a" * 64, "imp024"))
        self.assertEqual(parsed.handoff_dir, fixture.APPROVED_HANDOFF_DIRECTORY)
        self.assertEqual(parsed.lifetime_minutes, 30)
        self.assertEqual(fixture._parse_args(["stop", "--handoff-dir", str(parsed.handoff_dir)]).handoff_dir, parsed.handoff_dir)
        supervisor = fixture.FixtureSupervisor(Path(__file__).resolve().parents[1], output=io.StringIO(), candidate_preflight=True, candidate_variant="imp024")
        process = Mock()
        process.wait.return_value = 0
        supervisor.chat_guardian = process
        supervisor.chat_directory = self.directory
        with patch.object(Path, "exists", return_value=False), patch.object(Path, "is_symlink", return_value=False):
            supervisor._stop_chat_broker()
        process.stdin.close.assert_called_once()
        process.wait.assert_called_once_with(timeout=90)
        self.assertIsNone(supervisor.chat_guardian)

    def test_changed_python_and_ts_have_parseable_sources(self):
        # Python compile only: importing/executing the new boundary is not allowed
        # before independent review. TS validation belongs to available web tools.
        root = Path(__file__).resolve().parents[1]
        for name in ("scripts/imp024_browser.py", "scripts/local_browser_fixture.py"):
            compile((root / name).read_bytes(), name, "exec")

    def test_exact_input_collection_keeps_every_backend_build_and_host_byte(self):
        policy = fixture.IMP024_CANDIDATE_PREVIEW_POLICY
        root = Path(__file__).resolve().parents[1]
        changes = dict((*policy.reviewed_inputs, *policy.nonruntime_test_changes, *policy.harness_changes))
        # No Git or boundary execution: exercise readers/secret/size inventory
        # checks against only assigned/public sources with a fixed status oracle.
        with patch.object(fixture, "_candidate_status", return_value=changes):
            records, contents = fixture._collect_candidate_worktree_inputs(root, private_home=root, policy=policy)
        self.assertEqual({item.path for item in records if item.status == "committed"}, set(fixture.IMP024_COMMITTED_INVENTORY))
        self.assertIn("scripts/imp024_browser.py", contents)

    def test_archive_overlay_reread_uses_reviewed_worktree_modes_not_snapshot_modes(self):
        root = Path(__file__).resolve().parents[1]
        policy = fixture.IMP024_CANDIDATE_PREVIEW_POLICY
        overlay = b"services: {}\n"
        record = fixture.CandidateInputRecord(
            "compose.chat-synthetic.yaml", "committed", len(overlay), 0o664,
            hashlib.sha256(overlay).hexdigest(),
        )
        # Exercise preparation orchestration with all archive/write/runtime
        # operations mocked. No snapshot, Docker, broker or private state exists.
        with (
            patch.object(fixture, "_resolve_head_commit", return_value=policy.base_commit),
            patch.object(fixture, "_collect_candidate_worktree_inputs", return_value=((record,), {})),
            patch.object(fixture, "archive_head_snapshot"),
            patch.object(fixture, "_read_candidate_file", return_value=b"snapshot input") as snapshot_read,
            patch.object(fixture, "_read_candidate_file_with_mode", return_value=(overlay, 0o664)) as worktree_read,
            patch.object(fixture, "_write_candidate_snapshot_file") as write,
            patch.object(fixture, "validate_candidate_snapshot_tree"),
            patch.object(fixture, "validate_candidate_worktree_snapshot"),
        ):
            fixture.archive_candidate_snapshot(root, root / "mock-only-snapshot", private_home=root, policy=policy)
        worktree_read.assert_called_once_with(
            root, "compose.chat-synthetic.yaml", maximum_bytes=policy.max_file_bytes,
            allowed_modes=policy.allowed_input_modes,
        )
        self.assertFalse(any(call.args[1] == "compose.chat-synthetic.yaml" for call in snapshot_read.call_args_list))
        write.assert_called_once_with(root / "mock-only-snapshot", "compose.chat-synthetic.yaml", overlay, status="added")

    def test_chat_cleanup_keeps_bind_source_for_account_probe_and_still_rejects_failed_denial(self):
        for login_status in (401, 200, 503):
            with self.subTest(login_status=login_status):
                supervisor = fixture.FixtureSupervisor(
                    Path(__file__).resolve().parents[1], output=io.StringIO(),
                    candidate_preflight=True, candidate_variant="imp024",
                )
                supervisor.identity = fixture.generate_identity(18001)
                supervisor.identity.admin_user_id = str(uuid.uuid4())
                for member in supervisor.identity.members:
                    member.user_id = str(uuid.uuid4())
                supervisor.project_owned = True
                events = []
                channel_exists = True
                # Use the real fixed DB cleanup program and compose-run command,
                # mocking only execution. Removing the bind first reproduces the
                # actual create_host_path=False failure before any DB operation.
                compose = fixture.ComposeController.__new__(fixture.ComposeController)
                def invoke(arguments, **kwargs):
                    self.assertTrue(channel_exists, "API cleanup bind source was removed first")
                    self.assertEqual(arguments[:5], ["run", "--rm", "--no-deps", "api", "python"])
                    self.assertIn(".values(is_active=False)", arguments[-1])
                    events.append("disable-members")
                    return "2"
                compose.invoke = Mock(side_effect=invoke)
                compose.verify_project_resources_owned = Mock()
                compose.down = Mock(side_effect=lambda: events.append("down"))
                compose.verify_project_resources_removed = Mock()
                compose.remove_owned_images = Mock()
                compose.verify_project_images_removed = Mock()
                supervisor.compose = compose
                clients = []
                def api_client(_origin):
                    client = Mock()
                    client.login_status.side_effect = lambda *_args: (events.append("login-denial"), login_status)[1]
                    clients.append(client)
                    return client
                def stop_broker():
                    nonlocal channel_exists
                    events.append("stop-broker")
                    channel_exists = False
                # No Docker, HTTP, private inputs or new boundary execution.
                with patch.object(fixture, "ApiClient", side_effect=api_client), patch.object(supervisor, "_stop_chat_broker", side_effect=stop_broker):
                    errors = supervisor._cleanup()
                self.assertEqual(events[0], "disable-members")
                self.assertLess(events.index("login-denial"), events.index("down"))
                self.assertLess(events.index("down"), events.index("stop-broker"))
                self.assertEqual(supervisor.cleanup_owned_compose, "removed")
                self.assertTrue(all(client.clear_cookies.called for client in clients))
                if login_status == 401:
                    self.assertEqual(errors, [])
                    self.assertEqual(supervisor.cleanup_member_accounts, "verified")
                    self.assertEqual(len(clients), 2)
                else:
                    self.assertIn("Synthetic member deactivation or sign-in denial could not be verified.", errors)
                    self.assertEqual(supervisor.cleanup_member_accounts, "not-verified")
                    if login_status == 200:
                        clients[0].logout.assert_called_once()


class DevelopmentMemberHandoffTests(unittest.TestCase):
    """Map only the exact approved pathname to disposable synthetic test storage.

    Never read/write the real handoff or change its permissions. Exercise actual
    atomic JSON I/O, but supply synthetic directory identity/path observations.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir="/tmp/opencode", prefix="handoff-unit-")
        self.addCleanup(temporary.cleanup)
        self.storage = Path(temporary.name)
        self.approved = fixture.DEVELOPMENT_MEMBER_HANDOFF_DIRECTORY
        self.mode, self.uid, self.gid = 0o775, 1000, 1000
        self.identity = fixture.generate_identity(18002)
        self.member = self.identity.members[0]
        original_lstat, original_resolve = Path.lstat, Path.resolve
        original_open, original_fstat = os.open, os.fstat

        def directory_stat(info):
            values = list(info)
            values[0] = stat.S_IFDIR | self.mode
            values[4:6] = [self.uid, self.gid]
            return os.stat_result(values)

        def lstat(path):
            if path == self.approved:
                return directory_stat(original_lstat(self.storage))
            return original_lstat(path)

        def resolve(path, *args, **kwargs):
            if path == self.approved:
                return self.approved
            return original_resolve(path, *args, **kwargs)

        def open_file(path, *args, **kwargs):
            return original_open(self.storage if path == self.approved else path, *args, **kwargs)

        def fstat(fd):
            info = original_fstat(fd)
            if stat.S_ISDIR(info.st_mode):
                return directory_stat(info)
            return info

        for mocked in (
            patch.object(Path, "lstat", autospec=True, side_effect=lstat),
            patch.object(Path, "resolve", autospec=True, side_effect=resolve),
            patch.object(fixture.os, "open", side_effect=open_file),
            patch.object(fixture.os, "fstat", side_effect=fstat),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_legacy_private_and_exact_development_handoff_io_and_cleanup(self):
        for mode in (0o700, 0o775):
            with self.subTest(mode=oct(mode)):
                self.mode = mode
                self.assertEqual(fixture.validate_approved_handoff_directory(self.approved), self.approved)
                fixture.prepare_handoff_channel(self.approved)
                fixture.write_member_handoff(self.approved, self.member.username, self.member.password)
                fixture.write_cleanup_status(self.approved, fixture.initial_cleanup_status())
                content = (self.storage / fixture.MEMBER_HANDOFF_FILE).read_text()
                status_text = (self.storage / fixture.CLEANUP_STATUS_FILE).read_text()
                self.assertEqual(json.loads(content), {"username": self.member.username, "password": self.member.password})
                self.assertEqual(fixture.read_cleanup_status(self.approved), fixture.initial_cleanup_status())
                for filename in (fixture.MEMBER_HANDOFF_FILE, fixture.CLEANUP_STATUS_FILE):
                    self.assertEqual(stat.S_IMODE((self.storage / filename).stat().st_mode), 0o600)
                for value in (self.identity.admin_password, self.identity.postgres_password,
                              self.identity.app_password, self.identity.rate_limit_key, self.identity.origin):
                    self.assertNotIn(value, content + status_text)
                with self.assertRaises(fixture.FixtureError):
                    fixture.prepare_handoff_channel(self.approved)
                with self.assertRaises(fixture.FixtureError):
                    fixture.remove_member_handoff(self.approved, self.member.username, "changed" * 8)
                self.assertTrue(fixture.remove_member_handoff(self.approved, self.member.username, self.member.password))
                finished = fixture.initial_cleanup_status()
                finished.update(phase="stopped", exit_code=0, member_login="removed")
                fixture.write_cleanup_status(self.approved, finished)
                fixture.prepare_handoff_channel(self.approved)
                fixture.write_member_handoff(self.approved, self.member.username, self.member.password)
                self.assertEqual(fixture._remove_unexpected_member_handoff(self.approved), "removed")

    def test_exception_rejects_other_modes_paths_identity_and_symlinks(self):
        for mode in (0o750, 0o755, 0o770, 0o777, 0o1775):
            self.mode = mode
            with self.subTest(mode=oct(mode)), self.assertRaises(fixture.FixtureError):
                fixture.validate_approved_handoff_directory(self.approved)
        self.mode = 0o775
        for uid, gid in ((1001, 1000), (1000, 1001)):
            self.uid, self.gid = uid, gid
            with self.subTest(uid=uid, gid=gid), self.assertRaises(fixture.FixtureError):
                fixture.write_cleanup_status(self.approved, fixture.initial_cleanup_status())
        self.uid, self.gid = 1000, 1000
        with patch.object(fixture.os, "geteuid", return_value=1001), self.assertRaises(fixture.FixtureError):
            fixture.validate_approved_handoff_directory(self.approved)
        # Caller-supplied approval cannot widen the hard-coded development path.
        info = self.approved.lstat()
        with patch.object(Path, "lstat", return_value=info):
            with self.assertRaises(fixture.FixtureError):
                fixture.prepare_handoff_channel(self.storage, approved_directory=self.storage)
            with self.assertRaises(fixture.FixtureError):
                fixture._validate_private_directory(self.storage, approved_directory=self.storage)
        with patch.object(Path, "resolve", return_value=self.storage), self.assertRaises(fixture.FixtureError):
            fixture.validate_approved_handoff_directory(self.approved)
        info = self.storage.stat()
        values = list(info)
        values[0] = stat.S_IFLNK | 0o775
        with patch.object(Path, "lstat", return_value=os.stat_result(values)), self.assertRaises(fixture.FixtureError):
            fixture.validate_approved_handoff_directory(self.approved)

    def test_private_state_and_generic_io_never_receive_exception(self):
        operations = (
            lambda: fixture._validate_private_directory(self.approved),
            lambda: fixture._open_private_directory(self.approved),
            lambda: fixture._atomic_write_private_json(self.approved, "compose.env", {}, replace_existing=True),
            lambda: fixture._read_private_json(self.approved, fixture.MEMBER_HANDOFF_FILE, maximum_bytes=4096),
            lambda: fixture._unlink_private_file(self.approved, fixture.MEMBER_HANDOFF_FILE),
            lambda: fixture._write_control_record(self.approved, {"pid": 1, "start_time": 1}),
            lambda: fixture._atomic_write_private_json(self.approved, "compose.env", {}, replace_existing=True, member_handoff=True),
        )
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(fixture.FixtureError):
                operation()
        self.assertEqual(list(self.storage.iterdir()), [])

    def test_open_rechecks_identity_mode_inode_and_handoff_file_checks(self):
        real_fstat = os.fstat
        for attribute, value in (("st_gid", 1001), ("st_mode", stat.S_IFDIR | 0o777), ("st_ino", 0)):
            def changed_stat(fd):
                info = real_fstat(fd)
                return SimpleNamespace(**{name: value if name == attribute else getattr(info, name)
                                          for name in ("st_mode", "st_uid", "st_gid", "st_dev", "st_ino")})
            with self.subTest(attribute=attribute), patch.object(fixture.os, "fstat", side_effect=changed_stat), self.assertRaises(fixture.FixtureError):
                fixture._open_private_directory(self.approved, member_handoff=True)
        login = self.storage / fixture.MEMBER_HANDOFF_FILE
        login.symlink_to("unavailable-synthetic-target")
        with self.assertRaises(fixture.FixtureError):
            fixture.write_member_handoff(self.approved, self.member.username, self.member.password)
        login.unlink()
        fixture.write_member_handoff(self.approved, self.member.username, self.member.password)
        login.chmod(0o640)
        with self.assertRaises(fixture.FixtureError):
            fixture.remove_member_handoff(self.approved, self.member.username, self.member.password)
        login.chmod(0o600)
        login.write_text("x" * (fixture.MAX_CHANNEL_JSON_BYTES + 1))
        with self.assertRaises(fixture.FixtureError):
            fixture.remove_member_handoff(self.approved, self.member.username, self.member.password)
        with self.assertRaises(fixture.FixtureError):
            fixture.write_member_handoff(self.approved, "admin", self.member.password)
        with self.assertRaises(fixture.FixtureError):
            fixture.write_cleanup_status(self.approved, {"provider_key": "synthetic-denied"})


if __name__ == "__main__":
    unittest.main()
