"""Coordinator-only actual host-UID denial probe. REVIEW before execution."""

import argparse
from pathlib import Path
import os
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from app.chat_protocol import encode, receive, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    require(os.geteuid() == 1000 and args.directory.parent == Path("/tmp/opencode"))
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect(str(args.directory / "channel.sock"))
        connection.sendall(encode({"op": "hello"}))
        require(receive(connection) == {"ok": False})
    print('{"host_uid_peer_denied":true}')


if __name__ == "__main__":
    main()
