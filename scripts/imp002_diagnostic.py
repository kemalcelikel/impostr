"""HUMAN ONLY reviewed offline input-category diagnostic.

Run from the repository: /usr/bin/python3 -I -B scripts/imp002_diagnostic.py
Agents must NEVER run this command or operator_report(). Tests inject fake inputs.
This does not resolve effective configuration, validate credentials, or authorize
live use. No OpenCode imports/loader, reference expansion, subprocess or network.
Public category basis: OpenCode v1.18.34 core flag/global, config/config.ts and
auth/index.ts; @ai-sdk/azure 3.0.93. Paths are the existing resolver's fixed defaults.
"""

import errno
import json
import os
from pathlib import Path
import stat
import sys

MAX_INPUT = 256 * 1024
MAX_ENV_NAMES = 4096
# Keep classification separate from the unchanged transport's rejecting guard.
XDG_DIRECTORIES = frozenset({
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR", "XDG_CONFIG_DIRS", "XDG_DATA_DIRS",
})
XDG_SESSION = frozenset({
    "XDG_SESSION_ID", "XDG_SESSION_TYPE", "XDG_SESSION_CLASS", "XDG_SESSION_DESKTOP",
    "XDG_CURRENT_DESKTOP", "XDG_SEAT", "XDG_VTNR",
})
CONFIG_PATHS = frozenset({
    "OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_TUI_CONFIG",
    "OPENCODE_TEST_HOME", "OPENCODE_TEST_MANAGED_CONFIG_DIR",
})
# Only exact publicly established resource/key names; unknown Azure names stay other.
AZURE_AUTH = frozenset({"AZURE_API_KEY"})
AZURE_RESOURCE = frozenset({"AZURE_RESOURCE_NAME", "AZURE_COGNITIVE_SERVICES_RESOURCE_NAME"})
ENV_FIELDS = (
    "xdg_directory", "xdg_session", "xdg_unknown", "opencode_config_content",
    "opencode_config_path", "opencode_auth_content", "opencode_other",
    "azure_auth", "azure_resource", "azure_other",
)
SOURCE_FIELDS = (
    "inline_config", "inline_auth", "global_json", "global_named_json",
    "global_jsonc", "global_legacy", "default_auth",
)
AUTH_FIELDS = ("api_key", "oauth", "wellknown_remote", "bearer_header",
               "token_provider_declaration", "unsupported")
SOURCE_STATES = frozenset({
    "unknown", "absent", "literal_json", "expansion_required", "unsupported",
    "unsupported_format", "too_large", "unsafe", "unreadable", "uninspected_override",
})
# Explicit projection: no source-controlled names or values reach serialization.
REPORT_SCHEMA = {
    "schema": frozenset({"imp002-diagnostic-v1"}),
    "status": frozenset({"complete", "unavailable"}),
    "network_used": frozenset({False}),
    "environment": dict.fromkeys(ENV_FIELDS, bool),
    "sources": dict.fromkeys(SOURCE_FIELDS, SOURCE_STATES),
    "authentication_observed": dict.fromkeys(AUTH_FIELDS, bool),
    "ambiguity": {"endpoint": frozenset({"unknown", "potential"}),
                  "model": frozenset({"unknown", "potential"})},
    "effective_configuration": frozenset({"unestablished"}),
    "other_sources": frozenset({"uninspected"}),
}


def empty_report():
    return {
        "schema": "imp002-diagnostic-v1", "status": "unavailable", "network_used": False,
        "environment": dict.fromkeys(ENV_FIELDS, False),
        "sources": dict.fromkeys(SOURCE_FIELDS, "unknown"),
        "authentication_observed": dict.fromkeys(AUTH_FIELDS, False),
        "ambiguity": {"endpoint": "unknown", "model": "unknown"},
        "effective_configuration": "unestablished", "other_sources": "uninspected",
    }


def project_report(value, schema=REPORT_SCHEMA):
    """Reject wrong types/enum values; copy ONLY fixed keys, never arbitrary extras."""
    if type(value) is not dict:
        raise ValueError("report unavailable")
    result = {}
    for key, rule in schema.items():
        item = value[key]
        if type(rule) is dict:
            item = project_report(item, rule)
        elif rule is bool:
            if type(item) is not bool:
                raise ValueError("report unavailable")
        elif type(item) not in (str, bool) or item not in rule:
            raise ValueError("report unavailable")
        result[key] = item
    return result


def render_report(value):
    try:
        projected = project_report(value)
    except Exception:
        projected = empty_report()
    return json.dumps(projected, sort_keys=True, separators=(",", ":"))


