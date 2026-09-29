"""Atomic, human-only approval of the current project specification/rules pair."""

from __future__ import annotations

import hashlib
import re
import uuid
from bisect import bisect_right
from datetime import UTC, datetime
from html import unescape
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.dependencies import CurrentActor, DbSession, SettingsDependency, load_active_actor
from app.document_contract import MAX_REVISION_NUMBER, TEMPLATE_SOURCES
from app.models import (
    Project,
    ProjectDocument,
    ProjectDocumentPairApproval,
    ProjectDocumentRevision,
    User,
)
from app.project_documents import (
    ProjectDocumentView,
    _document_view,
    _get_project_and_actor,
    _read_revision,
)
from app.rate_limit import consume_rate_bucket

router = APIRouter(
    prefix="/projects/{project_id}/document-pair-approval",
    tags=["document-pair approval"],
)

PairKind = Literal["agents", "project"]
PAIR_KINDS: tuple[PairKind, PairKind] = ("agents", "project")
APPROVAL_HISTORY_PAGE_SIZE = 20
_PLACEHOLDER_PATTERN = re.compile(r"<[^<>\r\n]{1,200}>")
# Bare angle-word sequences catch markers such as <choose problem> without
# treating autolinks or tags with attributes as placeholders.
_ANGLE_TOKEN = re.compile(r"<([A-Za-z][A-Za-z0-9_-]{0,99})>")
_MULTIWORD_ANGLE_TOKEN = re.compile(
    r"<([A-Za-z][A-Za-z0-9_-]{0,99}(?:[ \t]+[A-Za-z][A-Za-z0-9_-]{0,99})+)>"
)
_HTML_TAGS = frozenset(
    """a abbr acronym address area article aside audio b base bdi bdo big blockquote body br
    button canvas caption center circle cite clipPath code col colgroup data datalist dd defs del
    details dfn dialog dir div dl dt em embed fieldset figcaption figure font footer form frame
    frameset g h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label
    legend li line link linearGradient main map mark marquee mask menu meta meter nav nobr noembed
    noframes noscript object ol optgroup option output p param path picture plaintext polygon
    polyline portal pre progress q radialGradient rect rp rt ruby s samp script search section
    select slot small source span stop strike strong style sub summary sup svg symbol table tbody
    td template text textarea tfoot th thead time title tr track tspan tt u ul use var
    video wbr""".lower().split()
)
_UNDECIDED_FIELD = re.compile(
    r"^(?:tbd|todo|tbc|tba|decide\s+later|to\s+be\s+"
    r"(?:decided|determined|confirmed|specified|completed)"
    r"|not\s+(?:yet\s+)?(?:decided|determined|specified|applicable|selected)"
    r"|unknown|undecided|unresolved"
    r"|unspecified|pending|n/?a|\?+|\.{2,}|…+)[.!?… ]*$",
    re.IGNORECASE,
)
_UNRESOLVED_TOKEN = re.compile(r"(?<!\w)(?:todo|tbd|tbc|tba|n/a)(?!\w)", re.IGNORECASE)
_UNRESOLVED_DEFERRED = re.compile(
    r"(?<!\w)(?:decide\s+later|to\s+be\s+"
    r"(?:decided|determined|confirmed|specified|completed)"
    r"|not\s+(?:yet\s+)?(?:decided|determined|specified|applicable|selected))(?!\w)",
    re.IGNORECASE,
)
_UNDECIDED_CONTEXTUAL_PREFIX = re.compile(
    r"^(?:unknown|undecided|unresolved|unspecified|pending)\b", re.IGNORECASE
)
_UNDECIDED_MARKED_CLAUSE = re.compile(
    r"(?:^|[^\w\s]|(?<!\w)_)\s*" + _UNDECIDED_CONTEXTUAL_PREFIX.pattern.removeprefix("^"),
    re.IGNORECASE,
)
_UNDECIDED_CONTEXTUAL_TAG = re.compile(r"\bpending\s*:", re.I)
_CHECKLIST_HEADING = re.compile(r"^\s*#{1,6}\s+starter checklist\s*#*\s*$", re.IGNORECASE)
_INDENTED_CODE = re.compile(r"^(?: {4,}| {0,3}\t)")
_MARKDOWN_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+")
_THEMATIC_BREAK = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
_NUMBERED_ITEM = re.compile(r"^\s*\d+[.)]\s+.+$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FIELD = re.compile(r"^[ \t]*[-*]\s+([^:\n]+):[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_LABELED_VALUE = re.compile(r"^([^:\n|]{1,80}):[ \t]*(.*)$")
_REFERENCE_DEFINITION = re.compile(r"^\s*\[[^\]\n]+\]:\s*\S.*$")
_REFERENCE_START = re.compile(r"^ {0,3}\[[^\]\n]+\]:[ \t]*(.*)$")
_REFERENCE_TITLE_VALUE = r'(?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\((?:\\.|[^)\\])*\))'
_REFERENCE_TITLE_LINE = re.compile(r"^[ \t]+" + _REFERENCE_TITLE_VALUE + r"[ \t]*$")
_REFERENCE_TITLE_CANDIDATE = re.compile(r"^[ \t]+[\"'(]")
_REFERENCE_DESTINATION = re.compile(
    r"^(?:<[^<>\s]+>|[^\s<>]+)(?:[ \t]+" + _REFERENCE_TITLE_VALUE + r")?[ \t]*$"
)
_URL_ONLY = re.compile(r"^(?:https?://|mailto:)\S+$", re.IGNORECASE)
_HTML_TAG_START = re.compile(r"</?([A-Za-z][A-Za-z0-9:-]*)(?=[\s/>])")
_HTML_VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
_LIST_PREFIX = re.compile(r"^(?:[-*+]|\d+[.)])[ \t]+")
_QUOTE_PREFIX = re.compile(r"^ {0,3}>[ \t]?")

# Deliberately a minimum *shape* check, not a claim that the decisions are true
# or sufficient. Match headings from each project's immutable starter, not the
# package's current template; optional sections may be omitted or reorganized.
_REQUIRED_SECTIONS = {
    "project": (
        "Purpose and users",
        "Scope",
        "Behavior and domain rules",
        "Technology and environment",
        "Architecture and repository map",
        "Decisions, risks, and open questions",
        "Definition of done",
    ),
    "agents": (
        "Sources of truth and scope",
        "Setup and verification commands",
        "Security and hardening workflow",
        "Git and task-state ownership",
    ),
}
_REQUIRED_PROJECT_FIELDS = (
    "Summary",
    "Problem",
    "Primary users",
    "Usage context",
    "Product outcomes",
)


def _paired_custom_element(content: str, name: str, opening_end: int) -> bool:
    # A bare dashed token can be a new placeholder (<choose-problem>) as well
    # as a custom element. Custom elements need an end tag; do not exempt the
    # standalone token just because its spelling is valid HTML.
    return (
        name.islower()
        and "-" in name
        and re.search(rf"</{re.escape(name)}[ \t]*>", content[opening_end:]) is not None
    )


def _unresolved_angle_marker(content: str, starter_tokens: set[str]) -> bool:
    if any(token in content for token in starter_tokens):
        return True
    for match in _ANGLE_TOKEN.finditer(content):
        name = match.group(1)
        if name.lower() not in _HTML_TAGS and not _paired_custom_element(
            content, name, match.end()
        ):
            return True
    for match in _MULTIWORD_ANGLE_TOKEN.finditer(content):
        # A recognized element may have bare boolean attributes, e.g. <section
        # hidden>. A paired lowercase dashed name is a custom element; unknown
        # word sequences and unpaired dashed names are undecided markers.
        name = match.group(1).split(maxsplit=1)[0]
        if name.lower() not in _HTML_TAGS and not _paired_custom_element(
            content, name, match.end()
        ):
            return True
    return False


def _line_body(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\r", "\n")):
        return line[:-1], line[-1:]
    return line, ""


def _fence_marker(line: str) -> tuple[str, int, str] | None:
    match = _FENCE.match(line)
    if match is None:
        return None
    marker = match.group(1)
    return marker[0], len(marker), match.group(2)


def _is_fence_close(line: str, fence: tuple[str, int]) -> bool:
    marker = _fence_marker(line)
    return bool(
        marker and marker[0] == fence[0] and marker[1] >= fence[1] and not marker[2].strip()
    )


def _inline_code_spans(value: str) -> list[tuple[int, int, int, int]]:
    """Return same-line Markdown code spans without interpreting their contents."""
    runs: list[tuple[int, int, int]] = []
    index = 0
    while index < len(value):
        if value[index] == "\\":
            end_slashes = index + 1
            while end_slashes < len(value) and value[end_slashes] == "\\":
                end_slashes += 1
            if (
                (end_slashes - index) % 2 == 1
                and end_slashes < len(value)
                and value[end_slashes] == "`"
            ):
                index = end_slashes + 1
                while index < len(value) and value[index] == "`":
                    index += 1
            else:
                index = end_slashes
            continue
        if value[index] != "`":
            index += 1
            continue
        end = index + 1
        while end < len(value) and value[end] == "`":
            end += 1
        runs.append((index, end, end - index))
        index = end

    indexes_by_length: dict[int, list[int]] = {}
    for run_index, (_start, _end, length) in enumerate(runs):
        indexes_by_length.setdefault(length, []).append(run_index)

    spans: list[tuple[int, int, int, int]] = []
    run_index = 0
    while run_index < len(runs):
        start, open_end, length = runs[run_index]
        matching_runs = indexes_by_length[length]
        next_match = bisect_right(matching_runs, run_index)
        if next_match == len(matching_runs):
            run_index += 1
            continue
        close_index = matching_runs[next_match]
        close_start, close_end, _close_length = runs[close_index]
        spans.append((start, open_end, close_start, close_end))
        run_index = close_index + 1
    return spans


def _blank_preserving_newlines(value: str) -> str:
    return "".join(character if character in "\r\n" else " " for character in value)


def _mask_html_comments(content: str) -> str:
    """Mask HTML comments outside fenced/indented and inline code, retaining lines."""
    masked_lines: list[str] = []
    fence: tuple[str, int] | None = None
    fence_quote_depth = 0
    in_comment = False
    in_cdata = False

    for line in content.splitlines(keepends=True):
        body, line_ending = _line_body(line)
        unquoted, quote_depth = _strip_quote_prefix(body)
        if fence is not None:
            if quote_depth >= fence_quote_depth:
                masked_lines.append(line)
                if _is_fence_close(unquoted, fence):
                    fence = None
                continue
            fence = None

        # A fence-looking line inside an open HTML comment is comment text, not
        # a code boundary. Conversely, comment delimiters in a code block never
        # change the comment state.
        if not in_comment and not in_cdata:
            marker = _fence_marker(unquoted)
            if marker is not None:
                fence = (marker[0], marker[1])
                fence_quote_depth = quote_depth
                masked_lines.append(line)
                continue
            if _INDENTED_CODE.match(body):
                masked_lines.append(line)
                continue

        code_spans = {
            start: end for start, _open_end, _close_start, end in _inline_code_spans(body)
        }
        pieces: list[str] = []
        index = 0
        while index < len(body):
            if in_cdata:
                close = body.find("]]>", index)
                if close < 0:
                    pieces.append(body[index:])
                    break
                end = close + 3
                pieces.append(body[index:end])
                index = end
                in_cdata = False
                continue
            if in_comment:
                close = body.find("-->", index)
                if close < 0:
                    pieces.append(_blank_preserving_newlines(body[index:]))
                    index = len(body)
                    break
                end = close + 3
                pieces.append(_blank_preserving_newlines(body[index:end]))
                index = end
                in_comment = False
                continue

            code_end = code_spans.get(index)
            if code_end is not None:
                pieces.append(body[index:code_end])
                index = code_end
                continue

            if body.startswith("<![CDATA[", index) and not _is_escaped(body, index):
                pieces.append("<![CDATA[")
                index += len("<![CDATA[")
                in_cdata = True
                continue
            if body.startswith("<!--", index) and not _is_escaped(body, index):
                pieces.append("    ")
                index += 4
                in_comment = True
                continue

            pieces.append(body[index])
            index += 1

        masked_lines.append("".join(pieces) + line_ending)

    return "".join(masked_lines)


def _is_escaped(value: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and value[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _strip_html_tags(value: str, *, preserve_prefix: bool = False) -> tuple[str, bool]:
    """Blank raw HTML subtrees without interpreting styles or attributes.

    Markdown code spans are protected by the caller. Keep character/newline
    positions so headings and adjacent Markdown evidence survive extraction.
    """
    pieces: list[str] = []
    elements: list[tuple[str, int]] = []
    index = 0

    def invalid(from_index: int) -> tuple[str, bool]:
        if not preserve_prefix:
            return "", True
        prefix = "".join(pieces)
        return prefix[:from_index] + _blank_preserving_newlines(value[from_index:]), True

    while index < len(value):
        if value[index] != "<" or _is_escaped(value, index):
            if not elements:
                pieces.append(value[index])
            else:
                pieces.append(_blank_preserving_newlines(value[index]))
            index += 1
            continue

        autolink = re.match(r"<(?:https?://|mailto:)[^>\s]+>", value[index:], re.IGNORECASE)
        if autolink is not None:
            # An autolink has no Markdown link label; its URL is not a decision.
            pieces.append(_blank_preserving_newlines(autolink.group(0)))
            index += len(autolink.group(0))
            continue

        tag = _HTML_TAG_START.match(value, index)
        if tag is None:
            # CDATA ends at ]]>, not at its first >. Other declarations and
            # processing instructions are outside this Markdown evidence grammar.
            if value.startswith("<![CDATA[", index):
                close = value.find("]]>", index + len("<![CDATA["))
                if close < 0:
                    return invalid(index)
                end = close + 3
                pieces.append(_blank_preserving_newlines(value[index:end]))
                index = end
                continue
            if value.startswith(("<!", "<?"), index):
                return invalid(index)
            if index + 1 < len(value) and value[index + 1] not in " \t\r\n=+-<>":
                return invalid(index)
            if not elements:
                pieces.append(value[index])
            else:
                pieces.append(_blank_preserving_newlines(value[index]))
            index += 1
            continue

        quote: str | None = None
        cursor = tag.end()
        while cursor < len(value):
            character = value[cursor]
            if quote is not None:
                if character == quote:
                    quote = None
            elif character in {"'", '"'}:
                quote = character
            elif character == ">":
                break
            cursor += 1
        if cursor == len(value):
            return invalid(index)
        tag_text = value[index : cursor + 1]
        name = tag.group(1).casefold()
        closing = value[index + 1 : index + 2] == "/"
        self_closing = tag_text[:-1].rstrip().endswith("/")
        if self_closing and name not in _HTML_VOID_TAGS:
            # HTML ignores the self-closing flag on non-void elements. The
            # following text may still be inside raw HTML until an actual end
            # tag, so this document has no safe approval-evidence boundary.
            return invalid(index)
        if closing:
            if not elements or elements[-1][0] != name:
                return invalid(elements[0][1] if elements else index)
            elements.pop()
        elif not self_closing and name not in _HTML_VOID_TAGS:
            elements.append((name, index))
        pieces.append(_blank_preserving_newlines(tag_text))
        index = cursor + 1

    if elements:
        return invalid(elements[0][1])
    return "".join(pieces), False


def _markdown_group_end(value: str, start: int, opener: str, closer: str) -> int | None:
    depth = 0
    quote: str | None = None
    index = start
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            index += 2
            continue
        if opener == "(" and character in {"'", '"'}:
            quote = None if quote == character else character if quote is None else quote
            index += 1
            continue
        if quote is not None:
            index += 1
            continue
        if character == opener:
            depth += 1
        elif character == closer:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _strip_markdown_images(value: str) -> str:
    """Image alt/title/reference text is not a rendered document decision."""
    pieces: list[str] = []
    index = 0
    while index < len(value):
        if value.startswith("![", index) and not _is_escaped(value, index):
            end = _markdown_group_end(value, index + 1, "[", "]")
            if end is None:
                return "".join(pieces) + _blank_preserving_newlines(value[index:])
            reference_start = end
            line_breaks = 0
            while reference_start < len(value) and value[reference_start] in " \t\n":
                if value[reference_start] == "\n":
                    line_breaks += 1
                    if line_breaks > 1:
                        break
                reference_start += 1
            if reference_start < len(value) and value[reference_start] == "[":
                end = _markdown_group_end(value, reference_start, "[", "]")
                if end is None:
                    return "".join(pieces) + _blank_preserving_newlines(value[index:])
            elif end < len(value) and value[end] == "(":
                end = _markdown_group_end(value, end, "(", ")")
                if end is None:
                    return "".join(pieces) + _blank_preserving_newlines(value[index:])
            # Handles inline, full/collapsed reference, and shortcut image forms.
            pieces.append(_blank_preserving_newlines(value[index:end]))
            index = end
        else:
            pieces.append(value[index])
            index += 1
    return "".join(pieces)


def _markdown_link_labels(value: str) -> tuple[str, bool]:
    """Only a link label is approval evidence, never its destination or title."""
    pieces: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "[" or _is_escaped(value, index):
            pieces.append(value[index])
            index += 1
            continue
        label_end = _markdown_group_end(value, index, "[", "]")
        if label_end is None:
            return "", True
        target_start = label_end
        while target_start < len(value) and value[target_start] in " \t":
            target_start += 1
        if target_start < len(value) and value[target_start] == "[":
            target_end = _markdown_group_end(value, target_start, "[", "]")
        elif label_end < len(value) and value[label_end] == "(":
            target_end = _markdown_group_end(value, label_end, "(", ")")
            if target_end is not None:
                destination = value[label_end + 1 : target_end - 1].strip()
                if destination and not _REFERENCE_DESTINATION.fullmatch(destination):
                    return "", True
        else:
            # Plain brackets or shortcut references display their label.
            pieces.append(value[index])
            index += 1
            continue
        if target_end is None or "\n" in value[index:target_end]:
            return "", True
        pieces.append(value[index + 1 : label_end - 1])
        index = target_end
    return "".join(pieces), False


def _mask_reference_definitions(
    lines: list[str], source_lines: list[str]
) -> tuple[list[str], bool]:
    """A reference's indented next-line title is metadata, not Markdown prose."""
    result = lines.copy()
    index = 0
    while index < len(result):
        definition = _REFERENCE_START.fullmatch(result[index])
        if definition is None:
            index += 1
            continue
        raw, _depth = _strip_quote_prefix(source_lines[index])
        raw_definition = _REFERENCE_START.fullmatch(_LIST_PREFIX.sub("", raw.lstrip(), count=1))
        destination = definition.group(1).strip() or (
            raw_definition.group(1).strip() if raw_definition is not None else ""
        )
        result[index] = ""
        index += 1
        if not destination:
            if index >= len(result):
                return [""] * len(result), True
            raw_destination, _depth = _strip_quote_prefix(source_lines[index])
            if not raw_destination[:1].isspace() or not _REFERENCE_DESTINATION.fullmatch(
                raw_destination.strip()
            ):
                return [""] * len(result), True
            result[index] = ""
            index += 1
        if index < len(result):
            raw_title, _depth = _strip_quote_prefix(source_lines[index])
            if _REFERENCE_TITLE_LINE.fullmatch(raw_title):
                result[index] = ""
                index += 1
            elif _REFERENCE_TITLE_CANDIDATE.match(raw_title):
                # It might be a malformed title; do not turn that ambiguity
                # into approval evidence beside another completed decision.
                return [""] * len(result), True
    return result, False


def _visible_markdown_text(value: str) -> tuple[str, bool]:
    """Extract bounded visible text for shape checks, not arbitrary HTML rendering."""
    code_spans = _inline_code_spans(value)
    prefix = "\ue000"
    while prefix in value:
        prefix += "\ue000"
    protected: dict[str, str] = {}
    for span_index, (start, open_end, close_start, end) in reversed(list(enumerate(code_spans))):
        token = f"{prefix}{span_index}\ue001"
        protected[token] = value[open_end:close_start]
        value = value[:start] + token + value[end:]

    if _REFERENCE_DEFINITION.fullmatch(value.strip()):
        return "", False
    # HTML declarations have precedence over image syntax: <![CDATA[ contains
    # the literal sequence ![, but its body must never become Markdown prose.
    value, ambiguous = _strip_html_tags(value)
    if ambiguous:
        return "", True
    value = _strip_markdown_images(value)
    value, ambiguous = _markdown_link_labels(value)
    if ambiguous:
        return "", True
    value = unescape(value)
    value = re.sub(r"\\([\\`*_{}\[\]()#+.\-!<>|~])", r"\1", value)
    value = re.sub(r"(?<!\w)[*_~]+(?=\S)|(?<=\S)[*_~]+(?!\w)", "", value)
    for token, code in protected.items():
        value = value.replace(token, code)
    return " ".join(value.split()), False


def _strip_quote_prefix(line: str) -> tuple[str, int]:
    depth = 0
    while match := _QUOTE_PREFIX.match(line):
        line = line[match.end() :]
        depth += 1
    return line, depth


def _markdown_lines(content: str) -> list[tuple[str, bool]]:
    """Only block-level visible Markdown can supply review decisions.

    Track container indentation rather than treating all four-space lines alike:
    inside a list they may be child items or continuation text, whereas outside
    (or four further columns inside) they are illustrative code.
    """
    result: list[tuple[str, bool]] = []
    fence: tuple[str, int] | None = None
    fence_quote_depth = 0
    list_columns: list[tuple[int, int]] = []
    for raw in content.splitlines():
        line, quote_depth = _strip_quote_prefix(raw)
        if fence is not None:
            if quote_depth >= fence_quote_depth:
                if _is_fence_close(line.strip(), fence):
                    fence = None
                result.append(("", False))
                continue
            fence = None  # A quoted fence cannot consume the following outer prose.

        if not line.strip():
            result.append(("", False))
            continue
        if _THEMATIC_BREAK.fullmatch(line):
            # Markdown thematic breaks precede list parsing: `- - -` is not
            # an unresolved list item or approval evidence.
            result.append(("", False))
            continue

        expanded = line.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip(" "))
        item = _LIST_PREFIX.match(expanded[indent:])
        if item is not None:
            # A marker beyond the list item's content column plus four spaces
            # is indented example code, even if it visually resembles a child.
            if list_columns and indent >= list_columns[-1][1] + 4:
                result.append(("", False))
                continue
            while list_columns and list_columns[-1][0] >= indent:
                list_columns.pop()
            if indent >= 4 and not list_columns:
                result.append(("", False))
                continue
            if list_columns and indent < list_columns[-1][1]:
                list_columns.clear()
                if indent >= 4:
                    result.append(("", False))
                    continue
            list_columns.append((indent, indent + item.end()))
            text = expanded[indent + item.end() :]
            text, nested_quote_depth = _strip_quote_prefix(text)
            quote_depth += nested_quote_depth
            is_heading = False
        else:
            while list_columns and indent < list_columns[-1][1]:
                list_columns.pop()
            if indent >= (list_columns[-1][1] + 4 if list_columns else 4):
                result.append(("", False))
                continue
            text = expanded.lstrip(" ") if list_columns else line
            is_heading = not list_columns

        marker = _fence_marker(text)
        if marker is not None:
            fence = (marker[0], marker[1])
            fence_quote_depth = quote_depth
            result.append(("", False))
            continue
        result.append((text, is_heading))

    # Protect literal inline code while excluding raw HTML across *all* lines:
    # an element may span an entire field, table, section, or heading.
    joined = _mask_html_comments("\n".join(line for line, _ in result))
    prefix = "\ue000"
    while prefix in joined:
        prefix += "\ue000"
    protected: dict[str, str] = {}
    lines = joined.split("\n")
    token_index = 0
    for line_index, line in enumerate(lines):
        for start, _open_end, _close_start, end in reversed(_inline_code_spans(line)):
            token = f"{prefix}{token_index}\ue001"
            token_index += 1
            protected[token] = line[start:end]
            line = line[:start] + token + line[end:]
        lines[line_index] = line
    joined = "\n".join(lines)
    visible, ambiguous = _strip_html_tags(joined, preserve_prefix=True)
    if ambiguous:
        # A malformed HTML boundary cannot establish which following text is
        # Markdown rather than element content. Do not approve this document.
        return [("", False) for _ in result]
    visible = _strip_markdown_images(visible)
    visible, ambiguous_link = _markdown_link_labels(visible)
    if ambiguous_link:
        return [("", False) for _ in result]
    for token, code in protected.items():
        visible = visible.replace(token, code)
    visible_lines = visible.split("\n")
    visible_lines, ambiguous_reference = _mask_reference_definitions(
        visible_lines, content.splitlines()
    )
    if ambiguous_reference:
        return [("", False) for _ in result]
    return [(line, heading) for line, (_old, heading) in zip(visible_lines, result, strict=True)]


def _undecided_text(value: str) -> bool:
    visible, ambiguous = _visible_markdown_text(value)
    if ambiguous:
        return True
    plain = re.sub(r"^[\W_]+|[\W_]+$", "", visible.strip())
    if not plain or _URL_ONLY.fullmatch(plain):
        return True
    marked = " ".join(plain.lower().split())
    normalized = " ".join(re.sub(r"[_-]+", " ", marked).split())
    # These explicit markers leave the *whole required value* unanswered even
    # beside concrete prose. Evaluate them on visible text, not punctuation
    # positions; context-dependent words such as "pending" remain separate.
    return (
        _UNDECIDED_FIELD.fullmatch(normalized) is not None
        or _UNRESOLVED_TOKEN.search(marked) is not None
        or _UNRESOLVED_DEFERRED.search(normalized) is not None
        or _UNDECIDED_CONTEXTUAL_PREFIX.match(normalized) is not None
        or _UNDECIDED_MARKED_CLAUSE.search(marked) is not None
        or _UNDECIDED_CONTEXTUAL_TAG.search(marked) is not None
    )


class DocumentPairApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_project_revision: Annotated[
        int,
        Field(strict=True, ge=1, le=MAX_REVISION_NUMBER),
    ]
    expected_agents_revision: Annotated[
        int,
        Field(strict=True, ge=1, le=MAX_REVISION_NUMBER),
    ]


class RevisionReference(BaseModel):
    id: uuid.UUID
    revision_number: int
    content_sha256: str


class DocumentPairApprovalView(BaseModel):
    id: uuid.UUID
    project_revision_id: uuid.UUID
    project_revision_number: int
    agents_revision_id: uuid.UUID
    agents_revision_number: int
    actor_user_id: uuid.UUID | None
    created_at: datetime


class DocumentPairApprovalStatus(BaseModel):
    current_project_revision: RevisionReference
    current_agents_revision: RevisionReference
    approved: bool
    latest_approval: DocumentPairApprovalView | None
    approvals: list[DocumentPairApprovalView]
    approval_offset: int
    approval_has_more: bool
    approval_next_cursor: str | None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _approval_cursor(approval: ProjectDocumentPairApproval) -> str:
    return f"{_utc(approval.created_at).isoformat(timespec='microseconds')}|{approval.id}"


def _parse_approval_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    timestamp, delimiter, identifier = cursor.partition("|")
    try:
        if delimiter != "|" or "|" in identifier:
            raise ValueError("Invalid cursor separator")
        created_at = datetime.fromisoformat(timestamp)
        if created_at.utcoffset() is None:
            raise ValueError("Cursor timestamp must include a timezone")
        return created_at.astimezone(UTC), uuid.UUID(identifier)
    except (ValueError, OverflowError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid approval history cursor.",
        ) from exc


def _lock_pair_heads(
    db: Session,
    project_id: uuid.UUID,
) -> tuple[dict[str, ProjectDocument], dict[PairKind, ProjectDocumentRevision]]:
    """Lock the two approval heads in one stable order before reading revisions."""
    documents = list(
        db.scalars(
            select(ProjectDocument)
            .where(
                ProjectDocument.project_id == project_id,
                ProjectDocument.kind.in_(PAIR_KINDS),
            )
            .order_by(ProjectDocument.kind)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    document_by_kind = {document.kind: document for document in documents}
    if set(document_by_kind) != set(PAIR_KINDS):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project specification and agent-rules drafts are not fully initialized.",
        )
    revisions = {
        kind: _read_revision(
            db,
            document_by_kind[kind],
            document_by_kind[kind].head_revision_number,
        )
        for kind in PAIR_KINDS
    }
    return document_by_kind, revisions


def _revision_reference(revision: ProjectDocumentRevision) -> RevisionReference:
    return RevisionReference(
        id=revision.id,
        revision_number=revision.revision_number,
        content_sha256=revision.content_sha256,
    )


def _approval_view(
    approval: ProjectDocumentPairApproval,
    revision_by_id: dict[uuid.UUID, ProjectDocumentRevision],
) -> DocumentPairApprovalView:
    project_revision = revision_by_id.get(approval.project_revision_id)
    agents_revision = revision_by_id.get(approval.agents_revision_id)
    if project_revision is None or agents_revision is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The saved approval history is incomplete.",
        )
    return DocumentPairApprovalView(
        id=approval.id,
        project_revision_id=project_revision.id,
        project_revision_number=project_revision.revision_number,
        agents_revision_id=agents_revision.id,
        agents_revision_number=agents_revision.revision_number,
        actor_user_id=approval.actor_user_id,
        created_at=_utc(approval.created_at),
    )


def _status_view(
    db: Session,
    project_id: uuid.UUID,
    documents: dict[str, ProjectDocument],
    revisions: dict[PairKind, ProjectDocumentRevision],
    *,
    limit: int,
    cursor: tuple[datetime, uuid.UUID] | None,
) -> DocumentPairApprovalStatus:
    current_approval = db.scalar(
        select(ProjectDocumentPairApproval).where(
            ProjectDocumentPairApproval.project_id == project_id,
            ProjectDocumentPairApproval.project_revision_id == revisions["project"].id,
            ProjectDocumentPairApproval.agents_revision_id == revisions["agents"].id,
        )
    )
    # A previously recorded tuple is not grandfathered past a newly enforced
    # validation rule (or corrupted starter provenance).
    approved = current_approval is not None and not _pair_validation_errors(
        db, documents, revisions
    )
    latest = current_approval or db.scalar(
        select(ProjectDocumentPairApproval)
        .where(ProjectDocumentPairApproval.project_id == project_id)
        .order_by(
            ProjectDocumentPairApproval.created_at.desc(),
            ProjectDocumentPairApproval.id.desc(),
        )
        .limit(1)
    )
    statement = select(ProjectDocumentPairApproval).where(
        ProjectDocumentPairApproval.project_id == project_id
    )
    if cursor is not None:
        created_at, approval_id = cursor
        statement = statement.where(
            or_(
                ProjectDocumentPairApproval.created_at < created_at,
                and_(
                    ProjectDocumentPairApproval.created_at == created_at,
                    ProjectDocumentPairApproval.id < approval_id,
                ),
            )
        )
    rows = list(
        db.scalars(
            statement.order_by(
                ProjectDocumentPairApproval.created_at.desc(),
                ProjectDocumentPairApproval.id.desc(),
            ).limit(limit + 1)
        ).all()
    )
    approval_has_more = len(rows) > limit
    page = rows[:limit]
    revision_ids = {
        revision_id
        for approval in [*page, *([latest] if latest is not None else [])]
        for revision_id in (approval.project_revision_id, approval.agents_revision_id)
    }
    revision_by_id = (
        {
            revision.id: revision
            for revision in db.scalars(
                select(ProjectDocumentRevision).where(ProjectDocumentRevision.id.in_(revision_ids))
            ).all()
        }
        if revision_ids
        else {}
    )

    current_project = revisions["project"]
    current_agents = revisions["agents"]
    return DocumentPairApprovalStatus(
        current_project_revision=_revision_reference(current_project),
        current_agents_revision=_revision_reference(current_agents),
        approved=approved,
        latest_approval=_approval_view(latest, revision_by_id) if latest is not None else None,
        approvals=[_approval_view(approval, revision_by_id) for approval in page],
        approval_offset=0,
        approval_has_more=approval_has_more,
        approval_next_cursor=_approval_cursor(page[-1]) if approval_has_more and page else None,
    )


def _file_validation_errors(
    kind: PairKind,
    content: str,
    template_revision: ProjectDocumentRevision,
) -> list[str]:
    expected_source = TEMPLATE_SOURCES[kind]
    source_digest = hashlib.sha256(template_revision.content.encode("utf-8")).hexdigest()
    if (
        template_revision.revision_number != 1
        or template_revision.origin != "template"
        or template_revision.template_source != expected_source
        or template_revision.template_sha256 != source_digest
        or template_revision.content_sha256 != source_digest
    ):
        return ["The original starter-template provenance could not be verified."]

    canonical_content = content.replace("\r\n", "\n").replace("\r", "\n")
    canonical_template = template_revision.content.replace("\r\n", "\n").replace("\r", "\n")
    errors: list[str] = []
    if not canonical_content.strip():
        errors.append("Add document content before approving this pair.")
    if canonical_content == canonical_template:
        errors.append("This document is unchanged from its saved starter revision.")

    placeholders = set(_PLACEHOLDER_PATTERN.findall(template_revision.content))
    if _unresolved_angle_marker(content, placeholders):
        errors.append("Replace unresolved document placeholders before approving this pair.")

    if _contains_starter_checklist(content, template_revision.content):
        errors.append("Remove the starter checklist before approving this pair.")

    starter_notes = tuple(
        line.strip()
        for line in template_revision.content.splitlines()
        if "STARTER TEMPLATE" in line.upper()
    )
    content_lines = {line.strip() for line in content.splitlines()}
    if starter_notes and any(note in content_lines for note in starter_notes):
        errors.append("Remove the starter-template setup notes before approving this pair.")
    template_quotes = {
        line.lstrip("> ").strip()
        for line in canonical_template.splitlines()
        if line.lstrip().startswith(">")
    }
    if any(
        line.lstrip("> ").strip() in template_quotes
        for line in canonical_content.splitlines()
        if line.lstrip().startswith(">")
    ):
        if not any("setup notes" in message for message in errors):
            errors.append("Remove the starter-template setup notes before approving this pair.")

    # The immutable starter deliberately contains angle placeholders. They are
    # not approval evidence, but must not make its trusted heading inventory
    # ambiguous under the stricter submitted-document HTML boundary.
    template_shape = _PLACEHOLDER_PATTERN.sub(
        lambda match: _blank_preserving_newlines(match.group()), canonical_template
    )
    template_sections = _sections(template_shape)
    content_sections = _sections(canonical_content)
    template_headings = {name for name, level, _ in template_sections if level == 2}
    content_headings = {name for name, level, _ in content_sections if level == 2}
    if any(section not in template_headings for section in _REQUIRED_SECTIONS[kind]):
        errors.append("The saved starter does not define the required review sections.")
    missing_sections = [
        section for section in _REQUIRED_SECTIONS[kind] if section not in content_headings
    ]
    if missing_sections:
        errors.append("Add project-specific sections for: " + ", ".join(missing_sections) + ".")
    for section in _REQUIRED_SECTIONS[kind]:
        if section not in content_headings:
            continue
        has_decision, undecided_value = _section_decisions(content_sections, section, level=2)
        if undecided_value:
            errors.append(f"Resolve undecided decisions under {section}.")
        if section != "Scope" and not has_decision:
            errors.append(f"Add a project-specific decision under {section}.")
    if kind == "project":
        purpose_lines = _section_lines(content_sections, "Purpose and users", level=2)
        fields = _project_field_values(purpose_lines)
        starter_fields = dict(_FIELD.findall(canonical_template))
        for field in _REQUIRED_PROJECT_FIELDS:
            values = fields.get(field, [])
            if field not in starter_fields:
                errors.append(f"The saved starter does not define the {field} decision.")
            elif (
                len(values) != 1
                or any(_undecided_text(part) for part in values[0])
                or any(_unresolved_angle_marker(part, placeholders) for part in values[0])
            ):
                errors.append(f"Fill the {field} decision for this project.")
        scope_children = _section_children(content_sections, "Scope", level=2)
        for section in ("In scope", "Out of scope"):
            has_decision, undecided_value = _section_decisions(scope_children, section, level=3)
            present = any(name == section and level == 3 for name, level, _ in scope_children)
            if not present or not has_decision or undecided_value:
                errors.append(f"Describe what is {section.lower()} for this project.")
    return errors


def _section_headings(content: str) -> set[str]:
    return {name for name, _level, _ in _sections(content)}


type ReviewSection = tuple[str, int, list[str]]


def _sections(content: str) -> list[ReviewSection]:
    """Extract headings and eligible body lines once for all approval checks."""
    sections: list[ReviewSection] = []
    for line, heading_allowed in _markdown_lines(content):
        heading = _MARKDOWN_HEADING.match(line) if heading_allowed else None
        if heading is not None:
            name, ambiguous = _visible_markdown_text(line[heading.end() :].strip().strip("#"))
            if ambiguous:
                name = ""
            name = re.sub(r"^\d+\.\s*", "", name)
            name = re.sub(r"\s+[—–-]\s+(required|optional)$", "", name, flags=re.I)
            name = " ".join(name.split())
            sections.append((name, len(heading.group(1)), []))
        elif sections:
            sections[-1][2].append(line)
    return sections


def _section_children(
    sections: list[ReviewSection], name: str, *, level: int
) -> list[ReviewSection]:
    for index, (heading, depth, _lines) in enumerate(sections):
        if heading == name and depth == level:
            end = index + 1
            while end < len(sections) and sections[end][1] > level:
                end += 1
            return sections[index + 1 : end]
    return []


def _section_lines(sections: list[ReviewSection], name: str, *, level: int) -> list[str]:
    lines: list[str] = []
    for index, (heading, depth, body) in enumerate(sections):
        if heading != name or depth != level:
            continue
        lines.extend(body)
        cursor = index + 1
        while cursor < len(sections) and sections[cursor][1] > level:
            lines.extend(sections[cursor][2])
            cursor += 1
    return lines


def _table_cells(row: str) -> list[str] | None:
    """Split one pipe row while keeping escaped/code-span pipes inside their cell."""
    row = row.strip()
    if "|" not in row:
        return None
    code_spans = {start: end for start, _open_end, _close_start, end in _inline_code_spans(row)}
    cells: list[str] = []
    cell: list[str] = []
    index = 0
    has_delimiter = False
    while index < len(row):
        code_end = code_spans.get(index)
        if code_end is not None:
            cell.append(row[index:code_end])
            index = code_end
        elif row[index] == "\\" and index + 1 < len(row) and row[index + 1] == "|":
            cell.append("\\|")
            index += 2
        elif row[index] == "|":
            has_delimiter = True
            cells.append("".join(cell).strip())
            cell = []
            index += 1
        else:
            cell.append(row[index])
            index += 1
    cells.append("".join(cell).strip())
    if row.startswith("|"):
        cells = cells[1:]
    if row.endswith("|"):
        cells = cells[:-1]
    return cells if has_delimiter and cells else None


def _table_separator(cells: list[str] | None) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _table_block(
    lines: list[str], index: int
) -> tuple[list[str], list[tuple[list[str], bool]], int] | None:
    header = _table_cells(lines[index])
    separator = _table_cells(lines[index + 1]) if index + 1 < len(lines) else None
    if (
        header is None
        or separator is None
        or len(header) != len(separator)
        or not _table_separator(separator)
    ):
        return None

    rows: list[tuple[list[str], bool]] = []
    cursor = index + 2
    while cursor < len(lines) and lines[cursor].strip():
        cells = _table_cells(lines[cursor])
        if cells is None:
            break
        if not _table_separator(cells):
            rows.append((cells, len(cells) != len(header)))
        cursor += 1
    return header, rows, cursor


def _strip_list_prefix(line: str) -> str:
    value = line.strip()
    while value.startswith(">"):
        value = value[1:].lstrip()
    return _LIST_PREFIX.sub("", value, count=1)


def _project_field_values(lines: list[str]) -> dict[str, list[tuple[str, ...]]]:
    values: dict[str, list[tuple[str, ...]]] = {}
    index = 0
    while index < len(lines):
        table = _table_block(lines, index)
        if table is not None:
            _header, rows, next_index = table
            for cells, malformed in rows:
                if malformed or len(cells) < 2:
                    continue
                label, label_ambiguous = _visible_markdown_text(cells[0])
                field = " ".join(label.split())
                if label_ambiguous or field not in _REQUIRED_PROJECT_FIELDS:
                    continue
                parts = tuple(_visible_markdown_text(cell)[0] for cell in cells[1:])
                values.setdefault(field, []).append(parts)
            index = max(next_index, index + 1)
            continue

        visible, ambiguous = _visible_markdown_text(_strip_list_prefix(lines[index]))
        if not ambiguous:
            labeled = _LABELED_VALUE.fullmatch(visible.strip())
            if labeled is not None:
                field = " ".join(labeled.group(1).split())
                if field in _REQUIRED_PROJECT_FIELDS:
                    values.setdefault(field, []).append((labeled.group(2),))
        index += 1
    return values


def _decision_evidence(lines: list[str]) -> tuple[bool, bool]:
    has_decision = False
    undecided_value = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        table = _table_block(lines, index)
        if table is not None:
            _header, rows, next_index = table
            for row_cells, malformed in rows:
                if malformed:
                    undecided_value = True
                    continue
                # In a multi-column table the first cell labels the decision;
                # a one-column table has no separate label/value columns.
                values = row_cells if len(row_cells) == 1 else row_cells[1:]
                if any(_undecided_text(cell) for cell in row_cells):
                    undecided_value = True
                elif values:
                    has_decision = True
            index = max(next_index, index + 1)
            continue

        pipe_cells = _table_cells(line)
        if pipe_cells is not None:
            # Without an adjacent table separator, ordinary prose containing
            # one pipe is still prose. Isolated pipe-wrapped rows are not table
            # evidence; unresolved cells and multi-pipe ambiguous rows fail
            # closed even if another line supplies a decision.
            if any(_undecided_text(cell) for cell in pipe_cells):
                undecided_value = True
                index += 1
                continue
            if line.strip().startswith("|") or line.strip().endswith("|"):
                index += 1
                continue
            if len(pipe_cells) > 2:
                undecided_value = True
                index += 1
                continue

        visible, ambiguous = _visible_markdown_text(_strip_list_prefix(line))
        if ambiguous or not visible:
            index += 1
            continue
        if _undecided_text(visible):
            # A marker can occur before a later colon ("Run checks; TODO:").
            # Testing only a labeled line's value would discard that marker.
            undecided_value = True
            index += 1
            continue
        labeled = _LABELED_VALUE.fullmatch(visible)
        if labeled is not None:
            if _undecided_text(labeled.group(2)):
                undecided_value = True
            else:
                has_decision = True
        else:
            has_decision = True
        index += 1
    return has_decision, undecided_value


def _section_decisions(
    sections: list[ReviewSection], name: str, *, level: int
) -> tuple[bool, bool]:
    has_decision, undecided = _decision_evidence(_section_lines(sections, name, level=level))
    for index, (heading, depth, _body) in enumerate(sections):
        if heading != name or depth != level:
            continue
        cursor = index + 1
        while cursor < len(sections) and sections[cursor][1] > level:
            # Headings organize body decisions; they do not supply one. A
            # labeled pending child heading is nevertheless an explicit open
            # decision under this required parent's Markdown hierarchy.
            child_heading = sections[cursor][0]
            labeled = _LABELED_VALUE.fullmatch(child_heading)
            if _undecided_text(child_heading) or (
                labeled is not None and _undecided_text(labeled.group(2))
            ):
                undecided = True
            cursor += 1
    return has_decision, undecided


def _contains_starter_checklist(content: str, template: str) -> bool:
    template_lines = template.splitlines()
    start = next(
        (index for index, line in enumerate(template_lines) if _CHECKLIST_HEADING.match(line)),
        None,
    )
    if start is None:
        return False
    if any(_CHECKLIST_HEADING.match(line) for line in content.splitlines()):
        return True

    heading = _MARKDOWN_HEADING.match(template_lines[start])
    assert heading is not None
    heading_level = len(heading.group(1))
    checklist_items: list[str] = []
    for line in template_lines[start + 1 :]:
        next_heading = _MARKDOWN_HEADING.match(line)
        if next_heading is not None and len(next_heading.group(1)) <= heading_level:
            break
        if _NUMBERED_ITEM.match(line):
            checklist_items.append(line.strip())
    if not checklist_items:
        return False
    content_lines = {line.strip() for line in content.splitlines()}
    return any(item in content_lines for item in checklist_items)


def _pair_validation_errors(
    db: Session,
    documents: dict[str, ProjectDocument],
    revisions: dict[PairKind, ProjectDocumentRevision],
) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for kind in PAIR_KINDS:
        try:
            template_revision = _read_revision(db, documents[kind], 1)
        except HTTPException:
            errors[TEMPLATE_SOURCES[kind].removesuffix(".example")] = [
                "The original starter-template provenance could not be verified."
            ]
            continue
        file_errors = _file_validation_errors(kind, revisions[kind].content, template_revision)
        if file_errors:
            errors[TEMPLATE_SOURCES[kind].removesuffix(".example")] = file_errors
    return errors


def _current_pair_documents(
    documents: dict[str, ProjectDocument],
    revisions: dict[PairKind, ProjectDocumentRevision],
) -> dict[PairKind, ProjectDocumentView]:
    return {kind: _document_view(documents[kind], revisions[kind]) for kind in PAIR_KINDS}


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


def _finish_read_only_post(
    db: Session,
    actor: User,
    project: Project,
    revisions: dict[PairKind, ProjectDocumentRevision],
    *,
    operation: str,
) -> None:
    if actor.role == "admin":
        # Stale/invalid POSTs evaluate private document heads; idempotent POSTs
        # read an existing approval. Commit the audit before returning a result.
        record_audit(
            db,
            action="admin.project.document_pair_approval.read",
            actor_user_id=actor.id,
            project_id=project.id,
            details={
                "operation": operation,
                "project_revision_number": revisions["project"].revision_number,
                "agents_revision_number": revisions["agents"].revision_number,
            },
        )
        db.commit()
    else:
        db.rollback()


@router.get("", response_model=DocumentPairApprovalStatus)
def get_document_pair_approval_status(
    project_id: uuid.UUID,
    db: DbSession,
    actor: CurrentActor,
    limit: int = Query(default=APPROVAL_HISTORY_PAGE_SIZE, ge=1, le=APPROVAL_HISTORY_PAGE_SIZE),
    cursor: Annotated[str | None, Query(max_length=96)] = None,
    offset: Annotated[int, Query(ge=0, le=0)] = 0,
) -> DocumentPairApprovalStatus:
    # Accept an explicit legacy offset=0, but reject nonzero offsets rather
    # than silently returning unstable pages to older clients.
    _ = offset
    active_user, project = _get_project_and_actor(db, actor, project_id)
    documents, revisions = _lock_pair_heads(db, project_id)
    result = _status_view(
        db,
        project_id,
        documents,
        revisions,
        limit=limit,
        cursor=_parse_approval_cursor(cursor) if cursor is not None else None,
    )
    if active_user.role == "admin":
        record_audit(
            db,
            action="admin.project.document_pair_approval.read",
            actor_user_id=active_user.id,
            project_id=project.id,
            details={
                "project_revision_number": revisions["project"].revision_number,
                "agents_revision_number": revisions["agents"].revision_number,
                "approved": result.approved,
            },
        )
        db.commit()
    else:
        db.rollback()
    return result


@router.post("", response_model=DocumentPairApprovalView)
def approve_document_pair(
    project_id: uuid.UUID,
    payload: DocumentPairApprovalRequest,
    db: DbSession,
    actor: CurrentActor,
    settings: SettingsDependency,
) -> DocumentPairApprovalView | JSONResponse:
    _initial_actor, _initial_project = _get_project_and_actor(db, actor, project_id)
    rate_limit = consume_rate_bucket(
        db,
        settings=settings,
        scope="project-document-pair-approval",
        subject=str(actor.id),
        limit=30,
        window_seconds=60 * 60,
    )
    # As with document saves, commit the limiter first, then revalidate and lock
    # the live account before taking document-head locks for the approval.
    db.commit()
    if not rate_limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many approval attempts. Try again later.",
            headers={"Retry-After": str(rate_limit.retry_after_seconds)},
        )
    active_user, project = _authorized_project_after_rate_limit(db, actor, project_id)
    documents, revisions = _lock_pair_heads(db, project_id)

    project_revision = revisions["project"]
    agents_revision = revisions["agents"]
    if (
        payload.expected_project_revision != project_revision.revision_number
        or payload.expected_agents_revision != agents_revision.revision_number
    ):
        status_view = _status_view(
            db,
            project_id,
            documents,
            revisions,
            limit=APPROVAL_HISTORY_PAGE_SIZE,
            cursor=None,
        )
        latest = _current_pair_documents(documents, revisions)
        body = {
            "detail": "A saved document changed. Review the latest PROJECT.md and AGENTS.md pair.",
            "latest": {
                "project": latest["project"].model_dump(mode="json"),
                "agents": latest["agents"].model_dump(mode="json"),
            },
            "approval_status": status_view.model_dump(mode="json"),
        }
        _finish_read_only_post(db, active_user, project, revisions, operation="stale_post")
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body)

    file_errors = _pair_validation_errors(db, documents, revisions)
    if file_errors:
        _finish_read_only_post(
            db, active_user, project, revisions, operation="validation_error_post"
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": {"files": file_errors}},
        )

    existing = db.scalar(
        select(ProjectDocumentPairApproval).where(
            ProjectDocumentPairApproval.project_id == project_id,
            ProjectDocumentPairApproval.project_revision_id == project_revision.id,
            ProjectDocumentPairApproval.agents_revision_id == agents_revision.id,
        )
    )
    if existing is not None:
        result = DocumentPairApprovalView(
            id=existing.id,
            project_revision_id=project_revision.id,
            project_revision_number=project_revision.revision_number,
            agents_revision_id=agents_revision.id,
            agents_revision_number=agents_revision.revision_number,
            actor_user_id=existing.actor_user_id,
            created_at=_utc(existing.created_at),
        )
        _finish_read_only_post(db, active_user, project, revisions, operation="idempotent_post")
        return result

    now = datetime.now(UTC)
    approval = ProjectDocumentPairApproval(
        id=uuid.uuid4(),
        project_id=project_id,
        project_revision_id=project_revision.id,
        agents_revision_id=agents_revision.id,
        actor_user_id=active_user.id,
        created_at=now,
    )
    db.add(approval)
    db.flush()
    record_audit(
        db,
        action="project.document_pair.approved",
        actor_user_id=active_user.id,
        project_id=project.id,
        details={
            "project_revision_id": str(project_revision.id),
            "project_revision_number": project_revision.revision_number,
            "agents_revision_id": str(agents_revision.id),
            "agents_revision_number": agents_revision.revision_number,
        },
    )
    db.commit()
    return DocumentPairApprovalView(
        id=approval.id,
        project_revision_id=project_revision.id,
        project_revision_number=project_revision.revision_number,
        agents_revision_id=agents_revision.id,
        agents_revision_number=agents_revision.revision_number,
        actor_user_id=active_user.id,
        created_at=now,
    )
