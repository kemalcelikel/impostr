"""Budgeted JSON tree builder, not json.loads followed by after-the-fact checks.

Input byte limit is also enforced while collecting qpdf stdout. Every container,
key/value node and scalar is budgeted before allocation; duplicates are rejected.
"""

import json
import math
import re

from pdf_protocol import PDFError, require

MAX_JSON = 8 * 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 100_000
MAX_DICTIONARIES = 12_000
MAX_SCALAR = 16 * 1024
NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


class Reader:
    def __init__(self, data: bytes):
        require(len(data) <= MAX_JSON, "limit")
        try:
            self.data = data.decode("utf-8")
        except UnicodeError as exc:
            raise PDFError() from exc
        self.pos = self.nodes = self.dictionaries = 0

    def whitespace(self):
        while self.pos < len(self.data) and self.data[self.pos] in " \t\r\n":
            self.pos += 1

    def take(self, char):
        self.whitespace()
        require(self.pos < len(self.data) and self.data[self.pos] == char)
        self.pos += 1

    def string(self):
        start = self.pos
        self.take('"')
        escaped = False
        while self.pos < len(self.data):
            char = self.data[self.pos]
            self.pos += 1
            require(self.pos - start <= MAX_SCALAR, "limit")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                try:
                    value = json.loads(self.data[start:self.pos])
                    require(len(value.encode("utf-8")) <= MAX_SCALAR, "limit")
                    return value
                except (ValueError, UnicodeError) as exc:
                    raise PDFError() from exc
        raise PDFError()

    def value(self, depth=0):
        self.whitespace()
        self.nodes += 1
        require(self.nodes <= MAX_NODES and depth <= MAX_DEPTH, "limit")
        require(self.pos < len(self.data))
        char = self.data[self.pos]
        if char == '"':
            return self.string()
        if char in "[{":
            self.pos += 1
            close = "]" if char == "[" else "}"
            if char == "{":
                self.dictionaries += 1
                require(self.dictionaries <= MAX_DICTIONARIES, "limit")
            value = [] if char == "[" else {}
            self.whitespace()
            require(self.pos < len(self.data))
            if self.data[self.pos] == close:
                self.pos += 1
                return value
            while True:
                if char == "[":
                    value.append(self.value(depth + 1))
                else:
                    self.nodes += 1
                    require(self.nodes <= MAX_NODES, "limit")
                    self.whitespace()
                    key = self.string()
                    require(key not in value)
                    self.take(":")
                    value[key] = self.value(depth + 1)
                self.whitespace()
                require(self.pos < len(self.data))
                if self.data[self.pos] == close:
                    self.pos += 1
                    return value
                self.take(",")
        for token, value in (("true", True), ("false", False), ("null", None)):
            if self.data.startswith(token, self.pos):
                self.pos += len(token)
                return value
        match = NUMBER.match(self.data, self.pos)
        require(match is not None)
        require(match.end() - self.pos <= 64, "limit")
        token = match.group()
        self.pos = match.end()
        value = float(token) if any(c in token for c in ".eE") else int(token)
        require(not isinstance(value, float) or math.isfinite(value))
        return value


def parse(data: bytes):
    reader = Reader(data)
    value = reader.value()
    reader.whitespace()
    require(reader.pos == len(reader.data))
    return value
