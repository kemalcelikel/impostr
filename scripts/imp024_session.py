"""Synthetic phase-one entrypoint. Execute ONLY after independent boundary review.

No operator/live/private resolver, arbitrary endpoint or credential input exists.
Each scenario is a new owned mandatory bwrap namespace, not a host server.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imp002_prototype import run
from imp024_inference import native_response


class SyntheticPlanning:
    """Deterministic native inference; executes NO tools. OpenCode owns execution."""
    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = 0
        self.validated = False

    def events(self, data, cancelled, deadline):
        # A deterministic fixture-contract failure is terminal inference data,
        # not a transient host service outage. Preserve rejection, don't retry
        # the same broken synthetic oracle until the worker's outer timeout.
        from imp024_protocol import Invalid, terminal_error
        try:
            yield from self._events(data, cancelled, deadline)
        except Invalid:
            yield terminal_error()

    def _events(self, data, cancelled, deadline):
        from imp024_worker import ANSWER, EDIT, PROMPTS
        from imp024_protocol import require
        self.calls += 1
        inputs = data["input"]
        users = [item for item in inputs if item.get("role") == "user"]
        require(len(users) == 1)
        content = users[0]["content"]
        text = content if isinstance(content, str) else "".join(part["text"] for part in content)
        require(text == PROMPTS[self.scenario])
        results = [item for item in inputs if item.get("type") == "function_call_output"]
        calls = [item for item in inputs if item.get("type") == "function_call"]
        require(len(calls) == len(results))
        names = [item["name"] for item in calls]
        require(names == ["read", "question", "edit"][:len(names)])
        if self.scenario == "error":
            require(self.calls == 1)
            yield from native_response("IMP024_PARTIAL")[:4]
            raise ValueError("synthetic terminal failure")
        if self.scenario == "denials":
            require(self.calls == 1)
            # Reject malicious model output BEFORE releasing tool arguments.
            yield from native_response(calls=[{"type": "function_call", "name": "shell",
                "call_id": "call_forbidden", "arguments": '{"command":"touch /project/forbidden"}'}])
            return
        stage = len(results)
        require(self.calls == stage + 1 and stage <= 3)
        if stage >= 1:
            require("Synthetic" in results[0]["output"])
        if stage >= 2:
            require(ANSWER in results[1]["output"])
        if stage >= 3:
            require("Edit applied successfully" in results[2]["output"])
        if stage == 3:
            self.validated = True
            yield from native_response("IMP024_PLANNING_OK")
            return
        if stage == 0:
            name, args = "read", {"filePath": "/project/PROJECT.md"}
        elif stage == 1:
            name, args = "question", {"questions": [{"question": "Which synthetic scope?", "header": "Scope",
                "options": [{"label": ANSWER, "description": "Local synthetic fixture"}]}]}
        else:
            name, args = "edit", {"filePath": "/project/PROJECT.md",
                "oldString": "# Synthetic IMP002 project\n", "newString": EDIT}
        yield from native_response(calls=[{"type": "function_call", "name": name,
            "call_id": "call_planning_" + str(stage), "arguments": json.dumps(args)}])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("planning", "denials", "cancel", "error"))
    args = parser.parse_args()
    try:
        return run("imp024-" + args.scenario)
    except Exception:
        print(json.dumps({"success": False, "planning_capability_unavailable": True}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
