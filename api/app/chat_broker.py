"""API-side fixed Unix client. Never receives provider/worker authentication."""

from __future__ import annotations

import os
import socket
import stat
import struct
import threading
from typing import Any, Protocol

from app.chat_protocol import (
    NATIVE_INLINE_CONTEXT,
    PDF_TRANSFER_SECONDS,
    STOP_SECONDS,
    ChannelError,
    encode_request,
    receive,
    request,
    require,
)

SOCKET_PATH = "/run/impostr-broker/channel.sock"


class Broker(Protocol):
    def call(self, value: dict[str, Any]) -> dict[str, Any]: ...


class UnixBroker:
    def call(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            require(os.geteuid() == 10001)
            request(value)
            native = (
                value.get("op") == "start" and value["payload"].get("kind") == NATIVE_INLINE_CONTEXT
            )
            timeout = (
                PDF_TRANSFER_SECONDS
                if native
                else (STOP_SECONDS + 1 if value.get("op") == "abort" else 3)
            )
            info = os.lstat(SOCKET_PATH)
            require(stat.S_ISSOCK(info.st_mode) and info.st_uid == 1000)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(timeout)
                connection.connect(SOCKET_PATH)
                _, uid, _ = struct.unpack(
                    "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                )
                require(uid == 1000)

                # Total framing deadline as well as idle I/O bound.
                def close_request() -> None:
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

                guard = threading.Timer(timeout + 1, close_request)
                guard.start()
                try:
                    connection.sendall(encode_request(value))
                    result = receive(connection)
                    require(isinstance(result, dict) and result.get("ok") is True)
                    return dict(result)
                finally:
                    guard.cancel()
        except Exception as exc:
            raise ChannelError() from exc
