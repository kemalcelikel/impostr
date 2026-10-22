"""COORDINATOR ONLY: exact-input native PDF proof; review BEFORE execution.

Read-only command: --preflight (with --restore-only for the restore profile).
Execution requires --api-only, --synthetic, --retirement-only or --restore-only,
--reviewed-harness and --fingerprint from review of these exact bytes. Synthetic
mode runs the fixed-path OpenCode -> shim -> broker -> PlanningHTTPSInference.events,
replacing ONLY its connection callable with an in-memory synthetic receiver.
No DNS/TLS/provider, extractor, private settings, host installs or live modes.

All execution modes build the ordinary pinned API development image and use a
fresh owned PostgreSQL. Sources are frozen before any Docker/worker operation;
the child runs entirely from that snapshot. Output is fixed stage/category JSON,
never bodies, credentials, filenames from uploads, exception text or tracebacks.
Failed checks stop; there is no formatter diagnostic/rebuild/retry loop. Finally
reuse label-scoped stack/image/volume/child cleanup, including generated accounts,
private inputs and broker scratch. Cleanup failure makes the whole check fail.
Retirement-only runs just the two fresh/populated migration preservation cases,
without broker/provider/browser startup or API/static/native acceptance suites.
Restore-only runs one whole-DB synthetic backup/restore drill and two refusal/
rollback checks, using the actual standalone local_data helper and fresh DBs only.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "api/tests"))
from imp024_verify import CheckOutput, RuffJsonOutput, Unavailable, Verify, report, require
from app.chat_protocol import FAILURE_REASONS

# Verified native backend + composer/owned-cleanup delivery; manual UI acceptance remains deferred.
BASELINE = "34dbcb0125a13638cbaa88150483b4534c07cff9"
CHECKPOINT = "34dbcb0125a13638cbaa88150483b4534c07cff9"
RESTORE_CHECKPOINT = "d05233ffc58f1459c6e50688977edfb5d52705a9"
RESTORE_INPUTS = (
    "scripts/local_data.py", "scripts/test_local_data.py",
    "api/tests/imp011_restore_fixture.py",
)
RESTORE_PATHS = frozenset(RESTORE_INPUTS) | {
    "scripts/imp025_verify.py", "AGENTS.md", "PROJECT.md", "BACKLOG.md", "DONE.md",
    "docs/local-development.md", "docs/local-development-history.md", "docs/agent-history.md", "docs/local-scope-history.md",
}
# Only owner-approved runtime/stream repair and history bookkeeping may be committed.
# Future profile anchors advance only after verified delivery, never arbitrary commits.
REPAIR_PATHS = frozenset({
    "scripts/imp002_prototype.py", "scripts/test_imp002_prototype.py",
    "scripts/imp023_worker.py", "scripts/test_imp023_session.py",
    "scripts/imp025_verify.py", "scripts/test_imp025_verify.py",
    "scripts/imp024_product_worker.py", "scripts/test_imp025_inline.py",
    "AGENTS.md", "PROJECT.md", "BACKLOG.md", "DONE.md",
    "docs/local-development.md", "docs/local-development-history.md", "docs/local-scope-history.md",
    "docs/agent-history.md",
})
# Finite approved retirement slice. Historical migration inputs remain immutable;
# removed parser sources are never read from the worktree or frozen into a build.
RETIREMENT_CHANGES = {
    **dict.fromkeys((
        ".dockerignore", "api/Dockerfile", "api/app/attachments.py", "api/app/chat_references.py",
        "api/app/config.py", "api/app/main.py", "api/app/models.py",
        "api/tests/imp025_native_fixture.py", "api/tests/test_attachments.py",
        "api/tests/test_attachments_migration.py", "api/tests/test_attachments_postgres.py",
        "api/tests/test_native_pdf_migration.py", "api/tests/test_native_pdf_storage.py",
        "api/tests/test_imp025_native_integration.py", "scripts/imp025_verify.py",
        "scripts/test_imp025_verify.py", "scripts/imp026_browser.py",
        "scripts/local_browser_fixture.py", "scripts/test_imp017_intake.py",
        "scripts/imp017_intake_verify.py", "scripts/test_imp017_intake_verify.py",
    ), "modified"),
    **dict.fromkeys((
        "scripts/imp025_fixtures.py",
        "api/migrations/versions/20261022_0013_retire_pdf_extraction.py",
    ), "added"),
    **dict.fromkeys((
        "api/app/pdf_extractor.py", "api/app/pdf_lifecycle.py", "api/app/pdf_lifecycle_policy.py",
        "api/app/pdf_protocol.py", "api/tests/imp017_lifecycle_joined.py",
        "api/tests/test_pdf_lifecycle.py", "api/tests/test_pdf_retry_migration.py",
        "scripts/imp017_fixtures.py", "scripts/imp017_lifecycle_verify.py",
        "scripts/imp017_mount_probe.py", "scripts/imp017_verify.py",
        "scripts/test_imp017_lifecycle.py", "scripts/test_imp017_pdf.py",
        "compose.pdf.yaml", "compose.pdf-app.yaml",
        "pdf-extractor/Dockerfile", "pdf-extractor/bootstrap.py", "pdf-extractor/bounded_json.py",
        "pdf-extractor/build.py", "pdf-extractor/dependencies.lock.json", "pdf-extractor/probe.py",
        "pdf-extractor/process.py", "pdf-extractor/seccomp.json", "pdf-extractor/structure.py",
        "pdf-extractor/supervisor.py", "pdf-extractor/worker.py",
    ), "deleted"),
}
RETIRED_INPUTS = frozenset(name for name, status in RETIREMENT_CHANGES.items() if status == "deleted")
MANIFEST = ".imp025-inputs.json"
# Preserve these superseded IMP-018 files outside native capture/execution.
SUPERSEDED_INPUTS = frozenset({
    "api/tests/test_chat_receipts.py", "api/tests/test_chat_references.py",
    "api/tests/test_chat_references_migration.py", "api/tests/imp018_pytest_diagnostic.py",
    "api/tests/imp018_scoped_server.py", "scripts/imp018_verify.py",
    "scripts/test_imp018_receipts.py", "scripts/test_imp018_verify.py",
})
NEW_INPUTS = (
    "api/app/attachment_cleanup.py", "api/app/chat_receipts.py", "api/app/chat_references.py",
    "api/migrations/versions/20261002_0010_pdf_turn_selections.py",
    "api/migrations/versions/20261014_0011_native_pdf_storage.py",
    "api/migrations/versions/20261014_0012_native_send_authorization.py",
    "api/migrations/versions/20261022_0013_retire_pdf_extraction.py",
    "api/tests/test_native_pdf_storage.py",
    "api/tests/test_native_pdf_migration.py", "api/tests/test_native_send_authorization.py",
    "api/tests/imp025_native_fixture.py",
    "api/tests/test_imp025_native_integration.py", "scripts/imp018_receipts.py",
    "scripts/test_imp018_references.py",
    "scripts/imp025_verify.py", "scripts/test_imp025_verify.py",
    "scripts/test_imp025_storage.py", "scripts/test_imp025_inline.py",
    "scripts/test_imp025_authorization.py", "scripts/test_imp025_wiring.py",
    "scripts/imp025_fixtures.py",
)
API_FILES = (
    "app/attachments.py", "app/attachment_cleanup.py", "app/chat.py", "app/chat_broker.py",
    "app/chat_dispatch.py", "app/chat_protocol.py", "app/chat_receipts.py", "app/chat_references.py",
    "app/chat_state.py", "app/main.py", "app/models.py", "app/pdf_intake.py",
    "migrations/versions/20261002_0010_pdf_turn_selections.py",
    "migrations/versions/20261014_0011_native_pdf_storage.py",
    "migrations/versions/20261014_0012_native_send_authorization.py",
    "migrations/versions/20261022_0013_retire_pdf_extraction.py",
    "tests/conftest.py", "tests/imp024_http.py", "tests/test_chat.py",
    "tests/test_native_pdf_storage.py", "tests/test_native_pdf_migration.py",
    "tests/test_native_send_authorization.py", "tests/imp025_native_fixture.py",
    "tests/test_imp025_native_integration.py",
)
# Superseded derivative selection/receipt suites are NOT native acceptance. Keep
# ordinary chat, original storage/auth/integrity and new native deletion regressions.
API_TESTS = (
    "tests/test_chat.py", "tests/test_native_pdf_storage.py", "tests/test_native_pdf_migration.py",
    "tests/test_native_send_authorization.py",
    "tests/test_imp025_native_integration.py::test_native_outage_restart_receipt_purge_quotes",
    "tests/test_imp025_native_integration.py::test_native_capture_delete_committed_fence",
    "tests/test_imp025_native_integration.py::test_native_active_delete_conflict_until_confirmed_stop",
)
PG_TESTS = (
    "tests/test_imp025_native_integration.py::test_postgres_native_migrations_preservation_and_legacy_fence",
    "tests/test_imp025_native_integration.py::test_postgres_extractor_retirement_preservation[False]",
    "tests/test_imp025_native_integration.py::test_postgres_extractor_retirement_preservation[True]",
    "tests/test_imp025_native_integration.py::test_postgres_native_capture_delete_race",
)
RETIREMENT_TEST = (
    "tests/test_imp025_native_integration.py::test_postgres_extractor_retirement_preservation"
)
STAGES = frozenset({
    "preflight", "frozen_inputs", "build", "database", "postgres", "migration", "api_tests",
    "api_lint", "api_format", "api_types", "member", "broker", "api_start", "native_order",
    "native_history", "native_bound", "native_rejections", "native_outage", "native_purge",
    "native_complete", "snapshot_execution", "imp025_verification",
    "native_diagnostic",
    "restore_seed", "restore_backup", "restore_compare", "restore_readable",
    "restore_refusal", "restore_rollback", "restore_transport", "restore_digest",
})
RESTORE_PARTS = (
    "users", "projects", "project_documents", "project_document_revisions",
    "project_document_pair_approvals", "project_approval_manifests", "conversations",
    "chat_turns", "chat_events", "project_attachments", "chat_submission_receipts",
    "chat_send_authorizations", "chat_turn_pdf_selections", "attachment_deletions",
    "attachment_purges", "web_sessions", "schema", "constraints", "indexes",
)
RESTORE_TABLES = frozenset(RESTORE_PARTS[:-3]) | {
    "alembic_version", "audit_events", "rate_limit_buckets", "document_conflict_proposals",
    "bootstrap_state", "conversation_preferences", "project_turn_reservations",
    "chat_interactions", "agent_document_proposals",
}
RESTORE_CONSTRAINT_FIELDS = (
    "table_name", "constraint_name", "kind", "deferrable", "initially_deferred",
    "validated", "no_inherit", "is_local", "inherit_count", "columns",
    "referenced_schema", "referenced_table", "referenced_columns", "update_action",
    "delete_action", "match_type", "delete_set_columns", "nulls_not_distinct",
    "check_expression", "operators",
)
RESTORE_CATEGORIES = frozenset({
    "target_not_fresh", "freshness_pg_failed", "restore_pg_failed", "docker_pg_failed",
    "helper_failure_unclassified", "helper_output_mismatch", "digest_mismatch",
    "relation_owner", "type_owner", "schema", "rows", "original_identity", "database", "operation",
    "constraint_definition_mismatch", "constraint_identity_mismatch",
})


def constraint_difference(actual, expected):
    """Only fixed comparison flags and an ordinal; no SQL or constraint names."""
    for ordinal, (new, old) in enumerate(zip(actual, expected)):
        same_identity = all(new[key] == old[key] for key in ("table", "name_sha256", "kind"))
        if not same_identity or any(new[key] != old[key] for key in ("definition_sha256", "flags_sha256")):
            fields = dict(category="constraint_definition_mismatch" if same_identity else "constraint_identity_mismatch",
                          constraint_ordinal=ordinal,
                           pretty_equal=new["pretty_sha256"] == old["pretty_sha256"],
                           flags_equal=new["flags_sha256"] == old["flags_sha256"],
                           definition_equal=new["definition_sha256"] == old["definition_sha256"],
                           constraint_kind=old["kind"],
                           mismatched_fields=[name for name in RESTORE_CONSTRAINT_FIELDS
                                              if new["field_sha256"][name] != old["field_sha256"][name]])
            if old["table"] in RESTORE_TABLES:
                fields["constraint_table"] = old["table"]
            return fields
    return {}


def restore_helper_failure(result, errors, refusal=None):
    """Exact fixed-string mapping only; captured stderr never enters report fields."""
    if result == (1 if refusal else 0) and errors == (refusal + "\n" if refusal else ""):
        return None
    if result == 0:
        return "helper_output_mismatch"
    return {
        "Restore requires a fresh empty DB, initialized app role, and no other DB clients.\n": "target_not_fresh",
        "Restore freshness query failed; private diagnostics suppressed.\n": "freshness_pg_failed",
        "Restore PostgreSQL transaction failed; private diagnostics suppressed.\n": "restore_pg_failed",
        "Docker/PostgreSQL operation failed; private diagnostics suppressed.\n": "docker_pg_failed",
    }.get(errors, "helper_failure_unclassified")
NATIVE_OPERATIONS = frozenset({
    "product_request", "upload_first", "upload_second", "upload_response", "upload_identity",
    "send_first", "wait_history", "wait_turn", "wait_terminal", "wait_failure_events", "wait_submission", "wait_deadline",
    "receipt_kind", "receipt_count", "receipt_call", "order_followup", "order_manifest",
    "transport_submission", "transport_events", "transport_normalize", "receiver_route", "receiver_json",
    "receiver_envelope", "receiver_manifest", "receiver_part", "receiver_decode",
    "receiver_original", "receiver_bytes", "receiver_tool", "receiver_binding",
    "receiver_response", "receiver_close",
})
NATIVE_CATEGORIES = frozenset({
    "operation", "assertion", "filesystem", "shape", "missing_field", "http", "http_status",
    "timeout", "missing_turn", "turn_failed", "turn_cancelled", "turn_interrupted",
    "submission_not_sent", "identity", "count", "binding",
})


def native_diagnostic(operation, category, *, reason=None):
    """Fixed call-site labels only, including when private exception text exists."""
    require(operation in NATIVE_OPERATIONS and category in NATIVE_CATEGORIES)
    fields = dict(operation=operation, category=category)
    if reason in FAILURE_REASONS:
        fields["reason"] = reason
    report("native_diagnostic", "failed", **fields)


def native_require(value, operation, category, *, reason=None):
    if not value:
        native_diagnostic(operation, category, reason=reason)
        raise Unavailable()


@contextmanager
def native_probe(operation):
    require(operation in NATIVE_OPERATIONS)
    try:
        yield
    except Exception as error:
        import http.client
        category = ("assertion" if isinstance(error, AssertionError) else
                    "timeout" if isinstance(error, TimeoutError) else
                    "filesystem" if isinstance(error, OSError) else
                    "http" if isinstance(error, http.client.HTTPException) else
                    "missing_field" if isinstance(error, KeyError) else
                    "shape" if isinstance(error, (TypeError, AttributeError, ValueError))
                        and not isinstance(error, Unavailable) else "operation")
        native_diagnostic(operation, category)
        raise


def source_path(name):
    """Only fixed application/build/host-code inputs, not dotenv/log/config trees."""
    return (
        name in {".dockerignore", "compose.yaml", "compose.chat.yaml"}
        or name in {f"overnight-agent/{item}.md.example" for item in ("PROJECT", "AGENTS", "BACKLOG")}
        or (name.startswith(("api/", "db/", "web/"))
            and not any(part.startswith(".env") or part in {"node_modules", "__pycache__", ".git"}
                        for part in Path(name).parts))
        or name.startswith("scripts/") and name.endswith(".py")
    ) and not Path(name).is_absolute() and ".." not in Path(name).parts and name not in (
        SUPERSEDED_INPUTS | RETIRED_INPUTS
    )


def git(*args):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, env={"PATH": "/usr/bin:/bin", "HOME": "/tmp/opencode"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=30, check=False,
    )
    require(result.returncode == 0 and len(result.stdout) <= 4 * 1024 * 1024)
    return result.stdout


def read_source(root, name):
    require(source_path(name))
    path = root / name
    for parent in (path, *path.parents):
        require(not parent.is_symlink())
        if parent == root:
            break
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 4 * 1024 * 1024)
        with os.fdopen(fd, "rb", closefd=False) as source:
            data = source.read(4 * 1024 * 1024 + 1)
        require(len(data) == info.st_size)
        return data
    finally:
        os.close(fd)


def fingerprint(sources, head, *, restore_only=False):
    require(re.fullmatch(r"[0-9a-f]{40}", head) is not None)
    rows = [dict(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
            for name, data in sorted(sources.items())]
    metadata = dict(base=RESTORE_CHECKPOINT if restore_only else BASELINE, head=head, files=rows)
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest(), metadata


def tracked_sources(revision):
    paths = set()
    for row in git("ls-tree", "-r", "-z", revision).split(b"\0"):
        if not row:
            continue
        header, name = row.split(b"\t", 1)
        name = name.decode("utf-8", "strict")
        if source_path(name):
            require(header.split()[0] in (b"100644", b"100755"))
            paths.add(name)
    return paths


def capture(*, restore_only=False):
    head = git("rev-parse", "HEAD").strip().decode("ascii")
    require(re.fullmatch(r"[0-9a-f]{40}", head) is not None)
    checkpoint = RESTORE_CHECKPOINT if restore_only else CHECKPOINT
    git("merge-base", "--is-ancestor", BASELINE, checkpoint)
    git("merge-base", "--is-ancestor", checkpoint, head)
    changed = git("diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                  "--name-only", "-z", checkpoint, head).split(b"\0")
    allowed = RESTORE_PATHS if restore_only else REPAIR_PATHS | RETIREMENT_CHANGES.keys()
    require(all(name.decode("utf-8", "strict") in allowed
                for name in changed if name))
    baseline_paths, current_paths = tracked_sources(checkpoint if restore_only else BASELINE), tracked_sources(head)
    new_inputs = RESTORE_INPUTS if restore_only else NEW_INPUTS
    paths = baseline_paths | set(new_inputs)
    require(baseline_paths <= current_paths <= paths)
    sources = {name: read_source(ROOT, name) for name in sorted(paths)}
    require(sum(map(len, sources.values())) <= 64 * 1024 * 1024)
    # Only declared new candidate/test inputs are admitted. Missing future native
    # code must not silently fall back to baseline or disappear from the fingerprint.
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    require(all(not source_path(name.decode()) or name.decode() in new_inputs
                for name in untracked if name))
    # Staging an undeclared new source must not hide it from the untracked check.
    indexed = git("ls-files", "--cached", "-z").split(b"\0")
    require(all(not source_path(name.decode()) or name.decode() in paths
                for name in indexed if name))
    require(git("rev-parse", "HEAD").strip().decode("ascii") == head)
    return sources, head


def freeze(destination, sources, metadata):
    destination.mkdir(mode=0o700)
    for name, data in sorted(sources.items()):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        path.write_bytes(data)
        path.chmod(0o444)
    (destination / MANIFEST).write_text(json.dumps(metadata, sort_keys=True), encoding="ascii")
    (destination / MANIFEST).chmod(0o444)


def check_frozen(expected, *, restore_only=False):
    require(ROOT != Path("/home/kemal/projects/impostr") and ROOT.name == "source"
            and ROOT.parent.parent == Path("/tmp/opencode")
            and stat.S_IMODE(ROOT.parent.stat().st_mode) == 0o700
            and ROOT.stat().st_uid == ROOT.stat().st_gid == 1000)
    metadata = json.loads((ROOT / MANIFEST).read_bytes())
    require(set(metadata) == {"base", "head", "files"}
            and metadata["base"] == (RESTORE_CHECKPOINT if restore_only else BASELINE))
    names = [row["path"] for row in metadata["files"]]
    require(names == sorted(set(names)) and set(RESTORE_INPUTS if restore_only else NEW_INPUTS) <= set(names))
    # Extra modules/build inputs could change execution without changing a listed
    # file. The snapshot contains only captured files and its bound manifest.
    entries = list(ROOT.rglob("*"))
    require(not any(path.is_symlink() for path in entries))
    require({path.relative_to(ROOT).as_posix() for path in entries if not path.is_dir()}
            == set(names) | {MANIFEST})
    sources = {name: read_source(ROOT, name) for name in names}
    actual, rebuilt = fingerprint(sources, metadata["head"], restore_only=restore_only)
    require(rebuilt == metadata and actual == expected)


class ResultOutput(CheckOutput):
    """Require actual pytest execution; skips/errors/empty successful commands fail."""
    def __init__(self, expected=None):
        super().__init__("pytest", check_files=API_FILES)
        self.expected = expected
        self.passes = 0
        self.skipped = False

    def line(self, line):
        super().line(line)
        match = re.search(rb"\b([0-9]+) passed\b", line)
        if match:
            self.passes = int(match.group(1))
        if re.search(rb"\b[1-9][0-9]* skipped\b", line):
            self.skipped = True
        if b"IMP025_STAGE " in line:
            value = line.partition(b"IMP025_STAGE ")[2].decode("ascii", "ignore")
            if value in {"pg_preservation", "pg_legacy_fence", "pg_send_schema", "pg_capture_delete"}:
                report("postgres", "observed", category=value)

    def finish(self):
        require(self.passes > 0 and not self.skipped and not self.reasons
                and (self.expected is None or self.passes == self.expected))


class SafeOutput(CheckOutput):
    def __init__(self):
        super().__init__("snapshot")
        self.success = False

    def line(self, line):
        if len(line) > 4096 or not line.startswith(b"{"):
            return
        try:
            row = json.loads(line)
            check, status = row["check"], row["status"]
            require(check in STAGES or check.startswith("cleanup_") or check in {
                "owned_cleanup", "owned_fixture", "ordinary_connection_phase"})
            require(status in {"started", "prepared", "passed", "failed", "observed"})
            # Child metadata is never forwarded. Fixed child phase/category names
            # only; raw private output (including generated login) cannot survive.
            safe = {}
            if row.get("phase") in STAGES:
                safe["phase"] = row["phase"]
            if row.get("category") in {"operation", "assertion", "database", "filesystem",
                    "pg_preservation", "pg_legacy_fence", "pg_send_schema", "pg_capture_delete",
                    "tests_failed", "test_errors", "test_import_error", "format_mismatch",
                    "lint_findings", "lint_diagnostic_unavailable", "type_errors"}:
                safe["category"] = row["category"]
            if check.startswith("restore_"):
                if row.get("category") in RESTORE_CATEGORIES:
                    safe["category"] = row["category"]
                if row.get("relation") in RESTORE_PARTS:
                    safe["relation"] = row["relation"]
                    for field in ("source_count", "target_count"):
                        require(type(row.get(field)) is int and 0 <= row[field] <= 100000)
                        safe[field] = row[field]
                if row.get("category") in {"constraint_definition_mismatch", "constraint_identity_mismatch"}:
                    require(type(row.get("constraint_ordinal")) is int and 0 <= row["constraint_ordinal"] < 256)
                    safe["constraint_ordinal"] = row["constraint_ordinal"]
                    if row.get("constraint_table") in RESTORE_TABLES:
                        safe["constraint_table"] = row["constraint_table"]
                    require(row.get("constraint_kind") in {"c", "f", "p", "u", "x"})
                    safe["constraint_kind"] = row["constraint_kind"]
                    names = row.get("mismatched_fields")
                    require(isinstance(names, list) and len(names) <= len(RESTORE_CONSTRAINT_FIELDS)
                            and all(name in RESTORE_CONSTRAINT_FIELDS for name in names)
                            and len(names) == len(set(names)))
                    safe["mismatched_fields"] = names
                    for field in ("pretty_equal", "flags_equal", "definition_equal"):
                        require(type(row.get(field)) is bool)
                        safe[field] = row[field]
            if check == "native_diagnostic":
                require(row.get("operation") in NATIVE_OPERATIONS
                        and row.get("category") in NATIVE_CATEGORIES)
                safe.update(operation=row["operation"], category=row["category"])
                if row.get("reason") in FAILURE_REASONS:
                    safe["reason"] = row["reason"]
            if check in {"api_lint", "api_format"} and "file" in row:
                require(row["file"] in API_FILES and isinstance(row.get("code"), str)
                        and (row["code"] == "format_mismatch"
                             or re.fullmatch(r"(?:E|F|I|UP|B)[0-9]{3}", row["code"])))
                safe.update(file=row["file"], code=row["code"])
                if "line" in row:
                    require(type(row["line"]) is int and 1 <= row["line"] <= 10000)
                    safe["line"] = row["line"]
            if check.startswith("cleanup_"):
                require(check in {"cleanup_broker_children", "cleanup_compose_down",
                    "cleanup_container_inventory", "cleanup_volume_inventory", "cleanup_network_inventory",
                    "cleanup_image_inventory", "cleanup_channel_directory", "cleanup_generated_inputs"})
            report(check, status, **safe)
            if check == "imp025_verification" and status == "passed":
                self.success = True
        except Exception:
            raise Unavailable() from None

    def finish(self):
        require(self.success)


class Receiver:
    """No listener. Trusted HTTPS transport's connection callable, not an ACK seam."""
    def __init__(self):
        self.originals = {}
        self.observations = []
        self.lock = threading.Lock()

    def transport(self, metadata):
        from imp024_operator_transport import PlanningHTTPSInference, explicit_contract
        receiver = self

        class NativeTransport(PlanningHTTPSInference):
            def __init__(self):
                # Intentionally skip HTTPSInference.__init__: NO DNS or TLS.
                self.contract = explicit_contract("https://synthetic.example.invalid",
                    "/openai/v1/responses", "none", "synthetic")
                self.acquire("generated-synthetic-key-not-real")

            def events(self, data, cancelled, deadline, *, submission=None):
                native_require(submission is not None and submission.ledger.native,
                               "transport_submission", "identity")
                self.connection = lambda: CapturedConnection(receiver, metadata, submission)
                with native_probe("transport_events"):
                    yield from super().events(data, cancelled, deadline, submission=submission)

            def normalize_planning(self, response, data, cancelled, deadline):
                with native_probe("transport_normalize"):
                    yield from super().normalize_planning(response, data, cancelled, deadline)

        return NativeTransport()

    def inspect(self, metadata, submission, encoded):
        from app.chat_protocol import PDF_DATA_PREFIX, occurrence_filename, MAX_PDF_FRAME, native_occurrence_manifest
        with native_probe("receiver_json"):
            data = json.loads(encoded)
            native_require(data["model"] == "synthetic" and data["store"] is False and data["stream"] is True,
                           "receiver_envelope", "identity")
            parts = [part for item in data["input"] if isinstance(item.get("content"), list)
                     for part in item["content"] if part.get("type") == "input_file"]
        # Turn.run passes binary-free metadata, not the native inline envelope.
        with native_probe("receiver_manifest"):
            manifest = native_occurrence_manifest(metadata)
        native_require(len(parts) == len(manifest) and len(encoded) <= MAX_PDF_FRAME,
                       "receiver_manifest", "count")
        for part, expected in zip(parts, manifest):
            native_require(set(part) == {"type", "filename", "file_data"}
                           and part["filename"] == occurrence_filename(expected)
                           and part["file_data"].startswith(PDF_DATA_PREFIX), "receiver_part", "identity")
            with native_probe("receiver_decode"):
                decoded = base64.b64decode(part["file_data"][len(PDF_DATA_PREFIX):], validate=True)
            with native_probe("receiver_original"):
                original = self.originals[expected["original_sha256"]]
            native_require(decoded == original and len(decoded) == expected["original_size"]
                           and hashlib.sha256(decoded).hexdigest() == expected["original_sha256"],
                           "receiver_bytes", "identity")
        tools = [item for item in data["input"] if item.get("type") == "function_call_output"]
        if metadata["prompt"] == "SYNTHETIC NATIVE TOOL" and tools:
            with native_probe("receiver_tool"):
                native_require(len(tools) == 1 and tools[0]["call_id"] == "call_native_read"
                               and metadata["documents"]["PROJECT.md"]["content"].strip().splitlines()[0]
                                   in tools[0]["output"], "receiver_tool", "identity")
        observation = dict(turn_id=submission.row["turn_id"], call=submission.row["call"],
            request_sha256=hashlib.sha256(encoded).hexdigest(), request_size=len(encoded),
            manifest=manifest, followup=bool(tools),
            authorization_id=submission.row.get("authorization_id"),
            rendered_sha256=submission.row.get("rendered_sha256"),
            manifest_sha256=submission.row.get("manifest_sha256"))
        native_require(observation["request_sha256"] == submission.row["request_sha256"]
                       and observation["request_size"] == submission.row["request_size"],
                       "receiver_binding", "binding")
        with self.lock:
            self.observations.append(observation)  # Metadata only, never request bodies.
        return bool(tools)


