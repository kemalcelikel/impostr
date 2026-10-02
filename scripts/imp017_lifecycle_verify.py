"""COORDINATOR ONLY, after review: focused joined lifecycle, NOT sandbox re-verification.

Reuses IntakeVerify owned inputs/cleanup and existing phase-one converter packaging.
Validates existing extractor contents without executing them. Only if its shared tag
is absent, reconstructs unchanged pinned inputs under a unique owned tag. Never
replaces/removes a pre-existing image. No sandbox reacceptance or private host inputs.
"""

import argparse
import hashlib
import io
import json
import os
import re
import selectors
import signal
import subprocess
import tarfile
import time

from imp017_intake_verify import IntakeVerify, POSTGRES_OWNER_SERVICE, PostgresTestOutput
from imp024_verify import ROOT, CheckOutput, EmptyOutput, report, require, stop_process

PASSES = (
    "PASS transient recovery and actual ready provenance",
    "PASS actual busy admission and durable retry",
    "PASS terminal failures remove retained blobs",
    "PASS delete during actual extraction cannot resurrect",
    "PASS API process crash lease recovery",
    "PASS PostgreSQL concurrent lease ownership",
    "PASS revoked attachment access denied",
    "PASS joined owned cleanup",
)
FILES = ("app/pdf_lifecycle.py", "app/pdf_lifecycle_policy.py", "app/pdf_extractor.py",
         "app/config.py", "app/main.py", "app/attachments.py", "app/models.py",
         "migrations/versions/20261002_0009_pdf_retry.py", "tests/test_pdf_lifecycle.py",
         "tests/test_pdf_retry_migration.py", "tests/imp017_lifecycle_joined.py")
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]
SHARED_IMAGE = "impostr-pdf:phase1"
VERIFIED_BUILD_SHA256 = "b976249ca1a5aea47689ac9210b15611b6b9c88ab9c337f766e5e1569faa4192"
BASE_IGNORE_SHA256 = "2a5c4d265dc4bea3149b6a36d51c1971c7017f6e849c8998ddfcf53de193f40c"
FIXTURE_ALLOWANCE = b"!scripts/imp017_fixtures.py\n"
PACKAGED_SOURCES = {
    "worker": {name: "pdf-extractor/" + name for name in (
        "worker.py", "structure.py", "bounded_json.py", "process.py", "bootstrap.py", "probe.py")},
    "supervisor": {name: "pdf-extractor/" + name for name in ("supervisor.py", "process.py")},
}
for sources in PACKAGED_SOURCES.values():
    sources["pdf_protocol.py"] = "api/app/pdf_protocol.py"

# Exact focused test function names only. Parametrized IDs, messages and source
# snippets are NEVER projected, even when pytest puts them in its short summary.
FOCUSED_TESTS = {
    "tests/test_pdf_lifecycle.py": frozenset({
        "test_claim_commit_before_io_ready_provenance_and_restart",
        "test_shutdown_drains_inflight_job_and_leaves_next_pending",
        "test_atomic_claim_concurrency_expiry_stale_completion_and_crash_budget",
        "test_transient_durable_backoff_recovery_and_exhaustion",
        "test_terminal_rejections_clear_blobs_without_retry",
        "test_delete_cascade_during_io_prevents_orphans_and_resurrection",
        "test_unverified_build_or_bad_result_is_never_persisted",
        "test_revoked_session_cannot_read_or_delete_ready_and_processing_is_server_owned",
        "test_lifespan_pdf_independent_of_chat_and_owned_shutdown",
        "test_pdf_configuration_defaults_off_and_rejects_ambiguous_flag",
    }),
    "tests/test_pdf_retry_migration.py": frozenset({
        "test_0008_pending_bytes_preserved_and_lossy_downgrade_denied",
    }),
    "tests/test_attachments.py": frozenset({
        "test_pending_commit_exact_download_escaped_ready_preview_and_delete",
        "test_real_overcap_stream_rejected_independent_of_content_length",
        "test_envelope_failures_retain_only_safe_metadata",
        "test_scope_revocation_csrf_and_filename_denials",
        "test_rechecks_authority_after_body_before_commit",
        "test_interrupted_upload_discards_partial_blob_and_retains_failure",
        "test_metadata_queries_do_not_fetch_deferred_blobs_and_admin_reads_are_audited",
    }),
    "tests/test_attachments_migration.py": frozenset({
        "test_pdf_intake_migration_preserves_approvals_chat_and_rejects_loss",
    }),
}


