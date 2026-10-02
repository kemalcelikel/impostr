"""COORDINATOR ONLY: owned synthetic PDF intake/API/DB verification.

Independent review is required before execution. This harness verifies upload and
durable intake only: it never starts an extractor, broker, worker or model. All
Compose input and cleanup reuse the reviewed IMP-024 coordinator verifier. Child
output is discarded except for fixed stages and allowlisted diagnostics.
"""

import json
import os
import re
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imp024_verify import (  # noqa: E402
    CheckOutput,
    ROOT,
    RuffJsonOutput,
    Unavailable,
    Verify,
    report,
    require,
)

API_CHECK_FILES = (
    "app/models.py",
    "app/attachments.py",
    "app/pdf_intake.py",
    "migrations/versions/20261002_0008_private_pdf_intake.py",
    "tests/test_attachments.py",
    "tests/test_attachments_migration.py",
    "tests/test_attachments_postgres.py",
)
EXPECTED_HEAD = "20261002_0009"
POSTGRES_STAGES = frozenset(
    {
        "schema_create",
        "preservation_base_migration",
        "preservation_seed",
        "preservation_snapshot",
        "preservation_upgrade",
        "preservation_history",
        "preservation_original",
        "preservation_retained_downgrade",
        "preservation_constraint_size_cap",
        "preservation_constraint_size_match",
        "preservation_constraint_failed_blob",
        "preservation_constraint_ready",
        "preservation_constraint_lease",
        "preservation_delete",
        "preservation_empty_downgrade",
        "preservation_reupgrade",
        "schema_types",
        "schema_conversation_fk",
        "api_account",
        "api_startup",
        "api_setup",
        "roundtrip_upload",
        "roundtrip_stored_original",
        "roundtrip_raw",
        "roundtrip_pending_metadata",
        "roundtrip_derivative_commit",
        "roundtrip_preview",
        "roundtrip_delete",
        "overcap_upload",
        "overcap_discarded_blob",
        "overcap_metadata",
        "overcap_recovery",
        "api_shutdown",
        "owned_cleanup",
        "unknown",
    }
)
POSTGRES_CATEGORIES = frozenset(
    {"assertion", "expected_exception_missing", "integrity", "database", "filesystem", "unexpected"}
)
UPLOAD_ROUTE = r"^/api/projects/[0-9a-fA-F-]{36}/chat/[0-9a-fA-F-]{36}/attachments/upload$"
UPLOAD_PATH = (
    "/api/projects/12345678-1234-1234-1234-123456789abc/"
    "chat/abcdefab-cdef-abcd-efab-cdefabcdefab/attachments/upload"
)
POSTGRES_OWNER_SERVICE = "api-integration-owner-check"


def postgres_owner_overlay(root=ROOT):
    """Give only the disposable fresh-schema test the generated DB owner login."""
    compose_file = json.dumps(str(root / "compose.yaml"))
    return (
        "services:\n"
        f"  {POSTGRES_OWNER_SERVICE}:\n"
        "    extends:\n"
        f"      file: {compose_file}\n"
        "      service: api-integration-check\n"
        "    environment:\n"
        "      DB_USER: ${POSTGRES_USER:?Set POSTGRES_USER in fixture}\n"
        "      DB_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in fixture}\n"
    )


def validate_upload_route_config(config):
    """Check the effective Nginx config's exact upload exception and fallback."""
    blocks = re.findall(
        r'^\s*location\s+~\s+"([^"]+)"\s*\{(.*?)^\s*\}',
        config,
        re.MULTILINE | re.DOTALL,
    )
    upload_blocks = [body for route, body in blocks if route == UPLOAD_ROUTE]
    require(len(upload_blocks) == 1)
    upload = upload_blocks[0]
    for directive in (
        "limit_except POST { deny all; }",
        "client_max_body_size 50000000;",
        "proxy_request_buffering off;",
    ):
        require(directive in upload)
    # The exception matches only the UUID-shaped upload endpoint, not siblings.
    route = re.compile(UPLOAD_ROUTE)
    require(route.fullmatch(UPLOAD_PATH))
    require(not route.fullmatch(UPLOAD_PATH + "/raw"))
    require(not route.fullmatch(UPLOAD_PATH.replace("/attachments/upload", "/attachments")))
    require(not route.fullmatch(UPLOAD_PATH.replace("/projects/", "/other/", 1)))

    api_blocks = re.findall(
        r'^\s*location\s+/api/\s*\{(.*?)^\s*\}',
        config,
        re.MULTILINE | re.DOTALL,
    )
    require(len(api_blocks) == 1 and "client_max_body_size 1m;" in api_blocks[0])
    # The 50 MB allowance must not leak into any other location.
    require(config.count("client_max_body_size 50000000;") == 1)


