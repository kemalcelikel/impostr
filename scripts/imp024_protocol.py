"""Pure planning/inference contract for pinned OpenCode 1.18.34 / OpenAI 3.0.88.

Source: tool/{read,edit,write,question,json-schema}.ts, session/llm/request.ts,
schema/v1/question.ts and SDK responses/{prepare-tools,convert-to-input}.ts.
Native functions are inference DATA, never commands for the host relay. The
namespace owns execution; only canonical proposal files and questions are allowed.
No schema references, provider tools, arbitrary targets or permission expansion.
"""

import copy
import re

FILES = ("PROJECT.md", "AGENTS.md", "BACKLOG.md")
PATHS = tuple("/project/" + name for name in FILES)
# Pinned Project.fromDirectory maps a non-VCS global project's worktree to '/'.
# Native read/edit ask path.relative(worktree, filepath), not relative(cwd,...).
# No Git/tool installation is required just to make canonical planning work.
PATTERNS = tuple("project/" + name for name in FILES)
MAX_DOCUMENT = 64 * 1024
MAX_REQUEST = 512 * 1024
MAX_RESPONSE = 512 * 1024
MAX_CALLS = 8
MAX_ITEMS = 96
MAX_TOKENS = 4096
MAX_QUESTIONS = 8
FUNCTIONS = ("read", "edit", "write", "question")


class Invalid(ValueError):
    """Fixed nonsecret category only."""


def require(ok):
    if not ok:
        raise Invalid("planning contract")


def bounded_text(value, maximum=MAX_DOCUMENT, empty=True):
    require(isinstance(value, str) and (empty or bool(value))
            and len(value.encode("utf-8")) <= maximum and "\0" not in value)
    return value


def identifier(value, prefix=None):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None
            and (prefix is None or value.startswith(prefix + "_")))
    return value


def canonical_path(value):
    require(value in PATHS)
    return value


def permission_path(pattern):
    require(pattern in PATTERNS)
    return "/" + pattern


def questions(value, custom=False):
    require(isinstance(value, list) and 1 <= len(value) <= MAX_QUESTIONS)
    for question in value:
        require(isinstance(question, dict)
                and {"question", "header", "options"} <= set(question)
                and not set(question) - {"question", "header", "options", "multiple", *(["custom"] if custom else [])})
        bounded_text(question["question"], 4096, empty=False)
        bounded_text(question["header"], 120, empty=False)
        for flag in ("multiple", "custom"):
            if flag in question:
                require(type(question[flag]) is bool)
        options = question["options"]
        require(isinstance(options, list) and 1 <= len(options) <= 16)
        labels = []
        for option in options:
            require(isinstance(option, dict) and set(option) == {"label", "description"})
            labels.append(bounded_text(option["label"], 256, empty=False))
            bounded_text(option["description"], 2048)
        require(len(labels) == len(set(labels)))
    return value


def arguments(name, value):
    require(name in FUNCTIONS and isinstance(value, dict))
    if name == "question":
        require(set(value) == {"questions"})
        questions(value["questions"])
        return value
    canonical_path(value.get("filePath"))
    if name == "read":
        require({"filePath"} <= set(value) <= {"filePath", "offset", "limit"})
        for key in ("offset", "limit"):
            if key in value:
                require(type(value[key]) is int and 1 <= value[key] <= 65536)
    elif name == "edit":
        require({"filePath", "oldString", "newString"} <= set(value)
                <= {"filePath", "oldString", "newString", "replaceAll"})
        bounded_text(value["oldString"], empty=False)
        bounded_text(value["newString"])
        require(value["oldString"] != value["newString"])
        if "replaceAll" in value:
            require(type(value["replaceAll"]) is bool)
    else:
        require(set(value) == {"filePath", "content"})
        bounded_text(value["content"])
    return value


