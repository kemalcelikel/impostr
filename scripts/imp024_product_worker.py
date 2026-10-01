"""Namespace-local product adapter, using the delivered phase-one planning driver.

Only framed control on inherited pipes; no host listener/mount/proxy. Execution
requires independent review. No private config, provider or broker credential.
"""

import json
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
                            require, start_payload, prompt_text)
from imp024_worker import Driver, Events, generated_config, read_surface


class ProductDriver(Driver):
    # Only product history reconstruction increases the native prompt input cap;
    # canonical documents/tool arguments/results and output keep phase-one caps.
    max_prompt = MAX_CONTEXT


class ProductEvents(Events):
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
    payload = start_payload(receive(Input()))
    validate_surface(payload)
    shim = HTTPServer(("127.0.0.1", 0), Shim)
    shim.max_request = shim.max_response = 512 * 1024
    shim_thread = threading.Thread(target=shim.serve_forever,
        kwargs={"poll_interval": 0.05}, daemon=True)
    shim_thread.start()
    with socket.socket(socket.AF_INET) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    password = secrets.token_hex(32)
    driver = ProductDriver(port, password)
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
            json.dump(generated_config(shim.server_address[1]), stream)
        server.start()
        events = ProductEvents(driver)
        session = driver.create("Product planning conversation")
        emit("started", {"native_session_id": session,
                          "context_reconstructed": bool(payload["history"])})
        threading.Thread(target=read_controls, daemon=True).start()
        driver.prompt(session, prompt_text(payload))
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


if __name__ == "__main__":
    raise SystemExit(main())
