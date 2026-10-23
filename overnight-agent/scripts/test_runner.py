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
            "if os.environ.get('FAKE_OUTCOME') in ('complete', 'block-first'):\n"
            "    import subprocess\n"
            "    sprint = 'sprint-workflow' in pathlib.Path('AGENTS.md').read_text()\n"
            "    if sprint:\n"
            "        number = counter.read_text()\n"
            "        subprocess.run(['git', 'switch', '-qc', 'feature/task-' + number], check=True)\n"
            "    backlog = pathlib.Path('BACKLOG.md')\n"
            "    outcome = '## [!]' if os.environ.get('FAKE_OUTCOME') == 'block-first' and counter.read_text() == '1' else '## [x]'\n"
            "    backlog.write_text(backlog.read_text().replace('## [~]', outcome, 1))\n"
            "    if sprint:\n"
            "        subprocess.run(['git', 'add', 'BACKLOG.md'], check=True)\n"
            "        subprocess.run(['git', '-c', 'user.name=Runner Test', '-c', 'user.email=runner@example.com', 'commit', '-qm', 'task outcome'], check=True)\n"
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

    def setup_sprint(self, name="custom-sprint"):
        (self.project / "AGENTS.md").write_text(SELECT_SPRINT + "\n")
        backlog = self.project / "BACKLOG.md"
        backlog.write_text(f"Sprint branch: {name}\n\n" + backlog.read_text())
        self.git("add", "AGENTS.md", "BACKLOG.md")
        self.git("-c", "user.name=Runner Test", "-c", "user.email=runner@example.com",
                 "commit", "-qm", "sprint setup")
        self.git("switch", "-qc", name)
        remote = Path(self.temp.name) / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-q", "origin", name)

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

    def test_sprint_continues_independent_tasks_without_repeating_delivered_work(self):
        self.init_repo()
        self.setup_sprint()
        backlog = self.project / "BACKLOG.md"

        result = self.run_runner(complete=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.project / ".opencode" / "invocations").read_text(), "2")
        self.assertIn("runner continues with other independent tasks",
                       (self.project / ".opencode" / "assignment.txt").read_text())
        self.assertIn("## [x] TASK-001", backlog.read_text())
        self.assertIn("## [x] TASK-002", backlog.read_text())
        self.assertEqual(self.git("branch", "--show-current"), "custom-sprint")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "origin/custom-sprint"))

        second = self.run_runner(complete=True)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual((self.project / ".opencode" / "invocations").read_text(), "2")

    def test_sprint_launch_from_task_branch_preserves_work(self):
        self.init_repo()
        self.setup_sprint()
        self.git("switch", "-qc", "feature/first")
        backlog = self.project / "BACKLOG.md"
        backlog.write_text(backlog.read_text().replace("## [ ] TASK-001", "## [!] TASK-001"))
        self.git("add", "BACKLOG.md")
        self.git("-c", "user.name=Runner Test", "-c", "user.email=runner@example.com",
                 "commit", "-qm", "task status")
        before = backlog.read_text()
        second = self.run_runner(complete=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("Start sprint work on custom-sprint", second.stdout)
        self.assertEqual(backlog.read_text(), before)
        self.assertFalse((self.project / ".opencode" / "invocations").exists())

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
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("## [x] TASK-001", backlog.read_text())
        self.assertIn("## [ ] TASK-002", backlog.read_text())
        self.assertEqual((self.project / "partial.py").read_text(), "broken but preserved\n")
        self.assertEqual(self.git("rev-parse", "HEAD~1"), initial_commit)
        self.assertIn("Partial/uncommitted task work preserved", result.stdout)

    def test_sprint_skips_unmerged_dependency_and_delivers_independent_task(self):
        (self.project / "BACKLOG.md").write_text(
            "## [ ] TASK-001 — Submitted\nBranch: feature/submitted\n"
            "## [ ] TASK-002 — Dependent\nDepends on: TASK-001\n"
            "## [ ] TASK-003 — Independent\nDepends on: None\n")
        self.init_repo()
        self.setup_sprint()
        backlog = self.project / "BACKLOG.md"
        backlog.write_text(backlog.read_text().replace("## [ ] TASK-001", "## [x] TASK-001"))
        result = self.run_runner(complete=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.project / ".opencode" / "invocations").read_text(), "1")
        content = (self.project / "BACKLOG.md").read_text()
        self.assertIn("## [ ] TASK-002", content)
        self.assertIn("## [x] TASK-003", content)
        self.assertIn("not verified integrated", result.stdout)

    def test_sprint_resumes_unfinished_task_in_place_then_stops_without_progress(self):
        self.init_repo()
        self.setup_sprint()
        result = self.run_runner()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.project / ".opencode" / "invocations").read_text(), "3")
        self.assertIn("continue in the current checkout", result.stdout)

    def test_sprint_continues_after_clean_blocked_task(self):
        self.init_repo()
        self.setup_sprint()
        result = subprocess.run(["bash", "./run-tonight.sh"], cwd=self.project,
                                env={**self.env, "FAKE_OUTCOME": "block-first"},
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.project / ".opencode" / "invocations").read_text(), "2")
        content = (self.project / "BACKLOG.md").read_text()
        self.assertIn("## [!] TASK-001", content)
        self.assertIn("## [x] TASK-002", content)

    def test_integrated_branch_dependency_is_eligible(self):
        (self.project / "BACKLOG.md").write_text(
            "## [x] TASK-001 — Integrated legacy work\nNo PR or branch metadata\n"
            "## [ ] TASK-002 — Dependent\n**Depends on:** `TASK-001`\n")
        self.init_repo()
        self.setup_sprint()
        result = subprocess.run(
            ["python3", "scripts/backlog.py", "count-eligible", "BACKLOG.md",
             "--sprint-ref", "refs/remotes/origin/custom-sprint"],
            cwd=self.project, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")

    def test_reconcile_preserves_newer_terminal_outcomes_and_other_task_content(self):
        backlog = self.project / "BACKLOG.md"
        backlog.write_text(
            "# New planning\n## [x] TASK-001 — New completed\nPR: newer\n"
            "## [ ] TASK-002 — Ready\nAcceptance: current\n"
            "## [-] TASK-003 — Deferred\nKeep draft\n")
        source = self.project / ".opencode" / "outcomes.log"
        source.write_text(
            "## [!] TASK-001 — Older failure\nBlocked: old\n"
            "## [!] TASK-002 — Failed\nBlocked: missing access\n"
            "## [x] TASK-003 — Old completion\nOld draft\n")
        result = subprocess.run(
            ["python3", "scripts/backlog.py", "reconcile", "BACKLOG.md", str(source)],
            cwd=self.project, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        content = backlog.read_text()
        self.assertIn("# New planning", content)
        self.assertIn("PR: newer", content)
        self.assertNotIn("Blocked: old", content)
        self.assertIn("## [!] TASK-002", content)
        self.assertIn("Blocked: missing access", content)
        self.assertIn("Acceptance: current", content)
        self.assertIn("## [!] TASK-002 — Ready", content)
        self.assertIn("Keep draft", content)

    def test_legacy_title_tasks_continue_and_reconcile_without_ids(self):
        (self.project / "BACKLOG.md").write_text(
            "# Existing project\n## [x] Old feature\nAlready implemented\n"
            "## [ ] Finish settings\n### Done looks like\n- Saves changes\n"
            "### Verification\n- Existing focused tests\n"
            "## [ ] Add search\nDepends on: Old feature\n")
        self.init_repo()
        self.setup_sprint()
        result = self.run_runner(complete=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.project / ".opencode" / "invocations").read_text(), "2")
        content = (self.project / "BACKLOG.md").read_text()
        self.assertIn("## [x] Finish settings", content)
        self.assertIn("## [x] Add search", content)
        self.assertIn("### Done looks like", content)

    def test_unknown_legacy_dependency_waits_without_stopping_independent_work(self):
        (self.project / "BACKLOG.md").write_text(
            "## [ ] TASK-001 — Finalize\nDepends on: All intended PRs merged\n"
            "## [ ] TASK-002 — Independent\nDepends on: None\n")
        self.init_repo()
        result = self.run_runner(complete=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        content = (self.project / "BACKLOG.md").read_text()
        self.assertIn("## [ ] TASK-001", content)
        self.assertIn("## [x] TASK-002", content)
        self.assertIn("unresolved reference", result.stdout)

    def test_resume_claim_keeps_original_task_when_queue_order_changes(self):
        backlog = self.project / "BACKLOG.md"
        backlog.write_text(
            "## [ ] TASK-002 — Newly eligible\nDepends on: None\n"
            "## [ ] TASK-001 — Partial work\nDepends on: None\n")
        source = self.project / ".opencode" / "resume.log"
        source.write_text("## [~] TASK-001 — Partial work\nExisting diff\n")
        result = subprocess.run(
            ["python3", "scripts/backlog.py", "claim-batch", "BACKLOG.md", "1",
             "--resume-from", str(source)], cwd=self.project, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## [ ] TASK-002", backlog.read_text())
        self.assertIn("## [~] TASK-001", backlog.read_text())
        self.assertIn("Partial work", result.stdout)
        self.assertNotIn("Newly eligible", result.stdout)

    def test_launch_outside_project_uses_project_checkout(self):
        self.init_repo()
        result = subprocess.run(["bash", str(self.project / "run-tonight.sh")],
                                cwd=self.temp.name, env={**self.env, "FAKE_OUTCOME": "complete"},
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("## [x] TASK-002", (self.project / "BACKLOG.md").read_text())

    def test_legacy_blank_dependency_does_not_consume_next_line(self):
        backlog = self.project / "BACKLOG.md"
        backlog.write_text(
            "## [ ] TASK-001 — Simple\nDepends on:\n\n"
            "Scope: preserve existing code\n### Verification\n- Focused test\n")
        self.init_repo()
        result = self.run_runner(complete=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Scope: preserve existing code", backlog.read_text())

    def test_reconcile_keeps_group_headings_and_new_acceptance(self):
        backlog = self.project / "BACKLOG.md"
        backlog.write_text(
            "## [ ] TASK-001 — Updated title\nAcceptance: new behavior\n"
            "\n## Later group\nGroup introduction\n"
            "## [ ] TASK-002 — Next\nKeep next\n")
        source = self.project / ".opencode" / "outcomes.log"
        source.write_text(
            "## [x] TASK-001 — Old title\nAcceptance: stale behavior\n"
            "Branch: feature/first\nPR: https://example.test/1\n"
            "## [ ] TASK-002 — Next\nOld next\n")
        result = subprocess.run(
            ["python3", "scripts/backlog.py", "reconcile", "BACKLOG.md", str(source)],
            cwd=self.project, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        content = backlog.read_text()
        self.assertIn("## [x] TASK-001 — Updated title", content)
        self.assertIn("Acceptance: new behavior", content)
        self.assertIn("## Later group\nGroup introduction", content)
        self.assertIn("PR: https://example.test/1", content)
        self.assertNotIn("stale behavior", content)

    def test_examples_and_group_metadata_do_not_change_task_dependencies(self):
        backlog = self.project / "BACKLOG.md"
        backlog.write_text(
            "## [ ] TASK-001 — Useful task\nDepends on: None\n"
            "```markdown\nDepends on: missing-example\n```\n"
            "## Later group\nDepends on: group-note\n"
            "## [ ] TASK-002 — Another task\nDepends on: None\n")
        self.init_repo()
        result = self.run_runner(complete=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("## [x] TASK-001", backlog.read_text())
        self.assertIn("## [x] TASK-002", backlog.read_text())

    def test_malformed_dependencies_wait_while_independent_work_completes(self):
        backlog = self.project / "BACKLOG.md"
        backlog.write_text(
            "## [ ] TASK-001 — Ambiguous\nDepends on: None\nDepends on: TASK-002\n"
            "## [ ] TASK-002 — Invalid\nDepends on: TASK-003,\n"
            "## [ ] TASK-003 — Useful\nDepends on: None\n")
        self.init_repo()
        result = self.run_runner(complete=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("## [x] TASK-003", backlog.read_text())
        self.assertIn("multiple dependency declarations", result.stdout)
        self.assertIn("invalid dependency declaration", result.stdout)

    def test_bold_sprint_metadata_ignores_fenced_example(self):
        backlog = self.project / "BACKLOG.md"
        backlog.write_text(
            "```markdown\nSprint branch: example\n```\n"
            "- **Sprint branch:** `actual-sprint`\n## [ ] TASK-001 — Task\n")
        result = subprocess.run(
            ["python3", "scripts/backlog.py", "sprint-branch", "BACKLOG.md"],
            cwd=self.project, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "actual-sprint")

    def test_timeout_counts_as_failure_even_with_terminal_outcome(self):
        self.init_repo()
        command = Path(self.temp.name) / "bin" / "timeout"
        command.write_text(
            "#!/bin/sh\nshift\n\"$@\"\nexit 124\n")
        command.chmod(0o755)
        result = self.run_runner(complete=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timed out", result.stdout)
        self.assertNotIn("All sessions complete", result.stdout)


if __name__ == "__main__":
    unittest.main()
