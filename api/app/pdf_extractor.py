"""Private API-side extractor client; no parser, workspace or DB dependencies."""

import os
import socket
import stat
import time
from collections.abc import Iterable
from typing import Any

from app.pdf_protocol import (
    API_UID,
    EXTRACTOR_UID,
    JOB_SECONDS,
    MAX_CONTROL,
    SOCKET_PATH,
    PDFError,
    counted,
    encode,
    metadata,
    peer,
    receive,
    remaining,
    require,
    result,
)


class UnixPDFExtractor:
    def extract(self, original: dict[str, Any], chunks: Iterable[bytes]) -> dict[str, Any]:
        metadata(original)
        deadline = time.monotonic() + JOB_SECONDS
        try:
            require(os.geteuid() == API_UID and os.getegid() == API_UID, "unavailable")
            directory = os.lstat(os.path.dirname(SOCKET_PATH))
            require(
                stat.S_ISDIR(directory.st_mode)
                and directory.st_uid == EXTRACTOR_UID
                and stat.S_IMODE(directory.st_mode) == 0o711,
                "unavailable",
            )
            info = os.lstat(SOCKET_PATH)
            require(
                stat.S_ISSOCK(info.st_mode)
                and info.st_uid == EXTRACTOR_UID
                and info.st_gid == API_UID
                and stat.S_IMODE(info.st_mode) == 0o660,
                "unavailable",
            )
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(remaining(deadline))
                connection.connect(SOCKET_PATH)
                peer(connection, EXTRACTOR_UID)
                connection.sendall(encode(original, MAX_CONTROL))
                accepted = receive(connection, deadline, MAX_CONTROL)
                if accepted.get("status") == "rejected":
                    return result(accepted)
                require(accepted == {"v": 1, "status": "accepted"} and type(accepted["v"]) is int)

                def send(block: bytes) -> None:
                    connection.settimeout(remaining(deadline))
                    connection.sendall(block)

                counted(chunks, send, original)
                connection.shutdown(socket.SHUT_WR)
                value = result(receive(connection, deadline), original)
                connection.settimeout(remaining(deadline))
                require(connection.recv(1) == b"")
                return value
        except PDFError:
            raise
        except TimeoutError as exc:
            raise PDFError("timeout") from exc
        except (OSError, ValueError) as exc:
            raise PDFError("unavailable") from exc
