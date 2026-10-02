"""COORDINATOR ONLY, reviewed owned fixture: HTTP/DB/process + actual PDF channel.

No mocks of conversion or fabricated derivatives. Start with converter stopped;
one fixed coordinator prompt starts the existing verified image. API restart uses
SIGKILL after real extraction/before DB completion. Synthetic data only, bounded
metadata/stage output, no PDF text/SQL/errors/login material on stdout/stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

from imp024_joined import ApiProcess, wait
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session

from app.database import database_url_from_environment
from app.models import Conversation, Project, ProjectAttachment, User, WebSession
from app.passwords import hash_password
from app.pdf_extractor import UnixPDFExtractor
from app.pdf_lifecycle import PDFProcessor
from app.pdf_lifecycle_policy import VERIFIED_BUILD_SHA256
from app.pdf_protocol import LABEL, MAX_CONTROL, SOCKET_PATH, encode, receive

sys.path.insert(0, "/opt/impostr-pdf-fixtures")
from imp017_fixtures import fixtures  # noqa: E402

STAGES = frozenset(
    {
        "prepare",
        "unavailable",
        "ready",
        "busy",
        "rejected",
        "delete",
        "restart",
        "revocation",
        "shutdown",
        "cleanup",
        "unknown",
    }
)


def fixture_only():
    assert os.geteuid() == os.getegid() == 10001
    assert os.environ.get("IMPOSTR_TEST_PDF_LIFECYCLE") == "1"
    assert os.environ.get("IMPOSTR_PDF_ENABLED") == "1"
    assert os.environ.get("IMPOSTR_CHAT_ENABLED", "0") == "0"


def shutdown_lifespan(lifespan, directory):
    @asynccontextmanager
    async def observed(application):
        async with lifespan(application):
            yield
        # Only normal lifespan exit (including PDFProcessor.close/join) attests
        # successful draining. An exception or direct signal death leaves no proof.
        (directory / "shutdown-complete").write_bytes(b"complete\n")

    return observed


def serve(directory, port):
    import uvicorn

    import app.main as main
    from app.config import AppSettings
    from app.pdf_lifecycle import PDFProcessor

    class ObservedExtractor(UnixPDFExtractor):
        def extract(self, metadata, chunks):
            value = super().extract(metadata, chunks)
            gate = directory / "after-extract"
            if gate.exists():
                (directory / "after-extract-entered").touch()
                wait(lambda: not gate.exists(), seconds=10, label="fixture gate")
            return value

    class ObservedProcessor(PDFProcessor):
        def __init__(self, engine):
            super().__init__(engine, ObservedExtractor())

    main.PDFProcessor = ObservedProcessor
    application = main.create_app(settings=AppSettings.from_environment())
    application.router.lifespan_context = shutdown_lifespan(
        application.router.lifespan_context, directory
    )
    uvicorn.run(
        application,
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
    )


class PDFAPI(ApiProcess):
    def launch(self):
        (self.directory / "shutdown-complete").unlink(missing_ok=True)
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                __file__,
                "serve",
                "--directory",
                str(self.directory),
                "--port",
                str(self.port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )

    def graceful_stop(self):
        assert self.process is not None and self.process.poll() is None
        marker = self.directory / "shutdown-complete"
        marker.unlink(missing_ok=True)
        os.killpg(self.process.pid, signal.SIGTERM)
        self.process.wait(timeout=55)
        # Pinned uvicorn 0.54.0 capture_signals re-raises SIGTERM after shutdown.
        # Exit status alone cannot distinguish that from an undrained signal death.
        assert self.process.returncode == -signal.SIGTERM
        assert marker.read_bytes() == b"complete\n"


def check():
    import httpx2

    engine = create_engine(
        database_url_from_environment(),
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
        pool_pre_ping=True,
    )
    user_id = uuid.uuid4()
    username = "pdf-life-" + user_id.hex[:16]
    password = "synthetic disposable PDF lifecycle passphrase"
    project_ids = []
    stage = "prepare"
    api = client = None
    passed = False
    try:
        with TemporaryDirectory(prefix="imp017-life-") as temporary:
            directory = Path(temporary)
            with Session(engine) as db, db.begin():
                db.add(
                    User(
                        id=user_id,
                        username=username,
                        password_hash=hash_password(password),
                        role="user",
                        is_active=True,
                    )
                )
            api = PDFAPI(directory)
            api.start()
            client = httpx2.Client(
                base_url=api.url, timeout=5, trust_env=False, follow_redirects=False
            )
            csrf = client.get("/api/auth/csrf").json()["csrf_token"]
            assert (
                client.post(
                    "/api/auth/login",
                    json={"username": username, "password": password},
                    headers={"Origin": "http://127.0.0.1:8080", "X-CSRF-Token": csrf},
                ).status_code
                == 200
            )

            def headers():
                return {
                    "Origin": "http://127.0.0.1:8080",
                    "X-CSRF-Token": client.cookies.get("impostr_csrf"),
                }

            project = client.post(
                "/api/projects", json={"name": "Synthetic PDF lifecycle"}, headers=headers()
            ).json()["id"]
            project_ids.append(uuid.UUID(project))
            root = f"/api/projects/{project}/chat"
            conversation = client.post(
                root, json={"title": "References"}, headers=headers()
            ).json()["id"]
            base = root + f"/{conversation}/attachments"
            values = fixtures()

            def upload(body):
                response = client.post(
                    base + "/upload?filename=reference.pdf",
                    content=body,
                    headers={**headers(), "Content-Type": "application/pdf"},
                )
                assert response.status_code == 201
                assert response.json()["processing_available"] is True
                assert response.json()["included_in_model"] is False
                return response.json()["id"]

            def state(attachment):
                response = client.get(base + "/" + attachment)
                assert response.status_code == 200
                return response.json()

            def terminal(attachment, expected):
                def finished():
                    metadata = state(attachment)
                    return metadata if metadata["status"] == expected else None

                return wait(finished, seconds=75, label="PDF durable state")

            stage = "unavailable"
            attachment = upload(values["valid"])
            wait(lambda: state(attachment)["last_error_code"] == "unavailable", seconds=8)
            metadata = state(attachment)
            assert metadata["status"] == "pending" and metadata["next_attempt_at"] is not None
            print("ACTION pdf-start", flush=True)
            assert sys.stdin.readline() == "\n"
            stage = "ready"
            metadata = terminal(attachment, "ready")
            assert 2 <= metadata["attempt_count"] <= 3
            assert metadata["provenance"]["build_sha256"] == VERIFIED_BUILD_SHA256
            assert client.get(base + f"/{attachment}/raw").content == values["valid"]
            preview = client.get(base + f"/{attachment}/preview")
            assert preview.status_code == 200 and LABEL in preview.text
            assert "Synthetic PDF reference 017" in preview.text
            print("PASS transient recovery and actual ready provenance", flush=True)
            mixed = upload(values["mixed"])
            assert terminal(mixed, "ready")["missing_pages"] == [2]

            stage = "busy"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as held:
                held.settimeout(2)
                held.connect(SOCKET_PATH)
                held.sendall(encode({"v": 1, "size": 8, "sha256": "a" * 64}, MAX_CONTROL))
                assert receive(held, time.monotonic() + 2) == {"v": 1, "status": "accepted"}
                attachment = upload(values["valid"])
                wait(lambda: state(attachment)["last_error_code"] == "busy", seconds=4)
            assert terminal(attachment, "ready")["attempt_count"] == 2
            print("PASS actual busy admission and durable retry", flush=True)

            stage = "rejected"
            for fixture, code in (
                ("malformed", "invalid"),
                ("escaped_action", "active_content"),
                ("zero", "no_text"),
                ("page_limit", "limit"),
            ):
                attachment = upload(values[fixture])
                metadata = terminal(attachment, "failed")
                assert metadata["failure_code"] == code and metadata["attempt_count"] == 1
                with Session(engine) as db:
                    row = db.get(ProjectAttachment, uuid.UUID(attachment))
                    assert row.original is None and row.text_content is None
                assert client.get(base + f"/{attachment}/raw").status_code == 404
            print("PASS terminal failures remove retained blobs", flush=True)

            stage = "delete"
            gate = directory / "after-extract"
            entered = directory / "after-extract-entered"
            for scope in ("attachment", "conversation"):
                entered.unlink(missing_ok=True)
                gate.touch()
                attachment = upload(values["valid"])
                wait(entered.exists, seconds=10)
                if scope == "attachment":
                    assert (
                        client.delete(base + "/" + attachment, headers=headers()).status_code == 204
                    )
                else:
                    # Product currently has no conversation-delete HTTP operation;
                    # prove the existing durable FK cascade with the owned fixture DB.
                    with Session(engine) as db, db.begin():
                        db.execute(
                            delete(Conversation).where(Conversation.id == uuid.UUID(conversation))
                        )
                gate.unlink()
                time.sleep(1)
                assert client.get(base + "/" + attachment).status_code == 404
                with Session(engine) as db:
                    assert db.get(ProjectAttachment, uuid.UUID(attachment)) is None
                if scope == "conversation":
                    conversation = client.post(
                        root, json={"title": "Recovery references"}, headers=headers()
                    ).json()["id"]
                    base = root + f"/{conversation}/attachments"
            print("PASS delete during actual extraction cannot resurrect", flush=True)

            stage = "restart"
            entered.unlink()
            gate.touch()
            attachment = upload(values["valid"])
            wait(entered.exists, seconds=10)
            assert state(attachment)["status"] == "processing"
            api.stop()  # Actual API process crash after extraction, before durable ready.
            gate.unlink()
            api.start()
            metadata = terminal(attachment, "ready")
            assert metadata["attempt_count"] == 2
            assert metadata["provenance"]["build_sha256"] == VERIFIED_BUILD_SHA256
            print("PASS API process crash lease recovery", flush=True)

            # Same durable uploaded row: two real PG connections race its expired
            # process lease. Only the winner may submit actual conversion/completion.
            entered.unlink()
            gate.touch()
            concurrent = upload(values["valid"])
            wait(entered.exists, seconds=10)
            api.stop()
            gate.unlink()
            with Session(engine) as db:
                lease = db.get(ProjectAttachment, uuid.UUID(concurrent)).lease_until
            wait(lambda: datetime.now(UTC) >= lease, seconds=50)
            barrier = Barrier(2)

            def contender():
                barrier.wait(timeout=5)
                return PDFProcessor(engine).claim(uuid.UUID(concurrent))

            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(pool.map(lambda _: contender(), range(2)))
            winners = [claim for claim in claims if claim is not None]
            assert len(winners) == 1
            PDFProcessor(engine).process(winners[0])  # Actual converter, not a mock result.
            api.start()
            assert terminal(concurrent, "ready")["attempt_count"] == 2
            print("PASS PostgreSQL concurrent lease ownership", flush=True)

            stage = "revocation"
            with Session(engine) as db, db.begin():
                db.execute(
                    update(WebSession)
                    .where(WebSession.user_id == user_id)
                    .values(revoked_at=datetime.now(UTC))
                )
            for suffix in ("", "/raw", "/preview"):
                assert client.get(base + "/" + attachment + suffix).status_code == 401
            assert client.delete(base + "/" + attachment, headers=headers()).status_code == 401
            print("PASS revoked attachment access denied", flush=True)
            stage = "shutdown"
            api.graceful_stop()
            passed = True
    except Exception as error:
        category = "assertion" if isinstance(error, AssertionError) else "operation"
        print(
            json.dumps(
                {
                    "diagnostic": "imp017_lifecycle",
                    "stage": stage if stage in STAGES else "unknown",
                    "category": category,
                }
            ),
            flush=True,
        )
    finally:
        try:
            if api is not None:
                api.stop()
            if client is not None:
                client.close()
            with Session(engine) as db, db.begin():
                db.execute(delete(Project).where(Project.id.in_(project_ids)))
                db.execute(delete(User).where(User.id == user_id))
            with Session(engine) as db:
                assert db.get(User, user_id) is None
                assert (
                    db.scalar(
                        select(ProjectAttachment.id).where(
                            ProjectAttachment.project_id.in_(project_ids)
                        )
                    )
                    is None
                )
            print("PASS joined owned cleanup", flush=True)
        except Exception:
            passed = False
            print(
                '{"diagnostic":"imp017_lifecycle","stage":"cleanup","category":"operation"}',
                flush=True,
            )
        engine.dispose()
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("serve", "check"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    fixture_only()
    if args.mode == "serve":
        serve(args.directory, args.port)
    else:
        raise SystemExit(check())