class FocusedTestOutput(CheckOutput):
    """Offline short-summary projection; no pytest plugin or execution changes."""

    def __init__(self):
        super().__init__("pytest", check_files=tuple(FOCUSED_TESTS))
        self.findings = [{"file": "unknown", "test": "unknown", "category": "unknown"}]

    def line(self, line):
        super().line(line)
        if len(line) > 4096:
            return
        match = re.fullmatch(
            rb"(?:FAILED|ERROR) (tests/[a-z_]+\.py)::(test_[a-z0-9_]+)"
            rb"(?:\[[^\r\n]{0,256}\])?(?: - ([^\r\n]{0,1024}))?", line)
        if match is None:
            return
        filename, test = (value.decode("ascii") for value in match.group(1, 2))
        if test not in FOCUSED_TESTS.get(filename, ()):
            return
        detail = match.group(3) or b""
        category = "assertion" if re.match(rb"(?:AssertionError\b|assert(?: |$))", detail) else "unknown"
        finding = {"file": filename, "test": test, "category": category}
        if self.findings[0]["file"] == "unknown":
            self.findings.clear()
        if finding not in self.findings and len(self.findings) < 16:
            self.findings.append(finding)


class ImageOutput:
    stdout_only = True

    def __init__(self, optional=False):
        self.buffer = bytearray()
        self.optional = optional
        self.image = None

    def feed(self, block):
        self.buffer.extend(block)
        require(len(self.buffer) <= 256)

    def finish(self):
        value = bytes(self.buffer)
        if value or not self.optional:
            require(re.fullmatch(rb"sha256:[0-9a-f]{64}\n", value))
            self.image = value.decode("ascii").removesuffix("\n")
        self.buffer.clear()


class PackagedOutput:
    """Hash bounded Docker cp tar bytes locally; never execute an unverified image."""

    stdout_only = True

    def __init__(self, expected):
        self.expected = expected
        self.buffer = bytearray()

    def feed(self, block):
        self.buffer.extend(block)
        require(len(self.buffer) <= 2 * 1024 * 1024)

    def finish(self):
        try:
            seen = set()
            with tarfile.open(fileobj=io.BytesIO(self.buffer), mode="r:") as archive:
                for member in archive:
                    if member.name in (".", "./") and member.isdir():
                        continue
                    name = member.name.removeprefix("./")
                    require(member.isfile() and name in self.expected and name not in seen)
                    require(0 <= member.size <= 2 * 1024 * 1024)
                    with archive.extractfile(member) as source:
                        require(hashlib.sha256(source.read()).hexdigest() == self.expected[name])
                    seen.add(name)
            require(seen == set(self.expected))
        finally:
            self.buffer.clear()


class JoinedOutput:
    def __init__(self, start):
        self.start = start
        self.buffer = bytearray()
        self.passed = set()
        self.started = False

    def feed(self, block):
        self.buffer.extend(block)
        require(len(self.buffer) <= 8192)
        while b"\n" in self.buffer:
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer[:] = rest
            text = line.decode("ascii")
            if text == "ACTION pdf-start":
                require(not self.started)
                self.started = True
                self.start()
            elif text in PASSES:
                self.passed.add(text)
                report(text.removeprefix("PASS "), "passed")
            elif text.startswith('{"diagnostic":'):
                # Project fixed enums only, never child exceptions/SQL/text.
                value = json.loads(text)
                stage = value.get("stage")
                require(stage in {"prepare", "unavailable", "ready", "busy", "rejected", "delete",
                                   "restart", "revocation", "shutdown", "cleanup", "unknown"})
                require(value.get("category") in {"assertion", "operation"})
                report("joined_diagnostic", "failed", stage=stage, category=value["category"])
            else:
                require(False)

    def finish(self):
        require(not self.buffer and self.started and set(PASSES) == self.passed)


