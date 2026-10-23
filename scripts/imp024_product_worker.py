"""Namespace-local product adapter, using the delivered phase-one planning driver.

Only framed control on inherited pipes; no host listener/mount/proxy. Execution
requires independent review. No private config, provider or broker credential.
"""

import json
import math
import os
import queue
import secrets
import socket
import threading
import time
from http.server import HTTPServer

import imp023_worker as previous
from imp002_worker import Shim
from imp024_channel import (FILES, MAX_CONTEXT, MAX_FRAME, TURN_SECONDS, answer, encode, event, receive,
                            require, broker_start_payload, resolved_prompt_text)
from imp024_worker import Driver, Events, TOOL_DENIALS, generated_config, read_surface
from imp024_channel import (MAX_PDF_FRAME, native_file_parts,
                            native_prompt_parts, pdf_envelope, native_manifest, occurrence_filename,
                            inline_pdf_data, native_dispatch_context, native_prompt_text,
                            receive_dispatch, NATIVE_INLINE_CONTEXT, PDF_TRANSFER_SECONDS)
from imp024_protocol import identifier


def native_prompt_body(context):
    """Explicit selected native parts, never repository file discovery/read grants."""
    parts = native_prompt_parts(context)
    body = dict(model=previous.MODEL, agent="tech-lead", tools=dict(TOOL_DENIALS), parts=parts)
    pdf_envelope(body, dict(body, parts=[parts[0]] + [dict(part, url="") for part in parts[1:]]))
    return body


def _echo_file(part, session):
    require(isinstance(part, dict) and {"type", "mime", "url", "filename"} <= set(part)
            <= {"type", "mime", "url", "filename", "id", "sessionID", "messageID"})
    require(part.get("sessionID") == session)
    for key in ("id", "messageID"):
        if key in part:
            identifier(part[key])
    return {key: part[key] for key in ("type", "mime", "url", "filename")}


def strip_native_history(value, session, manifest, *, allow_partial=False):
    """Bound/verify user file echoes, then discard them BEFORE ordinary history checks.

    Assistant/tool attachments,
    arbitrary source paths, extra binary fields and reordered echoes fail. During
    prompt materialization only, a validated prefix returns None (not history).
    The default still requires the full exact manifest.
    """
    manifest = native_manifest(manifest)
    require(isinstance(value, list) and len(value) < 16)
    files, stripped, envelope = [], [], []
    for message in value:
        require(isinstance(message, dict) and isinstance(message.get("info"), dict)
                and message["info"].get("sessionID") == session and isinstance(message.get("parts"), list))
        parts, bounded_parts = [], []
        for part in message["parts"]:
            require(isinstance(part, dict))
            if part.get("type") == "file":
                require(message["info"].get("role") == "user")
                files.append(_echo_file(part, session))
                bounded_parts.append(dict(part, url=""))
            else:
                require(part.get("type") not in ("subtask", "agent"))
                if part.get("type") == "tool":
                    require(isinstance(part.get("state"), dict) and not part["state"].get("attachments"))
                parts.append(part)
                bounded_parts.append(part)
        stripped.append(dict(message, parts=parts))
        envelope.append(dict(message, parts=bounded_parts))
    require(len(files) <= len(manifest))
    native_file_parts(files, manifest[:len(files)])
    pdf_envelope(value, envelope)
    if len(files) != len(manifest):
        require(allow_partial)
        return None
    return stripped


def native_event_projection(value, sessions, manifest):
    """Only a validated known PDF echo gets the large bound, and projects to nothing."""
    from imp024_worker import event_projection

    manifest = native_manifest(manifest)
    if isinstance(value, dict) and value.get("type") == "message.part.updated":
        fields = value.get("properties", {})
        part = fields.get("part") if isinstance(fields, dict) else None
        if isinstance(part, dict) and part.get("type") == "file":
            # Known OpenCode envelopes add an event ID and session/time metadata;
            # these do not authorize extra file fields or a different session.
            require({"type", "properties"} <= set(value) <= {"type", "properties", "id"}
                    and {"part"} <= set(fields) <= {"part", "sessionID", "time"})
            if "id" in value:
                identifier(value["id"])
            require(part.get("sessionID") in sessions)
            if "sessionID" in fields:
                require(identifier(fields["sessionID"]) == part["sessionID"])
            if "time" in fields:
                require(type(fields["time"]) in (int, float) and math.isfinite(fields["time"]))
            file = _echo_file(part, part["sessionID"])
            matches = [item for item in manifest if occurrence_filename(item) == file["filename"]]
            require(len(matches) == 1)
            # Single-event subset retains the original ordinal identity.
            require(file["type"] == "file" and file["mime"] == "application/pdf")
            inline_pdf_data(file["url"], matches[0])
            pdf_envelope(value, dict(value, properties=dict(fields, part=dict(part, url=""))))
            return None
    # Unknown/assistant/text/tool events keep their original small frame and
    # projection caps, even during a PDF-bearing turn.
    encode(value)
    return event_projection(value, sessions)


