"""Focused pure regressions: owned temporary synthetic files, no Docker or DB."""

import os
import ast
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import local_data as data


class LocalDataTests(unittest.TestCase):
    def test_archive_publication_failure_cleanup_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="impostr-data-pure-") as directory:
            output = Path(directory) / "backup.dump"
            with data.PrivatePath(str(output)) as path:
                with self.assertRaises(data.Refused), data.ArchiveOutput(path) as archive:
                    archive.write(b"not an archive")
                    archive.publish()
                self.assertEqual(list(Path(directory).iterdir()), [])
                with data.ArchiveOutput(path) as archive:
                    archive.write(b"PGDMPsynthetic")
                    archive.publish()
                self.assertEqual(output.read_bytes(), b"PGDMPsynthetic")
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                self.assertEqual(output.stat().st_nlink, 1)
                with self.assertRaises(data.Refused):
                    data.ArchiveOutput(path)
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_private_input_rejects_links_and_detects_held_inode_changes(self):
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="impostr-data-pure-") as directory:
            archive = Path(directory) / "backup.dump"
            archive.write_bytes(b"PGDMPsynthetic")
            archive.chmod(0o600)
            with data.PrivatePath(str(archive)) as path:
                path.open_input(archive=True)
                archive.write_bytes(b"PGDMPchanged")
                with self.assertRaises(data.Refused):
                    path.check()
            link = Path(directory) / "link.dump"
            link.symlink_to(archive)
            with data.PrivatePath(str(link)) as path, self.assertRaises(OSError):
                path.open_input(archive=True)
            link.unlink()
            os.link(archive, link)
            with data.PrivatePath(str(archive)) as path, self.assertRaises(data.Refused):
                path.open_input(archive=True)

    def test_restore_refuses_services_and_populated_db_before_streaming(self):
        dotenv = type("Dotenv", (), {"path": Path("/private/target.env"), "check": lambda _: None})()
        db = data.LocalDB("new-target", dotenv, "/private/empty-config")
        with patch.object(db, "run", return_value=b"db\napi\n") as run:
            with self.assertRaises(data.Refused):
                db.restore(object())
            self.assertEqual(run.call_count, 1)
        with patch.object(db, "quiescent"), patch.object(db, "run"), \
                patch.object(db, "pg", return_value=b"not-fresh\n") as pg:
            with self.assertRaises(data.Refused):
                db.restore(object())
            pg.assert_called_once_with(data.FRESH)

    def test_binary_stream_is_bounded_and_child_failures_never_expose_stderr(self):
        environment = {"PATH": "/usr/bin:/bin"}
        with self.assertRaises(data.Refused) as failure:
            data.run_child(["/usr/bin/python3", "-I", "-B", "-c",
                            "import sys; sys.stderr.write('synthetic secret'); sys.exit(3)"], environment)
        self.assertNotIn("synthetic secret", str(failure.exception))
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="impostr-data-pure-") as directory:
            output = Path(directory) / "bounded.dump"
            with data.PrivatePath(str(output)) as path, data.ArchiveOutput(path) as archive:
                with patch.object(data, "MAX_ARCHIVE", 8), self.assertRaises(data.Refused):
                    data.run_child(["/usr/bin/python3", "-I", "-B", "-c",
                                    "import sys; sys.stdout.buffer.write(b'PGDMP1234')"], environment,
                                   receive=archive.write)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_fixed_docker_and_pg_contract_ignore_ambient_settings(self):
        dotenv = type("Dotenv", (), {"path": Path("/private/synthetic.env"), "check": lambda _: None})()
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://unwanted", "POSTGRES_PASSWORD": "not-copied"}):
            db = data.LocalDB("synthetic", dotenv, "/private/empty-config")
        self.assertEqual(db.environment["DOCKER_HOST"], "unix:///var/run/docker.sock")
        self.assertNotIn("POSTGRES_PASSWORD", db.environment)
        self.assertIn(str(data.ROOT / "compose.yaml"), db.compose)
        self.assertIn('--role="$IMPOSTR_APP_DB_USER"', data.RESTORE)
        self.assertIn('IMPOSTR_APP_DB_USER="$IMPOSTR_APP_DB_USER"', data.FRESH)
        for option in ("--single-transaction", "--exit-on-error", "--no-owner", "--no-privileges", "--no-comments"):
            self.assertIn(option, data.RESTORE)
        for option in ("--clean", "--create"):
            self.assertNotIn(option, data.RESTORE)
        with self.assertRaises(data.Refused):
            data.project_name("../live")

    def test_early_restore_exit_keeps_fixed_pg_failure_not_host_pipe_error(self):
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="impostr-data-pure-") as directory:
            archive = Path(directory) / "early.dump"
            archive.write_bytes(b"PGDMP" + b"x" * (1024 * 1024))
            archive.chmod(0o600)
            message = "Restore PostgreSQL transaction failed; private diagnostics suppressed."
            with data.PrivatePath(str(archive)) as path:
                path.open_input(archive=True)
                with self.assertRaises(data.Refused) as failure:
                    data.run_child(["/usr/bin/python3", "-I", "-B", "-c",
                                    "import sys; sys.stderr.write('synthetic private error'); sys.exit(3)"],
                                   {"PATH": "/usr/bin:/bin"}, source=path, failure_message=message)
                self.assertEqual(str(failure.exception), message)

    def test_restore_diagnostics_forward_only_fixed_categories_and_relation_counts(self):
        from contextlib import redirect_stdout
        import imp025_verify as verify

        self.assertEqual(verify.restore_helper_failure(1,
                         "Restore freshness query failed; private diagnostics suppressed.\n"), "freshness_pg_failed")
        self.assertEqual(verify.restore_helper_failure(1, "synthetic private error"), "helper_failure_unclassified")
        refusal = "Restore PostgreSQL transaction failed; private diagnostics suppressed."
        self.assertIsNone(verify.restore_helper_failure(1, refusal + "\n", refusal))
        output = io.StringIO()
        with redirect_stdout(output):
            verify.SafeOutput().line(json.dumps({"check": "restore_transport", "status": "failed",
                "category": "restore_pg_failed", "error": "synthetic private error"}).encode())
            verify.SafeOutput().line(json.dumps({"check": "restore_digest", "status": "failed",
                "category": "digest_mismatch", "relation": "project_attachments",
                "source_count": 1, "target_count": 0, "rows": "synthetic private contents"}).encode())
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows, [
            {"check": "restore_transport", "status": "failed", "category": "restore_pg_failed"},
            {"check": "restore_digest", "status": "failed", "category": "digest_mismatch",
             "relation": "project_attachments", "source_count": 1, "target_count": 0},
        ])

    def test_constraint_diagnostic_does_not_equate_changed_definitions(self):
        from contextlib import redirect_stdout
        import imp025_verify as verify

        source = {"table": "project_attachments", "name_sha256": "a" * 64, "kind": "c",
                  "definition_sha256": "b" * 64, "pretty_sha256": "c" * 64, "flags_sha256": "d" * 64,
                  "field_sha256": {name: "a" * 64 for name in verify.RESTORE_CONSTRAINT_FIELDS}}
        target = dict(source, definition_sha256="e" * 64,
                      field_sha256=dict(source["field_sha256"], check_expression="b" * 64))
        fields = verify.constraint_difference([target], [source])
        self.assertEqual(fields, {"category": "constraint_definition_mismatch", "constraint_ordinal": 0,
                                  "pretty_equal": True, "flags_equal": True, "definition_equal": False,
                                  "constraint_table": "project_attachments", "constraint_kind": "c",
                                  "mismatched_fields": ["check_expression"]})
        output = io.StringIO()
        with redirect_stdout(output):
            verify.SafeOutput().line(json.dumps({"check": "restore_digest", "status": "failed",
                "relation": "constraints", "source_count": 125, "target_count": 125,
                "definition": "synthetic private SQL", **fields}).encode())
        self.assertEqual(json.loads(output.getvalue()), {
            "check": "restore_digest", "status": "failed", "relation": "constraints",
            "source_count": 125, "target_count": 125, **fields})
        changed_flags = dict(target, flags_sha256="f" * 64)
        self.assertFalse(verify.constraint_difference([changed_flags], [source])["flags_equal"])
        self.assertEqual(verify.constraint_difference([dict(source, pretty_sha256="f" * 64)], [source]), {})
        audit = dict(source, table="audit_events", kind="p")
        changed = dict(audit, definition_sha256="e" * 64,
                       field_sha256=dict(audit["field_sha256"], columns="b" * 64, operators="b" * 64))
        difference = verify.constraint_difference([changed], [audit])
        self.assertEqual(difference["constraint_table"], "audit_events")
        self.assertEqual(difference["mismatched_fields"], ["columns", "operators"])
        with self.assertRaises(verify.Unavailable):
            verify.SafeOutput().line(json.dumps({"check": "restore_digest", "status": "failed", **difference,
                                               "mismatched_fields": ["synthetic private contents"]}).encode())

    def test_constraint_state_keeps_behavior_and_ignores_storage_and_deparser_artifacts(self):
        # Execute only the pure projection function, not API imports or fixtures.
        path = Path(__file__).resolve().parents[1] / "api/tests/imp011_restore_fixture.py"
        module = ast.parse(path.read_bytes())
        node = next(item for item in module.body if isinstance(item, ast.FunctionDef) and item.name == "_constraint_state")
        namespace = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
        state = namespace["_constraint_state"]
        import imp025_verify as verify
        row = dict(table_name="attachment_deletions", constraint_name="synthetic_fk", kind="f",
                   deferrable=False, initially_deferred=False, validated=True, no_inherit=True,
                   is_local=True, inherit_count=0, columns=["conversation_id", "project_id"],
                   referenced_schema="public", referenced_table="conversations",
                   referenced_columns=["id", "project_id"], update_action="a", delete_action="c",
                   match_type="s", delete_set_columns=[], nulls_not_distinct=None,
                   check_expression=None, operators=[["fk_primary_foreign", 1, "pg_catalog", "=", "uuid", "uuid"]])
        source = dict(row, oid=123, conkey=[1, 4], pretty_definition="synthetic source deparser")
        target = dict(row, oid=456, conkey=[1, 2], pretty_definition="synthetic restored deparser")
        self.assertEqual(state(source), state(target))
        self.assertEqual(tuple(state(source)), verify.RESTORE_CONSTRAINT_FIELDS)
        for change in ({"columns": ["project_id", "conversation_id"]}, {"delete_action": "a"},
                       {"validated": False}, {"operators": []}):
            self.assertNotEqual(state(source), state(dict(target, **change)))
        check = dict(row, kind="c", check_expression="(original_size > 0)")
        self.assertNotEqual(state(check), state(dict(check, check_expression="(original_size >= 0)")))

    def test_constraint_field_frames_stay_within_existing_output_bounds(self):
        # Exercise the existing parser only: 125 synthetic metadata records, no DB.
        import re
        import imp024_verify
        import imp025_verify as verify

        path = Path(__file__).with_name("imp025_verify.py")
        module = ast.parse(path.read_bytes())
        node = next(item for item in ast.walk(module) if isinstance(item, ast.ClassDef) and item.name == "FixtureOutput")
        namespace = dict(Output=imp024_verify.Output, require=verify.require, Unavailable=verify.Unavailable,
                         RESTORE_CONSTRAINT_FIELDS=verify.RESTORE_CONSTRAINT_FIELDS, RESTORE_PARTS=verify.RESTORE_PARTS,
                         RESTORE_CATEGORIES=verify.RESTORE_CATEGORIES, report=verify.report, json=json, re=re)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
        reader = namespace["FixtureOutput"]("digest", "restore_digest")
        hashes = {name: "a" * 64 for name in verify.RESTORE_CONSTRAINT_FIELDS}
        lines = [json.dumps({"check": "restore_constraint_fields", "ordinal": ordinal, "field_sha256": hashes})
                 for ordinal in range(125)]
        item = dict(table="audit_events", name_sha256="a" * 64, kind="p",
                    definition_sha256="a" * 64, pretty_sha256="a" * 64, flags_sha256="a" * 64)
        parts = {name: {"count": 0, "sha256": "a" * 64} for name in verify.RESTORE_PARTS}
        parts["constraints"]["count"] = 125
        lines.append(json.dumps({"check": "restore_digest", "status": "passed", "digest": "a" * 64,
                                 "parts": parts, "constraint_details": [dict(item) for _ in range(125)]}))
        payload = ("\n".join(lines) + "\n").encode()
        for offset in range(0, len(payload), 8192):
            reader.feed(payload[offset:offset + 8192])
        reader.finish()
        self.assertEqual(reader.result["constraint_details"][7]["field_sha256"], hashes)

    def test_model_enum_rules_cover_static_simple_memberships(self):
        import re

        path = Path(__file__).resolve().parents[1] / "api/tests/imp011_restore_fixture.py"
        module = ast.parse(path.read_bytes())
        nodes = [item for item in module.body if isinstance(item, ast.FunctionDef)
                 and item.name in {"_simple_model_enum", "_enum_rule"}]
        namespace = {"re": re}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
        models = ast.parse((path.parents[1] / "app/models.py").read_bytes())
        admitted = set()
        for node in ast.walk(models):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "CheckConstraint" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                continue
            model = namespace["_simple_model_enum"](node.args[0].value)
            if model is None:
                continue
            name = next(item.value.value for item in node.keywords if item.arg == "name")
            admitted.add(name)
            column, members = model
            canonical, pattern = namespace["_enum_rule"](column, members)
            literals = ", ".join(f"'{value}'::character varying" for value in members)
            converted = ", ".join(f"('{value}'::character varying)::text" for value in members)
            array_cast = f"(({column})::text = ANY ((ARRAY[{literals}])::text[]))"
            literal_casts = f"(({column})::text = ANY (ARRAY[{converted}]))"
            self.assertIsNotNone(pattern.fullmatch(array_cast), name)
            self.assertIsNotNone(pattern.fullmatch(literal_casts), name)
            self.assertEqual(canonical, column + " IN (" + ",".join(f"'{value}'" for value in members) + ")")
        self.assertTrue({"ck_agent_proposal_state", "ck_audit_actor_kind", "ck_users_role", "ck_turn_state"} <= admitted)

    def test_model_enum_rules_reject_compounds_changed_members_and_non_string_columns(self):
        import re
        from types import SimpleNamespace

        path = Path(__file__).resolve().parents[1] / "api/tests/imp011_restore_fixture.py"
        module = ast.parse(path.read_bytes())
        nodes = [item for item in module.body if isinstance(item, ast.FunctionDef)
                 and item.name in {"_simple_model_enum", "_enum_rule", "_model_enum_checks", "_constraint_state"}]
        class StringType:
            pass
        class CharType(StringType):
            pass
        namespace = {"re": re, "String": StringType, "CheckConstraint": SimpleNamespace}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
        constraints = [SimpleNamespace(name="enum", sqltext="state IN ('imported','conflict')"),
                       SimpleNamespace(name="compound", sqltext="state IN ('imported','conflict') OR state IS NULL"),
                       SimpleNamespace(name="padded", sqltext="padded IN ('imported','conflict')")]
        table = SimpleNamespace(name="synthetic", schema=None, constraints=constraints,
                                c={"state": SimpleNamespace(type=StringType()), "padded": SimpleNamespace(type=CharType())})
        rules = namespace["_model_enum_checks"](SimpleNamespace(tables={"synthetic": table}))
        self.assertEqual(set(rules), {("synthetic", "enum")})
        canonical, pattern = rules[("synthetic", "enum")]
        expression = "((state)::text = ANY (ARRAY['imported'::text, 'conflict'::text]))"
        changed = expression.replace("'conflict'", "'other'")
        lossy = expression.replace("(state)::text", "(state)::character varying(3)")
        self.assertIsNone(pattern.fullmatch(changed))
        self.assertIsNone(pattern.fullmatch(lossy))
        self.assertIsNone(pattern.fullmatch(expression + " OR state IS NULL"))
        row = {name: None for name in (
            "table_name", "constraint_name", "kind", "deferrable", "initially_deferred", "validated",
            "no_inherit", "is_local", "inherit_count", "columns", "referenced_schema", "referenced_table",
            "referenced_columns", "update_action", "delete_action", "match_type", "delete_set_columns",
            "nulls_not_distinct", "check_expression", "operators")}
        row.update(table_name="synthetic", constraint_name="enum",
                   kind="c", check_expression=expression)
        state = namespace["_constraint_state"]
        self.assertEqual(state(row, rules)["check_expression"], canonical)
        self.assertEqual(state(dict(row, constraint_name="other_check"), rules)["check_expression"], expression)


if __name__ == "__main__":
    unittest.main()