def environment_categories(environment):
    """Name-only classification. Never retrieve path, Azure key/resource or other values."""
    flags = dict.fromkeys(ENV_FIELDS, False)
    for index, name in enumerate(environment):
        if index >= MAX_ENV_NAMES or type(name) is not str or len(name) > 256:
            raise ValueError("input unavailable")
        if name in XDG_DIRECTORIES:
            category = "xdg_directory"
        elif name in XDG_SESSION:
            category = "xdg_session"
        elif name.startswith("XDG_"):
            category = "xdg_unknown"
        elif name == "OPENCODE_CONFIG_CONTENT":
            category = "opencode_config_content"
        elif name in CONFIG_PATHS:
            category = "opencode_config_path"
        elif name == "OPENCODE_AUTH_CONTENT":
            category = "opencode_auth_content"
        elif name.startswith("OPENCODE_"):
            category = "opencode_other"
        elif name in AZURE_AUTH:
            category = "azure_auth"
        elif name in AZURE_RESOURCE:
            category = "azure_resource"
        elif name.startswith("AZURE_"):
            category = "azure_other"
        else:
            continue
        flags[category] = True
    return flags


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("input unavailable")
        value[key] = item
    return value


def nonfinite(_):
    raise ValueError("input unavailable")


def has_expansion(value):
    """Bounded scan, including keys. Detect references but NEVER resolve them."""
    pending = [(value, 0)]
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if visited > 32768 or depth > 64:
            raise ValueError("input unavailable")
        if type(item) is str and ("{env:" in item or "{file:" in item):
            return True
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.keys())
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    return False


def parse_literal(body):
    """Strict JSON only. JSONC/nonobjects/duplicates/nonfinite/deep inputs unsupported."""
    if type(body) not in (str, bytes):
        return "unsupported", None
    if len(body) > MAX_INPUT:
        return "too_large", None
    try:
        encoded = body.encode("utf-8") if type(body) is str else body
        if len(encoded) > MAX_INPUT:
            return "too_large", None
        value = json.loads(encoded.decode("utf-8"), object_pairs_hook=unique_object,
                           parse_constant=nonfinite)
        if type(value) is not dict:
            return "unsupported", None
        if has_expansion(value):
            return "expansion_required", None
        return "literal_json", value
    except (ValueError, UnicodeError, RecursionError):
        return "unsupported", None


def safe_directory(info, uid):
    # A root-owned sticky ancestor permits synthetic /tmp fixtures; it cannot
    # replace another user's owned entry. Every subsequent component is fd-pinned.
    return (stat.S_ISDIR(info.st_mode) and info.st_uid in (0, uid)
            and (not info.st_mode & 0o022
                 or info.st_uid == 0 and info.st_mode & stat.S_ISVTX))


def read_fixed_file(path, *, literal=True):
    """Operator fixed paths or synthetic test paths ONLY; never referenced/env paths.

    Walk with directory fds and NOFOLLOW (including ancestors), check owner/write
    permissions before reading. No links, devices, FIFO blocking or unbounded read.
    No private data or exceptions are returned except parsed in-memory JSON to collect.
    """
    directory = fd = None
    try:
        path = Path(path)
        if not path.is_absolute() or ".." in path.parts:
            return "unsafe", None
        uid = os.getuid()
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        directory = os.open("/", flags | os.O_DIRECTORY)
        if not safe_directory(os.fstat(directory), uid):
            return "unsafe", None
        for component in path.parts[1:-1]:
            child = os.open(component, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
            if not safe_directory(os.fstat(directory), uid):
                return "unsafe", None
        fd = os.open(path.name, flags, dir_fd=directory)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
                or info.st_mode & 0o022 or info.st_nlink != 1):
            return "unsafe", None
        if info.st_size > MAX_INPUT:
            return "too_large", None
        if not literal:
            return "unsupported_format", None
        with os.fdopen(fd, "rb", closefd=False) as stream:
            body = stream.read(MAX_INPUT + 1)
        return parse_literal(body)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return "absent", None
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            return "unsafe", None
        return "unreadable", None
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def literal_string(value):
    return type(value) is str and bool(value)


def observe_auth(value, flags, ambiguity):
    """Aggregate declared mechanisms, not provider identity, validity or chosen auth."""
    for entry in value.values():
        if type(entry) is not dict:
            flags["unsupported"] = True
            continue
        kind = entry.get("type")
        if kind == "api" and literal_string(entry.get("key")):
            flags["api_key"] = True
            if entry.get("metadata"):
                ambiguity["endpoint"] = "potential"
        elif (kind == "oauth" and literal_string(entry.get("access"))
              and literal_string(entry.get("refresh")) and type(entry.get("expires")) is int
              and entry["expires"] >= 0):
            flags["oauth"] = True
        elif (kind == "wellknown" and literal_string(entry.get("key"))
              and literal_string(entry.get("token"))):
            flags["wellknown_remote"] = True
        else:
            flags["unsupported"] = True