# Accept the source-derived schema grammar, NOT arbitrary executable JSON Schema.
# Descriptions/$schema are inert and bounded; all references/compositions are denied.
def schema(value, shape):
    require(isinstance(value, dict) and isinstance(shape, dict))
    require(not set(value) - {"type", "properties", "required", "items", "description", "$schema",
                              "title", "minimum", "maximum", "additionalProperties"})
    for key in ("description", "title"):
        if key in value:
            bounded_text(value[key], 8192)
    if "$schema" in value:
        require(value["$schema"] == "https://json-schema.org/draft/2020-12/schema")
    require(value.get("type") == shape["type"])
    if shape["type"] == "object":
        require(isinstance(value.get("properties"), dict)
                and set(value["properties"]) == set(shape["properties"]))
        required = value.get("required", [])
        require(isinstance(required, list) and all(isinstance(key, str) for key in required)
                and len(required) == len(set(required))
                and set(required) == set(shape.get("required", [])))
        require(value.get("additionalProperties", False) is False)
        require(not set(value) & {"items", "minimum", "maximum"})
        for key, expected in shape["properties"].items():
            schema(value["properties"][key], expected)
    elif shape["type"] == "array":
        require(not set(value) & {"properties", "required", "additionalProperties", "minimum", "maximum"})
        schema(value.get("items"), shape["items"])
    else:
        require(not set(value) & {"properties", "items", "required", "additionalProperties"})
        for key in ("minimum", "maximum"):
            if key in value:
                require(shape["type"] == "integer" and type(value[key]) in (int, float)
                        and abs(value[key]) <= 9007199254740991)


STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}


def object_schema(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required}


QUESTION_SCHEMA = object_schema({"question": STRING, "header": STRING,
    "options": {"type": "array", "items": object_schema({"label": STRING, "description": STRING})},
    "multiple": BOOLEAN}, ["question", "header", "options"])
SCHEMAS = {
    "read": object_schema({"filePath": STRING, "offset": {"type": "integer"},
                            "limit": {"type": "integer"}}, ["filePath"]),
    "edit": object_schema({"filePath": STRING, "oldString": STRING, "newString": STRING,
                            "replaceAll": BOOLEAN}, ["filePath", "oldString", "newString"]),
    "write": object_schema({"content": STRING, "filePath": STRING}),
    "question": object_schema({"questions": {"type": "array", "items": QUESTION_SCHEMA}}),
}


def definitions(tools):
    require(isinstance(tools, list) and len(tools) <= len(FUNCTIONS))
    names = set()
    for tool in tools:
        require(isinstance(tool, dict) and set(tool) <= {"type", "name", "description", "parameters", "strict"}
                and tool.get("type") == "function" and tool.get("name") in FUNCTIONS)
        name = tool["name"]
        require(name not in names and tool.get("strict", False) is False)
        names.add(name)
        bounded_text(tool.get("description", ""), 32768)
        schema(tool.get("parameters"), SCHEMAS[name])
    return names


def fixture_definitions():
    return [{"type": "function", "name": name, "description": "Synthetic planning only",
             "parameters": copy.deepcopy(SCHEMAS[name]), "strict": False} for name in FUNCTIONS]


def permission_policy():
    # Pinned matcher evaluates LAST match. Non-VCS worktree-relative spellings
    # designate the SAME three absolute paths as inference argument validation.
    # write/apply_patch alias edit; relay blocks patch. No broad path grants.
    return {"*": "deny", "read": {"*": "deny", **dict.fromkeys(PATTERNS, "allow")},
            "edit": {"*": "deny", **dict.fromkeys(PATTERNS, "ask")}, "question": "allow"}


def terminal_error(sequence=0):
    # Measured IMP-023 non-retryable SDK/OpenCode framing. Never provider details.
    import json
    return ("event: error\ndata: " + json.dumps({"type": "error", "sequence_number": sequence,
        "error": {"type": "invalid_request_error", "code": "invalid_prompt",
                  "message": "relay unavailable", "param": None}}, separators=(",", ":")) + "\n\n").encode()
