"""Security and lifecycle tests for the disposable local browser-review fixture."""

from __future__ import annotations

import ast
import hashlib
import io
import ipaddress
import json
import os
import pty
import re
import secrets
import select
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from http.cookiejar import Cookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import local_browser_fixture as fixture


def committed_username_validator():
    """Load the committed app's username rule without importing API dependencies."""
    repository_root = Path(fixture.__file__).resolve().parent.parent
    result = subprocess.run(
        ["git", "show", "--no-ext-diff", "--no-textconv", "HEAD:api/app/passwords.py"],
        cwd=repository_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError("The committed app username contract could not be loaded.")

    tree = ast.parse(result.stdout, filename="HEAD:api/app/passwords.py")
    pattern = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_USERNAME_PATTERN"
            for target in node.targets
        )
    )
    normalizer = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "normalize_username"
    )
    isolated = ast.Module(body=[pattern, normalizer], type_ignores=[])
    namespace: dict[str, object] = {"re": re}
    exec(compile(ast.fix_missing_locations(isolated), "committed_username_contract", "exec"), namespace)
    return namespace["normalize_username"]


class UsernameContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.normalize_username = staticmethod(committed_username_validator())

    def test_every_generated_account_name_passes_committed_app_validation(self) -> None:
        identity = fixture.generate_identity(18473)
        username_tag = identity.run_id[:12]
        self.assertRegex(identity.run_id, r"^[0-9a-f]{20}$")
        self.assertEqual(identity.project_name, f"impostr-review-{identity.run_id}")
        self.assertEqual(identity.admin_username, f"a{username_tag}")
        self.assertEqual(
            [member.username for member in identity.members],
            [f"m1{username_tag}", f"m2{username_tag}"],
        )
        self.assertLessEqual(len(identity.admin_username), 13)
        self.assertTrue(all(len(member.username) <= 14 for member in identity.members))
        usernames = [
            identity.admin_username,
            *(member.username for member in identity.members),
            *(fixture.denied_member_username(identity, index) for index in (1, 2)),
        ]

        self.assertEqual(len(usernames), len(set(usernames)))
        for username in usernames:
            with self.subTest(username=username):
                self.assertTrue(username.isascii() and username.isalnum())
                self.assertEqual(self.normalize_username(username), username)

    def test_previous_underscore_forms_match_the_committed_validator(self) -> None:
        identity = fixture.generate_identity(18474)
        previous_names = (
            f"reviewadmin_{identity.run_id}",
            f"review_member_a_{identity.run_id}",
            f"review_member_b_{identity.run_id}",
            f"review_denied_{identity.run_id}_1",
        )

        for username in previous_names:
            with self.subTest(username=username):
                self.assertEqual(self.normalize_username(username), username)


class MigrationVerificationTests(unittest.TestCase):
    def test_revision_output_is_reduced_to_a_fixed_safe_status(self) -> None:
        self.assertEqual(
            fixture.migration_revision_status("20260925_0004 (head)\n"),
            "expected",
        )
        self.assertEqual(fixture.migration_revision_status(""), "empty")
        secret = secrets.token_urlsafe(24)
        self.assertEqual(
            fixture.migration_revision_status(f"unknown {secret}"),
            "unexpected",
        )


class CommittedMigrationProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "source"
        self.versions = self.source / "api" / "migrations" / "versions"
        self.versions.mkdir(parents=True)

    def _write_revisions(self, names: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
        pinned = []
        for name in names:
            content = f"synthetic migration body for {name}\n".encode("utf-8")
            path = self.versions / name
            path.write_bytes(content)
            path.chmod(0o644)
            pinned.append((name, hashlib.sha256(content).hexdigest()))
        return tuple(pinned)

    def test_profile_digests_match_the_repository_migration_sources(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        for profile in fixture.COMMITTED_APP_MIGRATION_PROFILES:
            for filename, expected_digest in profile.revision_files:
                with self.subTest(profile=profile.name, migration=filename):
                    source = (
                        repository_root / "api" / "migrations" / "versions" / filename
                    )
                    self.assertEqual(
                        hashlib.sha256(source.read_bytes()).hexdigest(),
                        expected_digest,
                    )

    def test_current_0004_and_future_0005_committed_snapshots_select_distinct_profiles(
        self,
    ) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        filenames_0004 = tuple(
            name for name, _digest in fixture.COMMITTED_APP_MIGRATION_FILES_0004
        )
        for filename in filenames_0004:
            source = repository_root / "api" / "migrations" / "versions" / filename
            target = self.versions / filename
            target.write_bytes(source.read_bytes())
            target.chmod(0o644)

        self.assertEqual(
            fixture.select_committed_app_migration_profile(
                self.source,
                fixture.IMP013_CANDIDATE_BASE_COMMIT,
            ),
            "imp004",
        )

        migration_0005_name = fixture.COMMITTED_APP_MIGRATION_FILES_0005[-1][0]
        migration_0005_source = (
            repository_root / "api" / "migrations" / "versions" / migration_0005_name
        )
        migration_0005_target = self.versions / migration_0005_name
        migration_0005_target.write_bytes(migration_0005_source.read_bytes())
        migration_0005_target.chmod(0o644)
        self.assertEqual(
            fixture.select_committed_app_migration_profile(self.source, "b" * 40),
            "imp013",
        )

    def test_committed_0004_and_0005_profiles_require_exact_revision_bytes(self) -> None:
        filenames_0004 = (
            "20260925_0001_initial_baseline.py",
            "20260925_0002_identity_and_project_metadata.py",
            "20260925_0003_project_document_revisions.py",
            "20260925_0004_bounded_project_name_keys.py",
        )
        filenames_0005 = (*filenames_0004, "20260929_0005_document_pair_approvals.py")
        pinned_0004 = self._write_revisions(filenames_0004)
        fifth_content = f"synthetic migration body for {filenames_0005[-1]}\n".encode("utf-8")
        profiles = (
            fixture.CommittedMigrationProfile("imp004", "a" * 40, pinned_0004),
            fixture.CommittedMigrationProfile(
                "imp013",
                None,
                (
                    *pinned_0004,
                    (filenames_0005[-1], hashlib.sha256(fifth_content).hexdigest()),
                ),
            ),
        )

        self.assertEqual(
            fixture.select_committed_app_migration_profile(
                self.source,
                "a" * 40,
                profiles=profiles,
            ),
            "imp004",
        )
        self._write_revisions((filenames_0005[-1],))
        self.assertEqual(
            fixture.select_committed_app_migration_profile(
                self.source,
                "b" * 40,
                profiles=profiles,
            ),
            "imp013",
        )

        self.assertEqual(
            fixture.COMMITTED_APP_MIGRATION_PROFILES[0].commit,
            fixture.IMP013_CANDIDATE_BASE_COMMIT,
        )
        self.assertEqual(
            tuple(
                name
                for name, _digest in fixture.COMMITTED_APP_MIGRATION_PROFILES[1].revision_files
            ),
            filenames_0005,
        )

    def test_unknown_missing_forked_and_modified_migration_heads_fail_closed(self) -> None:
        filenames_0004 = (
            "20260925_0001_initial_baseline.py",
            "20260925_0002_identity_and_project_metadata.py",
            "20260925_0003_project_document_revisions.py",
            "20260925_0004_bounded_project_name_keys.py",
        )
        filenames_0005 = (*filenames_0004, "20260929_0005_document_pair_approvals.py")
        pinned_0004 = self._write_revisions(filenames_0004)
        fifth_content = f"synthetic migration body for {filenames_0005[-1]}\n".encode("utf-8")
        pinned_0005_file = (filenames_0005[-1], hashlib.sha256(fifth_content).hexdigest())
        profiles = (
            fixture.CommittedMigrationProfile("imp004", "a" * 40, pinned_0004),
            fixture.CommittedMigrationProfile("imp013", None, (*pinned_0004, pinned_0005_file)),
        )

        with self.assertRaises(fixture.FixtureError):
            fixture.select_committed_app_migration_profile(
                self.source,
                "c" * 40,
                profiles=profiles,
            )

        migration_0005 = self.versions / filenames_0005[-1]
        with self.assertRaises(fixture.FixtureError):
            fixture.select_committed_app_migration_profile(
                self.source,
                "b" * 40,
                profiles=profiles,
            )

        self._write_revisions((filenames_0005[-1],))
        with self.assertRaises(fixture.FixtureError):
            fixture.select_committed_app_migration_profile(
                self.source,
                "a" * 40,
                profiles=profiles,
            )
        self.assertEqual(
            fixture.select_committed_app_migration_profile(
                self.source,
                "b" * 40,
                profiles=profiles,
            ),
            "imp013",
        )

        fork = self.versions / "20260930_0006_unreviewed_fork.py"
        fork.write_text("unexpected migration fork\n", encoding="utf-8")
        fork.chmod(0o644)
        with self.assertRaises(fixture.FixtureError):
            fixture.select_committed_app_migration_profile(
                self.source,
                "b" * 40,
                profiles=profiles,
            )

        fork.unlink()
        migration_0005.write_text("modified committed migration\n", encoding="utf-8")
        migration_0005.chmod(0o644)
        with self.assertRaises(fixture.FixtureError):
            fixture.select_committed_app_migration_profile(
                self.source,
                "b" * 40,
                profiles=profiles,
            )


class MigrationDiagnosticTests(unittest.TestCase):
    @staticmethod
    def valid_diagnostic() -> dict[str, object]:
        return {
            "probe_stage": "complete",
            "discovery_status": "ok",
            "database_probe_status": "ok",
            "image_files_status": "ok",
            "script_location": "expected",
            "script_directory": "present",
            "versions_directory": "present",
            "migration_directory_mode": "0755",
            "migration_directory_owner": "root",
            "runtime_migration_access": "yes",
            "versions_directory_mode": "0755",
            "versions_directory_owner": "root",
            "runtime_versions_access": "yes",
            "image_files": {
                "alembic_ini": "present",
                "env_py": "present",
                "revision_0001": "present",
                "revision_0002": "present",
            },
            "discovered_revisions": ["20260925_0001", "20260925_0002"],
            "heads": ["20260925_0002"],
            "database_config": "expected",
            "database": "expected",
            "schema": "public",
            "alembic_version_table": "yes",
            "current": "expected",
            "users": "yes",
        }

    @classmethod
    def valid_candidate_diagnostic(cls) -> dict[str, object]:
        diagnostic = cls.valid_diagnostic()
        diagnostic["image_files"] = {
            **diagnostic["image_files"],
            "revision_0003": "present",
            "revision_0004": "present",
        }
        diagnostic["discovered_revisions"] = list(fixture.CANDIDATE_APP_REVISIONS)
        diagnostic["heads"] = [fixture.CANDIDATE_APP_MIGRATION]
        diagnostic["projects_name_key"] = "yes"
        diagnostic["project_documents"] = "yes"
        diagnostic["project_document_revisions"] = "yes"
        diagnostic["document_conflict_proposals"] = "yes"
        return diagnostic

    @classmethod
    def valid_imp013_candidate_diagnostic(cls) -> dict[str, object]:
        diagnostic = cls.valid_candidate_diagnostic()
        diagnostic["image_files"] = {
            **diagnostic["image_files"],
            "revision_0005": "present",
        }
        diagnostic["discovered_revisions"] = list(fixture.IMP013_CANDIDATE_APP_REVISIONS)
        diagnostic["heads"] = [fixture.IMP013_CANDIDATE_APP_MIGRATION]
        diagnostic["project_document_pair_approvals"] = "yes"
        return diagnostic

    def test_runtime_diagnostic_code_compiles_without_reading_database_settings(self) -> None:
        compile(fixture.MIGRATION_DIAGNOSTIC_PYTHON, "<migration-diagnostic>", "exec")

    def test_candidate_diagnostic_is_separate_and_probes_revision_and_schema(self) -> None:
        compile(
            fixture.CANDIDATE_MIGRATION_DIAGNOSTIC_PYTHON,
            "<candidate-migration-diagnostic>",
            "exec",
        )
        self.assertIn(
            "20260925_0003_project_document_revisions.py",
            fixture.CANDIDATE_MIGRATION_DIAGNOSTIC_PYTHON,
        )
        self.assertIn(
            "20260925_0004_bounded_project_name_keys.py",
            fixture.CANDIDATE_MIGRATION_DIAGNOSTIC_PYTHON,
        )
        self.assertIn(
            'current_revisions == ["20260925_0004"]',
            fixture.CANDIDATE_MIGRATION_DIAGNOSTIC_PYTHON,
        )
        self.assertNotIn("revision_0003", fixture.MIGRATION_DIAGNOSTIC_PYTHON)

        parsed_candidate = fixture.parse_migration_diagnostic(
            json.dumps(self.valid_candidate_diagnostic(), separators=(",", ":")),
            candidate=True,
        )
        self.assertIsNotNone(parsed_candidate)
        assert parsed_candidate is not None
        self.assertTrue(fixture.migration_diagnostic_is_complete(parsed_candidate, candidate=True))
        self.assertIsNone(
            fixture.parse_migration_diagnostic(
                json.dumps(self.valid_candidate_diagnostic(), separators=(",", ":"))
            ),
            "default committed-HEAD parsing must reject candidate-only evidence",
        )

    def test_imp013_diagnostic_requires_fresh_0005_and_approval_table(self) -> None:
        compile(
            fixture.IMP013_CANDIDATE_MIGRATION_DIAGNOSTIC_PYTHON,
            "<imp013-migration-diagnostic>",
            "exec",
        )
        self.assertIn(
            "20260929_0005_document_pair_approvals.py",
            fixture.IMP013_CANDIDATE_MIGRATION_DIAGNOSTIC_PYTHON,
        )
        self.assertIn(
            'current_revisions == ["20260929_0005"]',
            fixture.IMP013_CANDIDATE_MIGRATION_DIAGNOSTIC_PYTHON,
        )
        self.assertIn(
            '"project_document_pair_approvals" in tables',
            fixture.IMP013_CANDIDATE_MIGRATION_DIAGNOSTIC_PYTHON,
        )

        diagnostic = self.valid_imp013_candidate_diagnostic()
        parsed = fixture.parse_migration_diagnostic(
            json.dumps(diagnostic, separators=(",", ":")),
            imp013_candidate=True,
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(fixture.migration_diagnostic_is_complete(parsed, imp013_candidate=True))
        self.assertIn(
            "0005:present",
            fixture.format_migration_diagnostic(parsed, imp013_candidate=True),
        )
        self.assertIn(
            "project_document_pair_approvals=yes",
            fixture.format_migration_diagnostic(parsed, imp013_candidate=True),
        )
        self.assertIsNone(
            fixture.parse_migration_diagnostic(
                json.dumps(diagnostic),
                candidate=True,
            ),
            "the prior IMP-004 profile must not accept IMP-013 schema evidence",
        )

        missing_table = self.valid_imp013_candidate_diagnostic()
        missing_table["project_document_pair_approvals"] = "no"
        parsed_missing = fixture.parse_migration_diagnostic(
            json.dumps(missing_table),
            imp013_candidate=True,
        )
        self.assertIsNotNone(parsed_missing)
        assert parsed_missing is not None
        self.assertFalse(
            fixture.migration_diagnostic_is_complete(parsed_missing, imp013_candidate=True)
        )

        wrong_head = self.valid_imp013_candidate_diagnostic()
        wrong_head["heads"] = [fixture.CANDIDATE_APP_MIGRATION]
        parsed_wrong_head = fixture.parse_migration_diagnostic(
            json.dumps(wrong_head),
            imp013_candidate=True,
        )
        self.assertIsNotNone(parsed_wrong_head)
        assert parsed_wrong_head is not None
        self.assertFalse(
            fixture.migration_diagnostic_is_complete(parsed_wrong_head, imp013_candidate=True)
        )

    def test_only_allowlisted_image_revision_and_database_evidence_is_formatted(self) -> None:
        diagnostic = fixture.parse_migration_diagnostic(
            json.dumps(self.valid_candidate_diagnostic(), separators=(",", ":")),
            candidate=True,
        )

        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        self.assertTrue(fixture.migration_diagnostic_is_complete(diagnostic, candidate=True))
        self.assertEqual(
            fixture.format_migration_diagnostic(diagnostic, candidate=True),
            "probe_stage=complete discovery_status=ok database_probe_status=ok "
            "image_files_status=ok "
            "script_location=/app/migrations script_directory=present "
            "versions_directory=present migration_directory_mode=0755 "
            "migration_directory_owner=root runtime_migration_access=yes "
            "versions_directory_mode=0755 versions_directory_owner=root "
            "runtime_versions_access=yes "
            "image_files=alembic.ini:present,env.py:present,0001:present,0002:present,"
            "0003:present,0004:present "
            "revisions=20260925_0001,20260925_0002,20260925_0003,20260925_0004 "
            "heads=20260925_0004 database_config=expected database=expected schema=public "
            "alembic_version_table=yes catalog_current=expected users=yes "
            "candidate_schema=projects_name_key:yes,project_documents:yes,"
            "project_document_revisions:yes,document_conflict_proposals:yes",
        )

    def test_unreadable_image_revisions_fail_closed_with_modes_not_raw_errors(self) -> None:
        diagnostic_data = self.valid_candidate_diagnostic()
        diagnostic_data["versions_directory_mode"] = "0700"
        diagnostic_data["runtime_versions_access"] = "no"
        diagnostic_data["image_files_status"] = "permission-denied"
        diagnostic_data["image_files"]["revision_0001"] = "permission-denied"
        diagnostic_data["image_files"]["revision_0002"] = "permission-denied"
        diagnostic_data["image_files"]["revision_0003"] = "permission-denied"
        diagnostic_data["image_files"]["revision_0004"] = "permission-denied"
        diagnostic_data["discovered_revisions"] = []
        diagnostic_data["heads"] = []
        diagnostic_data["current"] = "empty"
        diagnostic_data["users"] = "no"
        diagnostic = fixture.parse_migration_diagnostic(
            json.dumps(diagnostic_data),
            candidate=True,
        )

        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        rendered = fixture.format_migration_diagnostic(diagnostic, candidate=True)
        self.assertIn("versions_directory_mode=0700", rendered)
        self.assertIn("runtime_versions_access=no", rendered)
        self.assertIn(
            "0001:permission-denied,0002:permission-denied,"
            "0003:permission-denied,0004:permission-denied",
            rendered,
        )
        self.assertFalse(fixture.migration_diagnostic_is_complete(diagnostic, candidate=True))

    def test_unknown_values_extra_output_and_oversized_diagnostics_fail_closed(self) -> None:
        secret = secrets.token_urlsafe(24)
        unknown = self.valid_diagnostic()
        unknown["script_location"] = secret
        self.assertIsNone(fixture.parse_migration_diagnostic(json.dumps(unknown)))

        injected = json.dumps(self.valid_diagnostic()) + secret
        self.assertIsNone(fixture.parse_migration_diagnostic(injected))

        oversized = " " * fixture.MAX_MIGRATION_DIAGNOSTIC_BYTES + secret
        self.assertIsNone(fixture.parse_migration_diagnostic(oversized))

    def test_candidate_diagnostics_reject_forks_missing_tables_and_extra_fields(self) -> None:
        forked = self.valid_candidate_diagnostic()
        forked["heads"] = ["20260925_0003", "20260925_0004"]
        parsed_forked = fixture.parse_migration_diagnostic(
            json.dumps(forked),
            candidate=True,
        )
        self.assertIsNotNone(parsed_forked)
        assert parsed_forked is not None
        self.assertFalse(fixture.migration_diagnostic_is_complete(parsed_forked, candidate=True))

        incomplete = self.valid_candidate_diagnostic()
        incomplete["project_document_revisions"] = "no"
        parsed_incomplete = fixture.parse_migration_diagnostic(
            json.dumps(incomplete),
            candidate=True,
        )
        self.assertIsNotNone(parsed_incomplete)
        assert parsed_incomplete is not None
        self.assertFalse(
            fixture.migration_diagnostic_is_complete(parsed_incomplete, candidate=True)
        )

        extra = self.valid_candidate_diagnostic()
        extra["database_url"] = secrets.token_urlsafe(32)
        self.assertIsNone(
            fixture.parse_migration_diagnostic(json.dumps(extra), candidate=True)
        )

    def test_stderr_classifier_reports_only_fixed_categories(self) -> None:
        secret = secrets.token_urlsafe(24).encode("ascii")
        stderr = b"Traceback (most recent call last):\nRuntimeError: " + secret

        category = fixture.classify_migration_diagnostic_stderr(stderr)

        self.assertEqual(category, "python-runtime")
        self.assertNotIn(secret.decode("ascii"), category)
        self.assertEqual(fixture.classify_migration_diagnostic_stderr(b""), "empty")

    def test_unrecognized_revisions_are_reduced_without_reflecting_their_value(self) -> None:
        diagnostic_data = self.valid_diagnostic()
        diagnostic_data["discovered_revisions"] = ["other"]
        diagnostic = fixture.parse_migration_diagnostic(json.dumps(diagnostic_data))

        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        rendered = fixture.format_migration_diagnostic(diagnostic)
        self.assertIn("revisions=other", rendered)
        self.assertNotIn("unexpected-revision", rendered)
        self.assertFalse(fixture.migration_diagnostic_is_complete(diagnostic))

    def test_migrate_keeps_the_committed_upgrade_and_current_commands(self) -> None:
        diagnostic = json.dumps(self.valid_candidate_diagnostic(), separators=(",", ":"))
        compose = fixture.ComposeController(
            docker=object(),
            source_dir=Path("/tmp/fixture-source"),
            env_file=Path("/tmp/fixture-env"),
            project_name="impostr-review-0123456789abcdef0123",
            committed_migration_profile="imp004",
        )
        with (
            patch.object(compose, "invoke", side_effect=["", "20260925_0004 (head)\n"]) as invoke,
            patch.object(
                compose,
                "run_migration_diagnostic",
                return_value=(0, diagnostic, "empty"),
            ) as diagnose,
        ):
            result = compose.migrate()

        self.assertIn("alembic_current=expected", result)
        self.assertEqual(
            invoke.call_args_list[0].args[0],
            ["run", "--rm", "api", "alembic", "upgrade", "head"],
        )
        self.assertEqual(
            invoke.call_args_list[1].args[0],
            ["run", "--rm", "api", "alembic", "current"],
        )
        diagnose.assert_called_once_with(candidate=True)

    def test_committed_imp013_profile_accepts_only_the_0005_diagnostic(self) -> None:
        diagnostic = json.dumps(
            self.valid_imp013_candidate_diagnostic(),
            separators=(",", ":"),
        )
        compose = fixture.ComposeController(
            docker=object(),
            source_dir=Path("/tmp/committed-imp013-source"),
            env_file=Path("/tmp/committed-imp013-env"),
            project_name="impostr-review-0123456789abcdef0123",
            committed_migration_profile="imp013",
        )
        with (
            patch.object(
                compose,
                "invoke",
                side_effect=["", "20260929_0005 (head)\n"],
            ) as invoke,
            patch.object(
                compose,
                "run_migration_diagnostic",
                return_value=(0, diagnostic, "empty"),
            ) as diagnose,
        ):
            evidence = compose.migrate()

        self.assertIn("alembic_current=20260929_0005", evidence)
        self.assertIn("0005:present", evidence)
        self.assertIn("project_document_pair_approvals=yes", evidence)
        self.assertEqual(
            invoke.call_args_list[0].args[0],
            ["run", "--rm", "api", "alembic", "upgrade", "head"],
        )
        self.assertEqual(
            invoke.call_args_list[1].args[0],
            ["run", "--rm", "api", "alembic", "current"],
        )
        diagnose.assert_called_once_with(imp013_candidate=True)

    def test_committed_migration_without_a_selected_profile_fails_before_upgrade(self) -> None:
        compose = fixture.ComposeController(
            docker=object(),
            source_dir=Path("/tmp/unprofiled-committed-source"),
            env_file=Path("/tmp/unprofiled-committed-env"),
            project_name="impostr-review-0123456789abcdef0123",
        )
        with patch.object(compose, "invoke") as invoke:
            with self.assertRaisesRegex(fixture.FixtureError, "profile was not verified"):
                compose.migrate()
        invoke.assert_not_called()

    def test_imp013_migrate_requires_0005_and_the_approval_schema(self) -> None:
        diagnostic = json.dumps(
            self.valid_imp013_candidate_diagnostic(),
            separators=(",", ":"),
        )
        compose = fixture.ComposeController(
            docker=object(),
            source_dir=Path("/tmp/imp013-candidate-source"),
            env_file=Path("/tmp/imp013-candidate-env"),
            project_name="impostr-review-0123456789abcdef0123",
            candidate=True,
            approval_candidate=True,
        )
        with (
            patch.object(
                compose,
                "invoke",
                side_effect=["", "20260929_0005 (head)\n"],
            ) as invoke,
            patch.object(
                compose,
                "run_migration_diagnostic",
                return_value=(0, diagnostic, "empty"),
            ) as diagnose,
        ):
            evidence = compose.migrate()

        self.assertIn("alembic_current=20260929_0005", evidence)
        self.assertIn("0005:present", evidence)
        self.assertIn("project_document_pair_approvals=yes", evidence)
        self.assertEqual(
            invoke.call_args_list[0].args[0],
            ["run", "--rm", "api", "alembic", "upgrade", "head"],
        )
        self.assertEqual(
            invoke.call_args_list[1].args[0],
            ["run", "--rm", "api", "alembic", "current"],
        )
        diagnose.assert_called_once_with(imp013_candidate=True)

    def test_imp007_migrate_reuses_the_pinned_0005_schema_not_the_imp004_profile(self) -> None:
        diagnostic = json.dumps(
            self.valid_imp013_candidate_diagnostic(),
            separators=(",", ":"),
        )
        compose = fixture.ComposeController(
            docker=object(),
            source_dir=Path("/tmp/imp007-candidate-source"),
            env_file=Path("/tmp/imp007-candidate-env"),
            project_name="impostr-review-0123456789abcdef0123",
            candidate=True,
            imp007_candidate=True,
        )
        with (
            patch.object(
                compose,
                "invoke",
                side_effect=["", "20260929_0005 (head)\n"],
            ) as invoke,
            patch.object(
                compose,
                "run_migration_diagnostic",
                return_value=(0, diagnostic, "empty"),
            ) as diagnose,
        ):
            evidence = compose.migrate()

        self.assertIn("alembic_current=20260929_0005", evidence)
        self.assertIn("0005:present", evidence)
        self.assertIn("project_document_pair_approvals=yes", evidence)
        self.assertEqual(
            invoke.call_args_list[0].args[0],
            ["run", "--rm", "api", "alembic", "upgrade", "head"],
        )
        self.assertEqual(
            invoke.call_args_list[1].args[0],
            ["run", "--rm", "api", "alembic", "current"],
        )
        diagnose.assert_called_once_with(imp013_candidate=True)

    def test_candidate_migrate_requires_single_head_and_candidate_diagnostics(self) -> None:
        diagnostic = json.dumps(self.valid_candidate_diagnostic(), separators=(",", ":"))
        compose = fixture.ComposeController(
            docker=object(),
            source_dir=Path("/tmp/candidate-source"),
            env_file=Path("/tmp/candidate-env"),
            project_name="impostr-review-0123456789abcdef0123",
            candidate=True,
        )
        with (
            patch.object(
                compose,
                "invoke",
                side_effect=["", "20260925_0004 (head)\n"],
            ) as invoke,
            patch.object(
                compose,
                "run_migration_diagnostic",
                return_value=(0, diagnostic, "empty"),
            ) as diagnose,
        ):
            evidence = compose.migrate()

        self.assertIn("alembic_current=20260925_0004", evidence)
        self.assertIn("revisions=20260925_0001,20260925_0002,20260925_0003,20260925_0004", evidence)
        self.assertIn("heads=20260925_0004", evidence)
        self.assertIn("candidate_schema=projects_name_key:yes", evidence)
        self.assertEqual(
            invoke.call_args_list[0].args[0],
            ["run", "--rm", "api", "alembic", "upgrade", "head"],
        )
        self.assertEqual(
            invoke.call_args_list[1].args[0],
            ["run", "--rm", "api", "alembic", "current"],
        )
        diagnose.assert_called_once_with(candidate=True)

    def test_empty_revision_and_missing_users_are_reported_in_safe_summary(self) -> None:
        diagnostic_data = self.valid_candidate_diagnostic()
        diagnostic_data["discovered_revisions"] = []
        diagnostic_data["heads"] = []
        diagnostic_data["alembic_version_table"] = "no"
        diagnostic_data["current"] = "table-absent"
        diagnostic_data["users"] = "no"
        diagnostic_data["image_files"] = {
            "alembic_ini": "present",
            "env_py": "present",
            "revision_0001": "present",
            "revision_0002": "present",
            "revision_0003": "present",
            "revision_0004": "present",
        }
        diagnostic = json.dumps(diagnostic_data)
        compose = fixture.ComposeController(
            docker=object(),
            source_dir=Path("/tmp/fixture-source"),
            env_file=Path("/tmp/fixture-env"),
            project_name="impostr-review-0123456789abcdef0123",
            committed_migration_profile="imp004",
        )
        with (
            patch.object(compose, "invoke", side_effect=["", ""]),
            patch.object(
                compose,
                "run_migration_diagnostic",
                return_value=(0, diagnostic, "empty"),
            ),
        ):
            with self.assertRaises(fixture.FixtureError) as caught:
                compose.migrate()

        message = str(caught.exception)
        self.assertIn("discovery_status=ok", message)
        self.assertIn("database_probe_status=ok", message)
        self.assertIn("image_files_status=ok", message)
        self.assertIn("alembic_current=empty", message)
        self.assertIn("heads=none", message)
        self.assertIn("alembic_version_table=no", message)
        self.assertIn("catalog_current=table-absent users=no", message)

class GitArchiveTests(unittest.TestCase):
    def test_snapshot_template_selection_requires_coherent_inventory(self) -> None:
        self.assertEqual(
            fixture.select_snapshot_templates(fixture.NESTED_TEMPLATE_PATHS),
            fixture.NESTED_TEMPLATE_PATHS,
        )
        self.assertEqual(
            fixture.select_snapshot_templates(
                (*fixture.LEGACY_TEMPLATE_PATHS, *fixture.NESTED_TEMPLATE_PATHS)
            ),
            fixture.LEGACY_TEMPLATE_PATHS,
        )
        for paths in (
            (),
            fixture.NESTED_TEMPLATE_PATHS[:2],
            (*fixture.LEGACY_TEMPLATE_PATHS[:1], *fixture.NESTED_TEMPLATE_PATHS),
        ):
            with self.subTest(paths=paths), self.assertRaises(fixture.FixtureError):
                fixture.select_snapshot_templates(paths)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout"
        self.root.mkdir()
        self.private_home = Path(self.temporary.name) / "private-home"
        self.private_home.mkdir(mode=0o700)

    def git(self, *arguments: str) -> str:
        environment = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(self.private_home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def initialize_committed_app(self) -> None:
        files = (
            ("compose.yaml", "committed compose definition\n"),
            ("api/app/bootstrap_admin.py", "committed bootstrap\n"),
            ("api/app/admin.py", "committed admin API\n"),
            ("api/app/auth.py", "committed auth API\n"),
            ("web/src/App.tsx", "committed real app shell\n"),
            ("db/Dockerfile", "committed database image\n"),
            ("PROJECT.md.example", "committed project template\n"),
            ("AGENTS.md.example", "committed instructions template\n"),
            ("BACKLOG.md.example", "committed backlog template\n"),
            (".opencode/private-provider.json", secrets.token_hex(32)),
        )
        for relative, content in files:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.git("init", "-q")
        self.git(
            "add",
            "compose.yaml",
            "db",
            "api",
            "web",
            "PROJECT.md.example",
            "AGENTS.md.example",
            "BACKLOG.md.example",
            ".opencode",
        )
        self.git(
            "-c",
            "user.name=Fixture Test",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "committed IMP-003 snapshot",
        )

    def test_snapshot_uses_committed_head_and_ignores_dirty_imp004_and_env(self) -> None:
        self.initialize_committed_app()
        committed = self.git("rev-parse", "HEAD")
        (self.root / "compose.yaml").write_text("dirty IMP-004 compose\n", encoding="utf-8")
        dirty_path = self.root / "api" / "app" / "dirty_imp004.py"
        dirty_path.write_text("uncommitted project code\n", encoding="utf-8")
        host_password = secrets.token_hex(32)
        (self.root / ".env").write_text(
            f"POSTGRES_PASSWORD={host_password}\n",
            encoding="utf-8",
        )
        snapshot = Path(self.temporary.name) / "snapshot"

        archived_commit = fixture.archive_head_snapshot(
            self.root,
            snapshot,
            private_home=self.private_home,
        )

        self.assertEqual(archived_commit, committed)
        self.assertEqual(
            (snapshot / "compose.yaml").read_text(encoding="utf-8"),
            "committed compose definition\n",
        )
        self.assertFalse((snapshot / "api" / "app" / "dirty_imp004.py").exists())
        self.assertFalse((snapshot / ".env").exists())
        self.assertFalse((snapshot / ".opencode").exists())
        self.assertFalse((snapshot / ".git").exists())

    def test_tree_check_and_archive_stay_pinned_if_head_moves_mid_snapshot(self) -> None:
        self.initialize_committed_app()
        original_commit = self.git("rev-parse", "HEAD")
        (self.root / "compose.yaml").write_text("second committed version\n", encoding="utf-8")
        self.git("add", "compose.yaml")
        self.git(
            "-c",
            "user.name=Fixture Test",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "second app snapshot",
        )
        later_commit = self.git("rev-parse", "HEAD")
        self.git("update-ref", "HEAD", original_commit)
        snapshot = Path(self.temporary.name) / "race-pinned-snapshot"
        original_run = subprocess.run
        commands: list[list[str]] = []
        moved_head = False

        def move_head_before_tree(command: list[str], **options):
            nonlocal moved_head
            if command[:2] == ["git", "ls-tree"] and not moved_head:
                moved = original_run(
                    ["git", "update-ref", "HEAD", later_commit],
                    cwd=self.root,
                    env=options["env"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=20,
                )
                self.assertEqual(moved.returncode, 0, moved.stderr)
                moved_head = True
            commands.append(list(command))
            return original_run(command, **options)

        with patch("local_browser_fixture.subprocess.run", side_effect=move_head_before_tree):
            archived_commit = fixture.archive_head_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
            )

        self.assertTrue(moved_head)
        self.assertEqual(archived_commit, original_commit)
        self.assertEqual(
            (snapshot / "compose.yaml").read_text(encoding="utf-8"),
            "committed compose definition\n",
        )
        tree_command = next(command for command in commands if command[1] == "ls-tree")
        archive_command = next(command for command in commands if command[1] == "archive")
        self.assertEqual(tree_command[-1], original_commit)
        self.assertEqual(archive_command[3], original_commit)

    def test_real_snapshot_preserves_migration_access_under_private_umask(self) -> None:
        repository_root = Path(fixture.__file__).resolve().parent.parent
        snapshot = Path(self.temporary.name) / "real-committed-snapshot"
        previous_umask = os.umask(0o077)
        try:
            fixture.archive_head_snapshot(
                repository_root,
                snapshot,
                private_home=self.private_home,
            )
        finally:
            os.umask(previous_umask)

        self.assertEqual(
            {path.name for path in (snapshot / "api" / "migrations" / "versions").glob("*.py")},
            {
                "20260925_0001_initial_baseline.py",
                "20260925_0002_identity_and_project_metadata.py",
                "20260925_0003_project_document_revisions.py",
                "20260925_0004_bounded_project_name_keys.py",
                "20260929_0005_document_pair_approvals.py",
                "20260930_0006_project_approval_manifests.py",
            },
        )
        self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o700)
        for relative in fixture.NESTED_TEMPLATE_PATHS:
            self.assertEqual(
                (snapshot / relative).read_bytes(),
                (repository_root / relative).read_bytes(),
            )
        self.assertFalse((snapshot / "overnight-agent" / "opencode.json").exists())
        self.assertFalse((snapshot / "PROJECT.md.example").exists())
        self.assertTrue((snapshot / ".dockerignore").is_file())
        for directory in (
            snapshot / "api",
            snapshot / "api" / "migrations",
            snapshot / "api" / "migrations" / "versions",
        ):
            with self.subTest(directory=directory.relative_to(snapshot)):
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755)

    def test_tracked_dotenv_file_blocks_snapshot_before_build_context_creation(self) -> None:
        self.initialize_committed_app()
        dotenv_value = secrets.token_hex(32)
        (self.root / "api" / ".env.production").write_text(
            f"{dotenv_value}\n",
            encoding="utf-8",
        )
        self.git("add", "api/.env.production")
        self.git(
            "-c",
            "user.name=Fixture Test",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "unsafe dotenv file",
        )
        snapshot = Path(self.temporary.name) / "blocked-snapshot"

        with self.assertRaises(fixture.FixtureError) as caught:
            fixture.archive_head_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
            )

        self.assertFalse(
            dotenv_value in str(caught.exception),
            "dotenv contents must not appear in failure details",
        )
        self.assertFalse(snapshot.exists())


class CandidateSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout"
        self.root.mkdir()
        self.private_home = Path(self.temporary.name) / "private-home"
        self.private_home.mkdir(mode=0o700)

    def git(self, *arguments: str) -> str:
        environment = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(self.private_home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def initialize_checkout(self, *, include_dockerignore: bool = True) -> str:
        files = (
            (
                ".dockerignore",
                "\n".join(fixture.CANDIDATE_DOCKERIGNORE_RULES) + "\n",
            ),
            ("compose.yaml", "services:\n  api: {}\n"),
            ("api/app/bootstrap_admin.py", "committed bootstrap\n"),
            ("api/app/admin.py", "committed admin API\n"),
            ("api/app/auth.py", "committed auth API\n"),
            ("api/app/main.py", "committed main\n"),
            ("api/app/models.py", "committed database models\n"),
            (
                "api/migrations/versions/20260925_0001_initial_baseline.py",
                "committed migration 0001\n",
            ),
            (
                "api/migrations/versions/20260925_0002_identity_and_project_metadata.py",
                "committed migration 0002\n",
            ),
            (
                "api/migrations/versions/20260925_0003_project_document_revisions.py",
                "committed migration 0003\n",
            ),
            (
                "api/migrations/versions/20260925_0004_bounded_project_name_keys.py",
                "committed migration 0004\n",
            ),
            ("api/tests/test_migrations.py", "committed migration tests\n"),
            ("api/tests/test_postgres_integration.py", "committed integration tests\n"),
            ("web/src/App.tsx", "committed real app shell\n"),
            ("web/src/ProjectWorkspace.tsx", "committed workspace UI\n"),
            ("web/src/ProjectWorkspace.test.tsx", "committed workspace tests\n"),
            ("scripts/local_browser_fixture.py", "committed host fixture\n"),
            ("scripts/test_local_browser_fixture.py", "committed host fixture tests\n"),
            ("db/Dockerfile", "committed database image\n"),
            ("PROJECT.md.example", "committed project template\n"),
            ("AGENTS.md.example", "committed instructions template\n"),
            ("BACKLOG.md.example", "committed backlog template\n"),
            (".opencode/private-provider.json", "synthetic-private-fixture-marker"),
        )
        if not include_dockerignore:
            files = tuple((path, content) for path, content in files if path != ".dockerignore")
        for relative, content in files:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            path.chmod(0o644)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git(
            "-c",
            "user.name=Fixture Test",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "candidate base",
        )
        return self.git("rev-parse", "HEAD")

    def policy(self, base_commit: str, *inputs: tuple[str, str]) -> fixture.CandidatePreviewPolicy:
        return fixture.CandidatePreviewPolicy(
            base_commit=base_commit,
            reviewed_inputs=tuple(inputs),
            nonruntime_test_changes=(),
        )

    def imp013_policy(self, base_commit: str) -> fixture.CandidatePreviewPolicy:
        return replace(
            fixture.IMP013_CANDIDATE_PREVIEW_POLICY,
            base_commit=base_commit,
        )

    def write_imp013_candidate(self) -> tuple[str, fixture.CandidatePreviewPolicy]:
        base = self.initialize_checkout()
        policy = self.imp013_policy(base)
        for path, status in (
            *policy.reviewed_inputs,
            *policy.nonruntime_test_changes,
            *policy.harness_changes,
        ):
            candidate_file = self.root / path
            candidate_file.parent.mkdir(parents=True, exist_ok=True)
            if status == "added":
                self.assertFalse(
                    candidate_file.exists(),
                    f"{path} must be absent from the pinned base",
                )
            candidate_file.write_text(f"candidate source for {path}\n", encoding="utf-8")
            candidate_file.chmod(0o644)
        return base, policy

    def initialize_imp007_checkout(self) -> str:
        self.initialize_checkout()
        baseline_files = (
            ("api/Dockerfile", "committed API build definition\n"),
            ("api/app/project_documents.py", "committed project document API\n"),
            ("scripts/backlog.py", "committed root compatibility oracle\n"),
        )
        for relative, content in baseline_files:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            path.chmod(0o644)
        self.git("add", "api/Dockerfile", "api/app/project_documents.py", "scripts/backlog.py")
        self.git(
            "-c",
            "user.name=Fixture Test",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "IMP-007 candidate fixture base",
        )
        return self.git("rev-parse", "HEAD")

    def imp007_policy(self, base_commit: str) -> fixture.CandidatePreviewPolicy:
        return replace(
            fixture.IMP007_CANDIDATE_PREVIEW_POLICY,
            base_commit=base_commit,
        )

    def write_imp007_candidate(self) -> tuple[str, fixture.CandidatePreviewPolicy]:
        base = self.initialize_imp007_checkout()
        policy = self.imp007_policy(base)
        for relative, status in (
            *policy.reviewed_inputs,
            *policy.nonruntime_test_changes,
            *policy.harness_changes,
        ):
            candidate_file = self.root / relative
            candidate_file.parent.mkdir(parents=True, exist_ok=True)
            if status == "added":
                self.assertFalse(candidate_file.exists(), f"{relative} must be absent from base")
            else:
                self.assertTrue(candidate_file.is_file(), f"{relative} must exist in base")
            if relative == ".dockerignore":
                content = "\n".join(fixture.IMP007_CANDIDATE_DOCKERIGNORE_RULES) + "\n"
            else:
                content = f"candidate source for {relative}\n"
            candidate_file.write_text(content, encoding="utf-8")
            candidate_file.chmod(0o644)
        return base, policy

    def test_fixed_allowlist_is_runtime_only_and_rejects_planning_paths(self) -> None:
        reviewed = {path for path, _status in fixture.CANDIDATE_REVIEWED_RUNTIME_INPUTS}
        self.assertEqual(
            reviewed,
            {
                ".dockerignore",
                "api/Dockerfile",
                "api/app/document_contract.py",
                "api/app/main.py",
                "api/app/models.py",
                "api/app/project_documents.py",
                "api/app/project_names.py",
                "api/app/project_templates.py",
                "api/app/projects.py",
                "api/app/workspaces.py",
                "api/migrations/versions/20260925_0003_project_document_revisions.py",
                "api/migrations/versions/20260925_0004_bounded_project_name_keys.py",
                "compose.yaml",
                "web/nginx/default.conf",
                "web/src/App.tsx",
                "web/src/ProjectWorkspace.tsx",
                "web/src/api.ts",
            },
        )
        for forbidden in (
            "PROJECT.md",
            "AGENTS.md",
            "BACKLOG.md",
            "../PROJECT.md",
            "api/app/../../PROJECT.md",
            "/tmp/secret.py",
            "api/.env.local",
        ):
            with self.subTest(forbidden=forbidden), self.assertRaises(fixture.FixtureError):
                fixture.validate_candidate_reviewed_paths(
                    (forbidden,),
                    policy=self.policy(
                        fixture.CANDIDATE_BASE_COMMIT,
                        (forbidden, "modified"),
                    ),
                )
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_candidate_reviewed_paths(
                ("api/app/main.py",),
                policy=self.policy(
                    fixture.CANDIDATE_BASE_COMMIT,
                    ("api/app/main.py", "modified"),
                    ("api/app/main.py", "modified"),
                ),
            )

    def test_imp013_policy_is_pinned_to_the_committed_head_and_exact_app_files(self) -> None:
        policy = fixture.IMP013_CANDIDATE_PREVIEW_POLICY
        self.assertEqual(policy.base_commit, "60e9480de5ac7a377f4eff79f28814f0c488aeb4")
        self.assertEqual(
            set(policy.reviewed_inputs),
            {
                ("api/app/document_pair_approvals.py", "added"),
                ("api/app/main.py", "modified"),
                ("api/app/models.py", "modified"),
                (
                    "api/migrations/versions/20260929_0005_document_pair_approvals.py",
                    "added",
                ),
                ("web/src/ProjectWorkspace.tsx", "modified"),
            },
        )
        self.assertEqual(
            set(policy.nonruntime_test_changes),
            {
                ("api/tests/test_document_pair_approval_postgres.py", "added"),
                ("api/tests/test_document_pair_approvals.py", "added"),
                ("api/tests/test_migrations.py", "modified"),
                ("api/tests/test_postgres_integration.py", "modified"),
                ("web/src/ProjectWorkspace.test.tsx", "modified"),
            },
        )
        self.assertTrue(policy.fingerprint_test_changes)
        self.assertTrue(policy.fingerprint_harness_changes)
        self.assertTrue(policy.strict_scope)
        self.assertEqual(policy.committed_support_paths, (".dockerignore",))
        self.assertEqual(policy.committed_support_paths, (".dockerignore",))
        self.assertEqual(
            policy.status_paths,
            (*fixture.CANDIDATE_STATUS_PATHS, "scripts"),
        )
        self.assertNotIn("PROJECT.md", policy.status_paths or ())
        self.assertEqual(policy.allowed_input_modes, frozenset({0o644, 0o664}))
        self.assertEqual(
            set(policy.harness_changes),
            {
                ("scripts/local_browser_fixture.py", "modified"),
                ("scripts/test_local_browser_fixture.py", "modified"),
            },
        )
        self.assertEqual(
            policy.allowed_test_literal_digests,
            fixture.IMP013_CANDIDATE_TEST_LITERAL_DIGESTS,
        )

    def test_imp007_policy_is_a_separate_exact_profile_over_the_approved_base(self) -> None:
        policy = fixture.IMP007_CANDIDATE_PREVIEW_POLICY
        self.assertEqual(policy.base_commit, "31d0f8f97bcf857b28d4e3f0c7bf51db8f7bf759")
        self.assertEqual(
            set(policy.reviewed_inputs),
            {
                (".dockerignore", "modified"),
                ("api/Dockerfile", "modified"),
                ("api/app/main.py", "modified"),
                ("api/app/project_documents.py", "modified"),
                ("api/app/backlog_markdown.py", "added"),
                ("api/app/backlog_tasks.py", "added"),
                ("web/src/ProjectWorkspace.tsx", "modified"),
            },
        )
        self.assertEqual(
            set(policy.nonruntime_test_changes),
            {
                ("api/tests/test_backlog_markdown.py", "added"),
                ("api/tests/test_backlog_tasks.py", "added"),
                ("api/tests/test_backlog_tasks_postgres.py", "added"),
                ("web/src/ProjectWorkspace.test.tsx", "modified"),
            },
        )
        self.assertEqual(
            set(policy.harness_changes),
            {
                ("scripts/local_browser_fixture.py", "modified"),
                ("scripts/test_local_browser_fixture.py", "modified"),
            },
        )
        self.assertTrue(policy.strict_scope)
        self.assertTrue(policy.fingerprint_test_changes)
        self.assertTrue(policy.fingerprint_harness_changes)
        self.assertEqual(policy.max_file_bytes, 512 * 1024)
        self.assertEqual(policy.max_total_bytes, 2 * 1024 * 1024)
        self.assertEqual(policy.allowed_input_modes, frozenset({0o644, 0o664}))
        self.assertEqual(policy.status_paths, (*fixture.CANDIDATE_STATUS_PATHS, "scripts"))
        self.assertEqual(policy.committed_support_paths, (".dockerignore", "scripts/backlog.py"))
        self.assertEqual(
            policy.allowed_test_literal_digests,
            fixture.IMP007_CANDIDATE_TEST_LITERAL_DIGESTS,
        )
        self.assertNotIn("scripts/backlog.py", dict(policy.reviewed_inputs))
        self.assertNotIn("PROJECT.md", policy.status_paths or ())

        for unapproved in ("scripts/backlog.py", "PROJECT.md"):
            with self.subTest(unapproved=unapproved), self.assertRaises(fixture.FixtureError):
                fixture.validate_candidate_reviewed_paths(
                    (unapproved,),
                    policy=replace(
                        policy,
                        reviewed_inputs=((unapproved, "modified"),),
                    ),
                )

    def test_candidate_fingerprint_binds_commit_path_status_mode_and_content_digest(self) -> None:
        content = b"candidate bytes that do not appear in a fingerprint"
        record = fixture.CandidateInputRecord(
            path="api/app/main.py",
            status="modified",
            size=len(content),
            mode=0o644,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        base = "a" * 40
        fingerprint = fixture._candidate_records_fingerprint(base, (record,))
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(
            fingerprint,
            fixture._candidate_records_fingerprint(base, (record,)),
        )
        self.assertNotEqual(
            fingerprint,
            fixture._candidate_records_fingerprint("b" * 40, (record,)),
        )
        self.assertNotEqual(
            fingerprint,
            fixture._candidate_records_fingerprint(
                base,
                (
                    fixture.CandidateInputRecord(
                        path=record.path,
                        status="added",
                        size=record.size,
                        mode=record.mode,
                        sha256=record.sha256,
                    ),
                ),
            ),
        )
        self.assertNotIn(content.decode(), fingerprint)

    def test_candidate_overlay_is_pinned_and_excludes_unrelated_checkout_inputs(self) -> None:
        base = self.initialize_checkout()
        candidate_file = self.root / "api/app/main.py"
        candidate_file.write_text("candidate main source\n", encoding="utf-8")
        candidate_file.chmod(0o644)
        secret = "synthetic-out-of-context-secret-value"
        (self.root / ".env").write_text(f"DB_PASSWORD={secret}\n", encoding="ascii")
        (self.root / "PROJECT.md").write_text("unrelated live planning\n", encoding="utf-8")
        (self.root / "BACKLOG.md").write_text("unrelated live backlog\n", encoding="utf-8")
        snapshot = Path(self.temporary.name) / "candidate-snapshot"
        policy = self.policy(base, ("api/app/main.py", "modified"))

        candidate = fixture.archive_candidate_snapshot(
            self.root,
            snapshot,
            private_home=self.private_home,
            policy=policy,
        )

        self.assertEqual(candidate.base_commit, base)
        self.assertRegex(candidate.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(
            (snapshot / "api/app/main.py").read_text(encoding="utf-8"),
            "candidate main source\n",
        )
        self.assertFalse((snapshot / ".env").exists())
        self.assertFalse((snapshot / "PROJECT.md").exists())
        self.assertFalse((snapshot / "BACKLOG.md").exists())
        self.assertFalse((snapshot / ".opencode").exists())
        self.assertFalse((snapshot / ".git").exists())
        self.assertNotIn(secret, candidate.fingerprint)

        fixture.validate_candidate_snapshot_tree(snapshot, candidate)
        candidate_file.write_text("changed after candidate capture\n", encoding="utf-8")
        with self.assertRaisesRegex(fixture.FixtureError, "changed during preview"):
            fixture.validate_candidate_worktree_snapshot(
                self.root,
                candidate,
                private_home=self.private_home,
                policy=policy,
            )

    def test_candidate_snapshot_refuses_missing_staged_unexpected_symlink_and_oversized_inputs(
        self,
    ) -> None:
        base = self.initialize_checkout()
        candidate_file = self.root / "api/app/main.py"
        policy = self.policy(base, ("api/app/main.py", "modified"))
        snapshot = Path(self.temporary.name) / "blocked-snapshot"

        with self.assertRaisesRegex(fixture.FixtureError, "missing"):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.assertFalse(snapshot.exists())

        candidate_file.write_text("working tree candidate\n", encoding="utf-8")
        candidate_file.chmod(0o644)
        self.git("add", "api/app/main.py")
        with self.assertRaises(fixture.FixtureError):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.git("reset", "-q", "HEAD", "--", "api/app/main.py")

        (self.root / "api/app/unreviewed.py").write_text("not allowlisted", encoding="utf-8")
        with self.assertRaisesRegex(fixture.FixtureError, "unexpected runtime input"):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        (self.root / "api/app/unreviewed.py").unlink()

        outside = Path(self.temporary.name) / "outside.py"
        outside.write_text("outside file", encoding="utf-8")
        candidate_file.unlink()
        candidate_file.symlink_to(outside)
        with self.assertRaises(fixture.FixtureError):
            fixture._read_candidate_file(self.root, "api/app/main.py", maximum_bytes=4096)
        candidate_file.unlink()
        candidate_file.write_text("x" * (fixture.MAX_CANDIDATE_FILE_BYTES + 1), encoding="ascii")
        candidate_file.chmod(0o644)
        with self.assertRaisesRegex(fixture.FixtureError, "size limit"):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )

    def test_candidate_snapshot_enforces_a_total_input_size_bound(self) -> None:
        base = self.initialize_checkout()
        main = self.root / "api/app/main.py"
        auth = self.root / "api/app/auth.py"
        for path, content in ((main, "x" * 8), (auth, "y" * 8)):
            path.write_text(content, encoding="ascii")
            path.chmod(0o644)
        policy = fixture.CandidatePreviewPolicy(
            base_commit=base,
            reviewed_inputs=(
                ("api/app/main.py", "modified"),
                ("api/app/auth.py", "modified"),
            ),
            nonruntime_test_changes=(),
            max_file_bytes=16,
            max_total_bytes=12,
        )

        with self.assertRaisesRegex(fixture.FixtureError, "total size limit"):
            fixture.archive_candidate_snapshot(
                self.root,
                Path(self.temporary.name) / "oversized-total",
                private_home=self.private_home,
                policy=policy,
            )

    def test_candidate_snapshot_rejects_literal_secrets_and_stale_fingerprints(self) -> None:
        base = self.initialize_checkout()
        candidate_file = self.root / "api/app/main.py"
        candidate_file.write_text(
            'DB_PASSWORD = "synthetic-literal-candidate-secret-value"\n',
            encoding="utf-8",
        )
        candidate_file.chmod(0o644)
        policy = self.policy(base, ("api/app/main.py", "modified"))
        snapshot = Path(self.temporary.name) / "blocked-secret-snapshot"
        secret = "synthetic-literal-candidate-secret-value"
        with self.assertRaises(fixture.FixtureError) as caught:
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.assertNotIn(secret, str(caught.exception))
        self.assertFalse(snapshot.exists())

        candidate_file.write_text("safe changed code\n", encoding="utf-8")
        candidate_file.chmod(0o644)
        with self.assertRaisesRegex(fixture.FixtureError, "fingerprint changed"):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                expected_fingerprint="0" * 64,
                policy=policy,
            )
        self.assertFalse(snapshot.exists())

    def test_candidate_snapshot_rejects_worktree_drift_during_archive(self) -> None:
        base = self.initialize_checkout()
        candidate_file = self.root / "api/app/main.py"
        candidate_file.write_text("captured candidate\n", encoding="utf-8")
        candidate_file.chmod(0o644)
        policy = self.policy(base, ("api/app/main.py", "modified"))
        snapshot = Path(self.temporary.name) / "raced-snapshot"
        archive_head = fixture.archive_head_snapshot

        def archive_then_change(root: Path, destination: Path, **kwargs: object) -> str:
            result = archive_head(root, destination, **kwargs)
            candidate_file.write_text("changed while archiving\n", encoding="utf-8")
            candidate_file.chmod(0o644)
            return result

        with patch("local_browser_fixture.archive_head_snapshot", side_effect=archive_then_change):
            with self.assertRaisesRegex(fixture.FixtureError, "changed during preview"):
                fixture.archive_candidate_snapshot(
                    self.root,
                    snapshot,
                    private_home=self.private_home,
                    policy=policy,
                )

    def test_candidate_root_dockerignore_is_a_closed_reviewed_rule_set(self) -> None:
        ignore = self.root / ".dockerignore"
        ignore.write_text("\n".join(fixture.CANDIDATE_DOCKERIGNORE_RULES) + "\n", encoding="utf-8")
        ignore.chmod(0o644)
        fixture.validate_candidate_dockerignore(self.root)
        ignore.write_text(
            "\n".join((*fixture.CANDIDATE_DOCKERIGNORE_RULES, "!PROJECT.md")) + "\n",
            encoding="utf-8",
        )
        ignore.chmod(0o644)
        with self.assertRaisesRegex(fixture.FixtureError, "not safely allowlisted"):
            fixture.validate_candidate_dockerignore(self.root)

    def test_imp013_snapshot_pins_test_content_but_does_not_copy_tests_into_runtime(self) -> None:
        base, policy = self.write_imp013_candidate()
        synthetic_test_password = "synthetic-test-fixture-password"
        synthetic_test_assignment = f'password = "{synthetic_test_password}"\n'
        changed_test = self.root / "api/tests/test_migrations.py"
        changed_test.write_text(synthetic_test_assignment, encoding="utf-8")
        changed_test.chmod(0o644)
        policy = replace(
            policy,
            allowed_test_literal_digests=(
                *policy.allowed_test_literal_digests,
                (
                    "api/tests/test_migrations.py",
                    "password",
                    hashlib.sha256(synthetic_test_password.encode("utf-8")).hexdigest(),
                ),
            ),
        )
        snapshot = Path(self.temporary.name) / "imp013-candidate-snapshot"

        candidate = fixture.archive_candidate_snapshot(
            self.root,
            snapshot,
            private_home=self.private_home,
            policy=policy,
        )

        expected_paths = (
            {path for path, _status in policy.reviewed_inputs}
            | {path for path, _status in policy.nonruntime_test_changes}
            | {path for path, _status in policy.harness_changes}
        )
        self.assertEqual(candidate.base_commit, base)
        self.assertEqual({record.path for record in candidate.records}, expected_paths)
        self.assertEqual(
            set(candidate.runtime_paths),
            {path for path, _ in policy.reviewed_inputs},
        )
        self.assertRegex(candidate.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(
            (snapshot / "api/app/document_pair_approvals.py").read_text(encoding="utf-8"),
            "candidate source for api/app/document_pair_approvals.py\n",
        )
        self.assertEqual(
            (snapshot / "api/tests/test_migrations.py").read_text(encoding="utf-8"),
            "committed migration tests\n",
            "candidate tests are fingerprinted but are not overlaid into the app snapshot",
        )
        dockerignore = snapshot / ".dockerignore"
        dockerignore_bytes = dockerignore.read_bytes()
        self.assertEqual(
            candidate.support_file_digests,
            ((".dockerignore", hashlib.sha256(dockerignore_bytes).hexdigest()),),
        )
        fixture.validate_candidate_dockerignore(snapshot)
        dockerignore.write_bytes(dockerignore_bytes + b"\n# changed after archiving\n")
        dockerignore.chmod(0o644)
        with self.assertRaisesRegex(fixture.FixtureError, "support file changed"):
            fixture.validate_candidate_snapshot_tree(snapshot, candidate)
        dockerignore.write_bytes(dockerignore_bytes)
        dockerignore.chmod(0o644)
        test_record = next(
            record
            for record in candidate.records
            if record.path == changed_test.relative_to(self.root).as_posix()
        )
        self.assertEqual(
            test_record.sha256,
            hashlib.sha256(synthetic_test_assignment.encode()).hexdigest(),
        )
        self.assertFalse(
            (snapshot / "api/tests/test_document_pair_approvals.py").exists(),
            "new test-only files must not enter the runtime snapshot",
        )
        self.assertFalse(
            (snapshot / "scripts/local_browser_fixture.py").exists(),
            "the fingerprinted host harness must not enter the app snapshot",
        )
        fixture.validate_candidate_snapshot_tree(snapshot, candidate)
        fixture.validate_candidate_worktree_snapshot(
            self.root,
            candidate,
            private_home=self.private_home,
            policy=policy,
        )

        changed_test.write_text("changed test code after preflight\n", encoding="utf-8")
        changed_test.chmod(0o644)
        with self.assertRaisesRegex(fixture.FixtureError, "changed during preview"):
            fixture.validate_candidate_worktree_snapshot(
                self.root,
                candidate,
                private_home=self.private_home,
                policy=policy,
            )
        pinned_destination = Path(self.temporary.name) / "imp013-stale-fingerprint"
        with self.assertRaisesRegex(fixture.FixtureError, "fingerprint changed"):
            fixture.archive_candidate_snapshot(
                self.root,
                pinned_destination,
                private_home=self.private_home,
                expected_fingerprint=candidate.fingerprint,
                policy=policy,
            )
        self.assertFalse(pinned_destination.exists())

    def test_imp013_archive_requires_the_committed_dockerignore_support_file(self) -> None:
        base = self.initialize_checkout(include_dockerignore=False)
        snapshot = Path(self.temporary.name) / "imp013-missing-dockerignore"

        with self.assertRaises(fixture.FixtureError):
            fixture.archive_head_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                expected_commit=base,
                additional_paths=(".dockerignore",),
            )

        self.assertFalse(snapshot.exists())

    def test_imp013_harness_drift_after_preflight_rejects_pinned_launch(self) -> None:
        _base, policy = self.write_imp013_candidate()
        snapshot = Path(self.temporary.name) / "imp013-harness-bound-snapshot"
        candidate = fixture.archive_candidate_snapshot(
            self.root,
            snapshot,
            private_home=self.private_home,
            policy=policy,
        )
        self.assertEqual(
            {record.path for record in candidate.records if record.path.startswith("scripts/")},
            {path for path, _status in policy.harness_changes},
        )
        harness_paths = {path for path, _status in policy.harness_changes}
        self.assertEqual(
            {record.path for record in candidate.records if record.path.startswith("scripts/")},
            harness_paths,
        )
        for index, harness_path in enumerate(sorted(harness_paths)):
            harness = self.root / harness_path
            harness_record = next(
                record for record in candidate.records if record.path == harness_path
            )
            original_harness_content = f"candidate source for {harness_path}\n".encode("utf-8")
            self.assertEqual(harness_record.status, "modified")
            self.assertEqual(harness_record.mode, 0o644)
            self.assertEqual(harness_record.size, len(original_harness_content))
            self.assertEqual(
                harness_record.sha256,
                hashlib.sha256(original_harness_content).hexdigest(),
            )
            self.assertFalse((snapshot / harness_path).exists())

            harness.write_text("changed host fixture after preflight\n", encoding="utf-8")
            harness.chmod(0o644)
            with self.assertRaisesRegex(fixture.FixtureError, "changed during preview"):
                fixture.validate_candidate_worktree_snapshot(
                    self.root,
                    candidate,
                    private_home=self.private_home,
                    policy=policy,
                )

            launch_snapshot = Path(self.temporary.name) / f"imp013-stale-harness-launch-{index}"
            with self.assertRaisesRegex(fixture.FixtureError, "fingerprint changed"):
                fixture.archive_candidate_snapshot(
                    self.root,
                    launch_snapshot,
                    private_home=self.private_home,
                    expected_fingerprint=candidate.fingerprint,
                    policy=policy,
                )
            self.assertFalse(launch_snapshot.exists())
            harness.write_bytes(original_harness_content)
            harness.chmod(0o644)

    def test_imp013_snapshot_ignores_unrelated_dirty_planning_and_logs(self) -> None:
        _base, policy = self.write_imp013_candidate()
        snapshot = Path(self.temporary.name) / "imp013-snapshot-with-dirty-planning"
        for name in ("PROJECT.md", "AGENTS.md", "BACKLOG.md", "DONE.md"):
            (self.root / name).write_text(
                f"unrelated dirty planning in {name}\n",
                encoding="utf-8",
            )
        (self.root / ".opencode" / "progress.md").write_text(
            "unrelated local runner log\n",
            encoding="utf-8",
        )
        (self.root / ".playwright-mcp").mkdir()
        (self.root / ".playwright-mcp" / "state.json").write_text(
            "unrelated local browser state\n",
            encoding="utf-8",
        )

        candidate = fixture.archive_candidate_snapshot(
            self.root,
            snapshot,
            private_home=self.private_home,
            policy=policy,
        )

        self.assertRegex(candidate.fingerprint, r"^[0-9a-f]{64}$")
        for name in ("PROJECT.md", "AGENTS.md", "BACKLOG.md", "DONE.md"):
            self.assertFalse((snapshot / name).exists())
        self.assertFalse((snapshot / ".opencode").exists())
        self.assertFalse((snapshot / ".playwright-mcp").exists())

    def test_imp013_snapshot_rejects_missing_unexpected_runtime_template_and_harness_paths(
        self,
    ) -> None:
        base, policy = self.write_imp013_candidate()
        snapshot = Path(self.temporary.name) / "imp013-blocked-snapshot"

        missing_test = self.root / "api/tests/test_document_pair_approvals.py"
        missing_test.unlink()
        with self.assertRaisesRegex(fixture.FixtureError, "test input is missing"):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.assertFalse(snapshot.exists())
        missing_test.write_text("candidate test restored\n", encoding="utf-8")
        missing_test.chmod(0o644)

        unexpected_inputs = (
            ("api/app/unreviewed_approval.py", "unreviewed candidate code\n"),
            ("PROJECT.md.example", "unexpected template change\n"),
            ("scripts/unreviewed_fixture.py", "unexpected harness change\n"),
        )
        for relative, content in unexpected_inputs:
            unexpected = self.root / relative
            unexpected.parent.mkdir(parents=True, exist_ok=True)
            original = unexpected.read_bytes() if unexpected.exists() else None
            unexpected.write_text(content, encoding="utf-8")
            unexpected.chmod(0o644)
            with self.subTest(path=relative), self.assertRaisesRegex(
                fixture.FixtureError,
                "unexpected scoped input",
            ):
                fixture.archive_candidate_snapshot(
                    self.root,
                    snapshot,
                    private_home=self.private_home,
                    policy=policy,
                )
            self.assertFalse(snapshot.exists())
            if original is None:
                unexpected.unlink()
            else:
                unexpected.write_bytes(original)
                unexpected.chmod(0o644)

        self.assertEqual(
            fixture._resolve_head_commit(self.root, private_home=self.private_home),
            base,
        )

    def test_imp013_snapshot_rejects_symlinks_literal_secrets_and_unreviewed_modes(self) -> None:
        _base, policy = self.write_imp013_candidate()
        snapshot = Path(self.temporary.name) / "imp013-unsafe-snapshot"
        runtime_file = self.root / "api/app/main.py"
        external = Path(self.temporary.name) / "outside.py"
        external.write_text("outside candidate bytes\n", encoding="utf-8")
        runtime_file.unlink()
        runtime_file.symlink_to(external)
        with self.assertRaises(fixture.FixtureError):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.assertFalse(snapshot.exists())

        runtime_file.unlink()
        runtime_file.write_text("candidate runtime source\n", encoding="utf-8")
        runtime_file.chmod(0o600)
        with self.assertRaises(fixture.FixtureError):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        runtime_file.chmod(0o644)

        secret = "synthetic-approval-candidate-secret"
        runtime_file.write_text(f'DB_PASSWORD = "{secret}"\n', encoding="utf-8")
        runtime_file.chmod(0o644)
        with self.assertRaises(fixture.FixtureError) as caught:
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.assertNotIn(secret, str(caught.exception))
        self.assertFalse(snapshot.exists())

    def test_imp013_snapshot_rejects_test_assignments_and_token_values(self) -> None:
        _base, policy = self.write_imp013_candidate()
        snapshot = Path(self.temporary.name) / "imp013-test-token-snapshot"
        test_file = self.root / "api/tests/test_document_pair_approvals.py"
        unapproved_password = "ordinary-unapproved-test-password"
        test_file.write_text(f'password = "{unapproved_password}"\n', encoding="utf-8")
        test_file.chmod(0o644)

        with self.assertRaises(fixture.FixtureError) as caught:
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )

        self.assertNotIn(unapproved_password, str(caught.exception))
        self.assertFalse(snapshot.exists())

        literal_secret = "synthetic-test-database-secret"
        test_file.write_text(f'DB_PASSWORD = "{literal_secret}"\n', encoding="utf-8")
        test_file.chmod(0o644)

        with self.assertRaises(fixture.FixtureError) as caught:
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )

        self.assertNotIn(literal_secret, str(caught.exception))
        self.assertFalse(snapshot.exists())

        secret_token = "ghp_" + "A" * 30
        test_file.write_text(f'password = "{secret_token}"\n', encoding="utf-8")
        test_file.chmod(0o644)

        with self.assertRaises(fixture.FixtureError) as caught:
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )

        self.assertNotIn(secret_token, str(caught.exception))
        self.assertFalse(snapshot.exists())

    def test_imp013_total_size_limit_counts_fingerprinted_test_changes(self) -> None:
        _base, policy = self.write_imp013_candidate()
        bounded_policy = replace(policy, max_total_bytes=100)
        snapshot = Path(self.temporary.name) / "imp013-oversized-total"

        with self.assertRaisesRegex(fixture.FixtureError, "total size limit"):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=bounded_policy,
            )
        self.assertFalse(snapshot.exists())

    def test_imp007_snapshot_fingerprints_exact_inputs_and_archives_only_runtime_support(
        self,
    ) -> None:
        base, policy = self.write_imp007_candidate()
        snapshot = Path(self.temporary.name) / "imp007-candidate-snapshot"
        (self.root / "PROJECT.md").write_text("unrelated live planning\n", encoding="utf-8")
        (self.root / ".opencode" / "progress.md").write_text(
            "unrelated local runner state\n",
            encoding="utf-8",
        )

        candidate = fixture.archive_candidate_snapshot(
            self.root,
            snapshot,
            private_home=self.private_home,
            policy=policy,
        )

        expected_paths = (
            {path for path, _status in policy.reviewed_inputs}
            | {path for path, _status in policy.nonruntime_test_changes}
            | {path for path, _status in policy.harness_changes}
        )
        self.assertEqual(candidate.base_commit, base)
        self.assertEqual({record.path for record in candidate.records}, expected_paths)
        self.assertEqual(
            set(candidate.runtime_paths),
            {path for path, _status in policy.reviewed_inputs},
        )
        self.assertRegex(candidate.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(
            candidate.support_file_digests,
            (
                (
                    ".dockerignore",
                    hashlib.sha256((snapshot / ".dockerignore").read_bytes()).hexdigest(),
                ),
                (
                    "scripts/backlog.py",
                    hashlib.sha256(b"committed root compatibility oracle\n").hexdigest(),
                ),
            ),
        )
        self.assertEqual(
            (snapshot / "scripts/backlog.py").read_bytes(),
            b"committed root compatibility oracle\n",
        )
        self.assertFalse((snapshot / "api/tests/test_backlog_markdown.py").exists())
        self.assertFalse((snapshot / "api/tests/test_backlog_tasks.py").exists())
        self.assertFalse((snapshot / "api/tests/test_backlog_tasks_postgres.py").exists())
        self.assertEqual(
            (snapshot / "web/src/ProjectWorkspace.test.tsx").read_text(encoding="utf-8"),
            "committed workspace tests\n",
        )
        self.assertFalse((snapshot / "scripts/local_browser_fixture.py").exists())
        self.assertFalse((snapshot / "scripts/test_local_browser_fixture.py").exists())
        self.assertFalse((snapshot / "PROJECT.md").exists())
        self.assertFalse((snapshot / ".opencode").exists())
        fixture.validate_candidate_dockerignore(snapshot, imp007=True)
        with self.assertRaisesRegex(fixture.FixtureError, "not safely allowlisted"):
            fixture.validate_candidate_dockerignore(snapshot)
        fixture.validate_candidate_snapshot_tree(snapshot, candidate)
        fixture.validate_candidate_worktree_snapshot(
            self.root,
            candidate,
            private_home=self.private_home,
            policy=policy,
        )

    def test_imp007_snapshot_rejects_unreviewed_or_missing_scoped_inputs(self) -> None:
        _base, policy = self.write_imp007_candidate()
        snapshot = Path(self.temporary.name) / "imp007-unreviewed-snapshot"

        for relative in (
            "api/app/unreviewed_backlog.py",
            "api/tests/test_backlog_extra.py",
            "scripts/backlog.py",
            "scripts/unreviewed_fixture.py",
            "PROJECT.md.example",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            original = path.read_bytes() if path.exists() else None
            path.write_text("unreviewed scoped candidate input\n", encoding="utf-8")
            path.chmod(0o644)
            with self.subTest(path=relative), self.assertRaisesRegex(
                fixture.FixtureError,
                "unexpected scoped input",
            ):
                fixture.archive_candidate_snapshot(
                    self.root,
                    snapshot,
                    private_home=self.private_home,
                    policy=policy,
                )
            self.assertFalse(snapshot.exists())
            if original is None:
                path.unlink()
            else:
                path.write_bytes(original)
                path.chmod(0o644)

        missing = self.root / "api/app/backlog_tasks.py"
        missing.unlink()
        with self.assertRaisesRegex(fixture.FixtureError, "reviewed candidate input is missing"):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.assertFalse(snapshot.exists())

    def test_imp007_snapshot_keeps_symlink_mode_size_and_runtime_secret_guards(self) -> None:
        _base, policy = self.write_imp007_candidate()
        snapshot = Path(self.temporary.name) / "imp007-unsafe-snapshot"
        runtime_file = self.root / "api/app/backlog_tasks.py"
        original = runtime_file.read_bytes()
        external = Path(self.temporary.name) / "outside-backlog.py"
        external.write_bytes(b"outside candidate bytes\n")

        runtime_file.unlink()
        runtime_file.symlink_to(external)
        with self.assertRaises(fixture.FixtureError):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.assertFalse(snapshot.exists())
        runtime_file.unlink()
        runtime_file.write_bytes(original)
        runtime_file.chmod(0o644)

        runtime_file.chmod(0o600)
        with self.assertRaises(fixture.FixtureError):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.assertFalse(snapshot.exists())
        runtime_file.chmod(0o644)

        secret = "synthetic-imp007-candidate-secret"
        runtime_file.write_text(f'DB_PASSWORD = "{secret}"\n', encoding="utf-8")
        runtime_file.chmod(0o644)
        with self.assertRaises(fixture.FixtureError) as caught:
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.assertNotIn(secret, str(caught.exception))
        self.assertFalse(snapshot.exists())

        runtime_file.write_bytes(b"x" * (fixture.MAX_CANDIDATE_FILE_BYTES + 1))
        runtime_file.chmod(0o644)
        with self.assertRaisesRegex(fixture.FixtureError, "size limit"):
            fixture.archive_candidate_snapshot(
                self.root,
                snapshot,
                private_home=self.private_home,
                policy=policy,
            )
        self.assertFalse(snapshot.exists())

    def test_imp007_fingerprint_rechecks_nonruntime_tests_and_fixture_harness(self) -> None:
        _base, policy = self.write_imp007_candidate()
        snapshot = Path(self.temporary.name) / "imp007-drift-snapshot"
        candidate = fixture.archive_candidate_snapshot(
            self.root,
            snapshot,
            private_home=self.private_home,
            policy=policy,
        )

        for relative in (
            "api/tests/test_backlog_tasks.py",
            "scripts/local_browser_fixture.py",
        ):
            changed = self.root / relative
            original = changed.read_bytes()
            changed.write_bytes(original + b"\n# changed after preflight\n")
            changed.chmod(0o644)
            with self.subTest(path=relative), self.assertRaisesRegex(
                fixture.FixtureError,
                "changed during preview",
            ):
                fixture.validate_candidate_worktree_snapshot(
                    self.root,
                    candidate,
                    private_home=self.private_home,
                    policy=policy,
                )

            stale_snapshot = Path(self.temporary.name) / f"imp007-stale-{Path(relative).name}"
            with self.assertRaisesRegex(fixture.FixtureError, "fingerprint changed"):
                fixture.archive_candidate_snapshot(
                    self.root,
                    stale_snapshot,
                    private_home=self.private_home,
                    expected_fingerprint=candidate.fingerprint,
                    policy=policy,
                )
            self.assertFalse(stale_snapshot.exists())
            changed.write_bytes(original)
            changed.chmod(0o644)

    def test_imp007_test_secret_exceptions_are_exact_and_do_not_reflect_literals(self) -> None:
        policy = fixture.IMP007_CANDIDATE_PREVIEW_POLICY
        allowed_literals = frozenset(policy.allowed_test_literal_digests)
        repository_root = Path(fixture.__file__).resolve().parent.parent
        for relative in {path for path, _name, _digest in policy.allowed_test_literal_digests}:
            fixture._reject_candidate_test_secrets(
                relative,
                (repository_root / relative).read_bytes(),
                allowed_literal_digests=allowed_literals,
            )

        relative = "api/tests/test_backlog_tasks_postgres.py"
        synthetic_literal = "synthetic-unapproved-test-password"
        with self.assertRaises(fixture.FixtureError) as caught:
            fixture._reject_candidate_test_secrets(
                relative,
                f'password = "{synthetic_literal}"\n'.encode("utf-8"),
                allowed_literal_digests=allowed_literals,
            )
        self.assertNotIn(synthetic_literal, str(caught.exception))

        token = "ghp_" + "A" * 30
        with self.assertRaises(fixture.FixtureError) as caught:
            fixture._reject_candidate_test_secrets(
                relative,
                f'password = "{token}"\n'.encode("utf-8"),
                allowed_literal_digests=allowed_literals,
            )
        self.assertNotIn(token, str(caught.exception))


class Imp007BacklogPreflightTests(unittest.TestCase):
    @staticmethod
    def _fixtures() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        content = "## [-] TASK-001 — Synthetic draft\n**Depends on:** None\n"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        document = {
            "kind": "backlog",
            "revision_number": 1,
            "content": content,
            "content_sha256": digest,
        }
        view = {
            "revision_number": 1,
            "content": content,
            "content_sha256": digest,
            "tasks": [
                {
                    "id": "TASK-001",
                    "status": "-",
                    "ready": False,
                    "eligible": False,
                    "waiting_on": [],
                }
            ],
            "summary": {
                "draft_count": 1,
                "ready_count": 0,
                "eligible_count": 0,
                "waiting_count": 0,
            },
        }
        return document, view, {"detail": "Not found"}

    def test_preflight_requires_revision_bound_view_and_foreign_read_write_denials(self) -> None:
        project_id = str(uuid.uuid4())
        document, view, not_found = self._fixtures()
        task_path = f"/api/projects/{project_id}/backlog/tasks"

        class FakeClient:
            def __init__(self, *, owner: bool, foreign_write_status: int = 404) -> None:
                self.owner = owner
                self.csrf_token = "synthetic-csrf-token"
                self.foreign_write_status = foreign_write_status
                self.calls: list[tuple[str, str, object | None, str | None]] = []

            def request(
                self,
                method: str,
                path: str,
                *,
                body: object | None = None,
                csrf_token: str | None = None,
            ) -> fixture.ApiResponse:
                self.calls.append((method, path, body, csrf_token))
                if self.owner:
                    return fixture.ApiResponse(200, view, {})
                status = self.foreign_write_status if method == "PUT" else 404
                return fixture.ApiResponse(status, not_found, {})

        owner = FakeClient(owner=True)
        other = FakeClient(owner=False)
        supervisor = fixture.FixtureSupervisor(
            Path("/fixture-test"),
            output=io.StringIO(),
            input_stream=io.StringIO(),
            candidate_preflight=True,
            candidate_variant="imp007",
        )

        supervisor._verify_candidate_backlog_tasks(
            owner,
            other,
            project_id=project_id,
            documents=[document],
        )

        self.assertEqual(owner.calls, [("GET", task_path, None, None)])
        self.assertEqual(
            other.calls,
            [
                ("GET", task_path, None, None),
                (
                    "PUT",
                    f"{task_path}/TASK-001",
                    {
                        "expected_revision": 1,
                        "status": "-",
                        "title": "Denied foreign task edit",
                        "body": "**Depends on:** None\n",
                    },
                    "synthetic-csrf-token",
                ),
            ],
        )

    def test_preflight_fails_if_a_foreign_member_can_read_or_edit_tasks(self) -> None:
        project_id = str(uuid.uuid4())
        document, view, not_found = self._fixtures()

        class FakeClient:
            def __init__(
                self,
                *,
                owner: bool,
                foreign_read_status: int = 404,
                foreign_write_status: int = 404,
                foreign_read_leak: bool = False,
                foreign_write_leak: bool = False,
            ):
                self.owner = owner
                self.csrf_token = "synthetic-csrf-token"
                self.foreign_read_status = foreign_read_status
                self.foreign_write_status = foreign_write_status
                self.foreign_read_leak = foreign_read_leak
                self.foreign_write_leak = foreign_write_leak

            def request(
                self,
                method: str,
                path: str,
                *,
                body: object | None = None,
                csrf_token: str | None = None,
            ) -> fixture.ApiResponse:
                if self.owner:
                    return fixture.ApiResponse(200, view, {})
                status = self.foreign_write_status if method == "PUT" else self.foreign_read_status
                leaks_data = (
                    self.foreign_write_leak
                    if method == "PUT"
                    else self.foreign_read_leak
                )
                payload = view if status == 200 or leaks_data else not_found
                return fixture.ApiResponse(status, payload, {})

        supervisor = fixture.FixtureSupervisor(
            Path("/fixture-test"),
            output=io.StringIO(),
            input_stream=io.StringIO(),
            candidate_preflight=True,
            candidate_variant="imp007",
        )
        for kwargs, expected_message in (
            ({"foreign_read_status": 200}, "read a foreign backlog task view"),
            (
                {"foreign_read_status": 404, "foreign_read_leak": True},
                "read a foreign backlog task view",
            ),
            ({"foreign_write_status": 200}, "edited a foreign backlog task"),
            (
                {"foreign_write_status": 404, "foreign_write_leak": True},
                "edited a foreign backlog task",
            ),
        ):
            with self.subTest(expected_message=expected_message):
                with self.assertRaisesRegex(fixture.FixtureError, expected_message):
                    supervisor._verify_candidate_backlog_tasks(
                        FakeClient(owner=True),
                        FakeClient(owner=False, **kwargs),
                        project_id=project_id,
                        documents=[document],
                    )


class ComposeSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.identity = fixture.generate_identity(18473)

    def test_run_address_is_unique_per_origin_but_remains_loopback(self) -> None:
        with patch("local_browser_fixture.secrets.randbelow", side_effect=[1, 2, 3, 1, 2, 4]):
            first = fixture.choose_loopback_host()
            second = fixture.choose_loopback_host()
        self.assertTrue(ipaddress.ip_address(first).is_loopback)
        self.assertTrue(ipaddress.ip_address(second).is_loopback)
        self.assertNotEqual(first, "127.0.0.1")
        self.assertNotEqual(second, "127.0.0.1")
        self.assertNotEqual(first, second)
        self.assertGreater(fixture.choose_loopback_port(first), 0)

    def valid_compose_config(self) -> dict[str, object]:
        identity = self.identity
        return {
            "services": {
                "db": {
                    "image": fixture.review_image_reference(identity.project_name, "db"),
                    "build": {
                        "labels": fixture.review_image_labels(identity.project_name, "db")
                    },
                    "environment": {"POSTGRES_PASSWORD": identity.postgres_password},
                    "ports": [],
                    "networks": {"backend": {}},
                    "volumes": [
                        {
                            "type": "volume",
                            "source": "postgres-data",
                            "target": "/var/lib/postgresql/data",
                        }
                    ],
                },
                "api": {
                    "image": fixture.review_image_reference(identity.project_name, "api"),
                    "build": {
                        "labels": fixture.review_image_labels(identity.project_name, "api")
                    },
                    "environment": {
                        "DB_PASSWORD": identity.app_password,
                        "IMPOSTR_RATE_LIMIT_KEY": identity.rate_limit_key,
                        "IMPOSTR_PUBLIC_ORIGIN": identity.origin,
                        "APP_PORT": str(identity.port),
                    },
                    "ports": [],
                    "networks": {"backend": {}},
                },
                "frontdoor": {
                    "image": fixture.review_image_reference(identity.project_name, "frontdoor"),
                    "build": {
                        "labels": fixture.review_image_labels(identity.project_name, "frontdoor")
                    },
                    "networks": {"backend": {}, "edge": {}},
                    "ports": [
                        {
                            "host_ip": identity.origin.split("//", 1)[1].split(":", 1)[0],
                            "published": str(identity.port),
                            "target": 8080,
                            "protocol": "tcp",
                        }
                    ]
                },
                "api-check": {"ports": []},
            },
            "networks": {"backend": {"internal": True}, "edge": {}},
            "volumes": {
                "postgres-data": {
                    "name": f"{identity.project_name}_postgres-data",
                    "external": False,
                }
            },
        }

    def valid_candidate_compose_config(self) -> tuple[dict[str, object], Path]:
        source = self.root / "candidate-source"
        for directory in (source, source / "api", source / "db", source / "web"):
            directory.mkdir(parents=True, exist_ok=True)
        config = self.valid_compose_config()
        services = config["services"]
        services["db"]["build"].update(
            context=str(source / "db"),
            dockerfile="Dockerfile",
        )
        services["db"]["environment"].update(
            POSTGRES_DB="impostr_review",
            POSTGRES_USER="review_owner",
            IMPOSTR_APP_DB_USER="review_app",
            IMPOSTR_APP_DB_PASSWORD=self.identity.app_password,
        )
        services["api"]["build"].update(
            context=str(source),
            dockerfile="api/Dockerfile",
            target="runtime",
        )
        services["api"]["environment"].update(
            DB_HOST="db",
            DB_PORT="5432",
            DB_NAME="impostr_review",
            DB_USER="review_app",
            IMPOSTR_TEMPLATE_DIR="/app/templates",
            IMPOSTR_WORKSPACE_ROOT="/workspaces",
        )
        services["frontdoor"]["build"].update(
            context=str(source / "web"),
            dockerfile="Dockerfile",
            target="runtime",
        )
        services["api-check"] = {
            "build": {
                "context": str(source),
                "dockerfile": "api/Dockerfile",
                "target": "development",
            },
            "ports": [],
            "networks": {"checks": {}},
        }
        services["api-integration-check"] = {
            "build": {
                "context": str(source),
                "dockerfile": "api/Dockerfile",
                "target": "development",
            },
            "ports": [],
            "networks": {"backend": {}},
        }
        services["web-check"] = {
            "build": {
                "context": str(source / "web"),
                "dockerfile": "Dockerfile",
                "target": "checks",
            },
            "ports": [],
            "networks": {"checks": {}},
        }
        config["networks"]["checks"] = {"internal": True}
        return config, source

    def test_compose_contract_accepts_only_loopback_frontdoor_and_owned_volume(self) -> None:
        fixture.validate_compose_config(json.dumps(self.valid_compose_config()), self.identity)

        public_bind = self.valid_compose_config()
        public_bind["services"]["frontdoor"]["ports"][0]["host_ip"] = "0.0.0.0"
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_compose_config(json.dumps(public_bind), self.identity)

        exposed_api = self.valid_compose_config()
        exposed_api["services"]["api"]["ports"] = [
            {"host_ip": "127.0.0.1", "published": "9999", "target": 8000}
        ]
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_compose_config(json.dumps(exposed_api), self.identity)

        external_volume = self.valid_compose_config()
        external_volume["volumes"]["postgres-data"]["external"] = True
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_compose_config(json.dumps(external_volume), self.identity)

        host_network = self.valid_compose_config()
        host_network["services"]["api"]["network_mode"] = "host"
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_compose_config(json.dumps(host_network), self.identity)

        host_mount = self.valid_compose_config()
        host_mount["services"]["frontdoor"]["volumes"] = [
            {"type": "bind", "source": "/tmp", "target": "/tmp"}
        ]
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_compose_config(json.dumps(host_mount), self.identity)

        shared_image = self.valid_compose_config()
        shared_image["services"]["api"]["image"] = "impostr-api:latest"
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_compose_config(json.dumps(shared_image), self.identity)

    def test_candidate_compose_contract_keeps_root_api_context_and_loopback_ownership(self) -> None:
        config, source = self.valid_candidate_compose_config()
        fixture.validate_candidate_compose_config(
            json.dumps(config),
            self.identity,
            source,
        )

        old_api_context = json.loads(json.dumps(config))
        old_api_context["services"]["api"]["build"]["context"] = str(source / "api")
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_candidate_compose_config(
                json.dumps(old_api_context),
                self.identity,
                source,
            )

        traversing_dockerfile = json.loads(json.dumps(config))
        traversing_dockerfile["services"]["api"]["build"]["dockerfile"] = "../Dockerfile"
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_candidate_compose_config(
                json.dumps(traversing_dockerfile),
                self.identity,
                source,
            )

        public_bind = json.loads(json.dumps(config))
        public_bind["services"]["frontdoor"]["ports"][0]["host_ip"] = "0.0.0.0"
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_candidate_compose_config(
                json.dumps(public_bind),
                self.identity,
                source,
            )

        host_context = json.loads(json.dumps(config))
        host_context["services"]["api"]["build"]["additional_contexts"] = {
            "host": "/"
        }
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_candidate_compose_config(
                json.dumps(host_context),
                self.identity,
                source,
            )

        inherited_env = json.loads(json.dumps(config))
        inherited_env["services"]["api"]["env_file"] = ["/host/secrets.env"]
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_candidate_compose_config(
                json.dumps(inherited_env),
                self.identity,
                source,
            )

        overridden_command = json.loads(json.dumps(config))
        overridden_command["services"]["api"]["command"] = ["sh", "-c", "unsafe"]
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_candidate_compose_config(
                json.dumps(overridden_command),
                self.identity,
                source,
            )

        unexpected_service = json.loads(json.dumps(config))
        unexpected_service["services"]["developer-shell"] = {"image": "unsafe:latest"}
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_candidate_compose_config(
                json.dumps(unexpected_service),
                self.identity,
                source,
            )

    def test_snapshot_bind_rewrite_changes_only_the_committed_loopback_address(self) -> None:
        source = self.root / "snapshot"
        source.mkdir()
        compose_file = source / "compose.yaml"
        compose_file.write_text(
            'services:\n  frontdoor:\n    ports:\n      - "127.0.0.1:${APP_PORT:-8080}:8080"\n',
            encoding="utf-8",
        )
        original = compose_file.read_text(encoding="utf-8")
        host = self.identity.origin.split("//", 1)[1].split(":", 1)[0]

        fixture.set_snapshot_loopback_host(source, host)

        rewritten = compose_file.read_text(encoding="utf-8")
        self.assertEqual(rewritten.count(f'"{host}:${{APP_PORT:-8080}}:8080"'), 1)
        self.assertEqual(rewritten.count('"127.0.0.1:${APP_PORT:-8080}:8080"'), 0)
        self.assertEqual(rewritten.replace(host, "127.0.0.1"), original)

    def test_snapshot_tags_and_labels_only_run_built_app_images(self) -> None:
        source = self.root / "snapshot-images"
        source.mkdir()
        compose_file = source / "compose.yaml"
        compose_file.write_text(
            "services:\n"
            "  db:\n"
            "    build:\n"
            "      context: ./db\n"
            "  api:\n"
            "    build:\n"
            "      context: ./api\n"
            "      target: runtime\n"
            "  frontdoor:\n"
            "    build:\n"
            "      context: ./web\n"
            "      target: runtime\n"
            "  api-check:\n"
            "    build:\n"
            "      context: ./api\n"
            "      target: development\n",
            encoding="utf-8",
        )

        fixture.set_snapshot_review_images(source, self.identity.project_name)

        rewritten = compose_file.read_text(encoding="utf-8")
        for service in fixture.REVIEW_IMAGE_SERVICES:
            self.assertIn(
                f"image: {fixture.review_image_reference(self.identity.project_name, service)}",
                rewritten,
            )
            labels = fixture.review_image_labels(self.identity.project_name, service)
            self.assertIn(
                f"{fixture.REVIEW_IMAGE_PROJECT_LABEL}: "
                f"{labels[fixture.REVIEW_IMAGE_PROJECT_LABEL]}",
                rewritten,
            )
            self.assertIn(f"{fixture.REVIEW_IMAGE_SERVICE_LABEL}: {service}", rewritten)
        api_check = rewritten.split("  api-check:\n", 1)[1]
        self.assertNotIn("image:", api_check)
        self.assertNotIn(f"{fixture.REVIEW_IMAGE_PROJECT_LABEL}:", api_check)

    def test_committed_head_image_tags_preserve_the_imp004_root_api_build_context(self) -> None:
        source = self.root / "committed-root-context"
        source.mkdir()
        compose_file = source / "compose.yaml"
        compose_file.write_text(
            "services:\n"
            "  db:\n"
            "    build:\n"
            "      context: ./db\n"
            "  api:\n"
            "    build:\n"
            "      context: .\n"
            "      dockerfile: api/Dockerfile\n"
            "      target: runtime\n"
            "  frontdoor:\n"
            "    build:\n"
            "      context: ./web\n"
            "      target: runtime\n",
            encoding="utf-8",
        )
        compose_file.chmod(0o644)

        fixture.set_snapshot_review_images(source, self.identity.project_name)

        rewritten = compose_file.read_text(encoding="utf-8")
        api_block = rewritten.split("  api:\n", 1)[1].split("  frontdoor:\n", 1)[0]
        self.assertIn("context: .\n", api_block)
        self.assertIn("dockerfile: api/Dockerfile\n", api_block)
        self.assertIn("target: runtime\n", api_block)
        self.assertIn(
            f"image: {fixture.review_image_reference(self.identity.project_name, 'api')}",
            api_block,
        )
        self.assertEqual(rewritten.count(f"{fixture.REVIEW_IMAGE_PROJECT_LABEL}:"), 3)

    def test_compose_env_is_mode_0600_and_secrets_stay_out_of_command_arguments(self) -> None:
        env_file = self.state / "compose.env"
        fixture.create_compose_env(env_file, self.identity)
        self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
        env_text = env_file.read_text(encoding="ascii")
        self.assertTrue(self.identity.postgres_password in env_text)
        self.assertTrue(self.identity.app_password in env_text)
        self.assertTrue(self.identity.rate_limit_key in env_text)

        source = self.root / "snapshot"
        source.mkdir()
        (source / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        docker = fixture.DockerClient(
            executable="docker",
            docker_socket="/var/run/docker.sock",
            state_dir=self.state,
        )
        compose = fixture.ComposeController(
            docker=docker,
            source_dir=source,
            env_file=env_file,
            project_name=self.identity.project_name,
        )
        command_line = " ".join(compose.command(["config", "--format", "json"]))
        for secret in (
            self.identity.postgres_password,
            self.identity.app_password,
            self.identity.rate_limit_key,
            self.identity.admin_password,
            *(member.password for member in self.identity.members),
        ):
            self.assertIsNotNone(secret)
            self.assertFalse(
                str(secret) in command_line,
                "secrets must not appear in process arguments",
            )
        self.assertIn(str(env_file), command_line)
        teardown_arguments = compose.command(
            ["down", "--volumes", "--remove-orphans", "--timeout", "10"]
        )
        self.assertEqual(
            teardown_arguments[teardown_arguments.index("--project-name") + 1],
            self.identity.project_name,
        )
        self.assertEqual(
            teardown_arguments[teardown_arguments.index("--env-file") + 1], str(env_file)
        )
        self.assertNotIn("prune", teardown_arguments)

    def test_private_recovery_file_holds_only_both_generated_member_logins(self) -> None:
        path = self.state / fixture.MEMBER_RECOVERY_FILE

        fixture.create_member_recovery_file(self.state, self.identity)

        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(
            json.loads(path.read_text(encoding="ascii")),
            [
                {"username": member.username, "password": member.password}
                for member in self.identity.members
            ],
        )
        for privileged_secret in (
            self.identity.admin_password,
            self.identity.postgres_password,
            self.identity.app_password,
            self.identity.rate_limit_key,
        ):
            self.assertNotIn(str(privileged_secret), path.read_text(encoding="ascii"))
        with self.assertRaises(fixture.FixtureError):
            fixture.create_member_recovery_file(self.state, self.identity)

    def test_recovery_file_rejects_non_private_directory_before_writing(self) -> None:
        self.state.chmod(0o755)
        with self.assertRaises(fixture.FixtureError):
            fixture.create_member_recovery_file(self.state, self.identity)
        self.assertFalse((self.state / fixture.MEMBER_RECOVERY_FILE).exists())

    def test_cleanup_database_transaction_disables_both_member_ids_and_revokes_sessions(
        self,
    ) -> None:
        compose = fixture.ComposeController(
            docker=object(),
            source_dir=self.root,
            env_file=self.root / "compose.env",
            project_name=self.identity.project_name,
        )
        member_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        admin_id = str(uuid.uuid4())
        with patch.object(compose, "run_api_python", return_value="2") as run:
            disabled = compose.disable_members_and_revoke_sessions(
                member_ids,
                [admin_id, *member_ids],
            )

        self.assertEqual(disabled, 2)
        code = run.call_args.args[0]
        compile(code, "<fixture-cleanup>", "exec")
        self.assertIn("update(User)", code)
        self.assertIn("values(is_active=False)", code)
        self.assertIn("update(WebSession)", code)
        self.assertIn("WebSession.revoked_at.is_(None)", code)
        for user_id in [admin_id, *member_ids]:
            self.assertIn(user_id, code)
        for secret in (
            self.identity.admin_password,
            self.identity.postgres_password,
            self.identity.app_password,
            *(member.password for member in self.identity.members),
        ):
            self.assertNotIn(str(secret), code)

    def test_docker_process_environment_does_not_inherit_host_secrets_or_proxy(self) -> None:
        host_db_secret = secrets.token_hex(24)
        host_app_secret = secrets.token_hex(24)
        provider_secret = secrets.token_hex(24)
        proxy_secret = secrets.token_hex(24)
        other_project = f"existing-{secrets.token_hex(8)}"
        with patch.dict(
            os.environ,
            {
                "POSTGRES_PASSWORD": host_db_secret,
                "DB_PASSWORD": host_app_secret,
                "AWS_SECRET_ACCESS_KEY": provider_secret,
                "HTTP_PROXY": f"http://proxy-user:{proxy_secret}@example.invalid",
                "COMPOSE_PROJECT_NAME": other_project,
            },
            clear=False,
        ):
            environment = fixture.private_docker_environment(self.state)

        values = " ".join(environment.values())
        for secret in (
            host_db_secret,
            host_app_secret,
            provider_secret,
            proxy_secret,
            other_project,
        ):
            self.assertFalse(secret in values, "host secrets must not enter the Docker environment")
        self.assertEqual(
            set(environment),
            {"PATH", "HOME", "DOCKER_CONFIG", "TMPDIR"},
        )

    def test_docker_error_output_is_not_reflected_to_operator(self) -> None:
        env_file = self.state / "compose.env"
        fixture.create_compose_env(env_file, self.identity)
        source = self.root / "snapshot"
        source.mkdir()
        (source / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        docker = fixture.DockerClient(
            executable="docker",
            docker_socket="/var/run/docker.sock",
            state_dir=self.state,
        )
        compose = fixture.ComposeController(
            docker=docker,
            source_dir=source,
            env_file=env_file,
            project_name=self.identity.project_name,
        )
        secret = str(self.identity.app_password)
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=19,
            stdout=f"compose echoed {secret}".encode(),
            stderr=f"docker diagnostic {secret}".encode(),
        )
        operator_output = io.StringIO()
        with (
            patch("local_browser_fixture.subprocess.run", return_value=completed),
            redirect_stdout(operator_output),
            redirect_stderr(operator_output),
        ):
            with self.assertRaises(fixture.FixtureError) as caught:
                compose.invoke(
                    ["config", "--format", "json"],
                    label="private config test",
                    capture_stdout=True,
                )
        self.assertFalse(secret in str(caught.exception), "Docker diagnostics must be redacted")
        self.assertFalse(secret in operator_output.getvalue(), "Docker output must be suppressed")

    def test_project_collision_is_rejected_without_teardown(self) -> None:
        class ExistingResources:
            def project_resource_ids(self, resource: str, project_name: str) -> str:
                return "foreign-resource" if resource == "volume" else ""

            def image_ids_for_project(self, project_name: str) -> list[str]:
                return []

            def image_ids_for_reference(self, reference: str) -> list[str]:
                return []

        compose = fixture.ComposeController(
            docker=ExistingResources(),
            source_dir=self.root,
            env_file=self.root / "compose.env",
            project_name=self.identity.project_name,
        )
        with self.assertRaises(fixture.FixtureError):
            compose.verify_no_existing_project_resources()


class ImageOwnershipTests(unittest.TestCase):
    class FakeDocker:
        def __init__(self, project_name: str) -> None:
            self.project_name = project_name
            self.references: dict[str, str] = {}
            self.labels: dict[str, dict[str, str]] = {}
            self.removed: list[tuple[str, str]] = []

        def project_resource_ids(self, _resource: str, _project_name: str) -> str:
            return ""

        def image_ids_for_project(self, project_name: str) -> list[str]:
            return [
                image_id
                for image_id, labels in self.labels.items()
                if labels.get(fixture.REVIEW_IMAGE_PROJECT_LABEL) == project_name
            ]

        def image_ids_for_reference(self, reference: str) -> list[str]:
            image_id = self.references.get(reference)
            return [image_id] if image_id else []

        def image_config_labels(self, image_id: str) -> dict[str, str]:
            return dict(self.labels.get(image_id, {}))

        def remove_image_reference(self, reference: str, expected_image_id: str) -> None:
            if self.references.get(reference) != expected_image_id:
                raise fixture.FixtureError("mock image reference changed")
            self.removed.append((reference, expected_image_id))
            del self.references[reference]
            if expected_image_id not in self.references.values():
                self.labels.pop(expected_image_id, None)

        def add_run_image(self, service: str) -> tuple[str, str]:
            reference = fixture.review_image_reference(self.project_name, service)
            image_id = "sha256:" + secrets.token_hex(32)
            self.references[reference] = image_id
            self.labels[image_id] = fixture.review_image_labels(self.project_name, service)
            return reference, image_id

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.identity = fixture.generate_identity(18473)
        self.docker = self.FakeDocker(self.identity.project_name)
        self.compose = fixture.ComposeController(
            docker=self.docker,
            source_dir=self.root,
            env_file=self.root / "compose.env",
            project_name=self.identity.project_name,
        )

    def test_partial_build_cleanup_removes_only_labeled_run_tags(self) -> None:
        run_tags = [self.docker.add_run_image(service) for service in ("db", "api")]
        shared_cache_id = "sha256:" + secrets.token_hex(32)
        self.docker.references["shared-builder-cache:latest"] = shared_cache_id
        self.docker.labels[shared_cache_id] = {"com.example.cache": "shared"}

        self.compose.remove_owned_images()

        self.assertCountEqual(self.docker.removed, run_tags)
        self.assertEqual(self.docker.references, {"shared-builder-cache:latest": shared_cache_id})
        self.assertNotIn(shared_cache_id, self.docker.removed)
        self.compose.verify_project_images_removed()

    def test_preexisting_or_foreign_image_tag_is_never_removed(self) -> None:
        reference = fixture.review_image_reference(self.identity.project_name, "api")
        foreign_id = "sha256:" + secrets.token_hex(32)
        self.docker.references[reference] = foreign_id
        self.docker.labels[foreign_id] = {"com.example.owner": "someone-else"}

        with self.assertRaises(fixture.FixtureError):
            self.compose.verify_no_existing_project_resources()
        with self.assertRaises(fixture.FixtureError):
            self.compose.remove_owned_images()

        self.assertEqual(self.docker.removed, [])
        self.assertEqual(self.docker.references[reference], foreign_id)

    def test_unexpected_untagged_run_labeled_image_fails_closed(self) -> None:
        orphan_id = "sha256:" + secrets.token_hex(32)
        self.docker.labels[orphan_id] = fixture.review_image_labels(
            self.identity.project_name,
            "db",
        )

        with self.assertRaises(fixture.FixtureError):
            self.compose.remove_owned_images()

        self.assertEqual(self.docker.removed, [])
        self.assertIn(orphan_id, self.docker.labels)

    def test_docker_removal_uses_only_exact_tag_and_disables_parent_pruning(self) -> None:
        image_id = "sha256:" + secrets.token_hex(32)
        service = "api"
        reference = fixture.review_image_reference(self.identity.project_name, service)
        labels = fixture.review_image_labels(self.identity.project_name, service)
        outputs = (
            f"{image_id}\n".encode(),
            json.dumps(labels).encode(),
            b"",
        )
        completed = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout=value, stderr=b"")
            for value in outputs
        ]
        docker = fixture.DockerClient(
            executable="docker",
            docker_socket="/var/run/docker.sock",
            state_dir=self.root,
        )
        with patch("local_browser_fixture.subprocess.run", side_effect=completed) as run:
            docker.remove_image_reference(reference, image_id)

        remove_arguments = run.call_args_list[-1].args[0]
        self.assertEqual(remove_arguments[-4:], ["image", "rm", "--no-prune", reference])
        self.assertNotIn("prune", remove_arguments[:-1])
        self.assertNotIn("--force", remove_arguments)


class RecoveryOwnershipTests(unittest.TestCase):
    class FakeDocker:
        def __init__(self, project_name: str, source_dir: Path, *, invalid_target: bool = False):
            self.project_name = project_name
            self.source_dir = source_dir
            self.environment: dict[str, str] = {}
            self.events: list[str] = []
            self.resources = {
                "container": ["a" * 64],
                "network": ["b" * 64, "c" * 64],
                "volume": [f"{project_name}_postgres-data"],
            }
            self.owner_resources = {
                "container": ["d" * 64],
                "network": ["e" * 64],
                "volume": ["unrelated-owner_postgres-data"],
            }
            self.labels = {
                ("container", "a" * 64): {
                    "com.docker.compose.project": project_name,
                    "com.docker.compose.service": (
                        "foreign-service" if invalid_target else "frontdoor"
                    ),
                    "com.docker.compose.project.working_dir": str(source_dir),
                    "com.docker.compose.project.config_files": str(source_dir / "compose.yaml"),
                },
                ("network", "b" * 64): {
                    "com.docker.compose.project": project_name,
                    "com.docker.compose.network": "backend",
                },
                ("network", "c" * 64): {
                    "com.docker.compose.project": project_name,
                    "com.docker.compose.network": "edge",
                },
                ("volume", f"{project_name}_postgres-data"): {
                    "com.docker.compose.project": project_name,
                    "com.docker.compose.volume": "postgres-data",
                },
                ("container", "d" * 64): {
                    "com.docker.compose.project": "unrelated-owner",
                    "com.docker.compose.service": "frontdoor",
                },
            }

        def command(self, arguments: list[str]) -> list[str]:
            return ["docker", *arguments]

        def probe_local_engine(self) -> None:
            self.events.append("probe")

        def project_resource_ids(self, resource: str, project_name: str) -> str:
            if project_name == self.project_name:
                return "\n".join(self.resources[resource])
            if project_name == "unrelated-owner":
                return "\n".join(self.owner_resources[resource])
            return ""

        def project_resource_labels(self, resource: str, resource_id: str) -> dict[str, str]:
            return dict(self.labels[(resource, resource_id)])

        def image_ids_for_project(self, _project_name: str) -> list[str]:
            return []

        def image_ids_for_reference(self, _reference: str) -> list[str]:
            return []

        def image_config_labels(self, _image_id: str) -> dict[str, str]:
            return {}

        def remove_image_reference(self, _reference: str, _expected_image_id: str) -> None:
            raise AssertionError("the fake recovery stack has no owned images")

    def setUp(self) -> None:
        self.state_temporary = tempfile.TemporaryDirectory(
            prefix="impostr-browser-review-",
        )
        self.addCleanup(self.state_temporary.cleanup)
        self.state = Path(self.state_temporary.name)
        self.source = self.state / "source"
        self.source.mkdir(mode=0o700)
        (self.source / "compose.yaml").write_text("services: {}\n", encoding="ascii")
        self.env_file = self.state / "compose.env"
        self.env_file.write_text("\n", encoding="ascii")
        self.env_file.chmod(0o600)
        self.control_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.control_temporary.cleanup)
        self.control = Path(self.control_temporary.name)
        self.identity = fixture.generate_identity(18473)
        self.recovery_record = {
            "state_dir": str(self.state),
            "project_name": self.identity.project_name,
            "owned": True,
            "resources_removed": False,
        }
        fixture._write_control_record(
            self.control,
            {
                "pid": os.getpid(),
                "start_time": fixture._proc_start_time(os.getpid()),
                "recovery": self.recovery_record,
            },
        )

    @staticmethod
    def cleanup_live_project(
        compose: fixture.ComposeController,
        state_dir: Path,
    ) -> None:
        if state_dir.exists():
            compose.down()
            compose.verify_project_resources_removed()
            compose.remove_owned_images()
            compose.verify_project_images_removed()

    def recover_with_fake_docker(
        self,
        docker: "RecoveryOwnershipTests.FakeDocker",
        *,
        handoff_directory: Path | None = None,
    ) -> tuple[dict[str, str], list[list[str]]]:
        commands: list[list[str]] = []

        def run_compose(command: list[str], **_options):
            commands.append(command)
            if "down" in command:
                docker.events.append("down")
                docker.resources = {resource: [] for resource in docker.resources}
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        with (
            patch("local_browser_fixture.DockerClient", return_value=docker),
            patch("local_browser_fixture.shutil.which", return_value="docker"),
            patch("local_browser_fixture.subprocess.run", side_effect=run_compose),
        ):
            if handoff_directory is None:
                result = fixture.recover_registered_project(self.control)
            else:
                fixture._write_guardian_failure_status(
                    handoff_directory,
                    control_directory=self.control,
                )
                status = fixture.read_cleanup_status(handoff_directory)
                assert status is not None
                result = status
        return result, commands

    def test_recovery_tears_down_only_the_registered_project(self) -> None:
        docker = self.FakeDocker(self.identity.project_name, self.source)
        owner_before = {key: list(value) for key, value in docker.owner_resources.items()}
        private_password = secrets.token_urlsafe(24)
        self.env_file.write_text(f"POSTGRES_PASSWORD={private_password}\n", encoding="ascii")
        self.env_file.chmod(0o600)

        result, commands = self.recover_with_fake_docker(docker)

        self.assertEqual(result["recovery_status"], "completed")
        self.assertEqual(result["owned_compose"], "removed")
        self.assertEqual(result["owned_images"], "removed")
        self.assertEqual(result["private_state"], "removed")
        self.assertFalse(self.state.exists())
        self.assertTrue(all(not identifiers for identifiers in docker.resources.values()))
        self.assertEqual(docker.owner_resources, owner_before)
        self.assertEqual(docker.events, ["probe", "down"])
        self.assertEqual(len(commands), 1)
        self.assertEqual(
            commands[0][commands[0].index("--project-name") + 1],
            self.identity.project_name,
        )
        self.assertNotIn(private_password, " ".join(commands[0]))
        control_text = (self.control / fixture.CONTROL_FILE).read_text(encoding="ascii")
        self.assertNotIn(private_password, control_text)
        for secret in (
            self.identity.admin_password,
            self.identity.postgres_password,
            self.identity.app_password,
            self.identity.rate_limit_key,
            *(member.password for member in self.identity.members),
        ):
            self.assertNotIn(str(secret), control_text)

    def test_recovery_refuses_mismatched_resource_labels_before_down(self) -> None:
        docker = self.FakeDocker(self.identity.project_name, self.source, invalid_target=True)

        result, commands = self.recover_with_fake_docker(docker)

        self.assertEqual(result["recovery_status"], "failed")
        self.assertEqual(result["owned_compose"], "not-verified")
        self.assertEqual(result["private_state"], "retained-for-recovery")
        self.assertEqual(commands, [])
        self.assertEqual(len(docker.resources["container"]), 1)
        self.assertEqual(len(docker.owner_resources["container"]), 1)
        self.assertTrue(self.state.exists())

    def test_guardian_abrupt_exit_recovers_stack_and_removes_only_member_handoff(self) -> None:
        channel_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(channel_temporary.cleanup)
        channel = Path(channel_temporary.name)
        fixture.write_cleanup_status(channel, fixture.initial_cleanup_status())
        member = self.identity.members[0]
        fixture.write_member_handoff(channel, member.username, str(member.password))
        ready_status = fixture.initial_cleanup_status()
        ready_status.update(
            phase="ready",
            member_login="published",
            member_accounts="pending",
            owned_compose="pending",
            owned_images="pending",
            private_state="pending",
            recovery_status="pending",
        )
        fixture.write_cleanup_status(channel, ready_status)
        docker = self.FakeDocker(self.identity.project_name, self.source)

        status, commands = self.recover_with_fake_docker(docker, handoff_directory=channel)

        self.assertEqual(status["phase"], "stopped")
        self.assertEqual(status["exit_code"], 1)
        self.assertEqual(status["recovery_status"], "completed")
        self.assertEqual(status["member_login"], "removed")
        self.assertEqual(status["owned_compose"], "removed")
        self.assertEqual(status["owned_images"], "removed")
        self.assertEqual(status["private_state"], "removed")
        self.assertFalse((channel / fixture.MEMBER_HANDOFF_FILE).exists())
        self.assertEqual(len(commands), 1)
        self.assertEqual(len(docker.owner_resources["container"]), 1)

    def test_unverified_ownership_keeps_recovery_record_and_reports_retry_state(self) -> None:
        channel_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(channel_temporary.cleanup)
        channel = Path(channel_temporary.name)
        ready_status = fixture.initial_cleanup_status()
        ready_status.update(
            phase="ready",
            member_login="published",
            member_accounts="pending",
            owned_compose="pending",
            owned_images="pending",
            private_state="pending",
            recovery_status="pending",
        )
        fixture.write_cleanup_status(channel, ready_status)
        member = self.identity.members[0]
        fixture.write_member_handoff(channel, member.username, str(member.password))
        docker = self.FakeDocker(self.identity.project_name, self.source, invalid_target=True)

        status, commands = self.recover_with_fake_docker(docker, handoff_directory=channel)

        self.assertEqual(status["recovery_status"], "failed")
        self.assertEqual(status["owned_compose"], "not-verified")
        self.assertEqual(status["owned_images"], "not-verified")
        self.assertEqual(status["private_state"], "retained-for-recovery")
        self.assertFalse(fixture._clean_previous_run(status))
        self.assertEqual(commands, [])
        self.assertTrue((self.control / fixture.CONTROL_FILE).exists())
        self.assertTrue(self.state.exists())
        self.assertEqual(len(docker.owner_resources["container"]), 1)
        self.assertFalse((channel / fixture.MEMBER_HANDOFF_FILE).exists())

    def test_pre_resource_failure_removes_only_private_state(self) -> None:
        fixture._unlink_private_file(self.control, fixture.CONTROL_FILE)
        recovery = {
            "state_dir": str(self.state),
            "project_name": self.identity.project_name,
            "owned": False,
            "resources_removed": False,
        }
        fixture._write_control_record(
            self.control,
            {
                "pid": os.getpid(),
                "start_time": fixture._proc_start_time(os.getpid()),
                "recovery": recovery,
            },
        )

        result = fixture.recover_registered_project(self.control)

        self.assertEqual(result["recovery_status"], "completed")
        self.assertEqual(result["owned_compose"], "not-created")
        self.assertEqual(result["private_state"], "removed")
        self.assertFalse(self.state.exists())

    def test_missing_ownership_record_never_claims_stack_cleanup(self) -> None:
        fixture._unlink_private_file(self.control, fixture.CONTROL_FILE)
        channel_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(channel_temporary.cleanup)
        channel = Path(channel_temporary.name)
        ready = fixture.initial_cleanup_status()
        ready.update(
            phase="ready",
            member_login="published",
            member_accounts="pending",
            owned_compose="pending",
            owned_images="pending",
            private_state="pending",
            recovery_status="pending",
        )
        fixture.write_cleanup_status(channel, ready)

        cleanup_verified = fixture._write_guardian_failure_status(
            channel,
            control_directory=self.control,
        )

        status = fixture.read_cleanup_status(channel)
        self.assertFalse(cleanup_verified)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status["recovery_status"], "manual-required")
        self.assertEqual(status["owned_compose"], "not-verified")
        self.assertEqual(status["private_state"], "retained-for-recovery")
        self.assertFalse(fixture._clean_previous_run(status))

    def test_prepare_durably_registers_ownership_before_first_create_capable_command(self) -> None:
        # Drive the real _prepare sequence with inert Compose/Docker stand-ins.
        # The SIGKILL guardian test below injects a record; this verifies that
        # production setup actually writes that record before Docker can build.
        # Migration-profile selection is covered separately; keep this assertion
        # scoped to ownership registration ordering.
        with tempfile.TemporaryDirectory(prefix="impostr-browser-review-") as temporary:
            state = Path(temporary)
            self_control = self.control / "production-registration"
            self_control.mkdir(mode=0o700)
            fixture._write_control_record(
                self_control,
                {"pid": os.getpid(), "start_time": fixture._proc_start_time(os.getpid())},
            )
            supervisor = fixture.FixtureSupervisor(
                Path(__file__).resolve().parent.parent,
                output=io.StringIO(),
                input_stream=io.StringIO(),
                control_directory=self_control,
            )
            docker = self.FakeDocker(self.identity.project_name, state / "source")
            observed: list[tuple[str, dict[str, object]]] = []

            class InertCompose:
                def __init__(self, **_options: object) -> None:
                    pass

                def config_json(self) -> str:
                    return "{}"

                def verify_no_existing_project_resources(self) -> None:
                    record = fixture._read_control_record(self_control)
                    assert record is not None
                    observed.append(("checked-empty", dict(record["recovery"])))

                def build(self) -> None:
                    record = fixture._read_control_record(self_control)
                    assert record is not None
                    observed.append(("before-build", dict(record["recovery"])))
                    raise fixture.FixtureError("simulated partial build")

            with (
                patch.object(supervisor.input_stream, "isatty", return_value=True),
                patch.object(supervisor.output, "isatty", return_value=True),
                patch("local_browser_fixture.shutil.which", return_value="docker"),
                patch("local_browser_fixture.create_private_state_dir", return_value=state),
                patch("local_browser_fixture.choose_loopback_host", return_value="127.4.5.6"),
                patch("local_browser_fixture.choose_loopback_port", return_value=18473),
                patch("local_browser_fixture.DockerClient", return_value=docker),
                patch("local_browser_fixture.archive_head_snapshot", return_value="2" * 40),
                patch(
                    "local_browser_fixture.select_committed_app_migration_profile",
                    return_value="imp004",
                ),
                patch("local_browser_fixture.set_snapshot_loopback_host"),
                patch("local_browser_fixture.set_snapshot_review_images"),
                patch("local_browser_fixture.ComposeController", InertCompose),
                patch("local_browser_fixture.validate_compose_config"),
            ):
                with self.assertRaisesRegex(fixture.FixtureError, "simulated partial build"):
                    supervisor._prepare()

            self.assertEqual([event for event, _ in observed], ["checked-empty", "before-build"])
            before_check, before_build = (recovery for _, recovery in observed)
            self.assertEqual(before_check["state_dir"], str(state))
            self.assertEqual(before_check["project_name"], before_build["project_name"])
            self.assertEqual(before_build["project_name"], supervisor.identity.project_name)
            self.assertFalse(before_check["owned"])
            self.assertTrue(before_build["owned"])
            self.assertFalse(before_build["resources_removed"])
            self.assertTrue(supervisor.project_owned)
            self.assertTrue((state / fixture.MEMBER_RECOVERY_FILE).is_file())
            record_text = (self_control / fixture.CONTROL_FILE).read_text(encoding="ascii")
            for secret in (
                supervisor.identity.admin_password,
                supervisor.identity.postgres_password,
                supervisor.identity.app_password,
                *(member.password for member in supervisor.identity.members),
            ):
                self.assertNotIn(str(secret), record_text)

    def test_stop_fails_after_recovering_a_crashed_ready_run(self) -> None:
        channel_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(channel_temporary.cleanup)
        channel = Path(channel_temporary.name)
        member = self.identity.members[0]
        fixture.write_member_handoff(channel, member.username, str(member.password))
        ready = fixture.initial_cleanup_status()
        ready.update(
            phase="ready", member_login="published", member_accounts="pending",
            owned_compose="pending", owned_images="pending", private_state="pending",
            recovery_status="pending",
        )
        fixture.write_cleanup_status(channel, ready)
        docker = self.FakeDocker(self.identity.project_name, self.source)
        commands: list[list[str]] = []

        def run_compose(command: list[str], **_options):
            commands.append(command)
            if "down" in command:
                docker.resources = {resource: [] for resource in docker.resources}
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        messages = io.StringIO()
        with (
            patch.object(fixture, "APPROVED_HANDOFF_DIRECTORY", channel),
            patch("local_browser_fixture._ensure_control_directory", return_value=self.control),
            patch("local_browser_fixture._signal_supervisor", return_value=False),
            patch("local_browser_fixture._open_verified_supervisor_pidfd", return_value=None),
            patch("local_browser_fixture.DockerClient", return_value=docker),
            patch("local_browser_fixture.shutil.which", return_value="docker"),
            patch("local_browser_fixture.subprocess.run", side_effect=run_compose),
            redirect_stderr(messages),
        ):
            result = fixture.stop_unattended(channel, timeout=2)

        status = fixture.read_cleanup_status(channel)
        self.assertEqual(result, 1)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status["exit_code"], 1)
        self.assertEqual(status["recovery_status"], "completed")
        self.assertTrue(fixture._clean_previous_run(status))
        self.assertEqual(len(commands), 1)
        self.assertFalse(self.state.exists())
        self.assertFalse((channel / fixture.MEMBER_HANDOFF_FILE).exists())
        self.assertIsNone(fixture._read_control_record(self.control))
        self.assertIn("setup or review failed", messages.getvalue())

    @unittest.skipUnless(
        os.environ.get("IMPOSTR_FIXTURE_LIVE_RECOVERY") == "1",
        "set IMPOSTR_FIXTURE_LIVE_RECOVERY=1 for the bounded local Docker recovery test",
    )
    def test_live_abrupt_failure_recovery_preserves_an_unrelated_compose_project(self) -> None:
        executable = fixture.shutil.which("docker")
        if executable is None:
            self.skipTest("Docker CLI is unavailable")

        target_state_temporary = tempfile.TemporaryDirectory(
            prefix="impostr-browser-review-",
            dir=tempfile.gettempdir(),
        )
        owner_state_temporary = tempfile.TemporaryDirectory(
            prefix="impostr-browser-review-",
            dir=tempfile.gettempdir(),
        )
        self.addCleanup(target_state_temporary.cleanup)
        self.addCleanup(owner_state_temporary.cleanup)
        target_state = Path(target_state_temporary.name)
        owner_state = Path(owner_state_temporary.name)
        target_identity = fixture.generate_identity(18483)
        owner_identity = fixture.generate_identity(18484)
        target_docker = fixture.DockerClient(
            executable=executable,
            docker_socket=fixture.LOCAL_DOCKER_SOCKET,
            state_dir=target_state,
        )
        image = None
        for candidate in (
            "nginx:1.29.0",
            "busybox:latest",
            "alpine:3.20",
            "hello-world:latest",
        ):
            try:
                target_docker.run(
                    ["image", "inspect", "--format", "{{.Id}}", candidate],
                    label="local recovery test image check",
                    timeout=10,
                    capture_stdout=True,
                )
                image = candidate
                break
            except fixture.FixtureError:
                continue
        if image is None:
            self.skipTest("No suitable container image is already cached; the test will not pull.")

        target_source = target_state / "source"
        owner_source = owner_state / "source"
        target_source.mkdir(mode=0o700)
        owner_source.mkdir(mode=0o700)
        target_env = target_state / "compose.env"
        owner_env = owner_state / "compose.env"
        for env_file in (target_env, owner_env):
            env_file.write_text("\n", encoding="ascii")
            env_file.chmod(0o600)

        runtime_override = (
            ""
            if image == "hello-world:latest"
            else "    entrypoint: [\"/bin/sh\", \"-c\"]\n"
            "    command: [\"sleep 600\"]\n"
        )
        compose_text = (
            "services:\n"
            "  frontdoor:\n"
            f"    image: {image}\n"
            f"{runtime_override}"
            "    volumes:\n"
            "      - postgres-data:/tmp/recovery-test-data\n"
            "    networks: [backend, edge]\n"
            "networks:\n"
            "  backend: {}\n"
            "  edge: {}\n"
            "volumes:\n"
            "  postgres-data: {}\n"
        )
        (target_source / "compose.yaml").write_text(compose_text, encoding="utf-8")
        (owner_source / "compose.yaml").write_text(compose_text, encoding="utf-8")
        target_compose = fixture.ComposeController(
            docker=target_docker,
            source_dir=target_source,
            env_file=target_env,
            project_name=target_identity.project_name,
        )
        self.addCleanup(self.cleanup_live_project, target_compose, target_state)
        owner_docker = fixture.DockerClient(
            executable=executable,
            docker_socket=fixture.LOCAL_DOCKER_SOCKET,
            state_dir=owner_state,
        )
        owner_compose = fixture.ComposeController(
            docker=owner_docker,
            source_dir=owner_source,
            env_file=owner_env,
            project_name=owner_identity.project_name,
        )
        self.addCleanup(self.cleanup_live_project, owner_compose, owner_state)

        target_compose.verify_no_existing_project_resources()
        target_compose.up()
        owner_compose.verify_no_existing_project_resources()
        owner_compose.up()
        owner_resources = {
            resource: owner_docker.project_resource_ids(
                resource,
                owner_identity.project_name,
            )
            for resource in ("container", "volume", "network")
        }
        self.assertTrue(all(owner_resources.values()))

        channel_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(channel_temporary.cleanup)
        channel = Path(channel_temporary.name)
        fixture.write_cleanup_status(channel, fixture.initial_cleanup_status())
        member = target_identity.members[0]

        control_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(control_temporary.cleanup)
        control = Path(control_temporary.name)
        lock_fd = fixture._open_control_lock(control)
        lock_open = True
        pty_errors: list[BaseException] = []
        real_run_under_pty = fixture.run_under_pty

        def kill_after_resource_creation(_command, **guardian_callbacks):
            def register_crash_state(process):
                guardian_callbacks["on_spawn"](process)
                record = fixture._read_control_record(control)
                assert record is not None
                record["recovery"] = {
                    "state_dir": str(target_state),
                    "project_name": target_identity.project_name,
                    "owned": True,
                    "resources_removed": False,
                }
                fixture._atomic_write_private_json(
                    control,
                    fixture.CONTROL_FILE,
                    record,
                    replace_existing=True,
                )
                fixture.write_member_handoff(channel, member.username, str(member.password))
                ready_status = fixture.initial_cleanup_status()
                ready_status.update(
                    phase="ready",
                    member_login="published",
                    member_accounts="pending",
                    owned_compose="pending",
                    owned_images="pending",
                    private_state="pending",
                    recovery_status="pending",
                )
                fixture.write_cleanup_status(channel, ready_status)

            try:
                return real_run_under_pty(
                    [
                        sys.executable,
                        "-c",
                        "import os, signal; os.kill(os.getpid(), signal.SIGKILL)",
                    ],
                    on_spawn=register_crash_state,
                    on_ready=guardian_callbacks["on_ready"],
                    stop_requested=guardian_callbacks["stop_requested"],
                    cwd=Path.cwd(),
                    environment=fixture._safe_runner_environment(control),
                )
            except BaseException as error:
                pty_errors.append(error)
                raise

        try:
            with (
                patch.object(fixture, "APPROVED_HANDOFF_DIRECTORY", channel),
                patch.object(fixture, "_ensure_control_directory", return_value=control),
                patch.object(fixture, "run_under_pty", side_effect=kill_after_resource_creation),
            ):
                guardian_exit = fixture._run_guardian(channel, 30, lock_fd)
                lock_open = False
        finally:
            if lock_open:
                os.close(lock_fd)
        self.assertEqual(pty_errors, [])
        self.assertEqual(guardian_exit, -signal.SIGKILL)

        status = fixture.read_cleanup_status(channel)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status["phase"], "stopped")
        self.assertEqual(status["recovery_status"], "completed")
        self.assertEqual(status["owned_compose"], "removed")
        self.assertEqual(status["owned_images"], "removed")
        self.assertEqual(status["private_state"], "removed")
        self.assertFalse((channel / fixture.MEMBER_HANDOFF_FILE).exists())
        self.assertFalse((control / fixture.CONTROL_FILE).exists())
        for resource, before in owner_resources.items():
            self.assertEqual(
                owner_docker.project_resource_ids(resource, owner_identity.project_name),
                before,
            )
        owner_docker.run(
            ["image", "inspect", "--format", "{{.Id}}", image],
            label="shared test image preservation check",
            timeout=10,
            capture_stdout=True,
        )


