"""Trusted host-only bounded submission ledger. NEVER copied into the worker.

Receipts describe submission, not provider acceptance/comprehension. No input text,
filename, credential, endpoint, tool data or worker event is retained here. A broker
restart loses this ledger: the API must persist observed receipts and interrupt
unknown dispatches, never replay them. Only trusted transports get a call capability.
"""

import copy
import hashlib
import json
import threading
import time

from app.chat_protocol import (MAX_FRAME, MAX_PDF_FRAME, NATIVE_INLINE_CONTEXT,
                               NATIVE_PDF_REFERENCE, SEND_GATE_SECONDS, broker_start_payload,
                               digest, manifest_digest, native_dispatch_context,
                               native_file_parts, native_prompt_text, original_manifest_digest,
                               pdf_envelope, resolved_prompt_text, require, send_authorization)
from imp024_protocol import MAX_CALLS


def native_user_text(data, *, pdf=False):
    users = [item for item in data["input"] if item.get("role") == "user"]
    require(len(users) == 1)
    content = users[0]["content"]
    if isinstance(content, str):
        return content
    require(isinstance(content, list))
    require(all(isinstance(part, dict) and part.get("type") in
                (("input_text", "input_file") if pdf else ("input_text",)) for part in content))
    return "".join(part["text"] for part in content if part["type"] == "input_text")


class Submission:
    """One host-only capability; attempting a write is conservative uncertainty."""
    def __init__(self, ledger, row):
        self.ledger, self.row = ledger, row
        self.bound = False
        self.finished = False
        self.authorized = False
        self.consumed_gate = False
        self.gate_deadline = None
        self.cancelled = None

    def check(self, data):
        require(digest(native_user_text(data, pdf=self.ledger.native)) == self.ledger.rendered_sha256)
        if self.ledger.native:
            parts = []
            for message in data["input"]:
                content = message.get("content", [])
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "input_file":
                            require(message.get("role") == "user")
                            parts.append(part)
            native_file_parts(parts, self.ledger.original_manifest, responses=True)
            stripped = dict(data, input=[dict(message, content=[
                dict(part, file_data="") if part.get("type") == "input_file" else part
                for part in message["content"]]) if isinstance(message.get("content"), list)
                else message for message in data["input"]])
            pdf_envelope(data, stripped)

    def bind(self, data, encoded=None, *, cancelled=None, deadline=None):
        self.check(data)
        canonical = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
        if encoded is None:
            encoded = canonical
        require(encoded == canonical)  # Hash the exact final serialized bytes, not another object.
        require(len(encoded) <= (MAX_PDF_FRAME if self.ledger.native else MAX_FRAME) and not self.finished)
        with self.ledger.lock:
            require(not self.ledger.closed and self.row["status"] == "pending")
            require(not self.ledger.native or not self.bound)
            self.row["request_sha256"] = hashlib.sha256(encoded).hexdigest()
            self.bound = True
            if self.ledger.native:
                require(cancelled is not None and deadline is not None)
                self.cancelled = cancelled
                self.gate_deadline = min(deadline, time.monotonic() + SEND_GATE_SECONDS)
                self.row["request_size"] = len(encoded)
                self.ledger.pending = send_authorization(dict(
                    **{name: self.row[name] for name in (
                        "project_id", "conversation_id", "turn_id", "epoch", "call",
                        "reference_kind", "rendered_sha256", "manifest_sha256",
                        "request_sha256", "request_size")}, original_manifest=self.ledger.original_manifest))
                # The trusted transport retains data/encoded while waiting. API sees
                # ONLY this metadata, no body, credential, DB/browser token or URL.
                while not self.authorized:
                    require(not self.ledger.closed and not self.finished and not cancelled.is_set()
                            and time.monotonic() < self.gate_deadline)
                    self.ledger.changed.wait(min(0.025, max(0, self.gate_deadline - time.monotonic())))

    def attempting(self):
        with self.ledger.lock:
            require(self.bound and not self.finished and self.row["status"] == "pending")
            require(not self.ledger.closed)
            if self.ledger.native:
                require(self.authorized and not self.consumed_gate and not self.cancelled.is_set()
                        and time.monotonic() < self.gate_deadline)
                self.consumed_gate = True
                self.ledger.pending = None
            self.row["status"] = "uncertain"

    def sent(self):
        with self.ledger.lock:
            require(self.bound and not self.finished and self.row["status"] == "uncertain")
            self.row["status"] = "sent"

    def consumed(self, data, *, cancelled=None, deadline=None):
        """Historical text-only fixture consumption; never native PDF sent evidence."""
        require(not self.ledger.native)
        self.bind(data, cancelled=cancelled, deadline=deadline)
        self.attempting()
        self.sent()

    def finish(self):
        with self.ledger.lock:
            if self.row["status"] == "pending":
                self.row["status"] = "failed-before-send"
            self.finished = True
            if self.ledger.active is self:
                self.ledger.pending = None
                self.ledger.active = None
            self.ledger.changed.notify_all()


