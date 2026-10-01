"""Fixed synthetic-only reason projection around the approved planning scenario.

Observes native shape; delegates validation unchanged. No private input inspection,
operator mode, raw bodies/transcripts/schema names/exception output or auth exists.
This is not a new worker scenario or a bypass of failed validation.
"""

import contextlib
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imp002_prototype as prototype
import imp002_relay as relay
from imp024_protocol import MAX_REQUEST, Invalid, definitions

KINDS = ("message", "function_call", "function_call_output")
DENIALS = ("function definition", "function data", "function call", "function result pairing",
           "unpaired function result", "message", "text only", "content", "other")
RULE_DENIAL = "The user has specified a rule which prevents you from using this specific tool call."


def result_category(output):
    # Fixed native categories and exact synthetic oracle assertions. Never raw
    # error text, arbitrary tokens/names/paths/schema fields or exception details.
    if output.startswith(RULE_DENIAL):
        return "native_rule_denial"
    if output == "[Tool execution was interrupted]" or output == "Tool execution aborted":
        return "interrupted"
    if output.startswith("The read tool was called with invalid arguments"):
        return "invalid_read_arguments"
    if "Synthetic" in output and "</content>" in output:
        return "synthetic_read_complete"
    if "Use synthetic local planning" in output:
        return "synthetic_question_answer"
    if "Edit applied successfully" in output:
        return "synthetic_edit_complete"
    return "other"


def request_shape(body):
    """Exact fixed fields; arbitrary attacker values can only become 'other'."""
    result = {"definitions_valid": False, "input_types": [], "result_shapes": []}
    try:
        if len(body) > MAX_REQUEST:
            return result
        data = relay.decode(body)
        if not isinstance(data, dict):
            return result
        try:
            definitions(data.get("tools", []))
            result["definitions_valid"] = True
        except (Invalid, TypeError, ValueError):
            pass
        inputs = data.get("input")
        if not isinstance(inputs, list):
            return result
        for item in inputs[:16]:
            if not isinstance(item, dict):
                result["input_types"].append("other")
                continue
            kind = item.get("type", "message")
            result["input_types"].append(kind if kind in KINDS else "other")
            if kind == "function_call_output":
                output = item.get("output")
                shape = "string" if isinstance(output, str) else "other"
                if isinstance(output, list):
                    shape = "text_parts" if all(isinstance(part, dict) and set(part) == {"type", "text"}
                        and part.get("type") == "input_text" and isinstance(part.get("text"), str)
                        for part in output) else "other_parts"
                result["result_shapes"].append(shape)
                if isinstance(output, str):
                    result.setdefault("result_categories", []).append(result_category(output))
    except Exception:
        pass
    return result


def observe(original, records):
    def validate(method, route, body, **kwargs):
        record = None
        if kwargs.get("planning") is True and len(records) < 8:
            record = request_shape(body)
            records.append(record)
        try:
            value = original(method, route, body, **kwargs)
        except relay.Denied as exc:
            if record is not None:
                record["denial"] = str(exc) if str(exc) in DENIALS else "other"
            raise
        if record is not None:
            record["accepted"] = True
        return value
    return validate


class BoundedOutput(io.StringIO):
    def write(self, value):
        if self.tell() + len(value) > 32768:
            raise ValueError("diagnostic output bound")
        return super().write(value)


def main():
    original = relay.validate
    records = []
    output = BoundedOutput()
    relay.validate = observe(original, records)
    try:
        with contextlib.redirect_stdout(output):
            code = prototype.run("imp024-planning")
        summary = relay.decode(output.getvalue())
        result = {"diagnostic_completed": True, "scenario_passed": code == 0,
                  "relay_calls": summary.get("relay_calls"), "relay_denied": summary.get("relay_denied"),
                  "owned_state_removed": summary.get("owned_state_removed") is True, "requests": records}
    except Exception:
        result = {"diagnostic_completed": False, "requests": records}
    finally:
        relay.validate = original
        output.close()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["diagnostic_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