class LifecycleVerify(IntakeVerify):
    def __init__(self):
        super().__init__()
        self.extractor_image = None
        self.reconstructed_tag = None
        self.reconstructed_image = None

    def prepare(self):
        super().prepare()
        # Remove the inherited synthetic chat overlay: no broker mounted or started.
        self.base = self.base[:-2] + ["-f", str(ROOT / "compose.pdf-app.yaml")]
        overlay = self.inputs / "lifecycle.compose.yaml"
        fd = os.open("lifecycle.compose.yaml", os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600, dir_fd=self.directories[self.inputs])
        with os.fdopen(fd, "w") as output:
            output.write(
                "services:\n  api-integration-check:\n    environment:\n"
                "      IMPOSTR_PDF_ENABLED: '1'\n      IMPOSTR_CHAT_ENABLED: '0'\n"
                "      IMPOSTR_TEST_PDF_LIFECYCLE: '1'\n"
                "    volumes:\n      - pdf-channel:/run/impostr-pdf:ro\n"
                "    stop_grace_period: 55s\n"
            )
        self.base += ["-f", str(overlay)]

    def validate_sources(self):
        # Approved phase-one input equality, including lock/build/bootstrap/seccomp.
        # The sole .dockerignore delta permits the API development fixture COPY.
        self.command(["git", "diff", "--no-ext-diff", "--no-textconv", "--exit-code",
                      "ca09dc3", "--", "pdf-extractor", "compose.pdf.yaml",
                      "api/app/pdf_protocol.py"], output=EmptyOutput())
        ignore = ROOT / ".dockerignore"
        require(not ignore.is_symlink())
        content = ignore.read_bytes()
        require(content.count(FIXTURE_ALLOWANCE) == 1)
        require(hashlib.sha256(content.replace(FIXTURE_ALLOWANCE, b"", 1)).hexdigest()
                == BASE_IGNORE_SHA256)
        override = ROOT / "pdf-extractor/Dockerfile.dockerignore"
        require(not override.exists() and not override.is_symlink())

    def image_at(self, tag):
        output = ImageOutput(optional=True)
        # A successful empty inventory alone means absent; daemon/CLI errors fail.
        self.command(DOCKER + ["image", "ls", "--no-trunc", "--format", "{{.ID}}",
                               "--filter", "reference=" + tag], output=output)
        return output.image

    def write_image_overlay(self, filename, image):
        fd = os.open(filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600, dir_fd=self.directories[self.inputs])
        with os.fdopen(fd, "w") as output:
            output.write("services:\n  pdf-extractor:\n    image: " + json.dumps(image) + "\n")
        return str(self.inputs / filename)

    def ensure_extractor(self):
        self.stage("extractor_source_inputs")
        self.validate_sources()
        self.stage("verified_image_available")
        image = self.image_at(SHARED_IMAGE)
        if image is None:
            # Separate namespace from inherited API/DB image-inventory cleanup.
            tag = "impostr-pdf-reconstruct:" + self.project
            require(self.image_at(tag) is None)
            overlay = self.write_image_overlay("extractor-build.compose.yaml", tag)
            # Never write the shared tag, even if another process creates it now.
            self.reconstructed_tag = tag
            self.stage("reconstruct_pinned_extractor")
            try:
                self.command(DOCKER + ["compose", "--env-file", "/dev/null", "-p", self.project,
                                      "-f", str(ROOT / "compose.pdf.yaml"), "-f", overlay,
                                      "build", "pdf-extractor"], seconds=900)
            finally:
                # Also identify a completed export if the CLI subsequently failed.
                self.reconstructed_image = self.image_at(tag)
            image = self.reconstructed_image
            require(image is not None)
        self.validate_sources()
        self.stage("extractor_provenance")
        name = self.project + "-extractor-provenance"
        self.command(DOCKER + ["ps", "-aq", "--filter", "name=^" + name + "$"],
                     output=EmptyOutput())
        self.runs.append(name)
        # Created but NEVER started: Docker cp checks actual image filesystem bytes,
        # not claims made by its Python interpreter, labels or mutable tag.
        self.command(DOCKER + ["create", "--name", name, "--pull", "never",
                              "--user", "10002:10002", "--network", "none", "--read-only",
                              "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                              "--security-opt", "seccomp=" + str(ROOT / "pdf-extractor/seccomp.json"),
                              "--memory", "512m", "--memory-swap", "512m", "--cpus", "1",
                              "--pids-limit", "16", "--shm-size", "1m", image])
        for directory, sources in PACKAGED_SOURCES.items():
            expected = {target: hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
                        for target, source in sources.items()}
            expected["build.json"] = VERIFIED_BUILD_SHA256
            self.command(DOCKER + ["cp", name + ":/" + directory + "/.", "-"],
                         output=PackagedOutput(expected), seconds=30)
        self.command(DOCKER + ["rm", name])
        self.runs.remove(name)
        self.extractor_image = image
        self.base += ["-f", self.write_image_overlay("extractor-pinned.compose.yaml", image)]
        report("extractor_provenance", "passed", source_base="ca09dc3",
               build_sha256=VERIFIED_BUILD_SHA256, image=image)

    def cleanup(self):
        # First remove the owned containers/stack. A pre-existing/shared image is
        # never adopted; only our exclusively reserved reconstruction tag is removed.
        okay = super().cleanup()
        if self.reconstructed_tag is not None:
            try:
                image = self.image_at(self.reconstructed_tag)
                if image is not None:
                    require(image == self.reconstructed_image)
                    self.command(DOCKER + ["image", "rm", self.reconstructed_tag])
                require(self.image_at(self.reconstructed_tag) is None)
                report("cleanup_reconstructed_extractor", "passed")
            except Exception:
                okay = False
                report("cleanup_reconstructed_extractor", "failed")
        return okay

    def joined(self):
        name = self.project + "-joined"
        self.runs.append(name)
        self.compose_used = True
        self.check_directories()
        process = subprocess.Popen(
            self.base + ["run", "--rm", "--no-deps", "-T", "--name", name,
                         "api-integration-check", "python", "-B",
                         "tests/imp017_lifecycle_joined.py", "check"],
            cwd=ROOT, env=self.environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        self.active.add(process.pid)

        def start():
            # Uses the validated immutable ID overlay; no tag resolution/build here.
            self.compose("up", "-d", "--no-build", "--pull", "never", "pdf-extractor", seconds=30)
            process.stdin.write(b"\n")
            process.stdin.flush()

        output = JoinedOutput(start)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        selector.register(process.stderr, selectors.EVENT_READ)
        stderr_size = 0
        deadline = time.monotonic() + 300
        try:
            while selector.get_map():
                require(time.monotonic() < deadline)
                for key, _ in selector.select(0.1):
                    block = os.read(key.fileobj.fileno(), 4096)
                    if not block:
                        selector.unregister(key.fileobj)
                    elif key.fileobj is process.stdout:
                        output.feed(block)
                    else:
                        stderr_size += len(block)
                        require(stderr_size <= 65536)  # Discard, never display.
            require(process.wait(timeout=5) == 0)
            output.finish()
        finally:
            selector.close()
            stop_process(process)
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()
            self.active.discard(process.pid)

    def run(self):
        passed = False
        try:
            self.prepare()
            self.write_postgres_owner_overlay()
            self.ensure_extractor()
            self.stage("build_api_db")
            self.compose("build", "db", "api", "api-check", "api-integration-check", seconds=600)
            # Initialize the named volume from the converter's UID-owned 0711
            # image directory BEFORE any API-only migration mount. Do not start it:
            # the first joined upload must observe a genuine unavailable channel.
            self.compose("create", "--no-build", "--pull", "never", "pdf-extractor")
            self.compose("up", "-d", "--wait", "db", seconds=180)
            self.compose("run", "--rm", "--no-deps", "api", "alembic", "upgrade", "head")
            self.check("focused_lifecycle", "api-check", "python", "-m", "pytest", "-p",
                       "no:cacheprovider", "tests/test_pdf_lifecycle.py",
                       "tests/test_pdf_retry_migration.py", "tests/test_attachments.py",
                       "tests/test_attachments_migration.py",
                        output=FocusedTestOutput())
            self.check("lifecycle_static", "api-check", "ruff", "check", *FILES,
                       output=CheckOutput("ruff_lint", check_files=FILES))
            self.check("lifecycle_format", "api-check", "ruff", "format", "--check", *FILES,
                       output=CheckOutput("ruff_format", check_files=FILES))
            self.check("lifecycle_types", "api-check", "mypy", "app",
                       output=CheckOutput("mypy", check_files=FILES))
            self.check_postgres_owner(
                "postgres_attachments", POSTGRES_OWNER_SERVICE, "python", "-m", "pytest",
                "-p", "no:cacheprovider", "--capture=tee-sys", "--tb=no",
                "tests/test_attachments_postgres.py", output=PostgresTestOutput(),
            )
            self.stage("joined")
            self.joined()
            passed = True
        except (Exception, KeyboardInterrupt):
            report("lifecycle_stage", "failed", phase=self.phase)
        finally:
            passed = self.cleanup() and passed
        report("synthetic_pdf_lifecycle", "passed" if passed else "failed")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewed-lifecycle", action="store_true", required=True)
    parser.parse_args()
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    return LifecycleVerify().run()


if __name__ == "__main__":
    raise SystemExit(main())
