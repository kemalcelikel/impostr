"""End-to-end runner guards using a fake OpenCode command and temporary repositories."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SELECT_SPRINT = "Use the installed `sprint-workflow` skill for branching and pull requests."


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "app"
        self.project.mkdir()
        scripts = self.project / "scripts"
        scripts.mkdir(parents=True)
        (self.project / ".opencode").mkdir()
        (self.project / ".gitignore").write_text(".opencode/\n")
        shutil.copy(ROOT / "run-tonight.sh", self.project / "run-tonight.sh")
        shutil.copy(ROOT / "scripts" / "backlog.py", scripts / "backlog.py")
        (self.project / "PROJECT.md").write_text("# Project\n")
        (self.project / "AGENTS.md").write_text("# Instructions\n")
        (self.project / "BACKLOG.md").write_text(
            "# Backlog\n\n## [ ] TASK-001 — First\nDo first\n\n"
            "## [ ] TASK-002 — Second\nDo second\n"
        )

        bin_dir = Path(self.temp.name) / "bin"
        bin_dir.mkdir()
        opencode = bin_dir / "opencode"
        opencode.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys\n"
            "pathlib.Path('.opencode/assignment.txt').write_text(sys.argv[-1])\n"
            "counter = pathlib.Path('.opencode/invocations')\n"
            "counter.write_text(str(int(counter.read_text()) + 1 if counter.exists() else 1))\n"
            "if os.environ.get('FAKE_OUTCOME') == 'complete':\n"
            "    backlog = pathlib.Path('BACKLOG.md')\n"
            "    backlog.write_text(backlog.read_text().replace('## [~]', '## [x]', 1))\n"
            "else:\n"
            "    sys.exit(1)\n"
        )
        opencode.chmod(0o755)
        for name in ("sbx", "sleep"):
            command = bin_dir / name
            command.write_text("#!/bin/sh\nexit 1\n" if name == "sbx" else "#!/bin/sh\nexit 0\n")
            command.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.project, check=True,
                              capture_output=True, text=True).stdout.strip()

    def init_repo(self):
        self.git("init", "-q")
        self.git("add", "AGENTS.md", "BACKLOG.md", "PROJECT.md", "scripts/backlog.py",
                 "run-tonight.sh", ".gitignore")
        self.git("-c", "user.name=Runner Test", "-c", "user.email=runner@example.com",
                 "commit", "-qm", "initial")

    def run_runner(self, *, complete=False):
        return subprocess.run(["bash", "./run-tonight.sh"], cwd=self.project,
                              env={**self.env, "FAKE_OUTCOME": "complete" if complete else "fail"},
                              capture_output=True, text=True, timeout=20)

    def test_non_repo_stops_without_claiming_or_committing(self):
        before = (self.project / "BACKLOG.md").read_text()
        result = self.run_runner()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("existing Git checkout", result.stdout)
        self.assertEqual((self.project / "BACKLOG.md").read_text(), before)
        self.assertFalse((self.project / ".git").exists())

    def test_failed_sessions_stop_after_three_without_losing_ready_items(self):
        self.init_repo()
        result = self.run_runner()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STOPPED FOR REVIEW", result.stdout)
        self.assertEqual((self.project / ".opencode" / "invocations").read_text(), "3")
        self.assertEqual((self.project / "BACKLOG.md").read_text().count("## [ ]"), 2)

    def test_dependency_waits_for_prior_outcome(self):
        (self.project / "BACKLOG.md").write_text(
            "# Backlog\n\n## [ ] TASK-002 — Dependent\n**Depends on:** TASK-001\n\n"
            "## [ ] TASK-001 — Prerequisite\n**Depends on:** None\n"
        )
        self.init_repo()
        result = self.run_runner(complete=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.project / ".opencode" / "invocations").read_text(), "2")
        self.assertIn("## [x] TASK-001", (self.project / "BACKLOG.md").read_text())
        self.assertIn("## [x] TASK-002", (self.project / "BACKLOG.md").read_text())

    def test_sprint_allows_only_one_item_then_requires_reconciliation(self):
        self.init_repo()
        (self.project / "AGENTS.md").write_text(SELECT_SPRINT + "\n")
        backlog = self.project / "BACKLOG.md"
        backlog.write_text("Sprint branch: custom-sprint\n\n" + backlog.read_text())
        self.git("add", "AGENTS.md", "BACKLOG.md")
        self.git("-c", "user.name=Runner Test", "-c", "user.email=runner@example.com",
                 "commit", "-qm", "sprint setup")
        self.git("switch", "-qc", "custom-sprint")
        self.git("update-ref", "refs/remotes/origin/custom-sprint", "HEAD")

        result = self.run_runner(complete=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Sprint run stopped after one task", result.stdout)
        self.assertEqual((self.project / ".opencode" / "invocations").read_text(), "1")
        self.assertIn("A later run begins on the fetched, reconciled sprint branch",
                      (self.project / ".opencode" / "assignment.txt").read_text())
        self.assertIn("## [x] TASK-001", backlog.read_text())
        self.assertIn("## [ ] TASK-002", backlog.read_text())

        self.git("switch", "-qc", "feature/first")
        self.git("add", "BACKLOG.md")
        self.git("-c", "user.name=Runner Test", "-c", "user.email=runner@example.com",
                 "commit", "-qm", "task status")
        before = backlog.read_text()
        second = self.run_runner(complete=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("Start sprint work on custom-sprint", second.stdout)
        self.assertEqual(backlog.read_text(), before)
        self.assertEqual((self.project / ".opencode" / "invocations").read_text(), "1")

    def test_sprint_refuses_stale_baseline_before_claiming(self):
        self.init_repo()
        (self.project / "AGENTS.md").write_text(SELECT_SPRINT + "\n")
        backlog = self.project / "BACKLOG.md"
        backlog.write_text("Sprint branch: sprint-v29\n\n" + backlog.read_text())
        self.git("add", "AGENTS.md", "BACKLOG.md")
        self.git("-c", "user.name=Runner Test", "-c", "user.email=runner@example.com",
                 "commit", "-qm", "sprint setup")
        self.git("switch", "-qc", "sprint-v29")
        self.git("update-ref", "refs/remotes/origin/sprint-v29", "HEAD~1")
        before = backlog.read_text()

        result = self.run_runner(complete=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Fetch and align", result.stdout)
        self.assertEqual(backlog.read_text(), before)
        self.assertFalse((self.project / ".opencode" / "invocations").exists())

    def test_dirty_sprint_checkout_runs_without_committing_partial_code(self):
        (self.project / "AGENTS.md").write_text(SELECT_SPRINT + "\n")
        backlog = self.project / "BACKLOG.md"
        backlog.write_text("Sprint branch: custom-sprint\n\n" + backlog.read_text())
        self.init_repo()
        self.git("switch", "-qc", "custom-sprint")
        self.git("update-ref", "refs/remotes/origin/custom-sprint", "HEAD")
        backlog.write_text(backlog.read_text().replace("## [ ] TASK-001", "## [~] TASK-001"))
        (self.project / "partial.py").write_text("broken but preserved\n")
        initial_commit = self.git("rev-parse", "HEAD")

        result = self.run_runner(complete=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("## [x] TASK-001", backlog.read_text())
        self.assertIn("## [ ] TASK-002", backlog.read_text())
        self.assertEqual((self.project / "partial.py").read_text(), "broken but preserved\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), initial_commit)


if __name__ == "__main__":
    unittest.main()
