"""Trusted host planning transport; no resolver, environment credentials or tools.

Construct/pin DNS and TLS BEFORE credential input. Only the reviewed human entrypoint
sets the API key in trusted memory. Known public HTTPS:443 Responses/API-key shape
only; unsupported reasoning/provider shapes fail closed, never guessed/adapted.
"""

import json
import re
import threading
import time
from urllib.parse import urlsplit

from imp002_relay import IO_TIMEOUT, ROUTE, decode, validate
from imp002_transport import Contract, HTTPSInference
from imp024_inference import frame, normalized_events, parsed_events
from imp024_protocol import MAX_REQUEST, MAX_RESPONSE, MAX_TOKENS


class Unavailable(ValueError):
    def __init__(self):
        super().__init__("Model connection unavailable")


def require(value):
    if not value:
        raise Unavailable()


def explicit_contract(authority, route, version, deployment):
    """Pure explicit facts, no defaults/private inspection. Key acquired later."""
    require(type(authority) is str and type(route) is str and type(version) is str)
    parts = urlsplit(authority)
    require(parts.scheme == "https" and parts.path == "" and not parts.query
            and not parts.fragment and not parts.username and not parts.password)
    require(route in ("/openai/v1/responses", f"/openai/deployments/{deployment}/responses"))
    require(version == "none" or re.fullmatch(r"[A-Za-z0-9.-]{1,64}", version))
    endpoint = authority + route + ("" if version == "none" else "?api-version=" + version)
    # Contract validates authority, route, deployment and literal API-key grammar;
    # this placeholder is never used for inference or mistaken for host auth.
    return Contract(endpoint, deployment, "unacquired-placeholder")


def no_secret(value, key, depth=0):
    """Reject literal contamination, including JSON-escaped tool argument values."""
    require(depth <= 64)
    if isinstance(value, str):
        require(key not in value)
    elif isinstance(value, dict):
        for name, item in value.items():
            no_secret(name, key, depth + 1)
            no_secret(item, key, depth + 1)
        if value.get("type") == "function_call" and value.get("arguments"):
            no_secret(decode(value["arguments"]), key, depth + 1)
    elif isinstance(value, list):
        for item in value:
            no_secret(item, key, depth + 1)