class NginxConfigOutput:
    """Parse `nginx -T` in memory; never forward the dumped configuration."""

    stdout_only = True

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, block):
        require(len(self.buffer) + len(block) <= 256 * 1024)
        self.buffer.extend(block)

    def finish(self):
        try:
            validate_upload_route_config(self.buffer.decode("utf-8"))
        except Exception:
            raise Unavailable() from None
        finally:
            self.buffer.clear()


class HeadOutput:
    """Accept only the expected current Alembic head, suppress other output."""

    def __init__(self):
        self.buffer = bytearray()
        self.found = False

    def feed(self, block):
        self.buffer.extend(block)
        require(len(self.buffer) <= 64 * 1024)
        while b"\n" in self.buffer:
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer[:] = rest
            self.line(line.rstrip(b"\r"))

    def line(self, line):
        if re.fullmatch(EXPECTED_HEAD.encode() + rb"(?:\s+\(head\))?", line.strip()):
            self.found = True

    def finish(self):
        if self.buffer:
            self.line(bytes(self.buffer).rstrip(b"\r"))
        require(self.found)
        self.buffer.clear()


class PostgresTestOutput(CheckOutput):
    """Require the one fresh-schema PostgreSQL test to execute, not skip."""

    def __init__(self):
        super().__init__("pytest", check_files=API_CHECK_FILES)
        self.executed = False

    def line(self, line):
        super().line(line)
        if line.startswith(b'{"diagnostic":'):
            try:
                require(len(line) <= 2048)
                value = json.loads(line)
                require(
                    isinstance(value, dict)
                    and value.get("diagnostic") == "imp017_intake_postgres"
                    and value.get("stage") in POSTGRES_STAGES
                    and value.get("category") in POSTGRES_CATEGORIES
                )
                # Reconstruct: arbitrary child fields/values never enter the report.
                finding = {"stage": value["stage"], "category": value["category"]}
                if finding not in self.findings:
                    require(len(self.findings) < 8)
                    self.findings.append(finding)
            except Exception:
                self.reasons.add("postgres_diagnostic_unavailable")
        if re.fullmatch(
            rb"(?:=+\s+)?1 passed(?:, [0-9]+ warnings?)?(?: in [0-9.]+s)?(?:\s+=+)?",
            line.strip(),
        ):
            self.executed = True

    def finish(self):
        require(self.executed)


