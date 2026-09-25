#!/usr/bin/env python3
"""Manage the Markdown work queue used by run-tonight.sh.

Commands: count, count-outcomes, sprint-branch, count-eligible, list-waiting,
claim-batch, next-batch, mark-running, reset-running, list-blocked, list-all.
count succeeds with zero for an empty queue. claim-batch/next-batch/mark-running return 1
when no work is available; invalid input returns 2. Completion, Git operations,
verification, and recovery decisions belong to the agents and project instructions.
"""

import argparse
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


STATUS_PATTERN = re.compile(r"^## \[([ ~x!\-])\] (.+)$")
ID_PATTERN = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*-\d+)(?:\s|$)")
DEPENDENCY_PATTERN = re.compile(r"(?m)^\s*(?:\*\*)?Depends on:(?:\*\*)?\s*(.*?)\s*$")


def load(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def save(path: str, content: str) -> None:
    destination = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, stat.S_IMODE(destination.stat().st_mode))
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def get_items(content: str) -> list[dict]:
    """Read task headings outside fenced examples; reject ambiguous identities."""
    items, identities, titles = [], set(), set()
    offset, fence = 0, None
    for line in content.splitlines(keepends=True):
        text = line.rstrip("\r\n")
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}\s*", text):
                fence = None
        else:
            opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", text)
            if opening:
                fence = (opening.group(1)[0], len(opening.group(1)))
            else:
                match = STATUS_PATTERN.fullmatch(text)
                if match:
                    title = match.group(2).strip()
                    if not title:
                        raise ValueError("Task titles must not be empty.")
                    identifier = ID_PATTERN.match(title)
                    key = identifier.group(1).casefold() if identifier else title.casefold()
                    if key in identities or title.casefold() in titles:
                        raise ValueError(f"Duplicate task ID/title: {title}")
                    identities.add(key)
                    titles.add(title.casefold())
                    items.append({"status": match.group(1), "title": title,
                                  "header_start": offset, "header_end": offset + len(text)})
                elif text.startswith("## ["):
                    raise ValueError(f"Invalid task heading: {text}")
        offset += len(line)
    for index, item in enumerate(items):
        end = items[index + 1]["header_start"] if index + 1 < len(items) else len(content)
        item["body"] = content[item["header_end"]:end].strip()
    return items


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Batch size must be a positive integer.") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("Batch size must be a positive integer.")
    return number


def cmd_count(path: str) -> int:
    print(sum(item["status"] == " " for item in get_items(load(path))))
    return 0


def cmd_count_outcomes(path: str) -> int:
    print(sum(item["status"] in {"x", "!"} for item in get_items(load(path))))
    return 0


def cmd_sprint_branch(path: str) -> int:
    branches = re.findall(r"(?m)^-? ?Sprint branch: [`]?([^\s`]+)[`]?\s*$", load(path))
    if len(branches) != 1 or branches[0].startswith("<"):
        raise ValueError("Expected one configured Sprint branch in BACKLOG.md.")
    print(branches[0])
    return 0


def eligible_items(content: str) -> tuple[list[dict], list[tuple[dict, list[str]]]]:
    """Ready items whose declared dependencies are already complete in this backlog."""
    items = get_items(content)
    by_id = {match.group(1).casefold(): item for item in items
             if (match := ID_PATTERN.match(item["title"]))}
    ready, waiting = [], []
    for item in items:
        if item["status"] != " ":
            continue
        matches = DEPENDENCY_PATTERN.findall(item["body"])
        if len(matches) > 1:
            raise ValueError(f"Multiple dependency declarations for {item['title']}")
        declaration = matches[0].strip() if matches else "None"
        dependencies = [] if declaration.casefold() == "none" else [
            part.strip() for part in declaration.split(",")]
        if not all(dependencies):
            raise ValueError(f"Invalid dependencies for {item['title']}")
        missing = []
        for identifier in dependencies:
            dependency = by_id.get(identifier.casefold())
            if dependency is None:
                raise ValueError(f"Unknown dependency {identifier} for {item['title']}")
            if dependency is item:
                raise ValueError(f"Self-dependency for {item['title']}")
            if dependency["status"] != "x":
                missing.append(identifier)
        if missing:
            waiting.append((item, missing))
        else:
            ready.append(item)
    return ready, waiting


def cmd_count_eligible(path: str) -> int:
    ready, _ = eligible_items(load(path))
    print(len(ready))
    return 0


def cmd_list_waiting(path: str) -> int:
    _, waiting = eligible_items(load(path))
    for item, missing in waiting:
        print(f"  [ ] {item['title']} (waiting for {', '.join(missing)})")
    if not waiting:
        print("  None")
    return 0


