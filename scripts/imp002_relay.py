"""Inference-only per-run Unix relay. Default transport is a synthetic stub.

The worker may reach this one per-run filesystem Unix socket, not a host HTTP
server. The separately reviewed operator transport owns upstream/auth; workers
never supply upstream URLs/headers. Bounded text is the default; explicit planning
mode adds source-constrained native function DATA, not host tool execution.
"""

import json
import os
import select
import socket
import struct
import threading
import time
from pathlib import Path

ROUTE = "/openai/v1/responses"
MODEL = "synthetic-deployment"
MAX_REQUEST = 128 * 1024
MAX_RESPONSE = 32 * 1024
MAX_CALLS = 4
IO_TIMEOUT = 3
CALL_TIMEOUT = 12


class Denied(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Denied("duplicate field")
        result[key] = value
    return result


def decode(body):
    try:
        return json.loads(body, object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(Denied("nonfinite")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Denied("invalid JSON") from exc


def pdf_contract():
    # The delivered product launcher copies the SAME pure module under this name;
    # trusted host product callers already import app from the fixed API source.
    # No file discovery/config loader, and missing support fails closed.
    try:
        import imp024_channel as contract
    except ModuleNotFoundError as exc:
        if exc.name != "imp024_channel":
            raise
        from app import chat_protocol as contract
    return contract


def validate(method, route, body, *, planning=False, input_text_limit=64000, pdf_manifest=None):
    from imp024_protocol import (MAX_REQUEST as PLANNING_REQUEST, MAX_ITEMS, MAX_TOKENS,
                                Invalid, arguments, bounded_text, definitions, identifier)
    # Product text-history reconstruction is explicit; all prototype/phase-one
    # callers keep the original bound. No arbitrary or unbounded caller setting.
    if input_text_limit != 64000 and not (planning and input_text_limit == 384 * 1024):
        raise Denied("input bound")
    pdf = None
    if pdf_manifest is not None:
        if not planning or input_text_limit != 384 * 1024:
            raise Denied("PDF mode")
        try:
            pdf = pdf_contract()
            pdf_manifest = pdf.native_manifest(pdf_manifest)
            if not pdf_manifest:
                raise Denied("PDF manifest")
        except (ImportError, ValueError) as exc:
            raise Denied("PDF manifest") from exc
    request_limit = pdf.MAX_PDF_FRAME if pdf else (PLANNING_REQUEST if planning else MAX_REQUEST)
    if method != "POST" or route != ROUTE or not 0 < len(body) <= request_limit:
        raise Denied("not inference")
    data = decode(body)
    allowed = {"model", "input", "stream", "store", "max_output_tokens", "tools",
               "tool_choice", "parallel_tool_calls", "reasoning", "text", "include", "prompt_cache_key"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise Denied("unsupported fields")
    if data.get("model") != MODEL or data.get("stream") is not True:
        raise Denied("model or stream")
    if data.get("store") is not False:
        raise Denied("storage forbidden")
    if "prompt_cache_key" in data:
        if not isinstance(data["prompt_cache_key"], str) or len(data["prompt_cache_key"]) > 128:
            raise Denied("cache key")
        # Native SDK emits a session-affinity hint. Never let it select shared
        # provider state: omit it from any future operator-owned transport.
        del data["prompt_cache_key"]
    if (not planning and data.get("tools", []) != []) or data.get("include", []) != []:
        raise Denied("external or stateful capability")
    try:
        names = definitions(data.get("tools", [])) if planning else set()
    except Invalid as exc:
        raise Denied("function definition") from exc
    if data.get("tool_choice", "none") not in ("none", "auto"):
        raise Denied("tool choice")
    if "parallel_tool_calls" in data and type(data["parallel_tool_calls"]) is not bool:
        raise Denied("parallel calls")
    maximum = data.get("max_output_tokens", 256)
    if type(maximum) is not int or not 1 <= maximum <= (MAX_TOKENS if planning else 1024):
        raise Denied("output bound")
    reasoning = data.get("reasoning", {})
    if not isinstance(reasoning, dict) or set(reasoning) - {"effort", "summary"}:
        raise Denied("reasoning")
    if reasoning.get("effort", "low") not in ("minimal", "low", "medium"):
        raise Denied("effort")
    if reasoning.get("summary", "auto") not in ("auto", "concise"):
        raise Denied("summary")
    text = data.get("text", {})
    if not isinstance(text, dict) or set(text) - {"verbosity", "format"}:
        raise Denied("text")
    if text.get("verbosity", "low") not in ("low", "medium", "high"):
        raise Denied("verbosity")
    if text.get("format", {"type": "text"}) != {"type": "text"}:
        raise Denied("format")
    messages = data.get("input")
    if not isinstance(messages, list) or not 1 <= len(messages) <= (MAX_ITEMS if planning else 32):
        raise Denied("input")
    pending, seen = {}, set()
    file_parts = []
    for message_index, message in enumerate(messages):
        if planning and isinstance(message, dict) and message.get("type") in ("function_call", "function_call_output"):
            try:
                call = identifier(message.get("call_id"))
                if message["type"] == "function_call":
                    if set(message) != {"type", "call_id", "name", "arguments"} or message.get("name") not in names or call in seen:
                        raise Denied("function call")
                    arguments(message["name"], decode(bounded_text(message["arguments"]).encode()))
                    pending[call] = message["name"]
                    seen.add(call)
                else:
                    if set(message) != {"type", "call_id", "output"} or call not in pending:
                        raise Denied("function result pairing")
                    bounded_text(message["output"])
                    del pending[call]
            except Invalid as exc:
                raise Denied("function data") from exc
            continue
        if pending and isinstance(message, dict) and message.get("role") == "user":
            raise Denied("unpaired function result")
        if planning and isinstance(message, dict) and "id" in message:
            # SDK replays assistant text with item IDs when store=false. Keep
            # text but strip the inert provider identity, never item references.
            try:
                identifier(message["id"])
                if message.get("role") != "assistant":
                    raise Denied("message id")
                message = dict(message)
                del message["id"]
                messages[message_index] = message
            except Invalid as exc:
                raise Denied("message id") from exc
        if not isinstance(message, dict) or set(message) - {"role", "content", "type"}:
            raise Denied("message")
        if message.get("type", "message") != "message":
            raise Denied("message type")
        if message.get("role") not in ("system", "developer", "user", "assistant"):
            raise Denied("role")
        content = message.get("content")
        # Native Responses permits plain text system/developer messages.
        if isinstance(content, str):
            if len(content.encode()) > input_text_limit:
                raise Denied("text bound")
            continue
        # Reconstructed product history becomes one native user prompt; up to
        # 416 ordered file occurrences plus text. Text-only messages retain 16.
        has_files = isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") == "input_file" for part in content)
        content_limit = pdf.MAX_NATIVE_PDF_OCCURRENCES + 16 if pdf and has_files else 16
        if not isinstance(content, list) or not 1 <= len(content) <= content_limit:
            raise Denied("content")
        if has_files and sum(not isinstance(part, dict) or part.get("type") != "input_file"
                             for part in content) > 16:
            raise Denied("text parts")
        for part in content:
            if pdf and isinstance(part, dict) and part.get("type") == "input_file":
                if message["role"] != "user":
                    raise Denied("PDF role")
                file_parts.append(part)
                continue
            if not isinstance(part, dict) or set(part) != {"type", "text"}:
                raise Denied("text only")
            if part["type"] not in ("input_text", "output_text"):
                raise Denied("media forbidden")
            if not isinstance(part["text"], str) or len(part["text"].encode()) > input_text_limit:
                raise Denied("text bound")
    if pending:
        raise Denied("unpaired function result")
    if pdf:
        try:
            pdf.native_file_parts(file_parts, pdf_manifest, responses=True)
            # Count the received (not reserialized) stripped nonbinary envelope,
            # including whitespace/escaping. Only canonical validated data URLs
            # are removable; encoded JSON escapes cannot buy extra text room.
            binary_size = sum(len(part["file_data"]) for part in file_parts)
            if len(body) - binary_size > PLANNING_REQUEST:
                raise Denied("PDF envelope")
        except ValueError as exc:
            raise Denied("PDF input") from exc
    return data


def stub_response():
    text = "IMP002_SYNTHETIC_OK"
    part = {"type": "output_text", "text": text, "annotations": []}
    item = {"id": "msg_synthetic", "type": "message", "role": "assistant",
            "status": "completed", "content": [part]}
    response = {"id": "resp_synthetic", "object": "response", "created_at": 1,
                "model": MODEL, "status": "completed", "output": [item],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
    events = [
        ("response.created", {"response": dict(response, status="in_progress", output=[])}),
        ("response.output_item.added", {"output_index": 0, "item": dict(item, content=[])}),
        ("response.content_part.added", {"item_id": item["id"], "output_index": 0,
                                         "content_index": 0, "part": dict(part, text="")}),
        ("response.output_text.delta", {"item_id": item["id"], "output_index": 0,
                                        "content_index": 0, "delta": text}),
        ("response.output_text.done", {"item_id": item["id"], "output_index": 0,
                                       "content_index": 0, "text": text}),
        ("response.content_part.done", {"item_id": item["id"], "output_index": 0,
                                        "content_index": 0, "part": part}),
        ("response.output_item.done", {"output_index": 0, "item": item}),
        ("response.completed", {"response": response}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(dict(fields, type=name, sequence_number=i))}\n\n"
                   for i, (name, fields) in enumerate(events)).encode()


def content_length(value, maximum=MAX_REQUEST, *, pdf_mode=False):
    """Shared bounded framing shape. Eight digits ONLY in explicit PDF mode."""
    if pdf_mode:
        if maximum != pdf_contract().MAX_PDF_FRAME:
            raise Denied("PDF length mode")
    elif not 1 <= maximum <= 512 * 1024:
        raise Denied("length mode")
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal()
            or len(value) > (8 if pdf_mode else 7)):
        raise Denied("length")
    length = int(value)
    if not 1 <= length <= maximum:
        raise Denied("length bound")
    return length


def read_request(stream, max_request=MAX_REQUEST, *, pdf_mode=False):
    # Deliberately no chunked encoding, redirects, CONNECT, upgrades or general
    # proxy semantics. The shim constructs a new request; worker auth is discarded.
    line = stream.readline(4097)
    if len(line) > 4096 or not line.endswith(b"\r\n"):
        raise Denied("request line")
    try:
        method, route, version = line.decode("ascii").strip().split(" ")
    except (ValueError, UnicodeError) as exc:
        raise Denied("request line") from exc
    if version != "HTTP/1.1":
        raise Denied("version")
    headers = {}
    total = 0
    for _ in range(32):
        line = stream.readline(4097)
        total += len(line)
        if total > 8192 or not line.endswith(b"\r\n"):
            raise Denied("headers")
        if line == b"\r\n":
            break
        try:
            key, value = line.decode("ascii").rstrip("\r\n").split(":", 1)
        except (ValueError, UnicodeError) as exc:
            raise Denied("header") from exc
        key = key.lower()
        if key in headers or key not in {"host", "content-type", "content-length", "connection"}:
            raise Denied("header forbidden")
        headers[key] = value.strip()
    else:
        raise Denied("headers")
    if headers.get("content-type") != "application/json":
        raise Denied("content type")
    length = content_length(headers.get("content-length", ""), max_request, pdf_mode=pdf_mode)
    body = stream.read(length)
    if len(body) != length:
        raise Denied("truncated")
    return method, route, body


def respond(connection, status, body, content_type="application/json"):
    if len(body) > MAX_RESPONSE:
        raise Denied("response bound")
    head = (f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode()
    connection.sendall(head + body)


class SyntheticRelay:
    """One serial request at a time, bounded lifetime/calls; no public listener.

    An operator can supply a trusted transport. No host transport module/config/auth
    is copied into the worker; this relay's default is still entirely synthetic.
    """

    def __init__(self, path: Path, lifetime=30, transport=None, *, planning=False, input_text_limit=64000,
                 receipts=None):
        if not 1 <= lifetime <= 60:
            raise ValueError("lifetime")
        self.path = path
        self.deadline = time.monotonic() + lifetime
        self.stop = threading.Event()
        self.calls = 0
        self.connections = 0
        self.denied = 0
        self.observed = []  # Only protocol shape/errors; never prompt/body/header values.
        self.transport = transport
        self.receipts = receipts  # Host construction only; never a worker field.
        self.pdf_manifest = None
        if receipts is not None and receipts.native:
            if not planning or input_text_limit != 384 * 1024 or transport is None:
                raise ValueError("PDF transport absent")
            self.pdf_manifest = pdf_contract().native_manifest(receipts.original_manifest)
        self.planning = planning
        if input_text_limit != 64000 and not (planning and input_text_limit == 384 * 1024):
            raise ValueError("input bound")
        self.input_text_limit = input_text_limit
        if planning:
            from imp024_protocol import MAX_REQUEST as request_bound, MAX_RESPONSE as response_bound, MAX_CALLS as call_bound
            self.max_request, self.max_response, self.max_calls = request_bound, response_bound, call_bound
        else:
            self.max_request, self.max_response, self.max_calls = MAX_REQUEST, MAX_RESPONSE, MAX_CALLS
        if self.pdf_manifest is not None:
            self.max_request = pdf_contract().MAX_PDF_FRAME
        self.active = None
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(str(path))
        path.chmod(0o600)
        self.listener.listen(2)
        self.listener.settimeout(0.1)
        self.thread = threading.Thread(target=self.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        if self.active is not None:
            try:
                self.active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.thread.join(IO_TIMEOUT + 1)
        self.listener.close()
        self.path.unlink(missing_ok=True)
        if self.thread.is_alive():
            raise RuntimeError("relay did not stop")
        self.transport = None
        self.pdf_manifest = None

    def run(self):
        while not self.stop.is_set() and time.monotonic() < self.deadline:
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            with connection:
                self.active = connection
                transfer_timeout = pdf_contract().PDF_TRANSFER_SECONDS if self.pdf_manifest is not None else IO_TIMEOUT
                connection.settimeout(transfer_timeout)
                finished = threading.Event()
                cancelled = threading.Event()
                deadline = min(self.deadline, time.monotonic() + (
                    transfer_timeout + CALL_TIMEOUT if self.pdf_manifest is not None else CALL_TIMEOUT))

                def guard():
                    # A total bound also covers a request trickled below the
                    # per-read idle timeout. Closing the shim peer cancels TLS.
                    while not finished.wait(0.025):
                        if self.stop.is_set() or time.monotonic() >= deadline:
                            cancelled.set()
                            try:
                                connection.shutdown(socket.SHUT_RDWR)
                            except OSError:
                                pass
                            return

                watcher = threading.Thread(target=guard, daemon=True)
                watcher.start()
                submission = None
                body = data = None
                try:
                    self.connections += 1
                    if self.connections > self.max_calls:
                        raise Denied("connection bound")
                    uid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
                    if uid != os.geteuid():
                        raise Denied("peer")
                    with connection.makefile("rb") as stream:
                        method, route, body = read_request(stream, self.max_request,
                                                           pdf_mode=self.pdf_manifest is not None)
                    self.calls += 1
                    if self.calls > self.max_calls:
                        raise Denied("call bound")
                    # Never retain attacker-controlled route or JSON key values.
                    self.observed.append({"inference_route": route == ROUTE})
                    if self.receipts is not None:
                        submission = self.receipts.begin(body)
                    try:
                        if self.input_text_limit == 64000:
                            data = validate(method, route, body, planning=self.planning)
                        else:
                            data = validate(method, route, body, planning=self.planning,
                                            input_text_limit=self.input_text_limit, pdf_manifest=self.pdf_manifest)
                    except Denied as exc:
                        self.observed[-1]["denial"] = str(exc)
                        raise
                    connection.settimeout(IO_TIMEOUT)  # Response/control writes retain their small idle bound.
                    if submission is not None:
                        # Native binding/gating MUST occur after the trusted transport
                        # substitutes its model and serializes the final body. This
                        # pre-transport seam validates only, never grants a send.
                        if submission.ledger.native:
                            submission.check(data)
                        else:
                            submission.bind(data)
                    if self.transport is None and self.planning:
                        raise Denied("planning transport absent")
                    if self.transport is None:
                        respond(connection, "200 OK", stub_response(), "text/event-stream")
                    else:
                        self.stream(connection, data, cancelled, deadline, submission=submission)
                except (Denied, OSError, ValueError, RecursionError):
                    self.denied += 1
                    try:
                        respond(connection, "403 Forbidden", b'{"error":"inference denied"}')
                    except OSError:
                        pass
                finally:
                    if submission is not None:
                        submission.finish()
                    body = data = submission = None
                    finished.set()
                    watcher.join(1)
                    self.active = None

    def stream(self, connection, data, cancelled, deadline, *, submission=None):
        # Only fixed sanitized errors cross this boundary. Exceptions/headers/
        # provider bodies must never be logged or forwarded.
        finished = threading.Event()

        def peer_guard():
            while not finished.wait(0.025):
                try:
                    if select.select([connection], [], [], 0)[0]:
                        # EOF, pipelining or any extra worker bytes cancels this
                        # inference. The single request body was already consumed.
                        cancelled.set()
                        return
                except OSError:
                    cancelled.set()
                    return

        watcher = threading.Thread(target=peer_guard, daemon=True)
        watcher.start()
        events = None
        started = False
        size = 0
        try:
            if submission is None:
                events = self.transport.events(data, cancelled, deadline)
            else:
                # Pass capability only to the injected TRUSTED HOST transport.
                # Worker ACK/events cannot reach or mutate this ledger.
                events = self.transport.events(data, cancelled, deadline, submission=submission)
            if self.planning:
                from imp024_inference import normalized_events
                events = normalized_events(events, data)
            for event in events:
                if self.pdf_manifest is not None:
                    # Even a mistakenly injected fixture cannot project successful
                    # native output without the actual gated transport submission.
                    if submission is None or not submission.consumed_gate or submission.row["status"] != "sent":
                        raise Denied("PDF submission absent")
                size += len(event)
                if size > self.max_response or cancelled.is_set() or time.monotonic() >= deadline:
                    raise Denied("stream bound")
                if not started:
                    connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                                       b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
                    started = True
                connection.sendall(f"{len(event):x}\r\n".encode() + event + b"\r\n")
            if not started:
                raise Denied("empty stream")
            connection.sendall(b"0\r\n\r\n")
        except Exception:
            self.denied += 1
            if not cancelled.is_set():
                try:
                    if started:
                        from imp024_protocol import terminal_error
                        error = terminal_error(1000000)
                        connection.sendall(f"{len(error):x}\r\n".encode() + error + b"\r\n0\r\n\r\n")
                    else:
                        respond(connection, "503 Service Unavailable", b'{"error":"relay unavailable"}')
                except OSError:
                    pass
        finally:
            cancelled.set()
            finished.set()
            try:
                if events is not None:
                    events.close()
            except Exception:
                # Generator cleanup exceptions can contain private SDK/socket
                # data. Never allow a credential-bearing thread traceback.
                self.denied += 1
            watcher.join(1)
