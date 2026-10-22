"""COORDINATOR ONLY: pinned native-PDF browser fixture controls.

`preflight` is read-only and prints the exact source fingerprint. After review,
`launch --fingerprint ...` creates a fresh owned stack and synthetic Member;
`stop` (or the bounded fixture lifetime) owns teardown. No live provider mode.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_browser_fixture as browser


ROOT = Path(__file__).resolve().parents[1]


def candidate_preflight() -> int:
    """Hash only the pinned base and explicit composer/harness overlay paths."""
    try:
        head, _changes = browser.imp026_verified_head(ROOT, private_home=Path("/tmp/opencode"))
        records, _contents = browser._collect_candidate_worktree_inputs(
            ROOT,
            private_home=Path("/tmp/opencode"),
            policy=browser.IMP026_CANDIDATE_PREVIEW_POLICY,
        )
        if browser._resolve_head_commit(ROOT, private_home=Path("/tmp/opencode")) != head:
            raise browser.FixtureError("The native candidate HEAD changed during preflight.")
        fingerprint = browser._candidate_records_fingerprint(head, records)
        print(json.dumps({
            "check": "imp026_preflight",
            "status": "passed",
            "base": browser.IMP026_BASE_COMMIT,
            "native_ancestor": browser.IMP026_NATIVE_ANCESTOR,
            "head": head,
            "fingerprint": fingerprint,
            "synthetic_pdf_path": str(
                Path("/tmp/opencode")
                / ("impostr-imp026-review-" + fingerprint[:20])
                / "native-review.pdf"
            ),
            "files": len(records),
            "boundary_executed": False,
        }, sort_keys=True))
        return 0
    except browser.FixtureError:
        print(json.dumps({"check": "imp026_preflight", "status": "failed",
                          "boundary_executed": False}, sort_keys=True), file=sys.stderr)
        return 1


def cleanup_status() -> int:
    """COORDINATOR ONLY: fixed codes, no raw registration/log/login transport.

    Read-only: no directory/lock creation, signals, recovery, Docker or deletion.
    Presence is not proof of removable ownership. Legacy registrations cannot
    identify the old fingerprint-derived PDF and report that explicitly.
    """
    report = {"check": "imp026_cleanup_status", "status": "unavailable"}
    try:
        status = browser.read_cleanup_status(browser.APPROVED_HANDOFF_DIRECTORY)
        control = browser._control_directory_path()
        directory_fd = browser._open_private_directory(control)
        try:
            lock_fd = os.open(browser.CONTROL_LOCK_FILE, os.O_RDONLY | os.O_NOFOLLOW,
                              dir_fd=directory_fd)
            try:
                browser._require_plain_private_file(os.fstat(lock_fd))
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    guardian = "idle"
                except BlockingIOError:
                    guardian = "active"
            finally:
                os.close(lock_fd)
        finally:
            os.close(directory_fd)
        record = browser._read_control_record(control)
        report.update(status="inspected", guardian=guardian,
                      cleanup=status, registration="missing" if record is None else "present")
        if record is not None:
            process_fd = browser._open_verified_supervisor_pidfd(record)
            report["supervisor"] = "exited" if process_fd is None else "active"
            if process_fd is not None:
                os.close(process_fd)
            recovery = record.get("recovery")
            if recovery is not None:
                state = browser._validate_recovery_state_directory(Path(recovery["state_dir"]))
                report["private_state"] = "present" if state.exists() or state.is_symlink() else "absent"
                report["compose_ownership"] = "acquired" if recovery["owned"] else "never-acquired"
                project = recovery["project_name"]
                if project is not None:
                    layout = browser.inspect_registered_watchdog_layout(recovery)
                    report.update(layout)
                    report["watchdog_paths"] = "absent" if all(
                        layout[field] == "absent" for field in
                        ("watchdog_root_layout", "watchdog_scratch_layout")) else "present"
                fingerprint = recovery.get("native_fingerprint")
                if fingerprint is None:
                    report["native_input"] = "unregistered"
                else:
                    path = Path("/tmp/opencode") / ("impostr-imp026-review-" + fingerprint[:20])
                    report["native_input"] = "present" if path.exists() or path.is_symlink() else "absent"
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:
        # Do not emit even partial private metadata or exception descriptions.
        print(json.dumps({"check": "imp026_cleanup_status", "status": "unavailable"}, sort_keys=True))
        return 1


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight", help="read-only exact-input fingerprint")
    commands.add_parser("status", help="coordinator-only read-only sanitized cleanup inspection")
    launch = commands.add_parser("launch", help="launch the reviewed fresh native-PDF browser fixture")
    launch.add_argument("--fingerprint", required=True)
    launch.add_argument("--lifetime-minutes", type=int, default=browser.DEFAULT_LIFETIME_MINUTES)
    for command in ("stop", "recover"):
        commands.add_parser(command, help=f"{command} this fixture's owned resources")
    args = parser.parse_args(arguments)
    if args.command == "preflight":
        return candidate_preflight()
    if args.command == "status":
        return cleanup_status()
    if args.command == "launch":
        if (re.fullmatch(r"[0-9a-f]{64}", args.fingerprint) is None
                or not browser.MIN_LIFETIME_MINUTES <= args.lifetime_minutes <= browser.MAX_LIFETIME_MINUTES):
            parser.error("launch requires a lowercase reviewed fingerprint and bounded lifetime")
        return browser.main([
            "launch", "--handoff-dir", str(browser.APPROVED_HANDOFF_DIRECTORY),
            "--lifetime-minutes", str(args.lifetime_minutes),
            "--imp026-candidate-fingerprint", args.fingerprint,
        ])
    return browser.main([args.command, "--handoff-dir", str(browser.APPROVED_HANDOFF_DIRECTORY)])


if __name__ == "__main__":
    raise SystemExit(main())
