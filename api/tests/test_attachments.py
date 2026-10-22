"""Functional raw intake tests; no extractor, dispatcher or model execution."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect
from test_projects import _login

from app import attachments
from app.main import create_app
from app.models import AuditEvent, Project, ProjectAttachment, User, WebSession
from app.pdf_protocol import LABEL, MAX_ORIGINAL, POLICY

PDF = b"%PDF-1.7\nSynthetic raw intake only; not structurally validated.\n%%EOF\n"


def headers(client):
    return {
        "Origin": "http://127.0.0.1:8080",
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }


def upload(client, base, body=PDF, **kwargs):
    return client.post(
        base + "/upload",
        params={"filename": 'Reference "017".pdf'},
        content=body,
        headers={**headers(client), "Content-Type": "application/pdf"},
        **kwargs,
    )


def setup_intake(client):
    _login(client, "pdf-owner", "synthetic PDF passphrase")
    project = client.post(
        "/api/projects", json={"name": "Private PDF intake"}, headers=headers(client)
    ).json()["id"]
    root = f"/api/projects/{project}/chat"
    conversation = client.post(
        root, json={"title": "PDF reference"}, headers=headers(client)
    ).json()["id"]
    return project, root, root + f"/{conversation}/attachments"


@pytest.fixture
def intake_setup(client, engine, account_factory):
    account_factory("pdf-owner", "synthetic PDF passphrase")
    project, root, base = setup_intake(client)
    return client, engine, project, root, base


def ready_derivative(db, attachment_id, text='Literal <script>alert("x")</script> & café\f\f'):
    row = db.get(ProjectAttachment, uuid.UUID(attachment_id))
    row.status = "ready"
    row.text_content = text
    row.text_size = len(text.encode())
    row.text_sha256 = hashlib.sha256(text.encode()).hexdigest()
    row.page_count = 2
    row.missing_pages = [2]
    row.extraction_policy = POLICY
    row.qpdf_version = "11.3.0"
    row.pdftotext_version = "22.12.0"
    row.extractor_build_sha256 = "a" * 64


def check_roundtrip(client, engine, base, stage=lambda _: None):
    stage("roundtrip_upload")
    response = upload(client, base)
    assert response.status_code == 201
    metadata = response.json()
    attachment_id = metadata["id"]
    uuid.UUID(attachment_id)
    assert metadata["status"] == "stored" and metadata["native_available"] is True
    assert metadata["processing_available"] is False and metadata["included_in_model"] is False
    assert metadata["original_sha256"] == hashlib.sha256(PDF).hexdigest()
    assert metadata["original_size"] == len(PDF)
    assert metadata["provenance"] is None
    assert "original" not in metadata and "text_content" not in metadata
    stage("roundtrip_stored_original")
    with Session(engine) as db:
        stored = db.get(ProjectAttachment, uuid.UUID(attachment_id))
        assert stored.original == PDF and stored.attempt_count == 0 and stored.lease_id is None
    stage("roundtrip_raw")
    raw = client.get(base + f"/{attachment_id}/raw")
    assert raw.status_code == 200 and raw.content == PDF
    assert hashlib.sha256(raw.content).hexdigest() == metadata["original_sha256"]
    assert raw.headers["content-disposition"] == (
        f'attachment; filename="attachment-{attachment_id}.pdf"'
    )
    assert raw.headers["x-content-type-options"] == "nosniff"
    assert raw.headers["cache-control"] == "no-store"
    stage("roundtrip_pending_metadata")
    assert client.get(base + f"/{attachment_id}/preview").status_code == 409
    assert client.get(base).json()["attachments"] == [metadata]
    stage("roundtrip_derivative_commit")
    with Session(engine) as db, db.begin():
        ready_derivative(db, attachment_id)
    stage("roundtrip_preview")
    preview = client.get(base + f"/{attachment_id}/preview")
    assert preview.status_code == 200
    assert "<script>" not in preview.text and "&lt;script&gt;" in preview.text
    assert "&amp; café" in preview.text and LABEL in preview.text
    assert preview.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in preview.headers["content-security-policy"]
    assert client.get(base + f"/{attachment_id}").json()["missing_pages"] == [2]
    stage("roundtrip_delete")
    assert client.delete(base + f"/{attachment_id}", headers=headers(client)).status_code == 204
    with Session(engine) as db:
        assert db.get(ProjectAttachment, uuid.UUID(attachment_id)) is None
    for suffix in ("", "/raw", "/preview"):
        assert client.get(base + f"/{attachment_id}" + suffix).status_code == 404
    assert client.get(base).json()["attachments"] == []


def test_pending_commit_exact_download_escaped_ready_preview_and_delete(intake_setup):
    client, engine, _, _, base = intake_setup
    check_roundtrip(client, engine, base)


@pytest.mark.parametrize("declared", [None, "1"])
def test_real_overcap_stream_rejected_independent_of_content_length(intake_setup, declared):
    client, engine, _, _, base = intake_setup
    check_overcap(client, engine, base, declared)


def check_overcap(client, engine, base, declared, stage=lambda _: None):
    def body():
        yield b"%PDF-"
        remaining = MAX_ORIGINAL - 5
        while remaining:
            block = b"x" * min(65536, remaining)
            yield block
            remaining -= len(block)
        yield b"!"

    supplied = {**headers(client), "Content-Type": "application/pdf"}
    if declared is not None:
        supplied["Content-Length"] = declared
    stage("overcap_upload")
    response = client.post(base + "/upload?filename=large.pdf", content=body(), headers=supplied)
    assert response.status_code == 413
    failed = response.json()["attachment"]
    assert failed["status"] == "failed" and failed["failure_code"] == "limit"
    assert failed["original_sha256"] is None and failed["original_size"] is None
    stage("overcap_discarded_blob")
    with Session(engine) as db:
        row = db.get(ProjectAttachment, uuid.UUID(failed["id"]))
        assert row.original is None and row.text_content is None
    stage("overcap_metadata")
    assert client.get(base + f"/{failed['id']}/raw").status_code == 404
    assert client.get(base).json()["attachments"][0]["failure_code"] == "limit"
    stage("overcap_recovery")
    assert client.delete(base + f"/{failed['id']}", headers=headers(client)).status_code == 204
    assert upload(client, base).status_code == 201


@pytest.mark.parametrize(
    "body,content_type,code,status",
    [
        (b"<html>spoof</html>", "application/pdf", "invalid", 422),
        (b"", "application/pdf", "invalid", 422),
        (PDF, "text/html", "invalid", 415),
    ],
)
def test_envelope_failures_retain_only_safe_metadata(
    intake_setup, body, content_type, code, status
):
    client, engine, _, _, base = intake_setup
    response = client.post(
        base + "/upload?filename=spoof.pdf",
        content=body,
        headers={**headers(client), "Content-Type": content_type},
    )
    assert response.status_code == status
    metadata = response.json()["attachment"]
    assert metadata["failure_code"] == code
    with Session(engine) as db:
        row = db.get(ProjectAttachment, uuid.UUID(metadata["id"]))
        assert row.original is None and row.text_content is None


def test_scope_revocation_csrf_and_filename_denials(
    intake_setup, account_factory, settings, workspace_root
):
    client, engine, _, root, base = intake_setup
    attachment_id = upload(client, base).json()["id"]
    second = client.post(root, json={"title": "Second"}, headers=headers(client)).json()["id"]
    wrong = root + f"/{second}/attachments"
    other_project = client.post(
        "/api/projects", json={"name": "Other private PDF project"}, headers=headers(client)
    ).json()["id"]
    wrong_project = base.replace(root.split("/")[3], other_project)
    for scoped in (wrong, wrong_project):
        for suffix in ("", "/raw", "/preview"):
            assert client.get(scoped + f"/{attachment_id}" + suffix).status_code == 404
        assert (
            client.delete(scoped + f"/{attachment_id}", headers=headers(client)).status_code == 404
        )
    assert upload(client, wrong_project).status_code == 404
    assert client.post(base + "/upload?filename=x.pdf", content=PDF).status_code == 403
    assert client.delete(base + f"/{attachment_id}").status_code == 403
    for filename in ("../x.pdf", "x\r\ny.pdf", "x.html"):
        assert (
            client.post(
                base + "/upload",
                params={"filename": filename},
                content=PDF,
                headers=headers(client),
            ).status_code
            == 422
        )
    account_factory("pdf-other", "synthetic other PDF passphrase")
    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as other:
        _login(other, "pdf-other", "synthetic other PDF passphrase")
        for suffix in (
            "",
            f"/{attachment_id}",
            f"/{attachment_id}/raw",
            f"/{attachment_id}/preview",
        ):
            assert other.get(base + suffix).status_code == 404
        assert upload(other, base).status_code == 404
        assert other.delete(base + f"/{attachment_id}", headers=headers(other)).status_code == 404
    with Session(engine) as db, db.begin():
        db.execute(update(WebSession).values(revoked_at=datetime.now(UTC)))
    for suffix in ("", f"/{attachment_id}", f"/{attachment_id}/raw", f"/{attachment_id}/preview"):
        assert client.get(base + suffix).status_code == 401
    assert upload(client, base).status_code == 401
    assert client.delete(base + f"/{attachment_id}", headers=headers(client)).status_code == 401


@pytest.mark.parametrize("change", ["revocation", "owner"])
def test_rechecks_authority_after_body_before_commit(
    intake_setup, monkeypatch, account_factory, change
):
    client, engine, project_id, _, base = intake_setup
    original = attachments.original_body
    other_id = account_factory("pdf-transfer", "synthetic other PDF passphrase")

    async def revoke_after_body(chunks):
        value = await original(chunks)
        with Session(engine) as db, db.begin():
            if change == "revocation":
                db.execute(update(WebSession).values(revoked_at=datetime.now(UTC)))
            else:
                db.execute(
                    update(Project)
                    .where(Project.id == uuid.UUID(project_id))
                    .values(owner_user_id=other_id)
                )
        return value

    monkeypatch.setattr(attachments, "original_body", revoke_after_body)
    assert upload(client, base).status_code == (401 if change == "revocation" else 404)
    with Session(engine) as db:
        assert db.scalar(select(ProjectAttachment.id)) is None


def test_interrupted_upload_discards_partial_blob_and_retains_failure(intake_setup, monkeypatch):
    client, engine, _, _, base = intake_setup

    async def interrupted(_):
        raise ClientDisconnect()

    monkeypatch.setattr(attachments, "original_body", interrupted)
    response = upload(client, base)
    assert response.status_code == 400
    metadata = response.json()["attachment"]
    assert metadata["failure_code"] == "upload_interrupted"
    with Session(engine) as db:
        row = db.get(ProjectAttachment, uuid.UUID(metadata["id"]))
        assert row.original is None and row.original_size is None


def test_metadata_queries_do_not_fetch_deferred_blobs_and_admin_reads_are_audited(intake_setup):
    client, engine, _, _, base = intake_setup
    attachment_id = upload(client, base).json()["id"]
    with Session(engine) as db, db.begin():
        db.execute(update(User).where(User.username == "pdf-owner").values(role="admin"))
    statements = []

    def capture(_, __, statement, *args):
        if statement.lstrip().upper().startswith("SELECT") and "project_attachments" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert client.get(base).status_code == 200
        assert client.get(base + f"/{attachment_id}").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert statements
    assert all(
        "project_attachments.original," not in sql and "project_attachments.text_content" not in sql
        for sql in statements
    )
    with Session(engine) as db:
        reads = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "admin.project.attachment.read")
        )
        assert len(list(reads)) == 2