class IntakeVerify(Verify):
    def __init__(self):
        super().__init__()
        self.phase = "prepare"
        self.postgres_owner_overlay = None

    def write_postgres_owner_overlay(self):
        overlay_name = "postgres-owner.compose.yaml"
        fd = os.open(
            overlay_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.directories[self.inputs],
        )
        with os.fdopen(fd, "w", encoding="ascii") as output:
            output.write(postgres_owner_overlay())
        self.postgres_owner_overlay = self.inputs / overlay_name

    def cleanup(self):
        if self.postgres_owner_overlay is None:
            return super().cleanup()
        original_base = self.base
        self.base = original_base + ["-f", str(self.postgres_owner_overlay)]
        try:
            # Include the separately built test service in Compose down / --rmi local.
            return super().cleanup()
        finally:
            self.base = original_base

    def stage(self, phase):
        self.phase = phase

    def check(self, stage, *args, output, seconds=300):
        self.stage(stage)
        try:
            self.compose("run", "--rm", *args, seconds=seconds, output=output)
        except Exception:
            report(
                stage + "_diagnostic",
                "failed",
                reasons=sorted(getattr(output, "reasons", ()))
                or ["check_operation_failed"],
                findings=getattr(output, "findings", []),
            )
            raise
        report(stage, "passed")

    def check_postgres_owner(self, stage, *args, output, seconds=300):
        require(stage == "postgres_attachments")
        require(
            args
            == (
                POSTGRES_OWNER_SERVICE,
                "python",
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--capture=tee-sys",
                "--tb=no",
                "tests/test_attachments_postgres.py",
            )
        )
        self.stage(stage)
        try:
            require(self.postgres_owner_overlay is not None)
            self.compose_used = True
            self.command(
                self.base
                + [
                    "-f",
                    str(self.postgres_owner_overlay),
                    "run",
                    "--build",
                    "--rm",
                    *args,
                ],
                seconds=seconds,
                output=output,
            )
        except Exception:
            report(
                stage + "_diagnostic",
                "failed",
                reasons=sorted(getattr(output, "reasons", ()))
                or ["check_operation_failed"],
                findings=getattr(output, "findings", []),
            )
            raise
        report(stage, "passed")

    def run(self):
        passed = False
        try:
            self.stage("prepare")
            self.prepare()
            self.write_postgres_owner_overlay()
            for stage, args, seconds in (
                (
                    "build",
                    ("build", "db", "api", "api-check", "api-integration-check", "frontdoor"),
                    600,
                ),
                ("database", ("up", "-d", "--wait", "db"), 180),
                ("migration", ("run", "--rm", "api", "alembic", "upgrade", "head"), 180),
            ):
                self.stage(stage)
                self.compose(*args, seconds=seconds)
                report(stage, "passed")

            self.check(
                "migration_current",
                "api",
                "alembic",
                "current",
                output=HeadOutput(),
            )
            self.check(
                "focused_tests",
                "api-check",
                "python",
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "tests/test_attachments.py",
                "tests/test_attachments_migration.py",
                "tests/test_chat.py",
                "tests/test_migrations.py",
                output=CheckOutput("pytest", check_files=API_CHECK_FILES),
                seconds=300,
            )
            self.check_postgres_owner(
                "postgres_attachments",
                POSTGRES_OWNER_SERVICE,
                "python",
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--capture=tee-sys",
                "--tb=no",
                "tests/test_attachments_postgres.py",
                output=PostgresTestOutput(),
                seconds=300,
            )
            self.check(
                "ruff_lint",
                "api-check",
                "ruff",
                "check",
                "--output-format",
                "json",
                *API_CHECK_FILES,
                output=RuffJsonOutput(check_files=API_CHECK_FILES),
            )
            self.check(
                "ruff_format",
                "api-check",
                "ruff",
                "format",
                "--check",
                *API_CHECK_FILES,
                output=CheckOutput("ruff_format", check_files=API_CHECK_FILES),
            )
            self.check(
                "mypy",
                "api-check",
                "mypy",
                "app",
                output=CheckOutput("mypy", check_files=API_CHECK_FILES),
            )

            self.check(
                "nginx_config_test",
                "--no-deps",
                "frontdoor",
                "nginx",
                "-t",
                output=CheckOutput("nginx_config", check_files=()),
            )
            self.check(
                "nginx_route_scope",
                "--no-deps",
                "frontdoor",
                "nginx",
                "-T",
                output=NginxConfigOutput(),
            )
            passed = True
        except (Exception, KeyboardInterrupt) as error:
            reason = (
                "filesystem_operation"
                if isinstance(error, OSError)
                else "interrupted"
                if isinstance(error, KeyboardInterrupt)
                else "operation_failed"
            )
            report("intake_stage", "failed", phase=self.phase, reason=reason)
        finally:
            passed = self.cleanup() and passed
        report("synthetic_pdf_intake_verification", "passed" if passed else "failed")
        return 0 if passed else 1


def main():
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    return IntakeVerify().run()


if __name__ == "__main__":
    raise SystemExit(main())