class HiddenBootstrapTests(unittest.TestCase):
    def test_getpass_passwords_are_written_only_to_a_hidden_pty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            admin_secret = secrets.token_urlsafe(32)
            command = [
                sys.executable,
                "-c",
                "import getpass, sys; "
                "one = getpass.getpass('New administrator password: '); "
                "two = getpass.getpass('Confirm new administrator password: '); "
                "print('private=' + one); sys.exit(0 if one == two else 9)",
            ]
            captured = io.StringIO()
            with patch("sys.stdout", captured), patch("sys.stderr", captured):
                fixture.run_hidden_password_prompts(
                    command,
                    prompts=fixture.ADMIN_PASSWORD_PROMPTS,
                    answers=(admin_secret, admin_secret),
                    cwd=root,
                    environment={"PATH": os.environ.get("PATH", os.defpath), "HOME": temporary},
                    timeout=10,
                )

            self.assertFalse(admin_secret in " ".join(command), "admin password must stay off argv")
            self.assertFalse(admin_secret in captured.getvalue(), "PTY output must remain private")

    def test_failed_prompt_contract_does_not_reveal_the_admin_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            admin_secret = secrets.token_urlsafe(32)
            with self.assertRaises(fixture.FixtureError) as caught:
                fixture.run_hidden_password_prompts(
                    [sys.executable, "-c", "print('early failure')"],
                    prompts=fixture.ADMIN_PASSWORD_PROMPTS,
                    answers=(admin_secret, admin_secret),
                    cwd=Path(temporary),
                    environment={"PATH": os.environ.get("PATH", os.defpath), "HOME": temporary},
                    timeout=5,
                )
            self.assertFalse(
                admin_secret in str(caught.exception),
                "bootstrap errors must not expose the admin password",
            )

    def test_bootstrap_failure_uses_only_a_bounded_redacted_diagnostic_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            admin_secret = secrets.token_urlsafe(32)
            database_secret = secrets.token_hex(32)
            provider_secret = secrets.token_hex(32)
            diagnostic_text = (
                "Username must be accepted "
                f"{admin_secret} {database_secret} {provider_secret}"
            )
            command = [
                sys.executable,
                "-c",
                "import getpass, os, sys; "
                "getpass.getpass('New administrator password: '); "
                "getpass.getpass('Confirm new administrator password: '); "
                "print(os.environ['DIAGNOSTIC_TEXT'], file=sys.stderr); sys.exit(1)",
            ]
            environment = {
                "PATH": os.environ.get("PATH", os.defpath),
                "HOME": temporary,
                "DIAGNOSTIC_TEXT": diagnostic_text,
            }

            with self.assertRaises(fixture.FixtureError) as caught:
                fixture.run_hidden_password_prompts(
                    command,
                    prompts=fixture.ADMIN_PASSWORD_PROMPTS,
                    answers=(admin_secret, admin_secret),
                    cwd=Path(temporary),
                    environment=environment,
                    timeout=10,
                )

            message = str(caught.exception)
            self.assertIn("diagnostic=username-validation", message)
            self.assertIn("terminal output suppressed", message)
            for secret in (admin_secret, database_secret, provider_secret, diagnostic_text):
                self.assertNotIn(secret, message)
            self.assertEqual(
                fixture.classify_bootstrap_diagnostic(
                    b"x" * fixture.MAX_BOOTSTRAP_DIAGNOSTIC_BYTES + b"Username must be"
                ),
                "unclassified",
                "diagnostics beyond the fixed capture bound must not be scanned",
            )

            database_error_text = (
                "Fixture database diagnostic: class=integrity sqlstate=23505 "
                "schema=missing-bootstrap_state migration=0002 "
                f"{admin_secret} {database_secret} {provider_secret}"
            )
            safe_database_code = fixture.classify_bootstrap_diagnostic(
                database_error_text.encode("utf-8")
            )
            self.assertEqual(
                safe_database_code,
                "database-integrity-23505-missing-bootstrap-state-migration-0002",
            )
            for secret in (admin_secret, database_secret, provider_secret):
                self.assertNotIn(secret, safe_database_code)


class SupervisorPidfdVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pidfd = 37
        self.start_time = 12345
        self.effective_uid = os.geteuid()
        self.handoff_directory = Path("/fixture-test-handoff")

        patchers = (
            patch.object(fixture, "APPROVED_HANDOFF_DIRECTORY", self.handoff_directory),
            patch.object(fixture.os, "pidfd_open", return_value=self.pidfd, create=True),
            patch.object(fixture.signal, "pidfd_send_signal", create=True),
            patch.object(fixture, "_proc_start_time", return_value=self.start_time),
            patch.object(Path, "read_bytes"),
            patch.object(fixture.select, "select", return_value=([], [], [])),
            patch.object(fixture.os, "close"),
        )
        (
            self.approved_handoff_patch,
            self.pidfd_open,
            self.pidfd_send_signal,
            self.proc_start_time,
            self.read_cmdline,
            self.select_result,
            self.close_pidfd,
        ) = tuple(patcher.start() for patcher in patchers)
        for patcher in patchers:
            self.addCleanup(patcher.stop)

    def _supervisor_arguments(
        self,
        *,
        script: str | None = None,
        handoff: str | None = None,
        lifetime: str | None = None,
    ) -> list[str]:
        return [
            sys.executable,
            script or str(Path(fixture.__file__).resolve()),
            "_supervise",
            "--handoff-dir",
            handoff or str(self.handoff_directory),
            "--lifetime-minutes",
            lifetime or str(fixture.DEFAULT_LIFETIME_MINUTES),
        ]

    def _verify(self, arguments: list[str], *, record_start_time: int | None = None) -> int | None:
        self.read_cmdline.return_value = b"\0".join(
            os.fsencode(argument) for argument in arguments
        ) + b"\0"
        return fixture._open_verified_supervisor_pidfd(
            {
                "pid": os.getpid(),
                "start_time": (
                    self.start_time if record_start_time is None else record_start_time
                ),
            }
        )

    def test_accepts_committed_and_candidate_supervisors_without_closing_pidfd(self) -> None:
        cases = (
            ("committed", self._supervisor_arguments()),
            (
                "candidate",
                self._supervisor_arguments()
                + ["--candidate-fingerprint", "b" * 64],
            ),
            (
                "imp013 candidate",
                self._supervisor_arguments()
                + ["--imp013-candidate-fingerprint", "c" * 64],
            ),
        )
        for name, arguments in cases:
            with self.subTest(name=name):
                self.close_pidfd.reset_mock()
                self.assertEqual(self._verify(arguments), self.pidfd)
                self.close_pidfd.assert_not_called()

    def test_accepts_imp007_only_with_its_distinct_sha256_supervisor_argument(self) -> None:
        arguments = self._supervisor_arguments() + [
            "--imp007-candidate-fingerprint",
            "d" * 64,
        ]

        self.assertEqual(self._verify(arguments), self.pidfd)
        self.close_pidfd.assert_not_called()

    def test_rejects_forged_or_malformed_supervisor_arguments(self) -> None:
        base = self._supervisor_arguments()
        fingerprint = "b" * 64
        wrong_command = list(base)
        wrong_command[2] = "_guardian"
        cases = (
            ("extra argument", base + ["unexpected"]),
            ("missing fingerprint value", base + ["--candidate-fingerprint"]),
            ("forged candidate option", base + ["--other-option", fingerprint]),
            ("uppercase fingerprint", base + ["--candidate-fingerprint", "A" * 64]),
            ("short fingerprint", base + ["--candidate-fingerprint", "b" * 63]),
            ("long fingerprint", base + ["--candidate-fingerprint", "b" * 65]),
            (
                "path-like fingerprint",
                base + ["--candidate-fingerprint", "../" + "b" * 61],
            ),
            (
                "forged script path",
                self._supervisor_arguments(script=f"{Path(fixture.__file__).resolve()}.other"),
            ),
            ("forged handoff path", self._supervisor_arguments(handoff="/other-handoff")),
            (
                "out-of-range lifetime",
                self._supervisor_arguments(lifetime=str(fixture.MAX_LIFETIME_MINUTES + 1)),
            ),
            ("malformed lifetime", self._supervisor_arguments(lifetime="120x")),
            ("wrong process mode", wrong_command),
        )

        for name, arguments in cases:
            with self.subTest(name=name):
                self.close_pidfd.reset_mock()
                with self.assertRaises(fixture.FixtureError):
                    self._verify(arguments)
                self.close_pidfd.assert_called_once_with(self.pidfd)

    def test_retains_supervisor_owner_and_start_time_checks(self) -> None:
        arguments = self._supervisor_arguments()

        self.close_pidfd.reset_mock()
        with patch.object(fixture.os, "geteuid", return_value=self.effective_uid + 1):
            with self.assertRaisesRegex(fixture.FixtureError, "could not be verified"):
                self._verify(arguments)
        self.close_pidfd.assert_called_once_with(self.pidfd)

        self.close_pidfd.reset_mock()
        with self.assertRaisesRegex(fixture.FixtureError, "could not be verified"):
            self._verify(arguments, record_start_time=self.start_time + 1)
        self.close_pidfd.assert_called_once_with(self.pidfd)