def observe_config(value, flags, ambiguity):
    """Look only at declarations; no merge, provider/SDK execution or URL construction."""
    providers = value.get("provider", {})
    if type(providers) is not dict:
        flags["unsupported"] = True
        return
    if value.get("model") is not None or value.get("small_model") is not None:
        ambiguity["model"] = "potential"
    for provider in providers.values():
        if type(provider) is not dict or type(provider.get("options", {})) is not dict:
            flags["unsupported"] = True
            continue
        options = provider.get("options", {})
        if "apiKey" in options:
            flags["api_key"] |= literal_string(options["apiKey"])
            flags["unsupported"] |= not literal_string(options["apiKey"])
        if "tokenProvider" in options:
            flags["token_provider_declaration"] = True
            flags["unsupported"] = True  # A JSON declaration is not a callable.
        headers = options.get("headers", {})
        if type(headers) is dict:
            flags["bearer_header"] |= any(
                name.lower() == "authorization" and type(item) is str
                and item.lower().startswith("bearer ") and bool(item[7:].strip())
                for name, item in headers.items())
        elif headers is not None:
            flags["unsupported"] = True
        # Deliberately coarse: declarations may interact with uninspected
        # sources/model-level overrides. Never assert an effective winner.
        if "api" in provider or any(key in options for key in ("baseURL", "resourceName")):
            ambiguity["endpoint"] = "potential"
        if "models" in provider:
            ambiguity.update(endpoint="potential", model="potential")


def collect(environment, read_source):
    """Injected mappings/readers for tests. No ambient inputs or default reader here."""
    report = empty_report()
    flags = report["environment"] = environment_categories(environment)
    sources = report["sources"]
    auth = report["authentication_observed"]
    ambiguity = report["ambiguity"]
    config_count = 0
    for source, name in (("inline_config", "OPENCODE_CONFIG_CONTENT"),
                         ("inline_auth", "OPENCODE_AUTH_CONTENT")):
        sources[source], value = parse_literal(environment[name]) if name in environment else ("absent", None)
        if value is not None:
            if source == "inline_config":
                config_count += 1
                observe_config(value, auth, ambiguity)
            else:
                observe_auth(value, auth, ambiguity)
    # Do not inspect either default tree if a directory/path override is present.
    # This is a conservative diagnostic rule, NOT OpenCode precedence semantics.
    path_override = flags["xdg_directory"] or flags["xdg_unknown"] or flags["opencode_config_path"]
    for source in SOURCE_FIELDS[2:]:
        if path_override or source == "default_auth" and flags["opencode_auth_content"]:
            sources[source] = "uninspected_override"
            continue
        sources[source], value = read_source(source)
        if value is not None:
            if source == "default_auth":
                observe_auth(value, auth, ambiguity)
            else:
                config_count += 1
                observe_config(value, auth, ambiguity)
    if (path_override or config_count > 1 or auth["wellknown_remote"]
            or flags["azure_resource"] or flags["azure_other"]):
        ambiguity.update(endpoint="potential", model="potential")
    if flags["azure_auth"]:
        # Presence alone does not establish a nonempty API key or effective auth.
        ambiguity["endpoint"] = "potential"
    report["status"] = "complete"
    return project_report(report)


def operator_report():
    """HUMAN ONLY; never invoke from an agent. No arguments or input-selected paths."""
    if os.getuid() != 1000 or os.getgid() != 1000:
        return empty_report()
    paths = {
        "global_json": ("/home/kemal/.config/opencode/config.json", True),
        "global_named_json": ("/home/kemal/.config/opencode/opencode.json", True),
        "global_jsonc": ("/home/kemal/.config/opencode/opencode.jsonc", False),
        "global_legacy": ("/home/kemal/.config/opencode/config", False),
        "default_auth": ("/home/kemal/.local/share/opencode/auth.json", True),
    }

    def read_source(source):
        path, literal = paths[source]
        return read_fixed_file(path, literal=literal)

    return collect(os.environ, read_source)


def main():
    # No argparse error/help path can echo attacker-controlled command arguments.
    try:
        value = operator_report() if len(sys.argv) == 1 else empty_report()
        output = render_report(value)
    except BaseException:
        output = render_report(empty_report())
    print(output)
    return 0 if json.loads(output)["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