class ReceiptLedger:
    def __init__(self, key, epoch, payload):
        self.native = payload.get("kind") == NATIVE_INLINE_CONTEXT
        if self.native:
            value = native_dispatch_context(payload)
            metadata = value["context"]
            self.original_manifest = [dict(item["manifest"]) for item in value["files"]]
        else:
            metadata = broker_start_payload(payload)
            self.original_manifest = []
        self.key, self.epoch = key, epoch
        self.rendered_sha256 = digest(native_prompt_text(metadata) if self.native else resolved_prompt_text(metadata))
        self.manifest_sha256 = manifest_digest(metadata)
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.rows = []
        self.closed = False
        self.active = None
        self.pending = None

    def begin(self, body):
        with self.lock:
            require(not self.closed and len(self.rows) < MAX_CALLS)
            require(not self.native or self.active is None)
            row = dict(project_id=self.key[0], conversation_id=self.key[1], turn_id=self.key[2],
                       epoch=self.epoch, call=len(self.rows) + 1,
                       rendered_sha256=self.rendered_sha256, manifest_sha256=self.manifest_sha256,
                        request_sha256=hashlib.sha256(body).hexdigest() if body is not None and not self.native else None,
                        status="pending")
            if self.native:
                row.update(reference_kind=NATIVE_PDF_REFERENCE, request_size=None, authorization_id=None,
                           original_manifest_sha256=original_manifest_digest(self.original_manifest))
            self.rows.append(row)
            submission = Submission(self, row)
            if self.native:
                self.active = submission
            return submission

    def pending_authorization(self):
        with self.lock:
            if (self.pending is None or self.closed or self.active is None or self.active.finished
                    or self.active.cancelled.is_set() or time.monotonic() >= self.active.gate_deadline):
                return None
            return copy.deepcopy(self.pending)

    def grant(self, value):
        value = send_authorization(value, granted=True)
        with self.lock:
            require(self.native and not self.closed and self.active is not None)
            call = self.active
            require(not call.finished and not call.authorized and self.pending is not None)
            require(not call.cancelled.is_set() and time.monotonic() < call.gate_deadline)
            require({k: v for k, v in value.items() if k != "authorization_id"} == self.pending)
            call.row["authorization_id"] = value["authorization_id"]
            call.authorized = True
            self.pending = None  # Grant is never offered/renewed twice, even before a write.
            self.changed.notify_all()

    def snapshot(self):
        with self.lock:
            # A validated-but-not-yet-submitted call is not a final never-sent
            # failure. Do not expose it until attempted or definitively closed.
            return copy.deepcopy([row for row in self.rows if row["status"] != "pending"])

    def close(self):
        # No relay remains when this is called. A stopped turn with no inference
        # attempt still supplies definite never-sent evidence (null request hash).
        if not self.rows:
            self.begin(None).finish()
        with self.lock:
            self.closed = True
            self.pending = None
            self.changed.notify_all()
