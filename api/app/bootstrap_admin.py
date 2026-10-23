"""Interactive offline command for first-admin setup and account recovery."""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.database import get_database_engine
from app.operator import bootstrap_admin, recover_admin


def _read_new_password() -> str:
    if not sys.stdin.isatty():
        raise ValueError("Run this command in an interactive terminal")
    password = getpass.getpass("New administrator password: ")
    confirmation = getpass.getpass("Confirm new administrator password: ")
    if password != confirmation:
        raise ValueError("The passwords did not match")
    return password


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Provision or recover an administrator offline; never pass passwords as arguments."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap", help="Create the first administrator once")
    bootstrap.add_argument("--username", required=True)
    recovery = commands.add_parser("recover", help="Reset and re-enable an existing administrator")
    recovery.add_argument("--username", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        password = _read_new_password()
        engine = get_database_engine()
        try:
            if args.command == "bootstrap":
                bootstrap_admin(engine, args.username, password)
                print("Administrator account provisioned.")
            else:
                recover_admin(engine, args.username, password)
                print("Administrator account recovered.")
        finally:
            engine.dispose()
    except (SQLAlchemyError, ValueError) as exc:
        if isinstance(exc, SQLAlchemyError):
            print("Database operation failed.", file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Administrator operation cancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