class UnattendedLifecycleTests(unittest.TestCase):
    def test_supervisor_survives_parent_pty_stdin_eof_after_handoff_until_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            program = "\n".join(
                (
                    "import sys",
                    "from pathlib import Path",
                    "import local_browser_fixture as fixture",
                    "supervisor = fixture.FixtureSupervisor(",
                    "    Path('.'), output=sys.stdout, input_stream=sys.stdin,",
                    "    lifetime_minutes=120,",
                    ")",
                    "supervisor._prepare = lambda: None",
                    "def publish_handoff():",
                    "    supervisor.handoff_published = True",
                    "    supervisor._say('HANDOFF_READY')",
                    "supervisor._publish_handoff = publish_handoff",
                    "supervisor._cleanup = lambda: []",
                    "raise SystemExit(supervisor.run())",
                )
            )
            environment = {
                "PATH": os.environ.get("PATH", os.defpath),
                "HOME": temporary,
                "PYTHONPATH": str(Path(fixture.__file__).resolve().parent),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            master_fd, slave_fd = pty.openpty()
            process: subprocess.Popen[bytes] | None = None
            try:
                process = subprocess.Popen(
                    [sys.executable, "-c", program],
                    cwd=temporary,
                    env=environment,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    close_fds=True,
                    start_new_session=True,
                )
                os.close(slave_fd)
                slave_fd = -1

                deadline = time.monotonic() + 5
                output = bytearray()
                while b"HANDOFF_READY" not in output and time.monotonic() < deadline:
                    ready, _, _ = select.select([master_fd], [], [], 0.2)
                    if ready:
                        output.extend(os.read(master_fd, 4096))
                    if process.poll() is not None:
                        break

                self.assertIn(b"HANDOFF_READY", output)
                self.assertIsNone(process.poll(), "the supervisor exited before PTY closure")

                # Ctrl-D is the PTY's canonical EOF marker while keeping its
                # output side open, matching a runner that closes stdin but still
                # collects the private handoff log.
                os.write(master_fd, b"\x04")
                time.sleep(0.2)
                self.assertIsNone(
                    process.poll(),
                    "PTY stdin EOF must not stop the fixture before handoff review",
                )

                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5), 0)
            finally:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                if slave_fd >= 0:
                    os.close(slave_fd)
                if master_fd >= 0:
                    os.close(master_fd)


class PrivateHandoffChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.channel = self.root / "handoff"
        self.channel.mkdir(mode=0o700)
        self.identity = fixture.generate_identity(18478)
        self.member = self.identity.members[0]

    @staticmethod
    def completed_status() -> dict[str, object]:
        status = fixture.initial_cleanup_status()
        status.update(
            phase="stopped",
            exit_code=0,
            member_login="removed",
            member_accounts="verified",
            owned_compose="removed",
            owned_images="removed",
            private_state="removed",
        )
        return status

    def test_handoff_and_status_are_atomic_private_allowlisted_records(self) -> None:
        fixture.prepare_handoff_channel(self.channel, approved_directory=self.channel)
        fixture.write_cleanup_status(self.channel, fixture.initial_cleanup_status())
        fixture.write_member_handoff(
            self.channel,
            self.member.username,
            str(self.member.password),
        )
        ready_status = fixture.initial_cleanup_status()
        ready_status.update(
            phase="ready",
            member_login="published",
            member_accounts="pending",
            owned_compose="pending",
            owned_images="pending",
            private_state="pending",
        )
        fixture.write_cleanup_status(self.channel, ready_status)

        handoff_path = self.channel / fixture.MEMBER_HANDOFF_FILE
        status_path = self.channel / fixture.CLEANUP_STATUS_FILE
        handoff_text = handoff_path.read_text(encoding="ascii")
        status_text = status_path.read_text(encoding="ascii")
        self.assertEqual(stat.S_IMODE(handoff_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(status_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.channel.stat().st_mode), 0o700)
        self.assertEqual(
            json.loads(handoff_text),
            {"username": self.member.username, "password": self.member.password},
        )
        self.assertEqual(set(json.loads(status_text)), fixture.CHANNEL_STATUS_FIELDS)
        self.assertEqual(
            {path.name for path in self.channel.iterdir()},
            {fixture.MEMBER_HANDOFF_FILE, fixture.CLEANUP_STATUS_FILE},
        )
        for value in (
            self.identity.admin_password,
            self.identity.postgres_password,
            self.identity.app_password,
            self.identity.rate_limit_key,
            self.identity.origin,
            "compose.env",
            "docker compose",
        ):
            self.assertNotIn(str(value), handoff_text + status_text)

    def test_channel_rejects_permissive_directories_and_symlink_targets(self) -> None:
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_approved_handoff_directory(self.channel)

        self.channel.chmod(0o755)
        with self.assertRaises(fixture.FixtureError):
            fixture.prepare_handoff_channel(self.channel, approved_directory=self.channel)
        self.channel.chmod(0o700)

        outside = self.root / "outside.txt"
        outside.write_text("keep", encoding="ascii")
        (self.channel / fixture.MEMBER_HANDOFF_FILE).symlink_to(outside)
        with self.assertRaises(fixture.FixtureError):
            fixture.write_member_handoff(
                self.channel,
                self.member.username,
                str(self.member.password),
            )
        self.assertEqual(outside.read_text(encoding="ascii"), "keep")

    def test_atomic_failure_leaves_no_partial_login_or_temporary_file(self) -> None:
        with patch("local_browser_fixture.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(fixture.FixtureError):
                fixture.write_member_handoff(
                    self.channel,
                    self.member.username,
                    str(self.member.password),
                )
        self.assertEqual(list(self.channel.iterdir()), [])

    def test_two_sequential_runs_require_verified_cleanup_and_fresh_member_logins(self) -> None:
        fixture.prepare_handoff_channel(self.channel, approved_directory=self.channel)
        fixture.write_cleanup_status(self.channel, fixture.initial_cleanup_status())
        first_password = str(self.member.password)
        fixture.write_member_handoff(self.channel, self.member.username, first_password)
        self.assertTrue(
            fixture.remove_member_handoff(self.channel, self.member.username, first_password)
        )
        fixture.write_cleanup_status(self.channel, self.completed_status())

        fixture.prepare_handoff_channel(self.channel, approved_directory=self.channel)
        fixture.write_cleanup_status(self.channel, fixture.initial_cleanup_status())
        second = fixture.generate_identity(18479).members[0]
        self.assertNotEqual(second.username, self.member.username)
        self.assertNotEqual(second.password, self.member.password)
        fixture.write_member_handoff(self.channel, second.username, str(second.password))
        content = (self.channel / fixture.MEMBER_HANDOFF_FILE).read_text(encoding="ascii")
        self.assertNotIn(first_password, content)
        self.assertEqual(
            json.loads(content),
            {"username": second.username, "password": second.password},
        )

    def test_next_run_is_blocked_by_leftover_login_or_unverified_owned_resources(self) -> None:
        fixture.write_cleanup_status(self.channel, self.completed_status())
        fixture.write_member_handoff(
            self.channel,
            self.member.username,
            str(self.member.password),
        )
        with self.assertRaises(fixture.FixtureError):
            fixture.prepare_handoff_channel(self.channel, approved_directory=self.channel)
        fixture.remove_member_handoff(
            self.channel,
            self.member.username,
            str(self.member.password),
        )

        incomplete = self.completed_status()
        incomplete["owned_compose"] = "not-verified"
        fixture.write_cleanup_status(self.channel, incomplete)
        with self.assertRaises(fixture.FixtureError):
            fixture.prepare_handoff_channel(self.channel, approved_directory=self.channel)

    def test_stop_record_cannot_signal_an_unrelated_same_user_process(self) -> None:
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            self.skipTest("pidfd signaling is unavailable on this host")
        control = self.root / "control"
        control.mkdir(mode=0o700)
        fixture._write_control_record(
            control,
            {"pid": os.getpid(), "start_time": fixture._proc_start_time(os.getpid())},
        )

        with self.assertRaises(fixture.FixtureError):
            fixture._signal_supervisor(fixture._read_control_record(control) or {})
        os.kill(os.getpid(), 0)

    def test_invalid_status_values_and_extra_fields_are_rejected(self) -> None:
        invalid = self.completed_status()
        invalid["handoff_url"] = self.identity.origin
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_cleanup_status(invalid)

        invalid = self.completed_status()
        invalid["phase"] = []
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_cleanup_status(invalid)

    def test_previous_clean_status_without_recovery_field_remains_readable(self) -> None:
        legacy = self.completed_status()
        legacy.pop("recovery_status")
        status_file = self.channel / fixture.CLEANUP_STATUS_FILE
        status_file.write_text(json.dumps(legacy) + "\n", encoding="ascii")
        status_file.chmod(0o600)

        status = fixture.read_cleanup_status(self.channel)

        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status["recovery_status"], "not-needed")
        self.assertTrue(fixture._clean_previous_run(status))

    def test_stop_reports_failed_setup_or_sigkill_despite_verified_resource_cleanup(self) -> None:
        control = self.root / "control"
        control.mkdir(mode=0o700)
        with (
            patch.object(fixture, "APPROVED_HANDOFF_DIRECTORY", self.channel),
            patch("local_browser_fixture._ensure_control_directory", return_value=control),
        ):
            for recovery_status in ("not-needed", "completed"):
                with self.subTest(recovery_status=recovery_status):
                    failed = self.completed_status()
                    failed.update(exit_code=1, recovery_status=recovery_status)
                    fixture.write_cleanup_status(self.channel, failed)
                    fixture._write_control_record(
                        control,
                        {"pid": os.getpid(), "start_time": fixture._proc_start_time(os.getpid())},
                    )
                    self.assertTrue(fixture._clean_previous_run(failed))
                    messages = io.StringIO()
                    with redirect_stderr(messages):
                        self.assertEqual(fixture.stop_unattended(self.channel), 1)
                    self.assertIn("setup or review failed", messages.getvalue())
                    self.assertIsNone(fixture._read_control_record(control))
                    # Recover means resource recovery, not successful setup/review.
                    self.assertEqual(fixture.recover_unattended(self.channel), 0)
                    recovered = fixture.read_cleanup_status(self.channel)
                    self.assertIsNotNone(recovered)
                    assert recovered is not None
                    self.assertEqual(recovered["exit_code"], 1)

            fixture.write_cleanup_status(self.channel, self.completed_status())
            self.assertEqual(fixture.stop_unattended(self.channel), 0)

    def test_guardian_fallback_removes_login_and_marks_unverified_owned_resources(self) -> None:
        ready = fixture.initial_cleanup_status()
        ready.update(
            phase="ready",
            member_login="published",
            member_accounts="pending",
            owned_compose="pending",
            owned_images="pending",
            private_state="pending",
        )
        fixture.write_cleanup_status(self.channel, ready)
        fixture.write_member_handoff(
            self.channel,
            self.member.username,
            str(self.member.password),
        )

        fixture._write_guardian_failure_status(self.channel)

        status = fixture.read_cleanup_status(self.channel)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status["phase"], "stopped")
        self.assertEqual(status["exit_code"], 1)
        self.assertEqual(status["member_login"], "removed")
        self.assertEqual(status["member_accounts"], "not-verified")
        self.assertEqual(status["owned_compose"], "not-verified")
        self.assertEqual(status["owned_images"], "not-verified")
        self.assertEqual(status["private_state"], "retained-for-recovery")
        self.assertFalse((self.channel / fixture.MEMBER_HANDOFF_FILE).exists())