class CapturedConnection:
    def __init__(self, receiver, metadata, submission):
        self.receiver, self.metadata, self.submission = receiver, metadata, submission
        self.followup = None

    def request(self, method, route, encoded, headers):
        native_require(method == "POST" and route == "/openai/v1/responses"
                       and headers["api-key"] == "generated-synthetic-key-not-real", "receiver_route", "identity")
        self.followup = self.receiver.inspect(self.metadata, self.submission, encoded)

    def getresponse(self):
        from imp005_verify import EarlyResponse
        from imp024_inference import native_response
        prompt = self.metadata["prompt"]
        if prompt == "SYNTHETIC NATIVE TOOL" and not self.followup:
            calls = [dict(type="function_call", name="read", call_id="call_native_read",
                          arguments=json.dumps({"filePath": "/project/PROJECT.md"}))]
            frames = native_response(calls=calls)
        else:
            frames = native_response("Synthetic native assistant quotation.")

        class Response(EarlyResponse):
            status = 200

            def getheader(self, name, default=None):
                return {"Content-Type": "text/event-stream"}.get(name, default)

            def getheaders(self):
                return [("Content-Type", "text/event-stream")]

            def close(self):
                with native_probe("receiver_close"):
                    # EarlyResponse wraps a LIST iterator, not a generator. Closing
                    # it must release frames without raising after a successful send.
                    close = getattr(self.frames, "close", None)
                    self.frames = iter(())
                    if close is not None:
                        close()

        with native_probe("receiver_response"):
            return Response(frames)

    def abort(self):
        pass

    def close(self):
        pass


