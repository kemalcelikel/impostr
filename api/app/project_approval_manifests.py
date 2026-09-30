"""Human approval of one validated PROJECT.md/AGENTS.md/BACKLOG.md snapshot."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.backlog_markdown import BacklogValidationError, ParsedBacklog, parse_backlog
from app.dependencies import (
    CurrentActor,
    DbSession,
    SettingsDependency,
    load_active_actor,
)
from app.document_contract import (
    DOCUMENT_FILENAMES,
    DOCUMENT_KINDS,
    MAX_DOCUMENT_BYTES,
    MAX_REVISION_NUMBER,
    TEMPLATE_SOURCES,
    DocumentKind,
)
from app.document_pair_approvals import (
    _PLACEHOLDER_PATTERN,
    PAIR_KINDS,
    RevisionReference,
    _markdown_lines,
    _pair_validation_errors,
    _table_block,
    _table_cells,
    _table_separator,
    _undecided_text,
    _unresolved_angle_marker,
    _visible_markdown_text,
)
from app.models import (
    Project,
    ProjectApprovalManifest,
    ProjectDocument,
    ProjectDocumentPairApproval,
    ProjectDocumentRevision,
    User,
)
from app.project_documents import _get_project_and_actor, _read_revision
from app.rate_limit import consume_rate_bucket

router = APIRouter(prefix="/projects/{project_id}/final-approval", tags=["final approval"])
_TODO_PLACEHOLDER = re.compile(r"(?<![\w])(?:TODO|TBD|TBC|TBA)(?![\w])", re.IGNORECASE)
_MARKDOWN_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_MARKDOWN_H2 = re.compile(r"^ {0,3}##[ \t]+(.+?)[ \t]*#*[ \t]*$")
_SECTION_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
_TASK_METADATA_NAMES = frozenset(
    {
        "depends on",
        "scope",
        "required capabilities",
        "documentation impact",
        "open decisions",
        "type",
        "branch",
        "pr",
    }
)
_UNDECIDED_HEADING_WORD = re.compile(
    r"(?<!\w)(?:unknown|undecided|unresolved|unspecified|pending)(?!\w)",
    re.IGNORECASE,
)
_HEADING_COMPOUND_WORD = re.compile(r"\b\w+(?:-\w+)+\b")
_UNDECIDED_HEADING_STATUS = re.compile(
    _UNDECIDED_HEADING_WORD.pattern + r"(?=[ \t]*(?:$|[^\w\s]))",
    re.IGNORECASE,
)
_SCOPE_FIELD = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+)?(?:\*\*)?Scope:(?:\*\*)?[ \t]*(.*?)[ \t]*$",
    re.IGNORECASE,
)
_LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s+")
_GUIDANCE_WORD = re.compile(r"[^\W_]+(?:[_-][^\W_]+)*", re.UNICODE)
_NON_SUBSTANTIVE_VALUES = frozenset(
    {
        "none",
        "n/a",
        "na",
        "not applicable",
        "no scope",
        "no acceptance criteria",
        "no verification steps",
        "x",
        "unknown",
        "undecided",
        "unresolved",
        "unspecified",
        "pending",
        "placeholder",
        "to be determined",
        "to be decided",
        "to be confirmed",
        "to be specified",
    }
)


class ProjectApprovalManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_pair_approval_id: uuid.UUID
    expected_backlog_revision: Annotated[
        int,
        Field(strict=True, ge=1, le=MAX_REVISION_NUMBER),
    ]


class ProjectApprovalManifestView(BaseModel):
    id: uuid.UUID
    pair_approval_id: uuid.UUID
    project: RevisionReference
    agents: RevisionReference
    backlog: RevisionReference
    actor_user_id: uuid.UUID | None
    created_at: datetime


class ProjectApprovalManifestStatus(BaseModel):
    current_project_revision: RevisionReference
    current_agents_revision: RevisionReference
    current_backlog_revision: RevisionReference
    current_pair_approval_id: uuid.UUID | None
    pair_approved: bool
    approved: bool
    current_manifest: ProjectApprovalManifestView | None
    latest_manifest: ProjectApprovalManifestView | None
    validation_errors: dict[str, list[str]]


@dataclass(frozen=True, slots=True)
class _ApprovalState:
    pair_approval: ProjectDocumentPairApproval | None
    pair_approved: bool
    validation_errors: dict[str, list[str]]
    current_manifest: ProjectApprovalManifest | None
    latest_manifest: ProjectApprovalManifest | None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _revision_reference(revision: ProjectDocumentRevision) -> RevisionReference:
    return RevisionReference(
        id=revision.id,
        revision_number=revision.revision_number,
        content_sha256=revision.content_sha256,
    )


def _lock_manifest_heads(
    db: Session,
    project_id: uuid.UUID,
) -> tuple[dict[DocumentKind, ProjectDocument], dict[DocumentKind, ProjectDocumentRevision]]:
    """Lock all three current heads in the same lexical order in every request."""
    documents = list(
        db.scalars(
            select(ProjectDocument)
            .where(
                ProjectDocument.project_id == project_id,
                ProjectDocument.kind.in_(DOCUMENT_KINDS),
            )
            .order_by(ProjectDocument.kind)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    document_by_kind = {cast(DocumentKind, document.kind): document for document in documents}
    if set(document_by_kind) != set(DOCUMENT_KINDS):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project documents are not fully initialized.",
        )
    revisions = {
        kind: _read_revision(
            db,
            document_by_kind[kind],
            document_by_kind[kind].head_revision_number,
        )
        for kind in DOCUMENT_KINDS
    }
    return document_by_kind, revisions


def _revision_integrity_errors(
    revision: ProjectDocumentRevision,
) -> list[str]:
    try:
        content = revision.content.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return ["The saved file is not valid UTF-8 text."]
    errors: list[str] = []
    if len(content) > MAX_DOCUMENT_BYTES:
        errors.append("The saved file exceeds the supported 128 KiB limit.")
    if b"\x00" in content:
        errors.append("The saved file contains a NUL character.")
    if hashlib.sha256(content).hexdigest() != revision.content_sha256:
        errors.append("The saved file digest does not match its immutable revision.")
    return errors


def _outside_fenced_code(content: str) -> list[str]:
    """Return Markdown lines outside fenced examples for evidence checks."""
    visible_lines: list[str] = []
    fence: tuple[str, int] | None = None
    for line in content.splitlines():
        if fence is not None:
            marker, minimum_length = fence
            if re.fullmatch(
                r" {0,3}" + re.escape(marker) + "{" + str(minimum_length) + r",}\s*",
                line,
            ):
                fence = None
            continue

        opening = _MARKDOWN_FENCE_OPEN.match(line)
        if opening is not None:
            fence = (opening.group(1)[0], len(opening.group(1)))
            continue
        visible_lines.append(line)
    return visible_lines


def _template_guidance_sections(content: str) -> list[str]:
    """Extract non-task level-two sections from the versioned starter."""
    sections: list[str] = []
    section_title: str | None = None
    section_lines: list[str] = []
    fence: tuple[str, int] | None = None

    for line in content.splitlines():
        if fence is not None:
            section_lines.append(line)
            marker, minimum_length = fence
            if re.fullmatch(
                r" {0,3}" + re.escape(marker) + "{" + str(minimum_length) + r",}\s*",
                line,
            ):
                fence = None
            continue

        opening = _MARKDOWN_FENCE_OPEN.match(line)
        if opening is not None:
            if section_title is not None:
                section_lines.append(line)
            fence = (opening.group(1)[0], len(opening.group(1)))
            continue

        heading = _MARKDOWN_H2.fullmatch(line)
        if heading is None:
            if section_title is not None:
                section_lines.append(line)
            continue

        if section_title is not None:
            sections.append("\n".join(section_lines))
        section_title = heading.group(1).strip()
        section_lines = []
        if section_title.startswith("["):
            # Task blocks are project content, not reusable setup guidance.
            section_title = None

    if section_title is not None:
        sections.append("\n".join(section_lines))
    return sections


def _retains_starter_guidance(template: str, content: str) -> bool:
    """Find copied setup prose, even if renamed, rewrapped or mixed with new text.

    Compare paragraphs/list items from *this project's saved starter*, not a
    hard-coded list of English phrases. Four-word shingles limit coincidences
    with ordinary owner guidance; requiring substantial coverage of one unit
    avoids penalizing a few shared words while catching cosmetic edits.
    """
    submitted_words = _GUIDANCE_WORD.findall(" ".join(_outside_fenced_code(content)).casefold())
    submitted_shingles = {
        tuple(submitted_words[index : index + 4]) for index in range(len(submitted_words) - 3)
    }
    for section in _template_guidance_sections(template):
        unit: list[str] = []
        # A copied single instruction is setup guidance even if the rest of the
        # section was removed. Paragraph and list boundaries prevent unrelated
        # authored additions from diluting that signal.
        for line in [*_outside_fenced_code(section), ""]:
            if not line.strip() or _LIST_ITEM.match(line):
                if unit:
                    words = _GUIDANCE_WORD.findall(" ".join(unit).casefold())
                    if len(words) >= 12:
                        shingles = {
                            tuple(words[index : index + 4]) for index in range(len(words) - 3)
                        }
                        if len(shingles & submitted_shingles) / len(shingles) >= 0.6:
                            return True
                    unit = []
            if line.strip():
                unit.append(line)
    return False


def _is_task_metadata_field(line: str) -> bool:
    # Inspect the visible label, not a particular placement of emphasis around
    # its colon. The caller has already masked examples/HTML and stripped list
    # framing. Only canonical labels end Scope; API: / Export: prose stays usable.
    # Decode before splitting: the colon can itself be inside a code span or
    # emphasized label. Splitting first would leave an unmatched Markdown opener.
    visible, ambiguous = _visible_markdown_text(line)
    if ambiguous:
        return False
    label, separator, _value = visible.partition(":")
    return bool(separator) and " ".join(label.split()).casefold() in _TASK_METADATA_NAMES


def _scope_values(body: str) -> list[str]:
    lines = _markdown_lines(body)
    fields = [
        (index, match)
        for index, (line, _heading) in enumerate(lines)
        if (match := _SCOPE_FIELD.fullmatch(line)) is not None
    ]
    if len(fields) != 1:
        # The caller rejects missing/duplicate fields by count, so no potentially
        # overlapping continuation needs to be assembled for malformed input.
        return [match.group(1) for _index, match in fields]

    index, match = fields[0]
    end = len(lines)
    for candidate, (line, heading_allowed) in enumerate(lines[index + 1 :], start=index + 1):
        heading = _SECTION_HEADING.fullmatch(line) if heading_allowed else None
        if (
            heading is not None and len(line.lstrip().split(maxsplit=1)[0]) <= 3
        ) or _is_task_metadata_field(line):
            # Scope is an inline field: collect its paragraph/list continuation,
            # including colon-labeled prose, but never borrow a known task
            # metadata field or the next task-level Markdown section.
            end = candidate
            break

    value_lines = [match.group(1)]
    value_lines.extend(line for line, _heading in lines[index + 1 : end])
    return ["\n".join(value_lines)]


def _has_substantive_text(value: str | None) -> bool:
    if value is None or not value.strip():
        return False
    substantive = False
    # A heading or a completed bullet cannot rescue another explicitly deferred
    # bullet. Reuse the pair-approval Markdown boundary: examples/HTML/comments
    # cannot establish ready-task scope, acceptance or verification evidence.
    lines = _markdown_lines(value)
    visible_lines = [line for line, _heading in lines]
    index = 0
    while index < len(lines):
        line, _heading_allowed = lines[index]
        if _SECTION_HEADING.fullmatch(line) is not None:
            # A heading organizes evidence but cannot supply it. Still inspect
            # its title as a status-bearing unit, including headings nested in a
            # list. Completed prose elsewhere cannot hide an explicitly deferred
            # child heading.
            if _undecided_heading(line):
                return False
            index += 1
            continue
        table = _table_block(visible_lines, index)
        if table is not None:
            header, rows, next_index = table
            for cells, malformed in rows:
                # The header/alignment row is framing, never an answer. In a
                # multi-column table the first column labels the result; in a
                # one-column table the row itself is the answer.
                values = cells if len(header) == 1 else cells[1:]
                if (
                    malformed
                    or any(_undecided_text(cell) for cell in cells)
                    or not values
                    or not all(_has_substantive_text(cell) for cell in values)
                ):
                    return False
                substantive = True
            index = next_index
            continue
        pipe_cells = _table_cells(line)
        if pipe_cells is not None:
            if _table_separator(pipe_cells):
                index += 1
                continue
            if any(_undecided_text(cell) for cell in pipe_cells):
                return False
            # A lone pipe-wrapped row or alignment row is not table data. A
            # sentence using one unwrapped pipe can still be ordinary prose.
            if line.strip().startswith("|") or line.strip().endswith("|"):
                index += 1
                continue
        # Markdown checkboxes are list-item framing, not part of the answer.
        line = re.sub(r"^\[[ xX]\][ \t]+", "", line)
        visible, ambiguous = _visible_markdown_text(line)
        if ambiguous:
            return False
        normalized = " ".join(visible.split()).casefold().strip(" .,:;!?…—–-()[]{}'\"")
        if not normalized:
            index += 1
            continue
        if _undecided_text(line) or normalized in _NON_SUBSTANTIVE_VALUES:
            return False
        substantive = True
        index += 1
    return substantive


def _undecided_heading(line: str) -> bool:
    heading = _SECTION_HEADING.fullmatch(line)
    if heading is None:
        return False
    title = heading.group(1)
    visible_title, ambiguous = _visible_markdown_text(title)
    if ambiguous:
        return True
    # Hyphenated words are single lexical subjects, not status clauses. Mask only
    # contextual status words *within* those compounds before reusing the ordinary
    # placeholder scanner; retain unconditional TODO and deferred-value markers.
    status_title = _HEADING_COMPOUND_WORD.sub(
        lambda match: _UNDECIDED_HEADING_WORD.sub("compound", match.group(0)),
        visible_title,
    )
    # A heading is a structural label, not a sentence. The ordinary evidence
    # scanner catches leading and delimiter-marked status labels. Also inspect
    # the end of each heading clause, not just the whole title: an explanation
    # after "concurrency unresolved — ..." does not complete that status. A word
    # modifying a subject ("unknown dependency IDs") is not clause-final status.
    return (
        _undecided_text(status_title) or _UNDECIDED_HEADING_STATUS.search(status_title) is not None
    )


def _ready_section_counts(interval: str) -> tuple[int, int]:
    """Count visible required-section headings across a task's whole raw interval.

    The task model exposes only the first Done looks like/Acceptance and
    Verification section, and its editable body can end before a later non-task
    H2. Approval must not ignore another visible section in that preserved
    interval or treat fenced/HTML/indented examples as section boundaries.
    """
    acceptance = verification = 0
    for line, _heading_allowed in _markdown_lines(interval):
        heading = _SECTION_HEADING.fullmatch(line)
        if heading is None:
            continue
        title = heading.group(1).strip().casefold()
        if title in {"done looks like", "acceptance"}:
            acceptance += 1
        elif title == "verification":
            verification += 1
    return acceptance, verification


def _visible_task_section(body: str, names: frozenset[str]) -> str | None:
    """Extract one visible task section without treating examples as boundaries."""
    lines = _markdown_lines(body)
    selected_index: int | None = None
    selected_level: int | None = None
    for index, (line, _heading_allowed) in enumerate(lines):
        heading = _SECTION_HEADING.fullmatch(line)
        if heading is None or heading.group(1).strip().casefold() not in names:
            continue
        selected_index = index
        selected_level = len(line.lstrip().split(maxsplit=1)[0])
        break

    if selected_index is None or selected_level is None:
        return None

    end = len(lines)
    for index, (line, _heading_allowed) in enumerate(
        lines[selected_index + 1 :], start=selected_index + 1
    ):
        heading = _SECTION_HEADING.fullmatch(line)
        if (
            heading is not None and len(line.lstrip().split(maxsplit=1)[0]) <= selected_level
        ) or _is_task_metadata_field(line):
            # Canonical metadata and its continuation are outside the required
            # section's evidence, just as they are outside the Scope field.
            end = index
            break
    return "\n".join(line for line, _heading_allowed in lines[selected_index + 1 : end]).strip()


def _has_unresolved_task_notes(interval: str) -> bool:
    """Check explicit open decisions even beyond the editable body at a non-task H2.

    The root helper associates that intervening text with the preceding task.
    Only visible Markdown counts: the pair-approval scanner masks fenced/indented
    examples, comments, and raw HTML before we inspect headings, prose or cells.
    """
    for line, _heading_allowed in _markdown_lines(interval):
        if not line.strip():
            continue
        if _SECTION_HEADING.fullmatch(line) is not None:
            if _undecided_heading(line):
                return True
            # The heading classifier owns contextual status, including compound
            # subjects. Do not scan it again as ordinary prose below.
            continue
        cells = _table_cells(line)
        if cells is not None:
            if _table_separator(cells):
                continue
            if any(_undecided_text(cell) for cell in cells):
                return True
        if _undecided_text(line):
            return True
    return False


def _ready_task_validation_errors(parsed_backlog: ParsedBacklog) -> list[str]:
    """Require project-specific execution detail only for owner-ready tasks."""
    errors: list[str] = []
    # Keep planning/parser eligibility aligned with the root helper. Approval
    # separately requires detail for every task marked ready, including waiters.
    for task in parsed_backlog.tasks:
        if not task.ready:
            continue
        scope_values = _scope_values(task.body)
        if len(scope_values) != 1 or not _has_substantive_text(scope_values[0]):
            errors.append(f"Ready task {task.id} must define substantive Scope information.")
        interval = parsed_backlog.content[task.body_start : task.raw_end]
        acceptance_count, verification_count = _ready_section_counts(interval)
        if acceptance_count > 1:
            errors.append(f"Ready task {task.id} has duplicate acceptance sections.")
        elif not _has_substantive_text(
            _visible_task_section(task.body, frozenset({"done looks like", "acceptance"}))
        ):
            errors.append(f"Ready task {task.id} must include substantive acceptance criteria.")
        if verification_count > 1:
            errors.append(f"Ready task {task.id} has duplicate verification sections.")
        elif not _has_substantive_text(
            _visible_task_section(task.body, frozenset({"verification"}))
        ):
            errors.append(f"Ready task {task.id} must include substantive verification steps.")
        if _has_unresolved_task_notes(interval):
            errors.append(f"Ready task {task.id} must resolve unresolved task notes.")
    return errors


def _backlog_validation_errors(
    db: Session,
    document: ProjectDocument,
    revision: ProjectDocumentRevision,
) -> list[str]:
    try:
        template_revision = _read_revision(db, document, 1)
    except HTTPException:
        return ["The original backlog starter-template provenance could not be verified."]

    expected_source = TEMPLATE_SOURCES["backlog"]
    try:
        template_bytes = template_revision.content.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return ["The original backlog starter-template provenance could not be verified."]
    template_digest = hashlib.sha256(template_bytes).hexdigest()
    if (
        template_revision.revision_number != 1
        or template_revision.origin != "template"
        or template_revision.template_source != expected_source
        or template_revision.template_sha256 != template_digest
        or template_revision.content_sha256 != template_digest
    ):
        return ["The original backlog starter-template provenance could not be verified."]

    errors = _revision_integrity_errors(revision)
    try:
        content_bytes = revision.content.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return errors

    if len(content_bytes) > MAX_DOCUMENT_BYTES:
        return errors

    canonical_content = revision.content.replace("\r\n", "\n").replace("\r", "\n")
    canonical_template = template_revision.content.replace("\r\n", "\n").replace("\r", "\n")
    if not canonical_content.strip():
        errors.append("Add backlog content before approving this snapshot.")
    if canonical_content == canonical_template:
        errors.append("This backlog is unchanged from its saved starter revision.")

    starter_notes = tuple(
        line.strip()
        for line in template_revision.content.splitlines()
        if "STARTER TEMPLATE" in line.upper()
    )
    content_lines = {line.strip() for line in revision.content.splitlines()}
    if starter_notes and any(note in content_lines for note in starter_notes):
        errors.append("Remove the backlog starter-template setup notes.")
    if _retains_starter_guidance(template_revision.content, revision.content):
        errors.append("Remove retained starter guidance before approving this backlog.")

    placeholders = set(_PLACEHOLDER_PATTERN.findall(template_revision.content))
    if _unresolved_angle_marker(revision.content, placeholders):
        errors.append("Replace unresolved backlog placeholders before approving this snapshot.")
    if _TODO_PLACEHOLDER.search(revision.content):
        errors.append("Resolve TODO/TBD placeholders before approving this snapshot.")

    if "\x00" in revision.content:
        if "The saved file contains a NUL character." not in errors:
            errors.append("The saved file contains a NUL character.")
    try:
        parsed = parse_backlog(revision.content)
    except BacklogValidationError:
        errors.append("The saved backlog has malformed task headings or dependencies.")
    else:
        if not parsed.tasks:
            errors.append("Add at least one valid task before approving this backlog.")
        errors.extend(_ready_task_validation_errors(parsed))
    return errors


def _current_pair_approval(
    db: Session,
    project_id: uuid.UUID,
    revisions: dict[DocumentKind, ProjectDocumentRevision],
) -> ProjectDocumentPairApproval | None:
    return db.scalar(
        select(ProjectDocumentPairApproval).where(
            ProjectDocumentPairApproval.project_id == project_id,
            ProjectDocumentPairApproval.project_revision_id == revisions["project"].id,
            ProjectDocumentPairApproval.agents_revision_id == revisions["agents"].id,
        )
    )


def _approval_state(
    db: Session,
    project_id: uuid.UUID,
    documents: dict[DocumentKind, ProjectDocument],
    revisions: dict[DocumentKind, ProjectDocumentRevision],
) -> _ApprovalState:
    pair_documents: dict[str, ProjectDocument] = {kind: documents[kind] for kind in PAIR_KINDS}
    pair_revisions = {kind: revisions[kind] for kind in PAIR_KINDS}
    pair_errors = _pair_validation_errors(db, pair_documents, pair_revisions)
    for kind in PAIR_KINDS:
        integrity_errors = _revision_integrity_errors(revisions[kind])
        if integrity_errors:
            filename = TEMPLATE_SOURCES[kind].removesuffix(".example")
            pair_errors.setdefault(filename, []).extend(integrity_errors)

    backlog_errors = _backlog_validation_errors(db, documents["backlog"], revisions["backlog"])
    validation_errors = dict(pair_errors)
    if backlog_errors:
        validation_errors[DOCUMENT_FILENAMES["backlog"]] = backlog_errors

    pair_approval = _current_pair_approval(db, project_id, revisions)
    pair_approved = pair_approval is not None and not pair_errors
    current_manifest = None
    if pair_approved and not backlog_errors:
        assert pair_approval is not None
        current_manifest = db.scalar(
            select(ProjectApprovalManifest).where(
                ProjectApprovalManifest.project_id == project_id,
                ProjectApprovalManifest.pair_approval_id == pair_approval.id,
                ProjectApprovalManifest.project_revision_id == revisions["project"].id,
                ProjectApprovalManifest.agents_revision_id == revisions["agents"].id,
                ProjectApprovalManifest.backlog_revision_id == revisions["backlog"].id,
            )
        )

    latest_manifest = db.scalar(
        select(ProjectApprovalManifest)
        .where(ProjectApprovalManifest.project_id == project_id)
        .order_by(
            ProjectApprovalManifest.created_at.desc(),
            ProjectApprovalManifest.id.desc(),
        )
        .limit(1)
    )
    return _ApprovalState(
        pair_approval=pair_approval,
        pair_approved=pair_approved,
        validation_errors=validation_errors,
        current_manifest=current_manifest,
        latest_manifest=latest_manifest,
    )


def _manifest_view(
    db: Session,
    manifest: ProjectApprovalManifest,
) -> ProjectApprovalManifestView:
    revision_ids = {
        manifest.project_revision_id,
        manifest.agents_revision_id,
        manifest.backlog_revision_id,
    }
    revision_by_id = {
        revision.id: revision
        for revision in db.scalars(
            select(ProjectDocumentRevision).where(ProjectDocumentRevision.id.in_(revision_ids))
        ).all()
    }
    if set(revision_by_id) != revision_ids:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The saved approval manifest is incomplete.",
        )
    return ProjectApprovalManifestView(
        id=manifest.id,
        pair_approval_id=manifest.pair_approval_id,
        project=_revision_reference(revision_by_id[manifest.project_revision_id]),
        agents=_revision_reference(revision_by_id[manifest.agents_revision_id]),
        backlog=_revision_reference(revision_by_id[manifest.backlog_revision_id]),
        actor_user_id=manifest.actor_user_id,
        created_at=_utc(manifest.created_at),
    )


def _status_view(
    db: Session,
    revisions: dict[DocumentKind, ProjectDocumentRevision],
    state: _ApprovalState,
) -> ProjectApprovalManifestStatus:
    current_view = (
        _manifest_view(db, state.current_manifest) if state.current_manifest is not None else None
    )
    if (
        state.latest_manifest is not None
        and state.current_manifest is not None
        and state.latest_manifest.id == state.current_manifest.id
    ):
        latest_view = current_view
    else:
        latest_view = (
            _manifest_view(db, state.latest_manifest) if state.latest_manifest is not None else None
        )
    return ProjectApprovalManifestStatus(
        current_project_revision=_revision_reference(revisions["project"]),
        current_agents_revision=_revision_reference(revisions["agents"]),
        current_backlog_revision=_revision_reference(revisions["backlog"]),
        current_pair_approval_id=(
            state.pair_approval.id if state.pair_approval is not None else None
        ),
        pair_approved=state.pair_approved,
        approved=current_view is not None,
        current_manifest=current_view,
        latest_manifest=latest_view,
        validation_errors=state.validation_errors,
    )


def _audit_read(
    db: Session,
    actor: User,
    project: Project,
    *,
    action: str,
    details: dict[str, object],
) -> None:
    if actor.role == "admin":
        record_audit(
            db,
            action=action,
            actor_user_id=actor.id,
            project_id=project.id,
            details=details,
        )
        db.commit()
    else:
        db.rollback()


def _finish_read_only_post(
    db: Session,
    actor: User,
    project: Project,
    revisions: dict[DocumentKind, ProjectDocumentRevision],
    *,
    operation: str,
) -> None:
    if actor.role == "admin":
        record_audit(
            db,
            action="admin.project.approval_manifest.read",
            actor_user_id=actor.id,
            project_id=project.id,
            details={
                "operation": operation,
                "project_revision_number": revisions["project"].revision_number,
                "agents_revision_number": revisions["agents"].revision_number,
                "backlog_revision_number": revisions["backlog"].revision_number,
            },
        )
        db.commit()
    else:
        db.rollback()


def _authorized_project_after_rate_limit(
    db: Session,
    actor: CurrentActor,
    project_id: uuid.UUID,
) -> tuple[User, Project]:
    active_user = load_active_actor(db, actor, for_update=True)
    project = db.scalar(
        select(Project).where(Project.id == project_id).execution_options(populate_existing=True)
    )
    if project is None or (active_user.role != "admin" and project.owner_user_id != active_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return active_user, project


def _precondition_conflict(
    project_id: uuid.UUID,
    payload: ProjectApprovalManifestRequest,
    revisions: dict[DocumentKind, ProjectDocumentRevision],
    state: _ApprovalState,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": (
                "The approved document pair or saved backlog changed. Review the current "
                "files and retry."
            ),
            "project_id": str(project_id),
            "expected_pair_approval_id": str(payload.expected_pair_approval_id),
            "current_pair_approval_id": (
                str(state.pair_approval.id) if state.pair_approval is not None else None
            ),
            "expected_backlog_revision": payload.expected_backlog_revision,
            "current_backlog_revision": _revision_reference(revisions["backlog"]).model_dump(
                mode="json"
            ),
        },
    )


@router.get("", response_model=ProjectApprovalManifestStatus)
def get_project_approval_manifest_status(
    project_id: uuid.UUID,
    db: DbSession,
    actor: CurrentActor,
) -> ProjectApprovalManifestStatus:
    active_user, project = _get_project_and_actor(db, actor, project_id)
    documents, revisions = _lock_manifest_heads(db, project_id)
    state = _approval_state(db, project_id, documents, revisions)
    result = _status_view(db, revisions, state)
    _audit_read(
        db,
        active_user,
        project,
        action="admin.project.approval_manifest.read",
        details={
            "approved": result.approved,
            "current_pair_approval_id": (
                str(state.pair_approval.id) if state.pair_approval is not None else None
            ),
            "project_revision_number": revisions["project"].revision_number,
            "agents_revision_number": revisions["agents"].revision_number,
            "backlog_revision_number": revisions["backlog"].revision_number,
        },
    )
    return result


@router.post("", response_model=ProjectApprovalManifestView)
def approve_project_manifest(
    project_id: uuid.UUID,
    payload: ProjectApprovalManifestRequest,
    db: DbSession,
    actor: CurrentActor,
    settings: SettingsDependency,
) -> ProjectApprovalManifestView | JSONResponse:
    _get_project_and_actor(db, actor, project_id)
    rate_limit = consume_rate_bucket(
        db,
        settings=settings,
        scope="project-approval-manifest",
        subject=str(actor.id),
        limit=30,
        window_seconds=60 * 60,
    )
    # Commit the rate bucket separately, then revalidate the live session/account
    # before taking all document-head locks in their stable kind order.
    db.commit()
    if not rate_limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many final-approval attempts. Try again later.",
            headers={"Retry-After": str(rate_limit.retry_after_seconds)},
        )

    active_user, project = _authorized_project_after_rate_limit(db, actor, project_id)
    documents, revisions = _lock_manifest_heads(db, project_id)
    state = _approval_state(db, project_id, documents, revisions)
    if (
        state.pair_approval is None
        or state.pair_approval.id != payload.expected_pair_approval_id
        or revisions["backlog"].revision_number != payload.expected_backlog_revision
    ):
        conflict_response = _precondition_conflict(project_id, payload, revisions, state)
        _finish_read_only_post(
            db,
            active_user,
            project,
            revisions,
            operation="stale_post",
        )
        return conflict_response

    if state.validation_errors:
        _finish_read_only_post(
            db,
            active_user,
            project,
            revisions,
            operation="validation_error_post",
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": {"files": state.validation_errors}},
        )

    assert state.pair_approval is not None
    existing = db.scalar(
        select(ProjectApprovalManifest).where(
            ProjectApprovalManifest.project_id == project_id,
            ProjectApprovalManifest.pair_approval_id == state.pair_approval.id,
            ProjectApprovalManifest.project_revision_id == revisions["project"].id,
            ProjectApprovalManifest.agents_revision_id == revisions["agents"].id,
            ProjectApprovalManifest.backlog_revision_id == revisions["backlog"].id,
        )
    )
    if existing is not None:
        existing_result = _manifest_view(db, existing)
        _finish_read_only_post(
            db,
            active_user,
            project,
            revisions,
            operation="idempotent_post",
        )
        return existing_result

    now = datetime.now(UTC)
    manifest = ProjectApprovalManifest(
        id=uuid.uuid4(),
        project_id=project_id,
        pair_approval_id=state.pair_approval.id,
        project_revision_id=revisions["project"].id,
        agents_revision_id=revisions["agents"].id,
        backlog_revision_id=revisions["backlog"].id,
        actor_user_id=active_user.id,
        created_at=now,
    )
    db.add(manifest)
    db.flush()
    record_audit(
        db,
        action="project.approval_manifest.approved",
        actor_user_id=active_user.id,
        project_id=project.id,
        details={
            "manifest_id": str(manifest.id),
            "pair_approval_id": str(state.pair_approval.id),
            "project_revision_id": str(revisions["project"].id),
            "project_revision_number": revisions["project"].revision_number,
            "agents_revision_id": str(revisions["agents"].id),
            "agents_revision_number": revisions["agents"].revision_number,
            "backlog_revision_id": str(revisions["backlog"].id),
            "backlog_revision_number": revisions["backlog"].revision_number,
        },
    )
    created_result = _manifest_view(db, manifest)
    db.commit()
    return created_result


@router.get("/files/{kind}", response_class=Response)
def download_approved_project_file(
    project_id: uuid.UUID,
    kind: DocumentKind,
    db: DbSession,
    actor: CurrentActor,
) -> Response:
    active_user, project = _get_project_and_actor(db, actor, project_id)
    documents, revisions = _lock_manifest_heads(db, project_id)
    state = _approval_state(db, project_id, documents, revisions)
    if state.current_manifest is None:
        _audit_read(
            db,
            active_user,
            project,
            action="admin.project.approved_file.read",
            details={"kind": kind, "approved": False},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No current valid three-document approval is available for download.",
        )

    manifest_revision_id = {
        "project": state.current_manifest.project_revision_id,
        "agents": state.current_manifest.agents_revision_id,
        "backlog": state.current_manifest.backlog_revision_id,
    }[kind]
    revision = revisions[kind]
    if manifest_revision_id != revision.id:
        # This is defensive in addition to the exact-revision manifest lookup.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The current document no longer matches its approved manifest.",
        )

    content = revision.content.encode("utf-8", errors="strict")
    filename = DOCUMENT_FILENAMES[kind]
    _audit_read(
        db,
        active_user,
        project,
        action="admin.project.approved_file.read",
        details={
            "kind": kind,
            "approved": True,
            "manifest_id": str(state.current_manifest.id),
            "revision_id": str(revision.id),
            "revision_number": revision.revision_number,
        },
    )
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