class CandidateCliTests(unittest.TestCase):
    def test_candidate_preflight_and_fingerprint_opt_in_are_explicit(self) -> None:
        fingerprint = "a" * 64
        self.assertEqual(
            fixture._parse_args(["candidate-preflight"]).command,
            "candidate-preflight",
        )
        self.assertEqual(
            fixture._parse_args(["imp013-candidate-preflight"]).command,
            "imp013-candidate-preflight",
        )
        committed_start = fixture._parse_args(["start"])
        self.assertIsNone(committed_start.candidate_fingerprint)
        self.assertIsNone(committed_start.imp013_candidate_fingerprint)
        committed_launch = fixture._parse_args(["launch"])
        self.assertIsNone(committed_launch.candidate_fingerprint)
        self.assertIsNone(committed_launch.imp013_candidate_fingerprint)

        candidate_start = fixture._parse_args(
            ["start", "--candidate-fingerprint", fingerprint]
        )
        candidate_launch = fixture._parse_args(
            ["launch", "--candidate-fingerprint", fingerprint]
        )
        self.assertEqual(candidate_start.candidate_fingerprint, fingerprint)
        self.assertEqual(candidate_launch.candidate_fingerprint, fingerprint)
        imp013_start = fixture._parse_args(
            ["start", "--imp013-candidate-fingerprint", fingerprint]
        )
        imp013_launch = fixture._parse_args(
            ["launch", "--imp013-candidate-fingerprint", fingerprint]
        )
        self.assertEqual(imp013_start.imp013_candidate_fingerprint, fingerprint)
        self.assertEqual(imp013_launch.imp013_candidate_fingerprint, fingerprint)
        self.assertEqual(
            fixture._candidate_selection(imp013_launch),
            (fingerprint, "imp013"),
        )
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fixture._parse_args(
                [
                    "launch",
                    "--candidate-fingerprint",
                    fingerprint,
                    "--imp013-candidate-fingerprint",
                    fingerprint,
                ]
            )

    def test_imp007_uses_a_separate_preflight_and_private_launch_fingerprint(self) -> None:
        fingerprint = "d" * 64
        self.assertEqual(
            fixture._parse_args(["imp007-candidate-preflight"]).command,
            "imp007-candidate-preflight",
        )
        launch = fixture._parse_args(
            ["launch", "--imp007-candidate-fingerprint", fingerprint]
        )
        self.assertEqual(launch.imp007_candidate_fingerprint, fingerprint)
        self.assertEqual(fixture._candidate_selection(launch), (fingerprint, "imp007"))
        supervisor = fixture.FixtureSupervisor(
            Path("/fixture-test"),
            candidate_fingerprint=fingerprint,
            candidate_variant="imp007",
        )
        self.assertIs(supervisor._candidate_policy(), fixture.IMP007_CANDIDATE_PREVIEW_POLICY)
        with self.assertRaisesRegex(fixture.FixtureError, "explicit opt-in"):
            fixture.FixtureSupervisor(Path("/fixture-test"), candidate_variant="imp007")

        guardian = fixture._parse_args(
            [
                "_guardian",
                "--handoff-dir",
                "/tmp/review-handoff",
                "--lifetime-minutes",
                "30",
                "--lock-fd",
                "9",
                "--imp007-candidate-fingerprint",
                fingerprint,
            ]
        )
        self.assertEqual(fixture._candidate_selection(guardian), (fingerprint, "imp007"))
        supervisor = fixture._parse_args(
            [
                "_supervise",
                "--handoff-dir",
                "/tmp/review-handoff",
                "--lifetime-minutes",
                "30",
                "--imp007-candidate-fingerprint",
                fingerprint,
            ]
        )
        self.assertEqual(fixture._candidate_selection(supervisor), (fingerprint, "imp007"))

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fixture._parse_args(["start", "--imp007-candidate-fingerprint", fingerprint])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fixture._parse_args(
                [
                    "launch",
                    "--candidate-fingerprint",
                    fingerprint,
                    "--imp007-candidate-fingerprint",
                    fingerprint,
                ]
            )
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fixture._parse_args(["launch", "--imp007-candidate-fingerprint", "A" * 64])

    def test_candidate_fingerprint_rejects_malformed_values(self) -> None:
        for value in ("A" * 64, "0" * 63, "0" * 65, "../" + "0" * 61):
            with self.subTest(value=value), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    fixture._parse_args(["launch", "--candidate-fingerprint", value])


class PtyGuardianTests(unittest.TestCase):
    def test_guardian_forwards_only_a_loopback_ready_event_and_exit_code(self) -> None:
        ready: list[str] = []
        spawned: list[int] = []
        child_program = (
            "import os, sys; "
            "assert all(os.isatty(fd) for fd in (0, 1, 2)); "
            "print('discarded-supervisor-output'); "
            "print('FIXTURE_HANDOFF_READY http://127.23.45.67:18473')"
        )
        captured = io.StringIO()
        with redirect_stdout(captured), redirect_stderr(captured):
            result = fixture.run_under_pty(
                [sys.executable, "-c", child_program],
                on_spawn=lambda process: spawned.append(process.pid),
                on_ready=ready.append,
                cwd=Path.cwd(),
            )

        self.assertEqual(result, 0)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(ready, ["http://127.23.45.67:18473"])
        self.assertNotIn("discarded-supervisor-output", captured.getvalue())
        self.assertIsNone(
            fixture._validated_ready_origin(b"FIXTURE_HANDOFF_READY http://10.0.0.1:80")
        )

    def test_guardian_reports_a_child_failure_without_forwarding_its_output(self) -> None:
        ready: list[str] = []
        child_program = (
            "import os, sys; "
            "assert os.isatty(0) and os.isatty(1) and os.isatty(2); "
            "print('FIXTURE_HANDOFF_READY http://127.0.0.1:18474'); "
            "sys.exit(7)"
        )
        result = fixture.run_under_pty(
            [sys.executable, "-c", child_program],
            on_spawn=lambda _process: None,
            on_ready=ready.append,
            cwd=Path.cwd(),
        )

        self.assertEqual(result, 7)
        self.assertEqual(ready, ["http://127.0.0.1:18474"])