class Product:
    def __init__(self, origin, login, receiver, stage):
        from imp024_http import Client
        self.client = Client(origin, timeout=10)
        self.login, self.receiver = login, receiver
        self.stage = stage
        self.base = None

    def request(self, method, path, payload=None, expected=200):
        with native_probe("product_request"):
            response = self.client.request(method, path, json=payload, headers={
                "Origin": self.client.base_url, "X-CSRF-Token": self.client.cookies.get("impostr_csrf", "")})
        native_require(response.status_code in expected if isinstance(expected, tuple)
                       else response.status_code == expected, "product_request", "http_status")
        return response

    def upload(self, body, expected=201):
        import http.client
        connection = http.client.HTTPConnection("127.0.0.1", self.client.port, timeout=30)
        try:
            connection.request("POST", self.base + "/attachments/upload?filename=synthetic.pdf", body, {
                "Origin": self.client.base_url, "Content-Type": "application/pdf",
                "X-CSRF-Token": self.client.cookies.get("impostr_csrf", ""),
                "Cookie": "; ".join(name + "=" + self.client.cookies.get(name, "")
                                    for name in ("impostr_session", "impostr_csrf")),
            })
            response = connection.getresponse()
            raw = response.read(8193)
            native_require(response.status == expected and len(raw) <= 8192, "upload_response", "http_status")
            if expected != 201:
                return None
            row = json.loads(raw)
            native_require(row["status"] == "stored" and row["native_available"] is True
                           and row["original_size"] == len(body)
                           and row["original_sha256"] == hashlib.sha256(body).hexdigest(), "upload_identity", "identity")
            self.receiver.originals[row["original_sha256"]] = body
            return dict(attachment_id=row["id"], expected_sha256=row["original_sha256"])
        finally:
            connection.close()

    def send(self, prompt, selections=(), expected=202, request_id=None):
        import uuid
        return self.request("POST", self.base + "/turns", dict(request_id=request_id or str(uuid.uuid4()),
            prompt=prompt, selections=list(selections)), expected).json()

    def wait(self, turn_id):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            with native_probe("wait_history"):
                history = self.request("GET", self.base).json()
                turn = next((item for item in history["turns"] if item["id"] == turn_id), None)
            native_require(turn is not None, "wait_turn", "missing_turn")
            if turn["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                if turn["state"] != "completed":
                    category = "turn_" + turn["state"]
                    native_diagnostic("wait_terminal", category)
                    # Reasons are durable EVENTS, not fields of the turn receipt.
                    # The first-turn slice has at most 256 events (64 per page).
                    # This bounded read is diagnostic only, never a send/reply retry.
                    with native_probe("wait_failure_events"):
                        after = 0
                        for _ in range(5):
                            page = self.request("GET", self.base + "/events?after=" + str(after)).json()
                            reason = next((row["data"].get("reason") for row in page["events"]
                                if row["turn_id"] == turn_id and row["type"] == "failed"
                                and row["data"].get("reason") in FAILURE_REASONS), None)
                            if reason is not None:
                                native_diagnostic("wait_failure_events", category, reason=reason)
                                break
                            if not page["events"]:
                                break
                            native_require(type(page["after"]) is int and page["after"] > after,
                                           "wait_failure_events", "shape")
                            after = page["after"]
                    raise Unavailable()
                native_require(turn["submission"]["status"] == "sent", "wait_submission", "submission_not_sent")
                self.receipt(turn)
                return turn
            time.sleep(0.1)
        native_require(False, "wait_deadline", "timeout")

    def receipt(self, turn):
        from app.chat_protocol import NATIVE_PDF_REFERENCE
        receipt = turn["submission"]
        native_require(receipt["reference_kind"] == NATIVE_PDF_REFERENCE, "receipt_kind", "identity")
        observations = [row for row in self.receiver.observations if row["turn_id"] == turn["id"]]
        native_require(len(observations) == len(receipt["calls"]) > 0, "receipt_count", "count")
        for observed, call in zip(observations, receipt["calls"]):
            with native_probe("receipt_call"):
                native_require(call["status"] == "sent" and call["call"] == observed["call"]
                               and call["request_sha256"] == observed["request_sha256"]
                               and call["request_size"] == observed["request_size"]
                               and call["reference_kind"] == NATIVE_PDF_REFERENCE
                               and call["authorization_id"] == observed["authorization_id"]
                               and observed["authorization_id"] is not None
                               and receipt["rendered_sha256"] == observed["rendered_sha256"]
                               and receipt["manifest_sha256"] == observed["manifest_sha256"], "receipt_call", "binding")

    def start(self):
        csrf = self.request("GET", "/api/auth/csrf").json()["csrf_token"]
        reply = self.client.post("/api/auth/login", json=self.login,
            headers={"Origin": self.client.base_url, "X-CSRF-Token": csrf})
        require(reply.status_code == 200)
        self.login.clear()
        # Normal Member authorization, no test auth/session bypass.
        self.request("GET", "/api/admin/users", expected=403)
        project = self.request("POST", "/api/projects", {"name": "Synthetic native PDF"}, 201).json()["id"]
        self.chat = "/api/projects/" + project + "/chat"
        self.conversation()

    def conversation(self):
        conv = self.request("POST", self.chat, {"title": "Native proof"}, 201).json()["id"]
        self.base = self.chat + "/" + conv

    def main_flow(self):
        from imp025_fixtures import text_pdf
        self.stage("native_order")
        with native_probe("upload_first"):
            first = self.upload(text_pdf())
        with native_probe("upload_second"):
            second = self.upload(text_pdf().replace(b"Synthetic", b"Different"))
        ordered = [second, first, second]
        with native_probe("send_first"):
            started = self.send("SYNTHETIC NATIVE TOOL", ordered)
        turn = self.wait(started["id"])
        observed = [row for row in self.receiver.observations if row["turn_id"] == turn["id"]]
        native_require(len(observed) == 2 and observed[1]["followup"], "order_followup", "count")
        native_require([item["attachment_id"] for item in observed[0]["manifest"]]
                       == [item["attachment_id"] for item in ordered], "order_manifest", "identity")
        report("native_order", "passed")
        self.stage("native_history")
        continued = self.wait(self.send("SYNTHETIC NATIVE HISTORY")["id"])
        history = [row for row in self.receiver.observations if row["turn_id"] == continued["id"]]
        require(len(history) == 1 and [item["attachment_id"] for item in history[0]["manifest"]]
                == [item["attachment_id"] for item in ordered]
                and all(item["message_index"] == 0 for item in history[0]["manifest"]))
        report("native_history", "passed")
        # Exact idempotency includes ordered IDs/hashes, not a new dispatch.
        count = len(self.receiver.observations)
        replay = self.send("SYNTHETIC NATIVE TOOL", ordered, request_id=started["request_id"])
        require(replay["id"] == started["id"] and len(self.receiver.observations) == count)
        return ordered, turn

    def bound_flow(self):
        self.stage("native_bound")
        # Two distinct originals total 49,999,999 bytes. Real receiver admission
        # crosses the large JSON, shim, relay and final host serialization bounds.
        self.conversation()
        files = [self.upload(b"%PDF-1.7\n" + b"x" * (size - 15) + b"\n%%EOF")
                 for size in (24_999_999, 25_000_000)]
        turn = self.wait(self.send("SYNTHETIC NATIVE BOUND", files)["id"])
        observed = [row for row in self.receiver.observations if row["turn_id"] == turn["id"]]
        require(len(observed) == 1 and sum(item["original_size"] for item in observed[0]["manifest"])
                == 49_999_999 and observed[0]["request_size"] > 66_000_000)
        before = len(self.receiver.observations)
        self.send("SYNTHETIC NATIVE OVERFLOW", files, expected=422)  # History charged too.
        require(len(self.receiver.observations) == before)
        report("native_bound", "passed")

    def rejection_flow(self):
        self.stage("native_rejections")
        self.conversation()
        selected = self.upload(b"%PDF-synthetic rejected selection")
        before = len(self.receiver.observations)
        self.send("SYNTHETIC NATIVE ALTERED HASH", [dict(selected, expected_sha256="f" * 64)], expected=409)
        own_base = self.base
        self.conversation()
        self.send("SYNTHETIC NATIVE FOREIGN", [selected], expected=404)
        self.base = own_base
        path = self.base + "/attachments/" + selected["attachment_id"]
        self.request("DELETE", path, expected=204)
        self.send("SYNTHETIC NATIVE DELETED", [selected], expected=404)
        self.upload(b"%PDF-" + b"x" * (50_000_000 - 5), expected=413)
        require(len(self.receiver.observations) == before)
        report("native_rejections", "passed")

    def close(self):
        self.client.close()


class NativeVerify(Verify):
    def __init__(self, synthetic, *, retirement_only=False, restore_only=False):
        require(sum((synthetic, retirement_only, restore_only)) <= 1)
        super().__init__()
        self.synthetic = synthetic
        self.retirement_only = retirement_only
        self.restore_only = restore_only
        self.restore_targets = []
        self.restore_files = None
        self.phase = "frozen_inputs"
        self.connection = self.runtime = self.product = None
        self.receiver = Receiver()

    def stage(self, name):
        require(name in STAGES)
        self.phase = name
        report(name, "started")

    def prepare(self):
        super().prepare()
        # Base synthetic chat overlay is deliberately omitted: no extractor or
        # fake text transport. API-only/retirement-only never start a worker/channel.
        self.base = self.base[:-2]
        from imp017_intake_verify import postgres_owner_overlay
        overlay = self.inputs / "native-checks.yaml"
        overlay.write_text(json.dumps({"services": {"api-integration-check": {"environment": {
            "IMPOSTR_TEST_CHAT_CHANNEL": "1", "IMPOSTR_TEST_CHAT_JOINED": "1", "IMPOSTR_TEST_NATIVE_PDF": "1"}}}}))
        self.base += ["-f", str(overlay)]
        self.owner_overlay = self.inputs / "native-owner.yaml"
        self.owner_overlay.write_text(postgres_owner_overlay(ROOT)
                                      + "      IMPOSTR_TEST_NATIVE_PDF: '1'\n"
                                      + "      IMPOSTR_TEST_RESTORE: '1'\n")
        if self.restore_only:
            self.restore_overlay = self.inputs / "restore-checks.yaml"
            self.restore_overlay.write_text(json.dumps({"services": {
                "api-integration-check": {"environment": {"IMPOSTR_TEST_RESTORE": "1"}}
            }}))
            self.base += ["-f", str(self.restore_overlay)]

    def run_restore(self):
        """Only generated DB settings and owned synthetic archives; no app startup."""
        from imp024_verify import Output
        import local_data
        # /tmp/opencode is group-writable synthetic harness scratch. Do NOT weaken
        # human helper ancestry checks for it. Put only our generated dotenv copies
        # and archives in a separate exclusive 0700 /tmp child, with 0600 files.
        self.restore_files = tempfile.TemporaryDirectory(prefix="impostr-restore-drill-", dir="/tmp")
        private = Path(self.restore_files.name)
        envs = {}

        class FixtureOutput(Output):
            stdout_only = True

            def __init__(self, action, phase):
                super().__init__()
                self.action, self.result = action, None
                self.phase = phase
                self.constraint_fields = []

            def line(self, line):
                if not line.startswith(b'{"check": "restore_'):
                    return  # Build/Alembic output discarded, not a success marker.
                row = json.loads(line)
                if self.action == "digest" and row.get("check") == "restore_constraint_fields":
                    require(self.result is None and set(row) == {"check", "ordinal", "field_sha256"}
                            and type(row["ordinal"]) is int and row["ordinal"] == len(self.constraint_fields)
                            and row["ordinal"] < 256)
                    hashes = row["field_sha256"]
                    require(isinstance(hashes, dict) and set(hashes) == set(RESTORE_CONSTRAINT_FIELDS)
                            and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                                    for value in hashes.values()))
                    self.constraint_fields.append(hashes)
                    return
                if row.get("check") == "restore_fixture" and row.get("status") == "failed":
                    category = row.get("category")
                    report(self.phase, "failed", category=category if category in RESTORE_CATEGORIES else "operation")
                    raise Unavailable()
                require(row.get("check") == "restore_" + self.action and row.get("status") == "passed"
                        and self.result is None)
                if self.action == "digest":
                    require(set(row) == {"check", "status", "digest", "parts", "constraint_details"}
                            and re.fullmatch(r"[0-9a-f]{64}", row["digest"]) is not None)
                    require(isinstance(row["parts"], dict) and set(row["parts"]) == set(RESTORE_PARTS))
                    for part in row["parts"].values():
                        require(set(part) == {"count", "sha256"} and type(part["count"]) is int
                                and 0 <= part["count"] <= 100000
                                and re.fullmatch(r"[0-9a-f]{64}", part["sha256"]) is not None)
                    details = row["constraint_details"]
                    require(isinstance(details, list) and len(details) == row["parts"]["constraints"]["count"]
                            and len(details) <= 256 and len(details) == len(self.constraint_fields))
                    for item, hashes in zip(details, self.constraint_fields):
                        require(set(item) == {"table", "name_sha256", "kind", "definition_sha256", "pretty_sha256", "flags_sha256"}
                                and isinstance(item["table"], str) and re.fullmatch(r"[a-z_]{1,63}", item["table"])
                                and item["kind"] in {"c", "f", "p", "u", "x"})
                        require(all(re.fullmatch(r"[0-9a-f]{64}", item[key]) is not None
                                    for key in ("name_sha256", "definition_sha256", "pretty_sha256", "flags_sha256")))
                        item["field_sha256"] = hashes
                else:
                    require(set(row) == {"check", "status"})
                self.result = row

            def finish(self):
                require(self.result is not None)

        def fixture(stack, action, *, owner=False):
            output = FixtureOutput(action, self.phase)
            base = stack.base + (["-f", str(self.owner_overlay)] if owner else [])
            service = "api-integration-owner-check" if owner else "api-integration-check"
            stack.compose_used = True
            stack.command(base + ["run", "--no-deps", "--rm", *(("--build",) if owner else ()), service, "python", "-B",
                                  "tests/imp011_restore_fixture.py", action],
                          seconds=180, output=output)
            return output.result

        def helper(stack, action, path, *, refusal=None):
            import io
            from contextlib import redirect_stderr
            # Invoke the actual CLI's implementation, with ONLY this owned dotenv.
            if stack.project not in envs:
                dotenv = private / (stack.project + ".env")
                fd = os.open(dotenv, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as output:
                    output.write((stack.inputs / "fixture.env").read_bytes())
                envs[stack.project] = dotenv
            errors = io.StringIO()
            with redirect_stderr(errors):
                result = local_data.main([action, "--project", stack.project, "--env-file",
                                          str(envs[stack.project]),
                                          "--output" if action == "backup" else "--input", str(path)])
            category = restore_helper_failure(result, errors.getvalue(), refusal)
            if category is not None:
                report(self.phase, "failed", category=category)
                raise Unavailable()

        def compare(actual, expected):
            if (actual["digest"], actual["parts"]) != (expected["digest"], expected["parts"]):
                for relation in RESTORE_PARTS:
                    if actual["parts"][relation] != expected["parts"][relation]:
                        fields = {"category": "digest_mismatch"}
                        if relation == "constraints":
                            fields.update(constraint_difference(actual["constraint_details"], expected["constraint_details"]))
                        report(self.phase, "failed", **fields, relation=relation,
                               source_count=expected["parts"][relation]["count"],
                               target_count=actual["parts"][relation]["count"])
                        break
                else:
                    report(self.phase, "failed", category="digest_mismatch")
                raise Unavailable()

        self.stage("build")
        self.compose("build", "db", "api-integration-check", seconds=600)
        self.stage("database")
        self.compose("up", "-d", "--wait", "db")
        self.stage("restore_seed")
        fixture(self, "seed")
        before = fixture(self, "digest")
        self.stage("restore_backup")
        archive = private / "owned.dump"
        helper(self, "backup", archive)
        for user in ("impostr_restored_app", "impostr_rollback_app"):
            target = Verify()
            self.restore_targets.append(target)  # Own cleanup even if prepare/build fails.
            target.prepare()
            target.base = target.base[:-2] + ["-f", str(self.restore_overlay)]
            dotenv = target.inputs / "fixture.env"
            dotenv.write_text(dotenv.read_text().replace("DB_USER=impostr_app\n", "DB_USER=" + user + "\n"))
            target.compose("build", "db", "api-integration-check", seconds=600)
        target, rollback = self.restore_targets
        self.stage("restore_compare")
        self.stage("restore_transport")
        helper(target, "restore", archive)
        report("restore_transport", "passed")
        self.stage("restore_digest")
        compare(fixture(target, "digest"), before)
        report("restore_digest", "passed")
        report("restore_compare", "passed")
        self.stage("restore_refusal")
        helper(target, "restore", archive,
               refusal="Restore requires a fresh empty DB, initialized app role, and no other DB clients.")
        compare(fixture(target, "digest"), before)  # Refusal must not alter target.
        report("restore_refusal", "passed")
        self.stage("restore_readable")
        fixture(target, "readable")
        report("restore_readable", "passed")
        self.stage("restore_rollback")
        # Add a superuser-only event trigger to the owned source, not the target.
        # Earlier tables restore before its post-data failure, proving real rollback.
        fixture(self, "poison", owner=True)
        poisoned = private / "owned-failing.dump"
        helper(self, "backup", poisoned)
        helper(rollback, "restore", poisoned,
               refusal="Restore PostgreSQL transaction failed; private diagnostics suppressed.")
        fixture(rollback, "empty")
        report("restore_rollback", "passed")

    def stop_broker(self):
        from imp024_verify import reap_children
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        reap_children(self.active)
        if self.runtime is not None:
            self.runtime.close(clean=True)
            self.runtime = None

    def check(self, stage, *args, output=None, seconds=300):
        self.stage(stage)
        try:
            self.compose("run", "--rm", "api-check", *args, output=output, seconds=seconds)
        except Exception:
            reasons = sorted(getattr(output, "reasons", ()))
            report(stage, "failed", category=reasons[0] if reasons else "operation")
            # Fixed lint/format filenames and codes from existing parsers only.
            for finding in getattr(output, "findings", ())[:16]:
                report(stage, "failed", **finding)
            raise
        report(stage, "passed")

    def run_native(self):
        import socket
        from imp005_connection import Connection, OwnedRuntime
        from imp024_operator_helper import MemberOutput
        self.stage("member")
        member = MemberOutput()
        self.compose("run", "--rm", "api-integration-check", "python", "-B",
                     "tests/imp024_operator_member.py", output=member)
        self.stage("broker")
        self.runtime = OwnedRuntime(self.inputs / "chat")
        self.connection = Connection(self.runtime, self.receiver.transport, mode="planning")
        self.connection.start()
        env = self.inputs / "fixture.env"
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        origin = "http://127.0.0.1:" + str(port)
        env.write_text(env.read_text().replace("APP_PORT=8080\n", f"APP_PORT={port}\n").replace(
            "IMPOSTR_PUBLIC_ORIGIN=http://127.0.0.1:8080\n", "IMPOSTR_PUBLIC_ORIGIN=" + origin + "\n")
            + "IMPOSTR_CHAT_CHANNEL_DIR=" + str(self.runtime.channel) + "\n")
        self.base += ["-f", str(ROOT / "compose.chat.yaml")]
        self.stage("api_start")
        self.compose("up", "-d", "--wait", "api", "frontdoor")
        self.product = Product(origin, member.login, self.receiver, self.stage)
        self.product.start()
        ordered, sent = self.product.main_flow()
        self.stage("native_outage")
        # Completed turns retain exact sent receipts after real API restart.
        prior_events = self.product.request("GET", self.product.base + "/events").json()["events"]
        prior_requests = len(self.receiver.observations)
        self.compose("restart", "api")
        self.compose("up", "-d", "--wait", "api")
        self.product.wait(sent["id"])
        require(self.product.request("GET", self.product.base + "/events").json()["events"] == prior_events
                and len(self.receiver.observations) == prior_requests)
        retired = self.connection.broker
        self.connection.close()
        require(all(turn.stopped.is_set() and turn.payload is None and turn.scratch is None
                    and turn.relay is None and turn.process is None for turn in retired.turns.values()))
        del retired
        self.connection = None  # Keep the channel inode/broker epoch; no new turn resubmit.
        attachment_path = self.product.base + "/attachments/" + ordered[0]["attachment_id"]
        self.product.request("DELETE", attachment_path, expected=202)
        self.product.send("SYNTHETIC NATIVE FENCED", expected=409)
        self.product.request("GET", attachment_path + "/raw", expected=404)
        self.connection = Connection(self.runtime, self.receiver.transport, mode="planning")
        self.connection.start()
        self.stage("native_purge")
        deadline = time.monotonic() + 130
        while time.monotonic() < deadline:
            result = self.product.request("DELETE", attachment_path, expected=(202, 204))
            if result.status_code == 204:
                break
            time.sleep(0.1)
        else:
            raise Unavailable()
        old = self.product.request("GET", self.product.base).json()
        original = next(row for row in old["turns"] if row["id"] == sent["id"])
        require(original["submission"]["status"] == "sent" and original["prompt"] == "SYNTHETIC NATIVE TOOL")
        # New broker contains only metadata tombstones for the purged turn; owned
        # scratch must have no turn/session/workspace content after the restart.
        require(set(self.runtime.scratch.iterdir()) == {self.runtime.scratch / "connection.lock"})
        require(sent["id"] in self.connection.broker.aborted_unknown)
        for turn in self.connection.broker.turns.values():
            require(turn.purged and turn.payload is None and not turn.events)
        events = self.product.request("GET", self.product.base + "/events").json()["events"]
        require(events == prior_events)
        require(any(row["data"].get("text") == "Synthetic native assistant quotation."
                    for row in events))
        before = len(self.receiver.observations)
        self.product.wait(sent["id"])
        require(len(self.receiver.observations) == before)
        future = self.product.wait(self.product.send("SYNTHETIC NATIVE DELETED HISTORY")["id"])
        files = [item for row in self.receiver.observations if row["turn_id"] == future["id"]
                 for item in row["manifest"]]
        require(files and all(item["attachment_id"] != ordered[0]["attachment_id"] for item in files))
        unavailable = [item for turn in old["turns"] for item in turn["references"]
                       if item["attachment_id"] == ordered[0]["attachment_id"]]
        require(unavailable and all(item["availability"] == "unavailable" for item in unavailable))
        report("native_outage", "passed")
        self.product.rejection_flow()
        self.product.bound_flow()
        require(self.connection.thread.is_alive() and not self.connection.failed.is_set())
        report("native_complete", "passed")

    def cleanup(self):
        targets_clean = True
        for target in reversed(self.restore_targets):
            targets_clean = target.cleanup() and targets_clean
        self.restore_targets.clear()
        if self.restore_files is not None:
            try:
                self.restore_files.cleanup()
            except Exception:
                targets_clean = False
            self.restore_files = None
        if self.base is not None and hasattr(self, "owner_overlay"):
            self.base += ["-f", str(self.owner_overlay)]
        closed = True
        try:
            if self.product is not None:
                self.product.close()
        except Exception:
            closed = False
        finally:
            self.product = None
        return super().cleanup() and closed and targets_clean

    def run(self):
        passed = False
        try:
            self.prepare()
            if self.restore_only:
                self.run_restore()
            else:
                self.stage("build")
                # The owner check service builds the one required development image
                # via run --build below; retirement needs no other application images.
                services = ("db",) if self.retirement_only else (
                    "db", "api", "api-check", "api-integration-check"
                )
                self.compose("build", *services, *(("frontdoor",) if self.synthetic else ()), seconds=600)
                self.stage("database")
                self.compose("up", "-d", "--wait", "db")
                self.stage("postgres")
                self.compose_used = True
                self.command(self.base + ["-f", str(self.owner_overlay), "run", "--build", "--rm",
                    "api-integration-owner-check", "python", "-m", "pytest", "-p", "no:cacheprovider",
                    "--tb=no", "--show-capture=no", "--color=no", "-s",
                    *((RETIREMENT_TEST,) if self.retirement_only else PG_TESTS)],
                    seconds=360, output=ResultOutput(expected=2 if self.retirement_only else 4))
                if not self.retirement_only:
                    self.stage("migration")
                    self.compose("run", "--rm", "api", "alembic", "upgrade", "head")
                    self.check("api_tests", "python", "-m", "pytest", "-p", "no:cacheprovider",
                        "--tb=no", "--show-capture=no", "--color=no", *API_TESTS, output=ResultOutput())
                    self.check("api_lint", "ruff", "check", "--output-format", "json", *API_FILES,
                        output=RuffJsonOutput(check_files=API_FILES))
                    self.check("api_format", "ruff", "format", "--check", *API_FILES,
                        output=CheckOutput("ruff_format", check_files=API_FILES))
                    self.check("api_types", "mypy", "app", output=CheckOutput("mypy", check_files=API_FILES))
                if self.synthetic:
                    self.run_native()
            passed = True
        except (Exception, KeyboardInterrupt) as error:
            category = ("assertion" if isinstance(error, AssertionError) else
                        "filesystem" if isinstance(error, OSError) else "operation")
            report("imp025_verification", "failed", phase=self.phase, category=category)
        finally:
            passed = self.cleanup() and passed
        report("imp025_verification", "passed" if passed else "failed")
        return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    parser.add_argument("--preflight", action="store_true")
    mode.add_argument("--api-only", action="store_true")
    mode.add_argument("--synthetic", action="store_true")
    mode.add_argument("--retirement-only", action="store_true")
    mode.add_argument("--restore-only", action="store_true")
    parser.add_argument("--reviewed-harness", action="store_true")
    parser.add_argument("--fingerprint")
    parser.add_argument("--frozen", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.preflight:
        if args.api_only or args.synthetic or args.retirement_only:
            parser.error("preflight accepts only optional --restore-only profile")
        if args.reviewed_harness or args.fingerprint or args.frozen:
            parser.error("preflight forbids execution flags")
    elif not args.reviewed_harness or not re.fullmatch(r"[0-9a-f]{64}", args.fingerprint or ""):
        parser.error("execution requires reviewed harness and exact fingerprint")
    elif not (args.api_only or args.synthetic or args.retirement_only or args.restore_only):
        parser.error("select an execution mode")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    parent = None
    try:
        if args.frozen:
            check_frozen(args.fingerprint, restore_only=args.restore_only)
            return NativeVerify(args.synthetic, retirement_only=args.retirement_only,
                                restore_only=args.restore_only).run()
        sources, head = capture(restore_only=args.restore_only)
        actual, metadata = fingerprint(sources, head, restore_only=args.restore_only)
        if args.preflight:
            report("preflight", "passed", baseline=metadata["base"], head=head, fingerprint=actual, files=len(sources),
                   boundary_executed=False)
            return 0
        require(actual == args.fingerprint)
        parent = Verify()
        parent.prepare()
        snapshot = parent.inputs / "source"
        freeze(snapshot, sources, metadata)
        require(fingerprint(*capture(restore_only=args.restore_only), restore_only=args.restore_only)[0] == actual)
        execution_mode = ("--restore-only" if args.restore_only else "--retirement-only" if args.retirement_only else
                          "--synthetic" if args.synthetic else "--api-only")
        parent.command(["/usr/bin/python3", "-I", "-B", str(snapshot / "scripts/imp025_verify.py"),
            execution_mode, "--reviewed-harness", "--fingerprint", actual,
            "--frozen"], seconds=1800, output=SafeOutput())
        return 0
    except (Exception, KeyboardInterrupt):
        report("snapshot_execution", "failed", category="operation")
        return 1
    finally:
        if parent is not None and not parent.cleanup():
            # Cleanup failure is never hidden by a successful return above.
            raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