def print_assignment(items: list[dict]) -> None:
    print("Runner-assigned batch: work on the following backlog items in order.\n")
    print("These dependency-eligible items have been marked [~] by the runner.")
    print("Follow AGENTS.md, PROJECT.md, and the overnight agent's instructions.")
    print("Verified local task-branch commits are authorized unless project policy is stricter.")
    print("Complete verification/review and the final affected-docs pass before marking work [x].")
    print("If a commit is required, verify that it succeeded before marking [x].")
    print("Mark blocked work [!] with a short reason and preserve useful partial changes.")
    print("Use the selected project workflow for branches, authorized pushes, and PR destinations.")
    print("Never merge. Push only with explicit user/workflow authorization and tool permission.")
    print("Never install or initialize skills. Keep recovery notes brief.")
    for index, item in enumerate(items, 1):
        print(f"\n### Item {index} of {len(items)}: {item['title']}\n")
        print(item["body"])
    print("\nAt the end, append one concise summary to DONE.md and stop.")
    print("Resetting [~] to [ ] does not erase partial code or previous attempts.")


def cmd_claim_batch(path: str, n: int) -> int:
    content = load(path)
    eligible, _ = eligible_items(content)
    claimed = eligible[:n]
    if not claimed:
        return 1
    save(path, replace_status(content, claimed, "~"))
    print_assignment(claimed)
    return 0


def cmd_next_batch(path: str, n: int) -> int:
    pending = [item for item in get_items(load(path)) if item["status"] == " "][:n]
    if not pending:
        return 1
    print("Runner-assigned batch: work on the following backlog items in order.\n")
    print("The runner marks these same titles [~] before launching this session.")
    print("Follow AGENTS.md, PROJECT.md, and the overnight agent's instructions.")
    print("Validate dependencies; selection is by file order, not dependency-aware.")
    print("Verified local task-branch commits are authorized unless project policy is stricter.")
    print("Complete verification/review and the final affected-docs pass before marking work [x].")
    print("If a commit is required, verify that it succeeded before marking [x].")
    print("Mark blocked work [!] with a short reason and preserve useful partial changes.")
    print("Use the selected project workflow for branches, authorized pushes, and PR destinations.")
    print("Never merge. Push only with explicit user/workflow authorization and tool permission.")
    print("Never install or initialize skills. Keep recovery notes brief.")
    for index, item in enumerate(pending, 1):
        print(f"\n### Item {index} of {len(pending)}: {item['title']}\n")
        print(item["body"])
    print("\nAt the end, append one concise summary to DONE.md and stop.")
    print("Resetting [~] to [ ] does not erase partial code or previous attempts.")
    return 0


def replace_status(content: str, items: list[dict], status: str) -> str:
    for item in reversed(items):
        position = item["header_start"] + 4
        content = content[:position] + status + content[position + 1:]
    return content


def cmd_mark_running(path: str, n: int) -> int:
    content = load(path)
    pending = [item for item in get_items(content) if item["status"] == " "][:n]
    if not pending:
        return 1
    save(path, replace_status(content, pending, "~"))
    return 0


def cmd_reset_running(path: str) -> int:
    content = load(path)
    running = [item for item in get_items(content) if item["status"] == "~"]
    if running:
        save(path, replace_status(content, running, " "))
    print(f"Reset {len(running)} unfinished item(s) to [ ] ready.")
    return 0


def cmd_list_blocked(path: str) -> int:
    blocked = [item for item in get_items(load(path)) if item["status"] == "!"]
    for item in blocked:
        print(f"  [!] {item['title']}")
    if not blocked:
        print("  None")
    return 0


def cmd_list_all(path: str) -> int:
    labels = {" ": "[ ] ready", "~": "[~] running", "x": "[x] done",
              "!": "[!] blocked", "-": "[-] skipped"}
    for item in get_items(load(path)):
        print(f"  {labels[item['status']]}  —  {item['title']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    functions = {"count": cmd_count, "count-outcomes": cmd_count_outcomes,
                  "sprint-branch": cmd_sprint_branch,
                  "count-eligible": cmd_count_eligible, "list-waiting": cmd_list_waiting,
                  "claim-batch": cmd_claim_batch,
                  "next-batch": cmd_next_batch,
                 "mark-running": cmd_mark_running, "reset-running": cmd_reset_running,
                 "list-blocked": cmd_list_blocked, "list-all": cmd_list_all}
    for name in functions:
        command = commands.add_parser(name)
        command.add_argument("path")
        if name in {"claim-batch", "next-batch", "mark-running"}:
            command.add_argument("n", type=positive_integer)
    args = parser.parse_args()
    try:
        function = functions[args.command]
        if hasattr(args, "n"):
            return function(args.path, args.n)
        return function(args.path)
    except (ValueError, OSError) as exc:
        print(f"Backlog error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
