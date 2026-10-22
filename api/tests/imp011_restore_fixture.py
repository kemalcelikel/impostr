"""One COORDINATOR-OWNED synthetic DB drill; no pytest suite, browser or provider.

Runs only in the frozen development image against freshly generated Compose DB
settings. JSON output is fixed labels and a digest of synthetic rows/schema only.
No dump bodies, URLs, logins, connection settings or exception details are emitted.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, MetaData, String, Table, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from test_attachments_migration import migrate, seed_history
from test_projects import _login

from app.config import AppSettings
from app.database import get_database_engine
from app.db import Base
from app.main import create_app
from app.models import (
    AttachmentDeletion,
    AttachmentPurge,
    ChatSendAuthorization,
    ChatSubmissionReceipt,
    ChatTurn,
    Project,
    ProjectAttachment,
    ProjectDocument,
    ProjectDocumentRevision,
    User,
    WebSession,
)
from app.passwords import hash_password
from app.project_templates import default_template_root, load_project_templates

sys.path.insert(0, "/opt/impostr-pdf-fixtures")
from imp025_fixtures import text_pdf

PASSWORD = "synthetic disposable restore passphrase"
BODY = text_pdf((b"Synthetic owned database restore",))
DATA_TABLES = (
    "users", "projects", "project_documents", "project_document_revisions",
    "project_document_pair_approvals", "project_approval_manifests", "conversations",
    "chat_turns", "chat_events", "project_attachments", "chat_submission_receipts",
    "chat_send_authorizations", "chat_turn_pdf_selections", "attachment_deletions",
    "attachment_purges", "web_sessions",
)


def seed(engine):
    migrate(engine, "head")
    owner, project, conversation = seed_history(engine)
    now = datetime.now(UTC)
    attachment, tombstone, grant = (uuid.uuid4() for _ in range(3))
    templates = load_project_templates(default_template_root())
    with Session(engine) as db, db.begin():
        db.get(User, owner).password_hash = hash_password(PASSWORD)
        db.add(User(username="restore-outsider", password_hash=hash_password(PASSWORD),
                    role="user", is_active=True))
        for revision in db.scalars(select(ProjectDocumentRevision)):
            document = db.get(ProjectDocument, revision.document_id)
            template = templates[document.kind]
            revision.content = template.content
            revision.content_sha256 = template.sha256
            revision.origin = "template"
            revision.author_user_id = None
            revision.template_source = template.source
            revision.template_sha256 = template.sha256
            if document.kind == "project":
                draft = "# New unapproved restored draft\n"
                document.head_revision_number = 2
                db.add(ProjectDocumentRevision(document_id=document.id, revision_number=2,
                       content=draft, content_sha256=hashlib.sha256(draft.encode()).hexdigest(),
                       origin="human", author_user_id=owner))
        db.add(ProjectAttachment(id=attachment, project_id=project, conversation_id=conversation,
                                 uploader_user_id=owner, filename="synthetic-restore.pdf",
                                 original=BODY, original_size=len(BODY),
                                 original_sha256=hashlib.sha256(BODY).hexdigest(), status="stored"))
        turn = db.scalar(select(ChatTurn))
        turn.submission_state = "sent"
        turn.stop_confirmed = True
        db.add(ChatSubmissionReceipt(turn_id=turn.id, call=1, status="sent",
                                     request_sha256="b" * 64, reference_kind="legacy-text-v1"))
        db.add(ChatSendAuthorization(turn_id=turn.id, call=2, epoch=uuid.uuid4(),
                                     authorization_id=grant, request_sha256="c" * 64,
                                     request_size=1234, original_manifest_sha256="d" * 64,
                                     expires_at=now + timedelta(seconds=30)))
        db.add(ChatSubmissionReceipt(turn_id=turn.id, call=2, status="sent", request_sha256="c" * 64,
                                     reference_kind="native-original-v1", request_size=1234,
                                     authorization_id=grant))
        db.add(AttachmentDeletion(attachment_id=tombstone, project_id=project,
                                  conversation_id=conversation, pending=True))
        db.add(AttachmentPurge(attachment_id=tombstone, turn_id=turn.id))
        db.add(WebSession(token_hash=b"r" * 32, csrf_token_hash=b"s" * 32, user_id=owner,
                          expires_at=now + timedelta(days=1), revoked_at=now))
    with engine.begin() as db:
        selections = Table("chat_turn_pdf_selections", MetaData(), autoload_with=db)
        turn = db.scalar(select(ChatTurn.id))
        for position, kind in enumerate(("legacy-text-v1", "native-original-v1")):
            db.execute(selections.insert().values(turn_id=turn, position=position,
                       attachment_id=attachment, expected_sha256=hashlib.sha256(BODY).hexdigest(),
                       reference_kind=kind))


def _simple_model_enum(sqltext):
    """Anchored DSL from immutable model code only, never DB/user SQL."""
    match = re.fullmatch(
        r"\s*([a-z_][a-z0-9_]*)\s+IN\s*\(\s*"
        r"('[a-z][a-z0-9_-]*'(?:\s*,\s*'[a-z][a-z0-9_-]*')*)\s*\)\s*", sqltext)
    if match is None:
        return None
    return match[1], tuple(re.findall(r"'([a-z][a-z0-9_-]*)'", match[2]))


def _enum_rule(column, members):
    """Closed whole-predicate language, linear in the static member count.

    Unbounded varchar/text casts preserve strings and NULL. Array-wide and
    per-literal casts have identical contents/types. Regex alternatives enumerate
    exactly the previously admitted finite spellings without a Cartesian product
    (chat state has many members). No arbitrary identifiers/values/operators or
    width-limited/CHAR casts can match.
    """
    literals = []
    for member in members:
        literal = f"'{member}'"
        forms = {literal, literal + "::text", literal + "::character varying",
                 f"({literal}::character varying)::text", f"({literal}::text)::character varying"}
        forms |= {f"({form})" for form in forms}
        literals.append("(?:" + "|".join(re.escape(form) for form in sorted(forms)) + ")")
    array = r"ARRAY\[" + ", ".join(literals) + r"\]"
    arrays = [array, r"\(" + array + r"\)", r"\(" + array + r"\)::text\[\]",
              r"\(" + array + r"\)::character varying\[\]"]
    # Quoting each array member also preserves a model label literally named
    # 'null'; an unquoted NULL array element would have different CHECK behavior.
    constants = {"'{" + ",".join(f'"{member}"' for member in members) + "}'"}
    if all(member.lower() != "null" for member in members):
        constants.add("'{" + ",".join(members) + "}'")
    arrays += [re.escape(value + cast) for value in constants
               for cast in ("::text[]", "::character varying[]")]
    columns = [re.escape(form) for form in (column, f"({column})::text", f"(({column})::text)")]
    predicate = "(?:" + "|".join(columns) + r") = ANY \((?:" + "|".join(arrays) + r")\)"
    canonical = column + " IN (" + ",".join(f"'{member}'" for member in members) + ")"
    return canonical, re.compile("(?:" + predicate + r"|\(" + predicate + r"\))")


def _model_enum_checks(metadata):
    rules = {}
    for table in metadata.tables.values():
        if table.schema not in {None, "public"}:
            continue
        for constraint in table.constraints:
            if not isinstance(constraint, CheckConstraint) or constraint.name is None:
                continue
            model = _simple_model_enum(str(constraint.sqltext))
            if model is None:
                continue
            column, members = model
            declared = table.c.get(column)
            # Plain String is VARCHAR. Exclude CHAR, Text, Enum and decorators:
            # their conversions/operator semantics are not assumed equivalent.
            if declared is not None and type(declared.type) is String:
                rules[(table.name, str(constraint.name))] = _enum_rule(column, members)
    return rules


def _constraint_state(row, enum_checks=None):
    """Stable PG17 behavior, not deparser spelling, storage attnums or OIDs.

    SELECT resolves ordered keys/operators to names. CHECK predicates stay exact
    except closed, proven-equivalent spellings of simple static model enum CHECKs.
    Supporting index expressions, predicates and INCLUDE columns are also covered
    by the separate unchanged exact pg_indexes snapshot.
    """
    state = {name: row[name] for name in (
        "table_name", "constraint_name", "kind", "deferrable", "initially_deferred",
        "validated", "no_inherit", "is_local", "inherit_count", "columns",
        "referenced_schema", "referenced_table", "referenced_columns", "update_action",
        "delete_action", "match_type", "delete_set_columns", "nulls_not_distinct",
        "check_expression", "operators",
    )}
    if state["kind"] == "c" and enum_checks is not None:
        rule = enum_checks.get((state["table_name"], state["constraint_name"]))
        expression = state["check_expression"]
        if rule is not None and isinstance(expression, str) and rule[1].fullmatch(expression):
            state["check_expression"] = rule[0]
    return state


def digest(engine):
    """All public rows plus schema definitions; assert restored app-role ownership."""
    enum_checks = _model_enum_checks(Base.metadata)
    with engine.connect() as db:
        tables = inspect(db).get_table_names(schema="public")
        result = {}
        for name in sorted(tables):
            table = Table(name, MetaData(), schema="public", autoload_with=db)
            result[name] = [dict(row._mapping) for row in db.execute(select(table).order_by(*table.primary_key))]
        assert result["alembic_version"] == [{"version_num": "20261022_0013"}], "schema"
        for name in DATA_TABLES:
            assert result[name], "rows"
        attachment = result["project_attachments"][0]
        assert bytes(attachment["original"]) == BODY, "original_identity"
        assert attachment["original_sha256"] == hashlib.sha256(BODY).hexdigest(), "original_identity"
        assert {row["reference_kind"] for row in result["chat_submission_receipts"]} == {
            "legacy-text-v1", "native-original-v1"}, "rows"
        assert result["web_sessions"][0]["revoked_at"] is not None, "rows"
        assert db.scalar(text("""SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                                  WHERE n.nspname='public' AND pg_get_userbyid(c.relowner)<>current_user""")) == 0, "relation_owner"
        assert db.scalar(text("""SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                                  WHERE n.nspname='public' AND pg_get_userbyid(t.typowner)<>current_user""")) == 0, "type_owner"
        result["schema"] = [tuple(row) for row in db.execute(text("""
          SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull,
                 pg_get_expr(d.adbin,d.adrelid)
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
          LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
          WHERE n.nspname='public' ORDER BY c.relname,a.attnum
        """))]
        constraint_rows = [dict(row) for row in db.execute(text("""
          SELECT c.relname AS table_name, k.conname AS constraint_name,
                 k.contype AS kind, k.condeferrable AS deferrable,
                 k.condeferred AS initially_deferred, k.convalidated AS validated,
                 k.connoinherit AS no_inherit, k.conislocal AS is_local,
                 k.coninhcount AS inherit_count,
                 ARRAY(SELECT a.attname
                       FROM unnest(k.conkey) WITH ORDINALITY AS entry(attnum,pos)
                       LEFT JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=entry.attnum
                       ORDER BY CASE WHEN k.contype='c' THEN a.attname END, entry.pos) AS columns,
                 rn.nspname AS referenced_schema, rc.relname AS referenced_table,
                 ARRAY(SELECT a.attname
                       FROM unnest(k.confkey) WITH ORDINALITY AS entry(attnum,pos)
                       JOIN pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=entry.attnum
                       ORDER BY entry.pos) AS referenced_columns,
                 k.confupdtype AS update_action, k.confdeltype AS delete_action,
                 k.confmatchtype AS match_type,
                 ARRAY(SELECT a.attname
                       FROM unnest(k.confdelsetcols) WITH ORDINALITY AS entry(attnum,pos)
                       JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=entry.attnum
                       ORDER BY entry.pos) AS delete_set_columns,
                 CASE WHEN k.contype IN ('p','u','x') THEN i.indnullsnotdistinct END AS nulls_not_distinct,
                 CASE WHEN k.contype='c' THEN pg_get_expr(k.conbin,k.conrelid) END AS check_expression,
                 (SELECT COALESCE(jsonb_agg(jsonb_build_array(op_groups.label, entry.pos,
                                           ns.nspname, o.oprname,
                                           format_type(o.oprleft,NULL),format_type(o.oprright,NULL))
                                          ORDER BY op_groups.label,entry.pos), '[]'::jsonb)
                  FROM (VALUES ('fk_primary_foreign',k.conpfeqop),
                               ('fk_primary_primary',k.conppeqop),
                               ('fk_foreign_foreign',k.conffeqop),
                               ('exclude',k.conexclop)) AS op_groups(label,opids)
                  CROSS JOIN LATERAL unnest(op_groups.opids) WITH ORDINALITY AS entry(opid,pos)
                  JOIN pg_operator o ON o.oid=entry.opid
                  JOIN pg_namespace ns ON ns.oid=o.oprnamespace) AS operators,
                 pg_get_constraintdef(k.oid,true) AS pretty_definition
          FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace
          LEFT JOIN pg_class rc ON rc.oid=k.confrelid
          LEFT JOIN pg_namespace rn ON rn.oid=rc.relnamespace
          LEFT JOIN pg_index i ON i.indexrelid=k.conindid
          WHERE n.nspname='public' ORDER BY c.relname,k.conname
        """)).mappings()]
        result["constraints"] = [_constraint_state(row, enum_checks) for row in constraint_rows]
        assert len(constraint_rows) <= 256, "schema"
        assert all(row["table_name"] in set(Base.metadata.tables) | {"alembic_version"}
                   for row in constraint_rows), "schema"
        assert all(row["kind"] in {"c", "f", "p", "u", "x"}
                   and (row["check_expression"] is not None) == (row["kind"] == "c")
                   for row in constraint_rows), "schema"
        result["indexes"] = [tuple(row) for row in db.execute(text("""
          SELECT tablename,indexname,indexdef FROM pg_indexes
          WHERE schemaname='public' ORDER BY tablename,indexname
        """))]
    def encode(value):
        if isinstance(value, (bytes, memoryview)):
            return {"bytes": bytes(value).hex()}
        if isinstance(value, (datetime, uuid.UUID)):
            return str(value)
        raise TypeError()
    def hashed(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=encode).encode()).hexdigest()
    return {
        "digest": hashed(result),
        "parts": {name: {"count": len(result[name]), "sha256": hashed(result[name])}
                  for name in (*DATA_TABLES, "schema", "constraints", "indexes")},
        "constraint_details": [
            {"table": row["table_name"], "name_sha256": hashed(row["constraint_name"]), "kind": row["kind"],
             "definition_sha256": hashed(_constraint_state(row, enum_checks)), "pretty_sha256": hashed(row["pretty_definition"]),
              "flags_sha256": hashed([row[name] for name in (
                  "kind", "deferrable", "initially_deferred", "validated", "no_inherit",
                  "is_local", "inherit_count", "update_action", "delete_action", "match_type")]),
             "field_sha256": {name: hashed(value) for name, value in _constraint_state(row, enum_checks).items()}}
            for row in constraint_rows
        ],
    }


def readable(engine):
    """Two ordinary synthetic users, targeted restored DB-backed reads only."""
    with Session(engine) as db:
        project = db.scalar(select(Project))
        attachment = db.scalar(select(ProjectAttachment))
        project_id, conversation_id, attachment_id = project.id, attachment.conversation_id, attachment.id
    settings = AppSettings(public_origin="http://127.0.0.1:8080",
                           rate_limit_key=b"synthetic-restore-only-rate-limit-key")
    app = create_app(engine, settings, workspace_root=Path("/workspaces"))
    base = f"/api/projects/{project_id}"
    raw = f"{base}/chat/{conversation_id}/attachments/{attachment_id}/raw"
    with TestClient(app) as client:
        _login(client, "pdf-migration", PASSWORD)
        assert client.get(base).status_code == 200
        response = client.get(raw)
        assert response.status_code == 200 and response.content == BODY
        for kind in ("project", "agents", "backlog"):
            response = client.get(f"{base}/documents/{kind}")
            assert response.status_code == 200
            if kind == "project":
                assert response.json()["content"] == "# New unapproved restored draft\n"
                assert response.json()["revision_number"] == 2
        client.cookies.clear()
        _login(client, "restore-outsider", PASSWORD)
        assert client.get(base).status_code == 404
        assert client.get(raw).status_code == 404


def main():
    engine = None
    try:
        assert os.geteuid() == 10001 and os.environ.get("IMPOSTR_TEST_RESTORE") == "1"
        assert len(sys.argv) == 2 and sys.argv[1] in {"seed", "digest", "readable", "empty", "poison"}
        engine = get_database_engine()
        action = sys.argv[1]
        if action == "seed":
            seed(engine)
        elif action == "digest":
            data = digest(engine)
            # One bounded metadata line per constraint, not a >64 KiB JSON line.
            # Only hashes travel here; the coordinator reports field NAMES only.
            for ordinal, item in enumerate(data["constraint_details"]):
                print(json.dumps({"check": "restore_constraint_fields", "ordinal": ordinal,
                                  "field_sha256": item.pop("field_sha256")}))
            print(json.dumps({"check": "restore_digest", "status": "passed", **data}))
            return 0
        elif action == "readable":
            readable(engine)
        elif action == "empty":
            with engine.connect() as db:
                assert not inspect(db).get_table_names(schema="public")
                assert db.scalar(text("""SELECT count(*) FROM pg_depend d JOIN pg_namespace n ON n.oid=d.refobjid
                                          WHERE d.refclassid='pg_namespace'::regclass AND n.nspname='public'""")) == 0
        else:
            # Archive containing an app-role-inaccessible event trigger must fail
            # after earlier CREATE TABLE work; --single-transaction must roll it back.
            with engine.begin() as db:
                db.execute(text("CREATE TABLE public.rollback_probe (id integer)"))
                db.execute(text("CREATE FUNCTION public.rollback_trigger() RETURNS event_trigger "
                                "LANGUAGE plpgsql AS $$ BEGIN RETURN; END $$"))
                db.execute(text("CREATE EVENT TRIGGER rollback_probe ON ddl_command_end "
                                "EXECUTE FUNCTION public.rollback_trigger()"))
        print(json.dumps({"check": "restore_" + action, "status": "passed"}))
        return 0
    except Exception as error:
        category = ("database" if isinstance(error, SQLAlchemyError) else
                    str(error) if isinstance(error, AssertionError) and str(error) in {
                        "schema", "rows", "original_identity", "relation_owner", "type_owner"
                    } else "operation")
        print(json.dumps({"check": "restore_fixture", "status": "failed", "category": category}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