class NativeEchoStream:
    """Bounded reader state; only binary-free projections enter ProductEvents.queue.

    Full binary echoes share ONE 68 MiB stream budget, rather than granting that
    allowance to every arbitrary message. Non-file events still share 512 KiB.
    Unexpected/repeated oversized echoes fail visibly rather than inflate queues.
    """
    def __init__(self, sessions, manifest):
        self.sessions = set(sessions)
        self.manifest = native_manifest(manifest)
        self.bytes = self.nonbinary_bytes = self.events = 0

    def read(self, stream):
        value, size = previous.parse_event(stream, max_line=MAX_PDF_FRAME, max_event=MAX_PDF_FRAME)
        projected = native_event_projection(value, self.sessions, self.manifest)
        file_echo = value.get("type") == "message.part.updated" and value.get(
            "properties", {}).get("part", {}).get("type") == "file"
        self.bytes += size
        self.events += 1
        require(self.bytes <= MAX_PDF_FRAME and self.events <= 256 + len(self.manifest))
        self.nonbinary_bytes += size - len(value["properties"]["part"]["url"]) if file_echo else size
        require(self.nonbinary_bytes <= MAX_FRAME)
        return projected


class ProductDriver(Driver):
    # Only product history reconstruction increases the native prompt input cap;
    # canonical documents/tool arguments/results and output keep phase-one caps.
    max_prompt = MAX_CONTEXT

    def __init__(self, port, password, *, native_context=None):
        super().__init__(port, password)
        self.native_context = native_dispatch_context(native_context) if native_context is not None else None
        self.native_manifest = [item["manifest"] for item in self.native_context["files"]] if self.native_context else None
        self.native_prompted = False

    def request_limit(self, operation):
        return MAX_PDF_FRAME if self.native_manifest is not None and operation == "prompt" else super().request_limit(operation)

    def response_limit(self, operation):
        return MAX_PDF_FRAME if self.native_manifest is not None and operation == "history" else super().response_limit(operation)

    def request_timeout(self, operation):
        if self.native_manifest is not None and operation in ("prompt", "history"):
            remaining = self.deadline - time.monotonic()
            require(remaining > 0)
            return min(PDF_TRANSFER_SECONDS, remaining)
        return super().request_timeout(operation)

    def validate_prompt(self, body, session):
        if self.native_manifest is None:
            return super().validate_prompt(body, session)
        require(self.native_context is not None and self.native_prompted
                and self.active_session == session and session not in self.cancelled_sessions)
        require(body == native_prompt_body(self.native_context))

    def prompt_native(self, session):
        require(self.native_context is not None and not self.native_prompted
                and session in self.sessions and self.active_session is None and self.idle(session))
        self.prior_users = {message["info"]["id"] for message in self.history(session)
                            if message["info"].get("role") == "user"}
        self.captured = read_surface()
        self.active_session = session
        self.turn_text = native_prompt_text(self.native_context["context"])
        self.native_prompted = True  # Commit locally BEFORE I/O; never retry an uncertain prompt.
        self.prompts += 1
        require(self.prompts == 1)
        try:
            return self._request("POST", "prompt", session, native_prompt_body(self.native_context))
        finally:
            self.native_context = None

    def _request(self, method, operation, target=None, body=None, authenticated=True):
        if self.native_manifest is None or operation != "history":
            return super()._request(method, operation, target, body, authenticated)
        require(method == "GET" and body is None and authenticated)
        with self.interaction_lock:
            connection, response = self.open(method, operation, target)
            try:
                raw = response.read(MAX_PDF_FRAME + 1)
                require(len(raw) <= MAX_PDF_FRAME and response.status == 200
                        and response.getheader("Content-Type", "").startswith("application/json"))
                from imp002_relay import decode
                value = decode(raw)
                # prompt_async can ACK before the message AND its separate part
                # writes finish. Validate every observed file as an exact ordered
                # prefix; never expose incomplete history as completion/proof.
                expected = self.native_manifest if self.native_prompted else []
                projected = strip_native_history(value, target, expected,
                                                 allow_partial=self.native_prompted)
                binary = sum(len(part["url"]) for message in value for part in message["parts"]
                             if part.get("type") == "file")
                require(len(raw) - binary <= MAX_FRAME)
                # The existing main status loop polls again within its unchanged
                # turn/start deadline, remaining responsive to aborts/events. No
                # prompt retry, new wait deadline, or partial completion history.
                # Driver.history() validates ordinary tools/metadata once complete.
                return projected if projected is not None else []
            finally:
                response.close()
                connection.close()

    def release(self):
        self.native_context = self.native_manifest = self.turn_text = self.captured = None