class ApiClientTests(unittest.TestCase):
    def test_client_performs_normal_csrf_login_and_keeps_admin_denial_status(self) -> None:
        received: dict[str, str] = {}
        user_id = str(uuid.uuid4())
        prelogin_csrf = secrets.token_urlsafe(32)
        session_csrf = secrets.token_urlsafe(32)
        unrelated_local_session = secrets.token_urlsafe(32)
        synthetic_session = secrets.token_urlsafe(32)
        member_username = f"reviewmember{secrets.token_hex(8)}"

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_arguments: object) -> None:
                return

            def send_json(self, status: int, payload: object) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path == "/api/auth/csrf":
                    received["prelogin_cookie"] = self.headers.get("Cookie", "")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Set-Cookie", f"impostr_csrf={prelogin_csrf}; Path=/")
                    body = json.dumps({"csrf_token": prelogin_csrf}).encode("utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/admin/users?limit=100&offset=0":
                    received["member_cookie"] = self.headers.get("Cookie", "")
                    self.send_json(403, {"detail": "Administrator access required"})
                else:
                    self.send_json(404, {"detail": "Not found"})

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(body.decode("utf-8"))
                received["origin"] = self.headers.get("Origin", "")
                received["csrf_header"] = self.headers.get("X-CSRF-Token", "")
                received["cookie"] = self.headers.get("Cookie", "")
                received["member_password"] = payload.get("password", "")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header(
                    "Set-Cookie",
                    f"impostr_session={synthetic_session}; Path=/; HttpOnly",
                )
                self.send_header("Set-Cookie", f"impostr_csrf={session_csrf}; Path=/")
                response_body = json.dumps(
                    {
                        "user": {
                            "id": user_id,
                            "username": payload.get("username"),
                            "role": "user",
                            "is_active": True,
                        },
                        "csrf_token": session_csrf,
                    }
                ).encode("utf-8")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

            def do_PUT(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                received["put_origin"] = self.headers.get("Origin", "")
                received["put_csrf_header"] = self.headers.get("X-CSRF-Token", "")
                received["put_body"] = body.decode("utf-8")
                self.send_json(200, {"saved": True})

        host = fixture.choose_loopback_host()
        server = ThreadingHTTPServer((host, 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f"http://{host}:{server.server_address[1]}"
        member_password = secrets.token_urlsafe(32)
        client = fixture.ApiClient(origin)
        client.cookies.set_cookie(
            Cookie(
                version=0,
                name="impostr_session",
                value=unrelated_local_session,
                port=None,
                port_specified=False,
                domain="127.0.0.1",
                domain_specified=False,
                domain_initial_dot=False,
                path="/",
                path_specified=True,
                secure=False,
                expires=None,
                discard=True,
                comment=None,
                comment_url=None,
                rest={"HttpOnly": None},
                rfc2109=False,
            )
        )

        user = client.login(member_username, member_password, expected_role="user")

        self.assertEqual(user["id"], user_id)
        self.assertEqual(client.admin_users_status(), 403)
        put_response = client.request(
            "PUT",
            "/api/synthetic-document",
            body={"content": "synthetic"},
            csrf_token=client.csrf_token,
        )
        self.assertEqual(put_response.status, 200)
        self.assertEqual(received["put_origin"], origin)
        self.assertEqual(received["put_csrf_header"], session_csrf)
        self.assertEqual(received["put_body"], '{"content":"synthetic"}')
        self.assertEqual(received["origin"], origin)
        self.assertTrue(received["csrf_header"] == prelogin_csrf, "login CSRF token was not sent")
        self.assertTrue(
            f"impostr_csrf={prelogin_csrf}" in received["cookie"],
            "pre-login CSRF cookie was not sent",
        )
        self.assertFalse(
            unrelated_local_session in received["prelogin_cookie"],
            "a cookie from another local origin must not be sent",
        )
        self.assertTrue(
            f"impostr_session={synthetic_session}" in received["member_cookie"],
            "the authenticated member cookie was not retained for same-origin requests",
        )
        self.assertTrue(
            received["member_password"] == member_password,
            "the synthetic member login body was not preserved",
        )
        client.clear_cookies()

    def test_login_status_verification_uses_normal_csrf_flow_for_401_denial(self) -> None:
        received: dict[str, str] = {}
        prelogin_csrf = secrets.token_urlsafe(32)
        username = f"reviewmember{secrets.token_hex(8)}"
        password = secrets.token_urlsafe(32)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_arguments: object) -> None:
                return

            def do_GET(self) -> None:
                if self.path != "/api/auth/csrf":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", f"impostr_csrf={prelogin_csrf}; Path=/")
                body = json.dumps({"csrf_token": prelogin_csrf}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(body.decode("utf-8"))
                received["origin"] = self.headers.get("Origin", "")
                received["csrf"] = self.headers.get("X-CSRF-Token", "")
                received["cookie"] = self.headers.get("Cookie", "")
                received["username"] = payload.get("username", "")
                received["password"] = payload.get("password", "")
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                response_body = json.dumps({"detail": "Invalid username or password"}).encode()
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

        host = fixture.choose_loopback_host()
        server = ThreadingHTTPServer((host, 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f"http://{host}:{server.server_address[1]}"
        client = fixture.ApiClient(origin)

        status = client.login_status(username, password)

        self.assertEqual(status, 401)
        self.assertEqual(received["origin"], origin)
        self.assertEqual(received["csrf"], prelogin_csrf)
        self.assertIn(f"impostr_csrf={prelogin_csrf}", received["cookie"])
        self.assertEqual(received["username"], username)
        self.assertEqual(received["password"], password)
        client.clear_cookies()


class CleanupTests(unittest.TestCase):
    class FakeCompose:
        def __init__(
            self,
            *,
            fail_down: bool = False,
            fail_account_cleanup: bool = False,
            fail_image_cleanup: bool = False,
            events: list[str] | None = None,
        ) -> None:
            self.fail_down = fail_down
            self.fail_account_cleanup = fail_account_cleanup
            self.fail_image_cleanup = fail_image_cleanup
            self.events = events if events is not None else []
            self.member_ids: list[str] = []
            self.revoked_ids: list[str] = []
            self.down_calls = 0
            self.verify_calls = 0
            self.remove_images_calls = 0

        def command(self, arguments: list[str]) -> list[str]:
            return ["docker", "compose", *arguments]

        def disable_members_and_revoke_sessions(
            self,
            member_ids: list[str],
            user_ids: list[str],
        ) -> int:
            self.events.append("disable-members")
            if self.fail_account_cleanup:
                raise fixture.FixtureError("safe mocked account cleanup failure")
            self.member_ids = list(member_ids)
            self.revoked_ids = list(user_ids)
            return len(member_ids)

        def down(self) -> None:
            self.events.append("down")
            self.down_calls += 1
            if self.fail_down:
                raise fixture.FixtureError("safe mocked failure")

        def verify_project_resources_removed(self) -> None:
            self.events.append("resources-removed")
            self.verify_calls += 1

        def remove_owned_images(self) -> None:
            self.events.append("remove-images")
            self.remove_images_calls += 1
            if self.fail_image_cleanup:
                raise fixture.FixtureError("safe mocked image cleanup failure")

        def verify_project_images_removed(self) -> None:
            self.events.append("images-removed")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fake_api_patch(
        self,
        events: list[str],
        *,
        status_by_username: dict[str, int] | None = None,
    ) -> tuple[object, list[tuple[str, str]]]:
        calls: list[tuple[str, str]] = []
        statuses = status_by_username or {}

        class FakeApiClient:
            def __init__(self, _origin: str) -> None:
                self.username = ""

            def login_status(self, username: str, password: str) -> int:
                self.username = username
                calls.append((username, password))
                events.append(f"login:{username}")
                return statuses.get(username, 401)

            def logout(self) -> None:
                events.append(f"logout:{self.username}")

            def clear_cookies(self) -> None:
                return

        return patch("local_browser_fixture.ApiClient", side_effect=FakeApiClient), calls

    def supervisor(self, state: Path, compose: object, *, owned: bool) -> fixture.FixtureSupervisor:
        supervisor = fixture.FixtureSupervisor(
            self.root,
            output=io.StringIO(),
            input_stream=io.StringIO(),
        )
        supervisor.state_dir = state
        supervisor.compose = compose  # type: ignore[assignment]
        supervisor.project_owned = owned
        identity = fixture.generate_identity(18474)
        identity.admin_user_id = str(uuid.uuid4())
        for member in identity.members:
            member.user_id = str(uuid.uuid4())
        supervisor.identity = identity
        if owned:
            fixture.create_member_recovery_file(state, identity)
        return supervisor

    def test_unowned_collision_never_runs_compose_down(self) -> None:
        state = self.root / "state"
        state.mkdir(mode=0o700)
        compose = self.FakeCompose()
        supervisor = self.supervisor(state, compose, owned=False)

        errors = supervisor._cleanup()

        self.assertEqual(errors, [])
        self.assertEqual(compose.down_calls, 0)
        self.assertEqual(compose.revoked_ids, [])
        self.assertFalse(state.exists())

    def test_owned_cleanup_disables_members_and_checks_denial_before_teardown(self) -> None:
        state = self.root / "owned-state"
        state.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(events=events)
        supervisor = self.supervisor(state, compose, owned=True)
        supervisor.handoff_published = True
        expected_ids = supervisor.identity.user_ids
        expected_member_ids = [member.user_id for member in supervisor.identity.members]
        expected_logins = [
            (member.username, member.password) for member in supervisor.identity.members
        ]
        api_patch, login_calls = self.fake_api_patch(events)

        with api_patch:
            errors = supervisor._cleanup()

        self.assertEqual(errors, [])
        self.assertEqual(compose.revoked_ids, expected_ids)
        self.assertEqual(compose.member_ids, expected_member_ids)
        self.assertEqual(login_calls, expected_logins)
        self.assertEqual(
            events,
            [
                "disable-members",
                *(f"login:{member.username}" for member in supervisor.identity.members),
                "down",
                "resources-removed",
                "remove-images",
                "images-removed",
            ],
        )
        self.assertEqual(compose.down_calls, 1)
        self.assertEqual(compose.verify_calls, 1)
        self.assertEqual(compose.remove_images_calls, 1)
        self.assertFalse(state.exists())
        self.assertFalse(supervisor.project_owned)

    def test_owned_cleanup_records_resource_removal_before_deleting_recovery_state(self) -> None:
        state = self.root / "recorded-clean-state"
        state.mkdir(mode=0o700)
        control = self.root / "control"
        control.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(events=events)
        identity = fixture.generate_identity(18490)
        identity.admin_user_id = str(uuid.uuid4())
        for member in identity.members:
            member.user_id = str(uuid.uuid4())
        fixture.create_member_recovery_file(state, identity)
        fixture._write_control_record(
            control,
            {
                "pid": os.getpid(),
                "start_time": fixture._proc_start_time(os.getpid()),
                "recovery": {
                    "state_dir": str(state),
                    "project_name": identity.project_name,
                    "owned": True,
                    "resources_removed": False,
                },
            },
        )
        supervisor = fixture.FixtureSupervisor(
            self.root,
            output=io.StringIO(),
            input_stream=io.StringIO(),
            control_directory=control,
        )
        supervisor.state_dir = state
        supervisor.compose = compose  # type: ignore[assignment]
        supervisor.project_owned = True
        supervisor.identity = identity
        api_patch, _ = self.fake_api_patch(events)

        with api_patch:
            errors = supervisor._cleanup()

        record = fixture._read_control_record(control)
        self.assertEqual(errors, [])
        self.assertFalse(state.exists())
        self.assertIsNotNone(record)
        assert record is not None
        self.assertTrue(record["recovery"]["resources_removed"])
        self.assertEqual(
            events[-4:],
            ["down", "resources-removed", "remove-images", "images-removed"],
        )

    def test_unrecorded_teardown_keeps_private_recovery_state_for_guardian_retry(self) -> None:
        state = self.root / "unrecorded-clean-state"
        state.mkdir(mode=0o700)
        control = self.root / "control-before-record-failure"
        control.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(events=events)
        identity = fixture.generate_identity(18491)
        identity.admin_user_id = str(uuid.uuid4())
        for member in identity.members:
            member.user_id = str(uuid.uuid4())
        fixture.create_member_recovery_file(state, identity)
        fixture._write_control_record(
            control,
            {
                "pid": os.getpid(),
                "start_time": fixture._proc_start_time(os.getpid()),
                "recovery": {
                    "state_dir": str(state),
                    "project_name": identity.project_name,
                    "owned": True,
                    "resources_removed": False,
                },
            },
        )
        supervisor = fixture.FixtureSupervisor(
            self.root,
            output=io.StringIO(),
            input_stream=io.StringIO(),
            control_directory=control,
        )
        supervisor.state_dir = state
        supervisor.compose = compose  # type: ignore[assignment]
        supervisor.project_owned = True
        supervisor.identity = identity
        api_patch, _ = self.fake_api_patch(events)

        with api_patch, patch(
            "local_browser_fixture._update_control_resources_removed",
            side_effect=fixture.FixtureError("safe mocked recovery-record write failure"),
        ):
            errors = supervisor._cleanup()

        record = fixture._read_control_record(control)
        self.assertIn("Owned teardown could not be durably recorded for recovery.", errors)
        self.assertTrue(state.exists())
        self.assertEqual(supervisor.cleanup_private_state, "retained-for-recovery")
        self.assertFalse(supervisor.project_owned)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertFalse(record["recovery"]["resources_removed"])

    def test_failed_teardown_preserves_private_state_for_safe_manual_recovery(self) -> None:
        state = self.root / "retained-state"
        state.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(fail_down=True, events=events)
        supervisor = self.supervisor(state, compose, owned=True)
        supervisor.handoff_published = True
        privileged_secrets = (
            supervisor.identity.admin_password,
            supervisor.identity.postgres_password,
            supervisor.identity.app_password,
            *(member.password for member in supervisor.identity.members),
        )
        api_patch, _ = self.fake_api_patch(events)

        with api_patch, patch("local_browser_fixture.time.sleep"):
            errors = supervisor._cleanup()

        self.assertIn("Owned Compose teardown could not be verified.", errors)
        self.assertEqual(compose.down_calls, 2)
        first_down = events.index("down")
        self.assertEqual(events[:first_down], [
            "disable-members",
            *(f"login:{member.username}" for member in supervisor.identity.members),
        ])
        self.assertEqual(compose.remove_images_calls, 0)
        self.assertTrue(state.exists())
        self.assertTrue(supervisor.project_owned)
        self.assertIn(str(state), supervisor.output.getvalue())
        for secret in privileged_secrets:
            self.assertFalse(
                str(secret) in supervisor.output.getvalue(),
                "privileged secrets must not appear in cleanup output",
            )

    def test_fault_cleanup_removes_member_handoff_and_publishes_sanitized_status(self) -> None:
        channel = self.root / "handoff"
        channel.mkdir(mode=0o700)
        state = self.root / "owned-state-with-channel"
        state.mkdir(mode=0o700)
        fixture.write_cleanup_status(channel, fixture.initial_cleanup_status())
        events: list[str] = []
        compose = self.FakeCompose(fail_down=True, events=events)
        supervisor = fixture.FixtureSupervisor(
            self.root,
            output=io.StringIO(),
            input_stream=io.StringIO(),
            handoff_directory=channel,
        )
        supervisor.state_dir = state
        supervisor.compose = compose  # type: ignore[assignment]
        supervisor.project_owned = True
        identity = fixture.generate_identity(18480)
        identity.admin_user_id = str(uuid.uuid4())
        for member in identity.members:
            member.user_id = str(uuid.uuid4())
        supervisor.identity = identity
        fixture.create_member_recovery_file(state, identity)
        sensitive_values = (
            identity.admin_username,
            str(identity.admin_password),
            str(identity.postgres_password),
            str(identity.app_password),
            str(identity.rate_limit_key),
            identity.project_name,
            identity.origin,
            str(state),
            str(self.root),
            *(str(member.password) for member in identity.members),
        )
        credential_secrets = (
            str(identity.admin_password),
            str(identity.postgres_password),
            str(identity.app_password),
            str(identity.rate_limit_key),
            *(str(member.password) for member in identity.members),
        )
        api_patch, _ = self.fake_api_patch(events)

        with (
            patch.object(fixture, "APPROVED_HANDOFF_DIRECTORY", channel),
            patch.object(supervisor, "_prepare"),
            patch.object(supervisor, "_wait_for_operator"),
            patch("local_browser_fixture.time.sleep"),
            api_patch,
        ):
            result = supervisor.run()

        status = fixture.read_cleanup_status(channel)
        self.assertEqual(result, 1)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status["phase"], "stopped")
        self.assertEqual(status["exit_code"], 1)
        self.assertEqual(status["member_login"], "removed")
        self.assertEqual(status["member_accounts"], "verified")
        self.assertEqual(status["owned_compose"], "not-verified")
        self.assertEqual(status["owned_images"], "not-verified")
        self.assertEqual(status["private_state"], "retained-for-recovery")
        self.assertFalse((channel / fixture.MEMBER_HANDOFF_FILE).exists())
        self.assertEqual(
            {path.name for path in channel.iterdir()},
            {fixture.CLEANUP_STATUS_FILE},
        )
        status_text = (channel / fixture.CLEANUP_STATUS_FILE).read_text(encoding="ascii")
        for sensitive_value in sensitive_values:
            self.assertNotIn(sensitive_value, status_text)
        output_text = supervisor.output.getvalue()
        for secret in credential_secrets:
            self.assertNotIn(secret, output_text)

    def test_two_successful_supervisor_runs_publish_fresh_members_sequentially(self) -> None:
        channel = self.root / "sequential-handoff"
        channel.mkdir(mode=0o700)
        fixture.prepare_handoff_channel(channel, approved_directory=channel)
        fixture.write_cleanup_status(channel, fixture.initial_cleanup_status())
        member_logins: list[tuple[str, str]] = []

        with patch.object(fixture, "APPROVED_HANDOFF_DIRECTORY", channel):
            for run_number in (1, 2):
                if run_number == 2:
                    fixture.prepare_handoff_channel(channel, approved_directory=channel)
                    fixture.write_cleanup_status(channel, fixture.initial_cleanup_status())

                state = self.root / f"sequential-state-{run_number}"
                state.mkdir(mode=0o700)
                events: list[str] = []
                compose = self.FakeCompose(events=events)
                supervisor = fixture.FixtureSupervisor(
                    self.root,
                    output=io.StringIO(),
                    input_stream=io.StringIO(),
                    handoff_directory=channel,
                )
                identity = fixture.generate_identity(18481 + run_number)
                identity.admin_user_id = str(uuid.uuid4())
                for member in identity.members:
                    member.user_id = str(uuid.uuid4())
                member_logins.append(
                    (identity.members[0].username, str(identity.members[0].password))
                )
                supervisor.state_dir = state
                supervisor.compose = compose  # type: ignore[assignment]
                supervisor.project_owned = True
                supervisor.identity = identity
                fixture.create_member_recovery_file(state, identity)
                api_patch, _ = self.fake_api_patch(events)

                with (
                    api_patch,
                    patch.object(supervisor, "_prepare"),
                    patch.object(supervisor, "_wait_for_operator"),
                ):
                    self.assertEqual(supervisor.run(), 0)

                status = fixture.read_cleanup_status(channel)
                self.assertIsNotNone(status)
                assert status is not None
                self.assertEqual(status["phase"], "stopped")
                self.assertEqual(status["exit_code"], 0)
                self.assertEqual(status["member_login"], "removed")
                self.assertEqual(status["member_accounts"], "verified")
                self.assertEqual(status["owned_compose"], "removed")
                self.assertEqual(status["owned_images"], "removed")
                self.assertEqual(status["private_state"], "removed")
                self.assertFalse((channel / fixture.MEMBER_HANDOFF_FILE).exists())
                self.assertFalse(state.exists())

        first, second = member_logins
        self.assertNotEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])

    def test_created_member_with_unusable_id_and_failed_teardown_keeps_recovery_warning(
        self,
    ) -> None:
        state = self.root / "unconfirmed-member-and-down-failed"
        state.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(fail_down=True, events=events)
        supervisor = self.supervisor(state, compose, owned=True)
        identity = supervisor.identity
        identity.admin_user_id = None
        for member in identity.members:
            member.user_id = None

        admin_user_id = str(uuid.uuid4())
        supervisor.admin_client = fixture.ApiClient(identity.origin)
        supervisor.admin_client.csrf_token = "synthetic-csrf-token"
        supervisor.admin_session_may_be_active = False
        created_member = identity.members[0]
        created_payload = {
            "id": "not-a-uuid",
            "username": created_member.username,
            "role": "user",
            "is_active": True,
        }
        expected_recovery = [
            {"username": member.username, "password": member.password}
            for member in identity.members
        ]

        with (
            patch.object(
                supervisor.admin_client,
                "login",
                return_value={"id": admin_user_id},
            ),
            patch.object(
                supervisor.admin_client,
                "request",
                return_value=fixture.ApiResponse(
                    status=201,
                    payload=created_payload,
                    headers={},
                ),
            ) as create_request,
            patch.object(supervisor.admin_client, "logout"),
        ):
            with self.assertRaisesRegex(fixture.FixtureError, "invalid account identifier"):
                supervisor._provision_and_verify_accounts("unused synthetic admin password")

            create_request.assert_called_once_with(
                "POST",
                "/api/admin/users",
                body={
                    "username": created_member.username,
                    "password": created_member.password,
                    "role": "user",
                },
                csrf_token="synthetic-csrf-token",
            )
            self.assertTrue(created_member.creation_unconfirmed)
            self.assertIsNone(created_member.user_id)
            self.assertFalse(identity.members[1].creation_unconfirmed)

            api_patch, login_calls = self.fake_api_patch(events)
            with api_patch, patch("local_browser_fixture.time.sleep"):
                errors = supervisor._cleanup()

        self.assertIn(
            "Synthetic member deactivation or sign-in denial could not be verified.",
            errors,
        )
        self.assertIn("Owned Compose teardown could not be verified.", errors)
        self.assertEqual(compose.member_ids, [])
        self.assertEqual(compose.revoked_ids, [admin_user_id])
        self.assertEqual(login_calls, [])
        self.assertEqual(compose.down_calls, 2)
        self.assertEqual(compose.remove_images_calls, 0)
        self.assertTrue(state.exists())
        self.assertTrue(supervisor.project_owned)

        recovery_path = state / fixture.MEMBER_RECOVERY_FILE
        self.assertEqual(stat.S_IMODE(recovery_path.stat().st_mode), 0o600)
        self.assertEqual(
            json.loads(recovery_path.read_text(encoding="ascii")),
            expected_recovery,
        )
        output = supervisor.output.getvalue()
        self.assertIn("Treat both generated Member logins", output)
        self.assertIn(str(recovery_path), output)
        for member in expected_recovery:
            self.assertNotIn(str(member["password"]), output)

    def test_malformed_successful_admin_login_and_failed_teardown_do_not_abandon_session(self) -> None:
        for logout_status in (204, 503):
            with self.subTest(logout_status=logout_status):
                state = self.root / f"malformed-admin-{logout_status}"
                state.mkdir(mode=0o700)
                compose = self.FakeCompose(fail_down=True)
                supervisor = self.supervisor(state, compose, owned=True)
                identity = supervisor.identity
                identity.admin_user_id = None
                for member in identity.members:
                    member.user_id = None
                received: list[tuple[str, str]] = []
                prelogin_csrf = secrets.token_urlsafe(24)
                session_csrf = secrets.token_urlsafe(24)
                session_cookie = secrets.token_urlsafe(24)

                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, _format: str, *_arguments: object) -> None:
                        return

                    def send_json(self, status: int, payload: object, cookie: str | None = None) -> None:
                        content = json.dumps(payload).encode("utf-8")
                        self.send_response(status)
                        self.send_header("Content-Type", "application/json")
                        if cookie is not None:
                            self.send_header("Set-Cookie", cookie)
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)

                    def do_GET(self) -> None:
                        if self.path == "/api/auth/csrf":
                            self.send_json(
                                200,
                                {"csrf_token": prelogin_csrf},
                                f"impostr_csrf={prelogin_csrf}; Path=/",
                            )
                        else:
                            self.send_json(404, {})

                    def do_POST(self) -> None:
                        received.append((self.path, self.headers.get("Cookie", "")))
                        if self.path == "/api/auth/login":
                            self.send_json(
                                200,
                                {
                                    "user": {
                                        "id": "not-a-uuid",
                                        "username": identity.admin_username,
                                        "role": "admin",
                                    },
                                    "csrf_token": session_csrf,
                                },
                                f"impostr_session={session_cookie}; Path=/; HttpOnly",
                            )
                        elif self.path == "/api/auth/logout":
                            self.send_json(logout_status, {})
                        else:
                            self.send_json(404, {})

                host = fixture.choose_loopback_host()
                server = ThreadingHTTPServer((host, 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                self.addCleanup(thread.join, 5)
                self.addCleanup(server.server_close)
                self.addCleanup(server.shutdown)
                identity.origin = f"http://{host}:{server.server_address[1]}"
                client = fixture.ApiClient(identity.origin)
                supervisor.admin_client = client
                supervisor.api_clients.append(client)
                admin_password = identity.admin_password
                self.assertIsNotNone(admin_password)

                with self.assertRaisesRegex(fixture.FixtureError, "invalid account identifier"):
                    supervisor._provision_and_verify_accounts(str(admin_password))
                with patch("local_browser_fixture.time.sleep"):
                    errors = supervisor._cleanup()

                self.assertEqual(received[0][0], "/api/auth/login")
                self.assertEqual(received[1][0], "/api/auth/logout")
                self.assertIn(f"impostr_session={session_cookie}", received[1][1])
                self.assertEqual(len(received), 2)
                self.assertEqual(compose.down_calls, 2)
                self.assertIn("Owned Compose teardown could not be verified.", errors)
                if logout_status != 204:
                    self.assertIn(
                        "Administrator logout could not be confirmed during cleanup.", errors
                    )
                    self.assertIn("administrator session as live", supervisor.output.getvalue())
                self.assertTrue(state.exists())
                self.assertTrue(supervisor.project_owned)
                self.assertEqual(
                    stat.S_IMODE((state / fixture.MEMBER_RECOVERY_FILE).stat().st_mode),
                    0o600,
                )
                self.assertNotIn(str(admin_password), supervisor.output.getvalue())
                self.assertNotIn(session_cookie, supervisor.output.getvalue())

    def test_unverified_member_denial_still_destroys_only_the_owned_stack(self) -> None:
        state = self.root / "denial-not-proved"
        state.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(events=events)
        supervisor = self.supervisor(state, compose, owned=True)
        supervisor.handoff_published = True
        second_username = supervisor.identity.members[1].username
        api_patch, _ = self.fake_api_patch(
            events,
            status_by_username={second_username: 200},
        )

        with api_patch:
            errors = supervisor._cleanup()

        self.assertTrue(any("deactivation or sign-in denial" in error for error in errors))
        self.assertNotIn("Owned Compose teardown could not be verified.", errors)
        self.assertEqual(compose.down_calls, 1)
        self.assertEqual(compose.remove_images_calls, 1)
        self.assertFalse(state.exists())
        self.assertFalse(supervisor.project_owned)
        self.assertEqual(
            events,
            [
                "disable-members",
                f"login:{supervisor.identity.members[0].username}",
                f"login:{second_username}",
                f"logout:{second_username}",
                "down",
                "resources-removed",
                "remove-images",
                "images-removed",
            ],
        )

    def test_account_deactivation_failure_still_destroys_owned_stack(self) -> None:
        state = self.root / "disable-failed"
        state.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(fail_account_cleanup=True, events=events)
        supervisor = self.supervisor(state, compose, owned=True)
        supervisor.handoff_published = True
        api_patch, login_calls = self.fake_api_patch(events)

        with api_patch:
            errors = supervisor._cleanup()

        self.assertTrue(any("deactivation or sign-in denial" in error for error in errors))
        self.assertEqual(compose.down_calls, 1)
        self.assertEqual(login_calls, [])
        self.assertEqual(
            events,
            ["disable-members", "down", "resources-removed", "remove-images", "images-removed"],
        )
        self.assertFalse(state.exists())

    def test_unverified_denial_exits_nonzero_even_after_owned_volume_removal(self) -> None:
        state = self.root / "failed-proof-cleaned-stack"
        state.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(fail_account_cleanup=True, events=events)
        supervisor = self.supervisor(state, compose, owned=True)
        supervisor.handoff_published = True
        api_patch, _ = self.fake_api_patch(events)

        with (
            api_patch,
            patch.object(supervisor, "_prepare"),
            patch.object(supervisor, "_publish_handoff"),
            patch.object(supervisor, "_wait_for_operator"),
        ):
            result = supervisor.run()

        self.assertEqual(result, 1)
        self.assertEqual(compose.down_calls, 1)
        self.assertFalse(state.exists())
        self.assertIn(
            "Cleanup warning: Synthetic member deactivation", supervisor.output.getvalue()
        )

    def test_failed_denial_and_failed_teardown_retain_both_private_member_logins(self) -> None:
        state = self.root / "denial-and-down-failed"
        state.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(fail_down=True, events=events)
        supervisor = self.supervisor(state, compose, owned=True)
        supervisor.handoff_published = True
        members = [
            {"username": member.username, "password": member.password}
            for member in supervisor.identity.members
        ]
        second_username = supervisor.identity.members[1].username
        api_patch, calls = self.fake_api_patch(events, status_by_username={second_username: 200})

        with api_patch, patch("local_browser_fixture.time.sleep"):
            errors = supervisor._cleanup()

        self.assertTrue(any("deactivation or sign-in denial" in error for error in errors))
        self.assertIn("Owned Compose teardown could not be verified.", errors)
        self.assertEqual(compose.down_calls, 2)
        self.assertEqual(compose.remove_images_calls, 0)
        self.assertEqual([username for username, _ in calls], [m["username"] for m in members])
        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
        recovery = state / fixture.MEMBER_RECOVERY_FILE
        self.assertEqual(stat.S_IMODE(recovery.stat().st_mode), 0o600)
        self.assertEqual(json.loads(recovery.read_text(encoding="ascii")), members)
        self.assertTrue(supervisor.project_owned)
        self.assertIn(str(recovery), supervisor.output.getvalue())
        self.assertIn("down", supervisor.output.getvalue())
        for member in members:
            matching = next(m for m in supervisor.identity.members if m.username == member["username"])
            self.assertIsNone(matching.password)
            self.assertNotIn(str(member["password"]), supervisor.output.getvalue())
        for secret in (
            supervisor.identity.admin_password,
            supervisor.identity.postgres_password,
            supervisor.identity.app_password,
        ):
            self.assertNotIn(str(secret), supervisor.output.getvalue())

    def test_failed_deactivation_and_teardown_fail_closed_with_recoverable_members(self) -> None:
        state = self.root / "disable-and-down-failed"
        state.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(fail_down=True, fail_account_cleanup=True, events=events)
        supervisor = self.supervisor(state, compose, owned=True)
        supervisor.handoff_published = True
        passwords = [member.password for member in supervisor.identity.members]
        api_patch, calls = self.fake_api_patch(events)

        with api_patch, patch("local_browser_fixture.time.sleep"):
            errors = supervisor._cleanup()

        self.assertEqual(calls, [])
        self.assertEqual(events, ["disable-members", "down", "down"])
        self.assertEqual(len(errors), 2)
        self.assertIn("Owned Compose teardown could not be verified.", errors)
        self.assertEqual(
            [
                member["password"]
                for member in json.loads(
                    (state / fixture.MEMBER_RECOVERY_FILE).read_text(encoding="ascii")
                )
            ],
            passwords,
        )
        self.assertTrue(supervisor.project_owned)
        self.assertTrue(all(member.password is None for member in supervisor.identity.members))
        self.assertIn("Treat both generated Member logins", supervisor.output.getvalue())
        for password in passwords:
            self.assertNotIn(str(password), supervisor.output.getvalue())

    def test_unverified_image_removal_retains_state_and_retries_owned_teardown(self) -> None:
        state = self.root / "image-removal-failed"
        state.mkdir(mode=0o700)
        events: list[str] = []
        compose = self.FakeCompose(fail_image_cleanup=True, events=events)
        supervisor = self.supervisor(state, compose, owned=True)
        supervisor.handoff_published = True
        api_patch, _ = self.fake_api_patch(events)

        with api_patch, patch("local_browser_fixture.time.sleep"):
            errors = supervisor._cleanup()

        self.assertIn("Owned Compose teardown could not be verified.", errors)
        self.assertEqual(compose.down_calls, 2)
        self.assertEqual(compose.remove_images_calls, 2)
        first_down = events.index("down")
        self.assertEqual(
            events[:first_down],
            [
                "disable-members",
                *(f"login:{member.username}" for member in supervisor.identity.members),
            ],
        )
        self.assertTrue(state.exists())
        self.assertTrue(supervisor.project_owned)

    def test_build_failure_still_tears_down_partial_run_images(self) -> None:
        state = self.root / "partial-build"
        state.mkdir(mode=0o700)
        events: list[str] = []

        class PartialBuildCompose(self.FakeCompose):
            def build(self) -> None:
                events.append("build-failed-after-partial-image")
                raise fixture.FixtureError("safe mocked partial build failure")

        compose = PartialBuildCompose(events=events)
        supervisor = fixture.FixtureSupervisor(
            self.root,
            output=io.StringIO(),
            input_stream=io.StringIO(),
        )

        def fail_during_build() -> None:
            supervisor.state_dir = state
            supervisor.compose = compose  # type: ignore[assignment]
            supervisor.identity = fixture.generate_identity(18477)
            supervisor.project_owned = True
            compose.build()

        with patch.object(supervisor, "_prepare", side_effect=fail_during_build):
            result = supervisor.run()

        self.assertEqual(result, 1)
        self.assertEqual(
            events,
            [
                "build-failed-after-partial-image",
                "down",
                "resources-removed",
                "remove-images",
                "images-removed",
            ],
        )
        self.assertFalse(state.exists())
        self.assertFalse(supervisor.project_owned)

    def test_setup_failure_always_enters_cleanup_and_never_publishes_credentials(self) -> None:
        output = io.StringIO()
        supervisor = fixture.FixtureSupervisor(
            self.root,
            output=output,
            input_stream=io.StringIO(),
        )
        supervisor.identity = fixture.generate_identity(18475)
        with (
            patch.object(
                supervisor,
                "_prepare",
                side_effect=fixture.FixtureError("controlled setup failure"),
            ),
            patch.object(supervisor, "_publish_handoff") as publish,
            patch.object(supervisor, "_wait_for_operator") as wait,
            patch.object(supervisor, "_cleanup", return_value=[]) as cleanup,
        ):
            result = supervisor.run()

        self.assertEqual(result, 1)
        cleanup.assert_called_once()
        publish.assert_not_called()
        wait.assert_not_called()
        self.assertIn("controlled setup failure", output.getvalue())
        for secret in (
            supervisor.identity.admin_password,
            supervisor.identity.postgres_password,
            supervisor.identity.app_password,
            *(member.password for member in supervisor.identity.members),
        ):
            self.assertFalse(
                str(secret) in output.getvalue(),
                "privileged secrets must not appear after setup failure",
            )

    def test_handoff_exposes_one_generated_member_for_automated_ui_login(self) -> None:
        output = io.StringIO()
        supervisor = fixture.FixtureSupervisor(
            self.root,
            output=output,
            input_stream=io.StringIO(),
        )
        supervisor.identity = fixture.generate_identity(18476)
        for member in supervisor.identity.members:
            member.user_id = str(uuid.uuid4())
        admin_secret = supervisor.identity.admin_password
        db_secrets = (
            supervisor.identity.postgres_password,
            supervisor.identity.app_password,
            supervisor.identity.rate_limit_key,
        )
        member_secrets = [member.password for member in supervisor.identity.members]
        member_usernames = [member.username for member in supervisor.identity.members]

        supervisor._publish_handoff()

        rendered = output.getvalue()
        self.assertTrue(supervisor.handoff_published)
        self.assertIn(supervisor.identity.origin, rendered)
        self.assertIn(str(member_secrets[0]), rendered)
        self.assertNotIn(str(member_secrets[1]), rendered)
        self.assertIn(member_usernames[0], rendered)
        self.assertNotIn(member_usernames[1], rendered)
        for required_step in (
            "Automated browser-tool sign-in",
            "playwright_browser_snapshot",
            "playwright_browser_fill_form",
            "playwright_browser_click",
            "playwright_browser_navigate",
            "#login-username",
            "#login-password",
            "button[type=submit]",
            "Welcome state",
            "same authenticated page",
            "ui-designer",
            "do not manually enter credentials",
            "PTY stdin EOF does not stop it",
            "bounded lifetime limit",
        ):
            self.assertIn(required_step, rendered)
        self.assertNotIn("/api/auth/login", rendered)
        self.assertIn("do not call the login API directly, inject cookies", rendered)
        for secret in (admin_secret, *db_secrets):
            self.assertFalse(
                str(secret) in rendered,
                "privileged secrets must not appear in the browser handoff",
            )
        self.assertTrue(all(member.password is not None for member in supervisor.identity.members))

    def test_prepare_rejects_redirected_credential_output_before_docker_access(self) -> None:
        supervisor = fixture.FixtureSupervisor(
            self.root,
            output=io.StringIO(),
            input_stream=io.StringIO(),
        )
        with patch("local_browser_fixture.shutil.which") as which:
            with self.assertRaises(fixture.FixtureError):
                supervisor._prepare()
        which.assert_not_called()


if __name__ == "__main__":
    unittest.main()