class PlanningHTTPSInference(HTTPSInference):
    """Same pinned public TLS dialer; bounded native planning, never host tools.

    Literal-key safe prefixes may stream before completion. Tools and terminal
    frames remain held until full normalization. Late failure does not retract
    already safe text and never authorizes proposals. Not an encoded/semantic
    exfiltration guarantee. No retry, redirect, provider IDs or raw errors.
    """

    def acquire(self, key):
        # Reuse literal credential grammar without redoing DNS or spawning a child.
        checked = Contract("https://" + self.contract.host + self.contract.route,
                           self.contract.deployment, key)
        require(key not in self.contract.host and key not in self.contract.route
                and key not in self.contract.deployment)
        self.contract.key = checked.key
        self.emitted_tail = ""

    def for_turn(self):
        # DNS/TLS are already pinned. Only this clone's tail spans the sequential
        # model calls of ONE turn; no project-to-project text state is shared.
        clone = object.__new__(type(self))
        clone.__dict__.update(self.__dict__)
        clone.emitted_tail = ""
        return clone

    def clear(self):
        self.contract.key = ""
        self.emitted_tail = ""

    def events(self, data, cancelled, deadline, *, submission=None):
        require(bool(self.contract.key) and self.contract.key != "unacquired-placeholder")
        native = submission is not None and submission.ledger.native
        manifest = submission.ledger.original_manifest if native else None
        data = validate("POST", ROUTE, json.dumps(data).encode(), planning=True,
                        input_text_limit=384 * 1024, pdf_manifest=manifest)
        no_secret(data, self.contract.key)
        body = dict(data, model=self.contract.deployment, stream=True, store=False,
                    max_output_tokens=min(data.get("max_output_tokens", MAX_TOKENS), MAX_TOKENS))
        encoded = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode()
        if native:
            from app.chat_protocol import MAX_PDF_FRAME
            require(len(encoded) <= MAX_PDF_FRAME)
        else:
            require(len(encoded) <= MAX_REQUEST)
        if submission is not None:
            # Rebind after host validation/model substitution to the actual native
            # input about to be serialized. No worker-provided receipt assertion.
            submission.bind(body, encoded, cancelled=cancelled, deadline=deadline)
        connection = self.connection()
        response = None
        finished = threading.Event()

        def guard():
            while not finished.wait(0.025):
                if cancelled.is_set() or time.monotonic() >= deadline:
                    connection.abort()
                    return

        watcher = threading.Thread(target=guard, daemon=True)
        watcher.start()
        try:
            require(not cancelled.is_set() and time.monotonic() < deadline)
            if submission is not None:
                submission.attempting()
            connection.request("POST", self.contract.route, encoded, {
                "api-key": self.contract.key, "Content-Type": "application/json",
                "Accept": "text/event-stream", "Accept-Encoding": "identity", "Connection": "close"})
            if submission is not None:
                submission.sent()  # Full HTTP request returned; NOT provider acceptance.
            response = connection.getresponse()
            require(response.status == 200
                    and response.getheader("Content-Type", "").split(";", 1)[0] == "text/event-stream"
                    and response.getheader("Content-Encoding", "identity") == "identity"
                    and sum(len(name) + len(value) for name, value in response.getheaders()) <= 8192)
            yield from self.normalize_planning(response, data, cancelled, deadline)
        except Exception:
            raise Unavailable() from None
        finally:
            finished.set()
            connection.abort()
            if response is not None:
                response.close()
            connection.close()
            watcher.join(IO_TIMEOUT + 1)
            require(not watcher.is_alive())

    def normalize_planning(self, response, data, cancelled, deadline):
        prior_tail = self.emitted_tail

        def blocks():
            while True:
                require(not cancelled.is_set() and time.monotonic() < deadline)
                block = response.read1(4096)
                if not block:
                    return
                yield block

        def guarded():
            parsed = parsed_events(blocks())
            text, arguments = "", {}
            try:
                for index, event in enumerate(parsed):
                    no_secret(event, self.contract.key)
                    name = event["type"]
                    if name == "response.output_text.delta":
                        text += event.get("delta", "")
                        no_secret(prior_tail + text, self.contract.key)
                    if name == "response.function_call_arguments.delta":
                        item = event.get("output_index")
                        arguments[item] = arguments.get(item, "") + event.get("delta", "")
                        no_secret(arguments[item], self.contract.key)
                    if name in ("response.failed", "response.incomplete"):
                        yield frame("error", {}, index)
                        return
                    yield frame(name, {k: v for k, v in event.items()
                                       if k not in ("type", "sequence_number")}, index)
            finally:
                parsed.close()

        normalized = normalized_events(guarded(), data)
        try:
            ready, pending = [], ""
            size, sequence = 0, 0
            early = False
            terminal = None

            def emit(value):
                nonlocal sequence
                name = value.pop("type")
                value.pop("sequence_number", None)
                raw = frame(name, value, sequence)
                sequence += 1
                return raw

            def delta(text):
                keep = len(self.contract.key) - 1
                self.emitted_tail = (self.emitted_tail + text)[-keep:] if keep else ""
                return emit({"type": "response.output_text.delta", "output_index": 0,
                             "content_index": 0, "item_id": "msg_planning", "delta": text})

            for raw in normalized:
                size += len(raw)
                require(size <= MAX_RESPONSE)
                value = decode(raw.split(b"data: ", 1)[1].strip())
                no_secret(value, self.contract.key)
                name = value["type"]
                if name == "response.output_text.delta":
                    pending += value["delta"]
                    no_secret(self.emitted_tail + pending, self.contract.key)
                    # Retain the LONGEST suffix that is a proper prefix of key.
                    maximum = min(len(pending), len(self.contract.key) - 1)
                    held = next((length for length in range(maximum, 0, -1)
                                 if pending.endswith(self.contract.key[:length])), 0)
                    safe = pending[:-held] if held else pending
                    # First safe text is genuinely early; subsequent tiny deltas
                    # coalesce to keep existing worker/API event bounds practical.
                    if safe and (not early or len(safe.encode()) >= 1024):
                        pending = pending[len(safe):]
                        early = True
                        yield delta(safe)
                elif name in ("response.created", "response.content_part.added") or (
                        name == "response.output_item.added" and value["item"]["type"] == "message"):
                    yield emit(value)
                else:
                    ready.append(value)
                    if name in ("response.completed", "error"):
                        terminal = name
            require(terminal is not None)
            if terminal == "response.completed" and pending:
                no_secret(self.emitted_tail + pending, self.contract.key)
                yield delta(pending)
            for value in ready:
                yield emit(value)
        finally:
            normalized.close()