class ProductEvents(Events):
    def read(self):
        if self.driver.native_manifest is None:
            return super().read()
        reader = NativeEchoStream(self.driver.sessions, self.driver.native_manifest)
        reader.bytes = reader.nonbinary_bytes = self.bytes  # Include server.connected.
        try:
            while not self.stopped.is_set():
                # Keep the live set: a session can be created while the blocking
                # SSE read waits. Snapshotting BEFORE read rejects its first echo.
                reader.sessions = self.driver.sessions
                projected = reader.read(self.response)
                self.bytes = reader.bytes
                if projected is not None:
                    self.queue.put_nowait(projected)
        except Exception as error:
            if not self.stopped.is_set():
                try:
                    self.queue.put_nowait(self.stream_failure(error))
                except queue.Full:
                    pass

    @property
    def stream_timeout(self):
        # A native question can be quiet while the API recovers its committed
        # pump lease. Silence is not a lost worker. The MAIN loop still enforces
        # the original driver deadline and closes this read on abort/expiry;
        # neither heartbeats nor new events renew the hard turn lifetime.
        remaining = self.driver.deadline - time.monotonic()
        require(remaining > 0)
        return remaining

    @staticmethod
    def stream_failure(error):
        return {"type": "driver.stream.failed", "reason": (
            "native_stream_timeout" if isinstance(error, TimeoutError) else "native_stream_invalid")}

    @staticmethod
    def parse_event(stream):
        # Native message.part.updated echoes the entire reconstructed user text
        # before projection discards non-tool updates. Its frame is larger than
        # phase one's 8 KiB line/32 KiB event defaults, not an assistant delta.
        # Retain the delivered 512 KiB total stream cap and all projection limits.
        return previous.parse_event(stream, max_line=MAX_FRAME, max_event=MAX_FRAME)


def validate_surface(payload):
    # The delivered nofollow binary reader decodes UTF-8 without universal-newline
    # translation. Compare exact canonical bytes, including CRLF, before startup.
    require(read_surface() == {name: payload["documents"][name]["content"] for name in FILES})


class Input:
    def recv(self, size):
        return os.read(0, size)


def emit(kind, data):
    value = encode(event({"type": kind, "data": data}))
    while value:
        count = os.write(1, value)
        require(count > 0)
        value = value[count:]


