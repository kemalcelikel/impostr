"""Bounded visible task sections shared by the editor and approval validator."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_LABELS = frozenset(
    {
        "scope",
        "acceptance",
        "done looks like",
        "verification",
        "depends on",
        "required capabilities",
        "documentation impact",
        "open decisions",
        "type",
        "branch",
        "pr",
    }
)


@dataclass(frozen=True)
class TaskSections:
    scope: tuple[str, ...]
    acceptance: tuple[str, ...]
    verification: tuple[str, ...]


def extract_task_sections(body: str, *, introductory_scope: bool = False) -> TaskSections:
    # Lazy imports keep the evidence grammar authoritative without introducing a
    # cycle through project_documents -> backlog_markdown -> pair approvals.
    from app.document_pair_approvals import _markdown_lines, _visible_markdown_text

    if not body:
        return TaskSections((), (), ())
    lines = _markdown_lines(body)
    raw_lines = body.splitlines()

    def body_line(index: int) -> str:
        line = lines[index][0]
        prefix = re.match(r"^ {0,3}([-*+]|\d+[.)])[ \t]+", raw_lines[index])
        # Keep list framing for the editor's existing Markdown-summary contract;
        # content still comes only from the bounded visible-evidence scanner.
        return prefix.group() + line if prefix and line.strip() else line

    boundaries: list[tuple[int, int, str, str]] = []
    for index, (line, heading_allowed) in enumerate(lines):
        heading = _HEADING.fullmatch(line) if heading_allowed else None
        if heading:
            title, ambiguous = _visible_markdown_text(heading.group(2))
            boundaries.append(
                (index, len(heading.group(1)), "" if ambiguous else title.casefold(), "")
            )
            continue
        framing = re.sub(r"^\[[ xX]\][ \t]+", "", line)
        visible, ambiguous = _visible_markdown_text(framing)
        label, separator, _value = visible.partition(":")
        name = " ".join(label.split()).casefold()
        if not ambiguous and separator and name in _LABELS:
            # Preserve inline Markdown in the value, not just its plain label.
            raw_label, _colon, raw_value = framing.partition(":")
            raw_value = raw_value.lstrip()
            for marker in ("**", "__", "`", "*", "_"):
                if (
                    raw_label.startswith(marker)
                    and raw_label.count(marker) % 2
                    and raw_value.startswith(marker)
                ):
                    raw_value = raw_value[len(marker) :].lstrip()
                    break
            boundaries.append((index, 0, name, raw_value))

    values: dict[str, list[str]] = {"scope": [], "acceptance": [], "verification": []}
    for offset, (index, level, name, inline) in enumerate(boundaries):
        key = "acceptance" if name == "done looks like" else name
        if key not in values:
            continue
        end = len(lines)
        for next_index, next_level, _name, _inline in boundaries[offset + 1 :]:
            if (
                next_level == 0
                or (level == 0 and next_level <= 3)
                or (level and next_level <= level)
            ):
                end = next_index
                break
        value_lines = [inline] if inline else []
        value_lines.extend(body_line(cursor) for cursor in range(index + 1, end))
        values[key].append("\n".join(value_lines).strip())

    if introductory_scope and not values["scope"]:
        # Only the opening task prose, after dependency/metadata fields and
        # before any section, is an implicit scope. Metadata continuation is
        # never an answer: require a paragraph boundary after inline metadata.
        intro: list[str] = []
        skip_metadata = False
        boundary_by_index = {index: (level, name) for index, level, name, _inline in boundaries}
        for index, (line, _allowed) in enumerate(lines):
            boundary = boundary_by_index.get(index)
            if boundary is not None:
                level, name = boundary
                if level or name in {"acceptance", "done looks like", "verification"}:
                    break
                if name != "depends on":
                    break
                skip_metadata = True
                continue
            if not raw_lines[index].strip():
                skip_metadata = False
                if intro:
                    intro.append("")
            elif not skip_metadata:
                intro.append(line)
        if intro:
            values["scope"].append("\n".join(intro).strip())
    return TaskSections(*(tuple(values[key]) for key in ("scope", "acceptance", "verification")))
