"""Bounded native function SSE normalization; no tool execution or upstream access.

Function arguments are held until a consistent response.completed is validated.
Only then is a native function item emitted to the namespace's tool executor.
Text deltas may stream early; errors never become successful completion.
"""

import json

from imp002_relay import MODEL, decode
from imp024_protocol import (MAX_DOCUMENT, MAX_RESPONSE, arguments, bounded_text,
                            definitions, identifier, require, terminal_error)


def frame(name, fields, sequence):
    return ("event: " + name + "\ndata: " + json.dumps(dict(fields, type=name, sequence_number=sequence),
            ensure_ascii=True, separators=(",", ":")) + "\n\n").encode()


def native_response(text="", calls=()):
    """Credential-free fixture generator using measured Responses function events."""
    outputs = []
    if text:
        outputs.append({"id": "msg_planning", "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]})
    for index, call in enumerate(calls):
        outputs.append(dict(call, id="fc_planning_" + str(index), status="completed"))
    response = {"id": "resp_planning", "object": "response", "created_at": 1, "model": MODEL,
                "status": "completed", "output": outputs,
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
    events = [("response.created", {"response": dict(response, status="in_progress", output=[])})]
    for index, item in enumerate(outputs):
        empty = dict(item, status="in_progress")
        if item["type"] == "message":
            empty["content"] = []
            part = item["content"][0]
            events += [("response.output_item.added", {"output_index": index, "item": empty}),
                ("response.content_part.added", {"item_id": item["id"], "output_index": index,
                    "content_index": 0, "part": dict(part, text="")}),
                ("response.output_text.delta", {"item_id": item["id"], "output_index": index,
                    "content_index": 0, "delta": text}),
                ("response.output_text.done", {"item_id": item["id"], "output_index": index,
                    "content_index": 0, "text": text}),
                ("response.content_part.done", {"item_id": item["id"], "output_index": index,
                    "content_index": 0, "part": part})]
        else:
            empty["arguments"] = ""
            events += [("response.output_item.added", {"output_index": index, "item": empty}),
                ("response.function_call_arguments.delta", {"item_id": item["id"], "output_index": index,
                    "delta": item["arguments"]}),
                ("response.function_call_arguments.done", {"item_id": item["id"], "output_index": index,
                    "arguments": item["arguments"]})]
        events.append(("response.output_item.done", {"output_index": index, "item": item}))
    events.append(("response.completed", {"response": response}))
    return [frame(name, fields, sequence) for sequence, (name, fields) in enumerate(events)]


def function_item(item, names):
    require(isinstance(item, dict) and not set(item) - {"id", "type", "status", "name", "call_id", "arguments"}
            and item.get("type") == "function_call" and item.get("name") in names
            and item.get("status", "completed") == "completed")
    identifier(item.get("id"))
    identifier(item.get("call_id"))
    arguments(item["name"], decode(bounded_text(item.get("arguments")).encode()))
    return {key: item[key] for key in ("type", "name", "call_id", "arguments")}


def parsed_events(blocks):
    buffer = bytearray()
    total = 0
    try:
        for block in blocks:
            require(isinstance(block, bytes))
            total += len(block)
            require(total <= MAX_RESPONSE)
            buffer.extend(block)
            buffer = bytearray(bytes(buffer).replace(b"\r\n", b"\n"))
            while b"\n\n" in buffer:
                raw, _, rest = buffer.partition(b"\n\n")
                buffer = bytearray(rest)
                require(len(raw) <= MAX_DOCUMENT * 2)
                fields = [line for line in raw.decode().split("\n") if line and not line.startswith(":")]
                if not fields:
                    continue
                names = [line[7:] for line in fields if line.startswith("event: ")]
                payloads = [line[6:] for line in fields if line.startswith("data: ")]
                require(len(names) <= 1 and len(payloads) == 1 and len(fields) == len(names) + 1)
                event = decode(payloads[0])
                require(isinstance(event, dict) and isinstance(event.get("type"), str)
                        and (not names or names[0] == event["type"]))
                yield event
            require(len(buffer) <= MAX_DOCUMENT * 2)
        require(not buffer.strip())
    finally:
        close = getattr(blocks, "close", None)
        if close:
            close()


def normalized_events(blocks, data):
    names = definitions(data.get("tools", []))
    sequence = 0
    text = ""
    items = {}
    calls = {}
    done = set()
    terminal = False
    started = False

    def emit(name, fields):
        nonlocal sequence
        result = frame(name, fields, sequence)
        sequence += 1
        return result

    parsed = parsed_events(blocks)
    try:
        for event in parsed:
            require(not terminal)
            name = event["type"]
            if name == "error":
                # Never forward arbitrary provider error metadata. Reframe the
                # measured SDK/OpenCode terminal schema even before text/tools.
                yield terminal_error(sequence)
                return
            if name in ("response.created", "response.in_progress"):
                require(not items)
                response = event.get("response")
                require(isinstance(response, dict) and response.get("status") == "in_progress"
                        and response.get("output") == [])
                if not started:
                    started = True
                    yield emit("response.created", {"response": {"id": "resp_planning", "object": "response",
                        "created_at": 1, "model": MODEL, "status": "in_progress", "output": []}})
                continue
            if name == "response.output_item.added":
                index, item = event.get("output_index"), event.get("item")
                require(started and type(index) is int and index == len(items) and index < 8 and isinstance(item, dict)
                        and item.get("type") in ("message", "function_call"))
                identifier(item.get("id"))
                require(item["id"] not in [value["id"] for value in items.values()])
                items[index] = item
                if item["type"] == "function_call":
                    require(item.get("name") in names and item.get("arguments") == "")
                    identifier(item.get("call_id"))
                    calls[index] = ""
                else:
                    require(index == 0 and item.get("role") == "assistant" and item.get("content") == [])
                    yield emit(name, {"output_index": 0, "item": {"type": "message", "id": "msg_planning",
                        "role": "assistant", "status": "in_progress", "content": []}})
                    yield emit("response.content_part.added", {"output_index": 0, "item_id": "msg_planning",
                        "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}})
                continue
            if name == "response.completed":
                response = event.get("response")
                require(isinstance(response, dict) and response.get("status") == "completed")
                output = response.get("output")
                require(isinstance(output, list) and 1 <= len(output) <= 8 and len(output) == len(items)
                        and done == set(items))
                validated_calls = []
                seen = set()
                final_text = ""
                for index, item in enumerate(output):
                    require(isinstance(item, dict) and item.get("id") == items[index]["id"]
                            and item.get("type") == items[index]["type"])
                    if item["type"] == "function_call":
                        call = function_item(item, names)
                        require(call["arguments"] == calls[index] and call["call_id"] not in seen
                                and call["call_id"] == items[index]["call_id"] and call["name"] == items[index]["name"])
                        seen.add(call["call_id"])
                        validated_calls.append(call)
                    else:
                        require(index == 0 and item.get("role") == "assistant"
                                and isinstance(item.get("content"), list) and len(item["content"]) == 1)
                        part = item["content"][0]
                        require(isinstance(part, dict) and part.get("type") == "output_text")
                        final_text = bounded_text(part.get("text"))
                require(text == final_text and (text or validated_calls))
                # Rebuild terminal native frames; skip the text delta already sent.
                for raw in native_response(text, validated_calls):
                    native = decode(raw.split(b"data: ", 1)[1].strip())
                    if native["type"] == "response.created":
                        continue
                    if text and native["type"] in ("response.output_item.added",
                            "response.content_part.added", "response.output_text.delta") and native.get("output_index", 0) == 0:
                        continue
                    native.pop("type")
                    native.pop("sequence_number")
                    event_name = raw.split(b"\n", 1)[0][7:].decode()
                    yield emit(event_name, native)
                terminal = True
                return
            index = event.get("output_index")
            require(type(index) is int and index in items and index not in done)
            item = items[index]
            if "item_id" in event:
                require(event["item_id"] == item["id"])
            if name == "response.output_item.done":
                final = event.get("item")
                require(isinstance(final, dict) and final.get("id") == item["id"] and final.get("type") == item["type"])
                if item["type"] == "function_call":
                    function_item(final, names)
                    require(final.get("arguments") == calls[index] and final.get("name") == item["name"]
                            and final.get("call_id") == item["call_id"])
                done.add(index)
            elif item["type"] == "function_call":
                require(name in ("response.function_call_arguments.delta", "response.function_call_arguments.done"))
                if name.endswith(".delta"):
                    calls[index] += bounded_text(event.get("delta"))
                    bounded_text(calls[index])
                else:
                    require(event.get("arguments") == calls[index])
            elif name == "response.output_text.delta":
                require(event.get("content_index") == 0)
                delta = bounded_text(event.get("delta"))
                text += delta
                bounded_text(text)
                yield emit(name, {"output_index": 0, "content_index": 0, "item_id": "msg_planning", "delta": delta})
            elif name == "response.output_text.done":
                require(event.get("text") == text)
            else:
                require(name in ("response.content_part.added", "response.content_part.done")
                        and event.get("content_index") == 0 and isinstance(event.get("part"), dict)
                        and event["part"].get("type") == "output_text")
        require(terminal)
    finally:
        parsed.close()