def main():
    dispatch = receive_dispatch(Input())
    native = dispatch.get("kind") == NATIVE_INLINE_CONTEXT
    payload = dispatch["context"] if native else dispatch
    validate_surface(payload)
    shim = HTTPServer(("127.0.0.1", 0), Shim)
    shim.max_request = shim.max_response = 512 * 1024
    shim.pdf_manifest = [item["manifest"] for item in dispatch["files"]] if native else None
    if native:
        shim.max_request = MAX_PDF_FRAME
    shim_thread = threading.Thread(target=shim.serve_forever,
        kwargs={"poll_interval": 0.05}, daemon=True)
    shim_thread.start()
    with socket.socket(socket.AF_INET) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    password = secrets.token_hex(32)
    driver = ProductDriver(port, password, native_context=dispatch if native else None)
    dispatch = None  # The driver owns the only retained inline prompt.
    server = previous.Server(driver, password)
    events = None
    controls = queue.Queue(maxsize=16)
    stopped = threading.Event()
    failure_reason = "worker_error"

    def read_controls():
        try:
            while not stopped.is_set():
                controls.put_nowait(receive(Input()))
        except Exception:
            try:
                controls.put_nowait({"op": "abort"})
            except queue.Full:
                pass

    try:
        with open("/tmp/generated.json", "w") as stream:
            json.dump(generated_config(shim.server_address[1], native_pdf=native), stream)
        server.start()
        events = ProductEvents(driver)
        session = driver.create("Product planning conversation")
        emit("started", {"native_session_id": session,
                          "context_reconstructed": bool(payload["history"])})
        threading.Thread(target=read_controls, daemon=True).start()
        if native:
            driver.prompt_native(session)
        else:
            driver.prompt(session, resolved_prompt_text(payload))
        pending = {}
        delivered = ""
        next_status = 0
        deadline = min(driver.deadline, time.monotonic() + TURN_SECONDS - 5)
        while time.monotonic() < deadline:
            try:
                control = controls.get_nowait()
            except queue.Empty:
                control = None
            if control:
                require(isinstance(control, dict))
                if control.get("op") == "abort":
                    require(set(control) == {"op"})
                    driver.abort(session)
                    emit("cancelled", {})
                    return 0
                require(set(control) == {"op", "interaction_id", "answer"}
                        and control["op"] == "reply" and control["interaction_id"] in pending)
                kind, value = pending.pop(control["interaction_id"])
                validated = answer(kind, value, control["answer"])
                if kind == "question":
                    driver.question_reply(session, value["id"], validated["answers"])
                else:
                    driver.permission_reply(session, value["id"], validated["reply"])
            try:
                value = events.queue.get(timeout=0.05)
            except queue.Empty:
                value = None
            if value:
                kind, data = value["type"], value.get("properties", {})
                if kind == "driver.stream.failed":
                    failure_reason = value["reason"]
                    raise ValueError("native stream unavailable")
                if kind == "message.part.delta":
                    emit("delta", {"text": data["delta"]})
                    delivered += data["delta"]
                elif kind == "session.error":
                    emit("failed", {"reason": "native_session_error"})
                    return 1
                elif kind == "tool.state":
                    emit("tool", {"tool": data["tool"], "status": data["status"]})
                elif kind in ("question.asked", "permission.asked"):
                    kind = "question" if kind.startswith("question") else "permission"
                    clean = {key: item for key, item in data.items() if key != "sessionID"}
                    require(clean["id"] not in pending)
                    pending[clean["id"]] = (kind, clean)
                    emit(kind, clean)
            # Native finish checks bind the actual dispatched user/assistant and
            # successful tools; an idle heartbeat alone cannot mean completion.
            if pending or time.monotonic() < next_status:
                continue
            next_status = time.monotonic() + 0.5
            if driver.idle(session):
                history = driver.history(session)
                assistants = [item for item in history if item["info"].get("role") == "assistant"]
                if assistants and assistants[-1]["info"].get("time", {}).get("completed"):
                    if assistants[-1]["info"].get("error"):
                        emit("failed", {"reason": "native_session_error"})
                        return 1
                    proposals = driver.finish(session)
                    # Bind incremental bytes to terminal native text, repairing a
                    # status/history race without duplicating queued SSE deltas.
                    final = "".join(part.get("text", "") for item in assistants
                                    for part in item["parts"] if part.get("type") == "text")
                    require(final.startswith(delivered))
                    if final[len(delivered):]:
                        emit("delta", {"text": final[len(delivered):]})
                    emit("completed", {"proposals": proposals})
                    return 0
        failure_reason = "worker_deadline"
        raise ValueError("turn unavailable")
    except Exception:
        emit("failed", {"reason": failure_reason})
        return 1
    finally:
        stopped.set()
        try:
            if events is not None:
                events.close()
        finally:
            try:
                server.close()
            finally:
                shim.shutdown()
                shim.server_close()
                shim_thread.join(3)
                driver.release()
                shim.pdf_manifest = None
                payload = None


if __name__ == "__main__":
    raise SystemExit(main())
