"""Trusted HOST ONLY transport; never mount this module/config/auth in a worker.

The private resolver is for a reviewed operator invocation ONLY. It deliberately
supports a narrow literal global JSON Azure/API-key setup, not the OpenCode config
loader (which can execute plugins, fetch remote config and expand arbitrary files).
Unsupported/ambiguous existing setup is a capability stop, not a fallback.
Public interface references: OpenCode v1.18.34 provider/provider.ts, auth/index.ts,
core/src/global.ts; bundled @ai-sdk/azure 3.0.93 dist/index.js.
"""

import errno
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import threading
import time
from urllib.parse import urlencode, urlsplit

from imp002_relay import Denied, IO_TIMEOUT, MAX_REQUEST, MAX_RESPONSE, MODEL, decode
from imp002_diagnostic import has_expansion, safe_directory

CA_FILE = "/etc/ssl/certs/ca-certificates.crt"
TARGET = "gpt-6.1-sol"  # OpenCode model selector, NOT an assumed deployment ID.
MAX_PRIVATE_FILE = 256 * 1024
MAX_FRAME = 16384
INSPECTION_REASONS = frozenset({
    "configuration_unsupported", "model_unsupported", "environment_override",
    "file_unavailable", "file_permissions", "file_parse",
    "runtime_mismatch", "runtime_unavailable", "unknown",
})
INSPECTION_FILE_DETAILS = frozenset({
    "directory_ownership", "directory_write_mode", "file_ownership",
    "file_write_mode", "file_type", "file_hardlinks", "access_denied",
    "symlink_or_not_directory",
})
INSPECTION_FILE_SOURCES = frozenset({"config", "auth"})
# OpenCode v1.18.34 core/src/global.ts consumes xdg-basedir 5.1.0 paths;
# that dependency's index.js reads these directory variables, not session metadata.
# Only config/data select inputs for this host-only resolver. Global's cache/state
# and xdg-basedir's runtime/search exports are NOT config/auth search paths.
XDG_DIRECTORY_OVERRIDES = frozenset({
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR", "XDG_CONFIG_DIRS", "XDG_DATA_DIRS",
})
XDG_SESSION_METADATA = frozenset({
    "XDG_SESSION_ID", "XDG_SESSION_TYPE", "XDG_SESSION_CLASS", "XDG_SESSION_DESKTOP",
    "XDG_CURRENT_DESKTOP", "XDG_SEAT", "XDG_VTNR",
})
AZURE_RESOURCE_INPUTS = frozenset({"AZURE_RESOURCE_NAME"})
DEFAULT_HOME = "/home/kemal"
GLOBAL_FILES = ("config.json", "opencode.json", "opencode.jsonc")


class Unavailable(RuntimeError):
    """Never render chained exceptions: they may contain endpoint/auth/body data."""

    def __init__(self, message, *, reason="unknown", detail=None):
        super().__init__(message)
        self.reason = reason if type(reason) is str and reason in INSPECTION_REASONS else "unknown"
        self.detail = detail if type(detail) is str and detail in INSPECTION_FILE_DETAILS else None
        self.source = None


def inspection_reason(exc):
    """Operator-inspect ONLY: no message, exception class, or private detail output."""
    reason = exc.reason if isinstance(exc, Unavailable) else None
    return reason if type(reason) is str and reason in INSPECTION_REASONS else "unknown"


def inspection_file_details(exc):
    """Operator-inspect ONLY: recheck fixed enums, including after mutation.

    Details apply solely to the existing reader's file_permissions failures. No
    paths, exception messages/classes/errno, metadata values or chained errors.
    """
    if inspection_reason(exc) != "file_permissions":
        return {}
    detail = getattr(exc, "detail", None)
    if type(detail) is not str or detail not in INSPECTION_FILE_DETAILS:
        return {}
    result = {"detail_code": detail}
    source = getattr(exc, "source", None)
    if type(source) is str and source in INSPECTION_FILE_SOURCES:
        result["source_category"] = source
    return result


class Contract:
    def __init__(self, endpoint, deployment, key):
        if not isinstance(endpoint, str) or any(ord(c) < 33 or ord(c) > 126 for c in endpoint):
            raise Unavailable("nonliteral HTTPS endpoint", reason="configuration_unsupported")
        parts = urlsplit(endpoint)
        if (parts.scheme != "https" or parts.port not in (None, 443) or parts.username
                or parts.password or parts.fragment or not parts.hostname
                or not re.fullmatch(r"[a-zA-Z0-9.-]+", parts.hostname)
                or "." not in parts.hostname or len(parts.hostname) > 253 or parts.hostname.endswith(".")):
            raise Unavailable("unsupported HTTPS endpoint", reason="configuration_unsupported")
        # Routes are constructed ONLY by the resolver, never by a worker.
        if not re.fullmatch(r"/openai/(?:v1/|deployments/[A-Za-z0-9._-]+/)responses", parts.path):
            raise Unavailable("unsupported inference route", reason="configuration_unsupported")
        if parts.query and not re.fullmatch(r"api-version=[A-Za-z0-9.-]{1,64}", parts.query):
            raise Unavailable("unsupported inference query", reason="configuration_unsupported")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", deployment):
            raise Unavailable("unsupported deployment", reason="model_unsupported")
        if (not isinstance(key, str) or not 8 <= len(key) <= 4096
                or not key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in key)):
            raise Unavailable("unsupported API credential", reason="configuration_unsupported")
        self.host = parts.hostname
        self.route = parts.path + ("?" + parts.query if parts.query else "")
        self.deployment = deployment
        self.key = key
        # No credential digest; this pins only the privately resolved contract.
        self.fingerprint = hashlib.sha256(json.dumps(
            [endpoint, deployment, "api-key", "Responses", False], separators=(",", ":")
        ).encode()).hexdigest()

    def __repr__(self):
        return "<private inference contract>"


def selected_path(value):
    """Pure validation of a selected directory, not reference/path expansion."""
    if (type(value) is not str or not value.startswith("/") or value.startswith("//")
            or len(value.encode("utf-8")) > 4096 or len(value.split("/")) > 64
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(part in (".", "..") for part in value.split("/"))):
        raise Unavailable("unsupported selected directory", reason="configuration_unsupported")
    return Path(value)


def private_json(path, *, missing_ok=False, literal=True):
    """Reviewed selected paths or synthetic fixtures ONLY; no referenced paths.

    NOFOLLOW/dirfd pin every ancestor before opening the bounded regular file.
    Never discover via exists(), follow links, write, or execute host config.
    """
    directory = fd = None
    try:
        path = selected_path(str(path))
        uid = os.getuid()
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        directory = os.open("/", flags | os.O_DIRECTORY)
        check_private_directory(os.fstat(directory), uid)
        for component in path.parts[1:-1]:
            child = os.open(component, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
            check_private_directory(os.fstat(directory), uid)
        fd = os.open(path.name, flags, dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise Unavailable("unsafe private file", reason="file_permissions", detail="file_type")
        if info.st_uid != uid:
            raise Unavailable("unsafe private file", reason="file_permissions", detail="file_ownership")
        if info.st_mode & 0o022:
            raise Unavailable("unsafe private file", reason="file_permissions", detail="file_write_mode")
        if info.st_nlink != 1:
            raise Unavailable("unsafe private file", reason="file_permissions", detail="file_hardlinks")
        if info.st_size > MAX_PRIVATE_FILE:
            raise Unavailable("unsupported private file", reason="file_unavailable")
        if not literal:
            raise Unavailable("legacy config unsupported", reason="configuration_unsupported")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            body = stream.read(MAX_PRIVATE_FILE + 1)
        if len(body) > MAX_PRIVATE_FILE:
            raise Unavailable("private file bound", reason="file_unavailable")
        try:
            value = decode(body)
        except Denied as exc:
            raise Unavailable("invalid private JSON", reason="file_parse") from exc
        if not isinstance(value, dict):
            raise Unavailable("unsupported private JSON", reason="configuration_unsupported")
        try:
            if has_expansion(value):
                raise Unavailable("nonliteral private JSON", reason="configuration_unsupported")
        except ValueError as exc:
            raise Unavailable("private JSON bound", reason="file_parse") from exc
        return value
    except OSError as exc:
        if missing_ok and exc.errno == errno.ENOENT:
            return None
        # ELOOP/ENOTDIR do not establish which component is a link. Do not stat,
        # readlink or retry without NOFOLLOW to refine this fixed category.
        detail = ("access_denied" if isinstance(exc, PermissionError)
                  or exc.errno in (errno.EACCES, errno.EPERM) else
                  "symlink_or_not_directory" if exc.errno in (errno.ELOOP, errno.ENOTDIR) else None)
        reason = "file_permissions" if detail else "file_unavailable"
        raise Unavailable("private file unavailable", reason=reason, detail=detail) from exc
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def check_private_directory(info, uid):
    """Keep the reviewed directory policy; classify only already-observed metadata."""
    if safe_directory(info, uid):
        return
    detail = ("symlink_or_not_directory" if not stat.S_ISDIR(info.st_mode) else
              "directory_ownership" if info.st_uid not in (0, uid) else "directory_write_mode")
    raise Unavailable("unsafe private directory", reason="file_permissions", detail=detail)


def provider_settings(config):
    """Validate nested object shapes before either credential selection or parsing."""
    if not isinstance(config, dict) or not isinstance(config.get("provider", {}), dict):
        raise Unavailable("unsupported config shape", reason="configuration_unsupported")
    provider = config.get("provider", {}).get("azure", {})
    if not isinstance(provider, dict) or not isinstance(provider.get("options", {}), dict):
        raise Unavailable("unsupported provider shape", reason="configuration_unsupported")
    return provider, provider.get("options", {})


def check_environment_names(environment):
    """Injected name-only policy; no values read (including unused XDG exports)."""
    for index, name in enumerate(environment):
        if index >= 4096 or type(name) is not str or len(name) > 256:
            raise Unavailable("environment bound", reason="environment_override")
        if (name.startswith("OPENCODE_")
                or name.startswith("AZURE_") and name not in AZURE_RESOURCE_INPUTS
                or name.startswith("XDG_") and name not in XDG_DIRECTORY_OVERRIDES | XDG_SESSION_METADATA):
            raise Unavailable("ambient provider/config override", reason="environment_override")


def check_operator_context():
    """Offline name-only guard; never read values, clear env or discover files."""
    if os.getuid() != 1000 or os.getgid() != 1000:
        raise Unavailable("unreviewed identity", reason="runtime_mismatch")
    check_environment_names(os.environ)


def selected_private_paths(environment):
    """xdg-basedir 5.1.0: nonempty XDG home exports win, empty ones use os.homedir().

    This pinned Linux host's default home is supported, not alternate HOME trees.
    Refuse drift when a fallback is needed instead of silently reading defaults.
    """
    config = environment.get("XDG_CONFIG_HOME")
    data = environment.get("XDG_DATA_HOME")
    if not config or not data:
        home = environment.get("HOME", DEFAULT_HOME)
        if home != DEFAULT_HOME:
            raise Unavailable("unreviewed home fallback", reason="environment_override")
    return (selected_path(config or DEFAULT_HOME + "/.config") / "opencode",
            selected_path(data or DEFAULT_HOME + "/.local/share") / "opencode")


def merge_literal(target, source):
    """Remeda 2.26.0 mergeDeep subset: recurse objects, replace arrays/scalars."""
    result = dict(target)
    for key, value in source.items():
        previous = result.get(key)
        result[key] = merge_literal(previous, value) if type(previous) is dict and type(value) is dict else value
    return result


def contract_from_inputs(environment, read_source):
    """Injected supported-source interpretation; tests use fake env/reader ONLY.

    Not OpenCode's effective account/project/plugin/managed configuration loader.
    The human resolver alone supplies ambient inputs and the reviewed reader.
    """
    check_environment_names(environment)
    config_dir, data_dir = selected_private_paths(environment)

    def read(path, source, **kwargs):
        try:
            return read_source(path, **kwargs)
        except Unavailable as exc:
            if inspection_reason(exc) == "file_permissions":
                # Category comes from the fixed call site, never a private path,
                # filename, JSON key or credential/auth mechanism.
                exc.source = source
            raise

    # Legacy TOML migration/import is unsupported, even alongside valid JSON.
    if read(config_dir / "config", "config", missing_ok=True, literal=False) is not None:
        raise Unavailable("legacy config unsupported", reason="configuration_unsupported")
    config = {}
    for name in GLOBAL_FILES:
        value = read(config_dir / name, "config", missing_ok=True)
        if value is None:
            continue
        if has_expansion(value) or value.get("plugin"):
            raise Unavailable("unsupported global source", reason="configuration_unsupported")
        # Upstream parses each file BEFORE merging. Do not let a later valid
        # object conceal malformed earlier provider/list shapes in our subset.
        provider, _ = provider_settings(value)
        if (type(provider.get("models", {})) is not dict
                or type(value.get("disabled_providers", [])) is not list
                or "enabled_providers" in value and type(value["enabled_providers"]) is not list):
            raise Unavailable("unsupported global shape", reason="configuration_unsupported")
        config = merge_literal(config, value)
    # Azure custom loader consults stored auth metadata EVEN with a literal
    # options.apiKey. Read it to reject unsupported mechanisms/metadata, never
    # skip it and accidentally bind that key to the wrong resource.
    auth = read(data_dir / "auth.json", "auth", missing_ok=True) or {}
    if any(type(entry) is dict and entry.get("type") == "wellknown" for entry in auth.values()):
        raise Unavailable("remote auth config unsupported", reason="configuration_unsupported")
    return contract_from_settings(config, auth.get("azure"),
                                  resource_name=environment.get("AZURE_RESOURCE_NAME"))


def resolve_operator_contract():
    """OPERATOR ONLY, AFTER independent review + synthetic checks; no network.

    Bounded validated XDG-selected global config/API auth and AZURE_RESOURCE_NAME
    are supported. No cwd/project config, JSONC comments, env/file expansion,
    OAuth/token refresh, managed config, plugins, remote config or SDK execution.
    Paths/contents/errors are never returned to an agent or printed.
    """
    check_operator_context()
    # Copy only supported selected values, never dump/serialize the environment.
    environment = {name: os.environ[name] for name in
                   ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "AZURE_RESOURCE_NAME") if name in os.environ}
    return contract_from_inputs(environment, private_json)


def contract_from_settings(config, api_auth=None, *, resource_name=None):
    """Pure supported-subset interpretation; tests pass ONLY synthetic settings."""
    provider, options = provider_settings(config)
    if api_auth is not None:
        if (type(api_auth) is not dict or api_auth.get("type") != "api"
                or type(api_auth.get("key")) is not str
                or "metadata" in api_auth and type(api_auth["metadata"]) is not dict
                or api_auth.get("metadata")):
            raise Unavailable("existing auth mechanism/metadata unsupported", reason="configuration_unsupported")
    if (not isinstance(config.get("disabled_providers", []), list)
            or config.get("enabled_providers") is not None and not isinstance(config["enabled_providers"], list)):
        raise Unavailable("unsupported provider list shape", reason="configuration_unsupported")
    if config.get("plugin") or config.get("disabled_providers", []).count("azure"):
        raise Unavailable("provider modified/disabled", reason="configuration_unsupported")
    if config.get("enabled_providers") is not None and "azure" not in config["enabled_providers"]:
        raise Unavailable("provider disabled", reason="configuration_unsupported")
    if provider.get("npm", "@ai-sdk/azure") != "@ai-sdk/azure":
        raise Unavailable("unsupported provider", reason="configuration_unsupported")
    # Pinned OpenCode can use provider.api as the SDK base URL. This narrow
    # resolver does not implement that precedence; never silently select the
    # resourceName endpoint and send credentials to a different upstream.
    if "api" in provider:
        raise Unavailable("unsupported provider endpoint override", reason="configuration_unsupported")
    if "env" in provider:
        raise Unavailable("unsupported provider credential environment", reason="configuration_unsupported")
    allowed = {"baseURL", "resourceName", "apiKey", "apiVersion", "useDeploymentBasedUrls",
               "timeout", "headerTimeout", "chunkTimeout", "maxRetries"}
    if not isinstance(options, dict) or set(options) - allowed:
        raise Unavailable("unsupported provider options/auth/headers", reason="configuration_unsupported")
    models = provider.get("models", {})
    if not isinstance(models, dict):
        raise Unavailable("unsupported model shape", reason="model_unsupported")
    model = models.get(TARGET)
    if not isinstance(model, dict) or model.get("headers") or model.get("options") or model.get("provider"):
        raise Unavailable("unsupported model overrides", reason="model_unsupported")
    # OpenCode's model.api.id mapping is explicit; otherwise the selector itself
    # is the SDK's model ID. Do not assert which one the existing account uses.
    deployment = model.get("id", TARGET)
    if not isinstance(deployment, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", deployment):
        raise Unavailable("unsupported deployment", reason="model_unsupported")
    base = options.get("baseURL")
    # OpenCode resolveSDK treats an empty baseURL as catalog fallback; this
    # subset does not reinterpret malformed/empty endpoints as resource settings.
    if "baseURL" in options and (type(base) is not str or not base):
        raise Unavailable("unsupported base URL", reason="configuration_unsupported")
    if base is None:
        # Azure custom(): first nonblank config resource, then API metadata
        # (unsupported above), then AZURE_RESOURCE_NAME. No cognitive-services
        # env, SDK env secret, OAuth accountId or arbitrary AZURE_ fallback.
        resource = options.get("resourceName", resource_name)
        if not isinstance(resource, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,100}", resource):
            raise Unavailable("resource contract missing", reason="configuration_unsupported")
        # Source-defined SDK URL construction, not an invented host setting.
        base = f"https://{resource}.openai.azure.com/openai"
    if not isinstance(base, str) or "{" in base or "}" in base:
        raise Unavailable("nonliteral endpoint", reason="configuration_unsupported")
    parts = urlsplit(base)
    if parts.query or parts.fragment:
        raise Unavailable("base URL query/fragment", reason="configuration_unsupported")
    based = options.get("useDeploymentBasedUrls", False)
    if type(based) is not bool:
        raise Unavailable("deployment route setting", reason="configuration_unsupported")
    azure = bool(parts.hostname and parts.hostname.endswith(".openai.azure.com"))
    endpoint = base.rstrip("/") + (f"/deployments/{deployment}/responses" if based
                                  else "/v1/responses" if azure else "/responses")
    if azure or based:
        version = options.get("apiVersion", "v1")  # Pinned SDK default.
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", version):
            raise Unavailable("API version", reason="configuration_unsupported")
        endpoint += "?" + urlencode({"api-version": version})
    key = options.get("apiKey")
    if "apiKey" not in options:
        entry = api_auth
        if not isinstance(entry, dict) or entry.get("type") != "api":
            raise Unavailable("existing API credential missing/unsupported", reason="configuration_unsupported")
        key = entry.get("key")
    if not isinstance(key, str) or "{" in key:
        raise Unavailable("nonliteral API credential", reason="configuration_unsupported")
    return Contract(endpoint, deployment, key)


def resolve_addresses(host):
    """Bound DNS in a credential-free child; no endpoint in args/env/logs.

    Pin the returned PUBLIC address for dialing. No HTTP proxy or ambient CA env is
    consulted. A hung DNS child is killed/reaped by subprocess.run's timeout.
    """
    code = ("import json,socket,sys; h=sys.stdin.buffer.read(254).decode('ascii'); "
            "a=socket.getaddrinfo(h,443,type=socket.SOCK_STREAM); "
            "sys.stdout.write(json.dumps([[x[0],x[4][0]] for x in a[:16]]))")
    try:
        result = subprocess.run(["/usr/bin/python3", "-I", "-B", "-c", code],
                                input=host.encode("ascii"), capture_output=True,
                                timeout=IO_TIMEOUT, env={}, close_fds=True, check=True)
        if len(result.stdout) > 4096:
            raise Unavailable("DNS bound")
        values = decode(result.stdout)
        addresses = []
        for family, address in values:
            ip = ipaddress.ip_address(address)
            if (family not in (socket.AF_INET, socket.AF_INET6) or not ip.is_global
                    or ip.is_multicast or ip.is_reserved or ip.is_unspecified
                    or getattr(ip, "ipv4_mapped", None) is not None):
                raise Unavailable("nonpublic upstream address")
            addresses.append((family, address))
        if not addresses:
            raise Unavailable("no upstream address")
        return addresses
    except (OSError, ValueError, subprocess.SubprocessError, TypeError) as exc:
        raise Unavailable("DNS unavailable") from exc


class FixedHTTPS(http.client.HTTPSConnection):
    def __init__(self, contract, address, context):
        super().__init__(contract.host, 443, timeout=IO_TIMEOUT, context=context)
        self.address = address
        self.lock = threading.Lock()
        self.cancelled = False

    def connect(self):
        family, address = self.address
        raw = socket.socket(family, socket.SOCK_STREAM)
        raw.settimeout(IO_TIMEOUT)
        with self.lock:
            if self.cancelled:
                raw.close()
                raise Unavailable("cancelled")
            self.sock = raw
        try:
            raw.connect((address, 443))
            # Deferred handshake means cancellation can shut down the socket
            # during TLS negotiation as well as during headers/body.
            wrapped = self._context.wrap_socket(raw, server_hostname=self.host, do_handshake_on_connect=False)
            with self.lock:
                if self.cancelled:
                    wrapped.close()
                    raise Unavailable("cancelled")
                self.sock = wrapped
            wrapped.do_handshake()
        except BaseException:
            raw.close()
            self.abort()
            raise

    def abort(self):
        with self.lock:
            self.cancelled = True
            current = self.sock
            if current is not None:
                try:
                    current.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                current.close()


def native_event(name, fields):
    return ("event: " + name + "\ndata: " + json.dumps(dict(fields, type=name),
            ensure_ascii=True, separators=(",", ":")) + "\n\n").encode()


def response_items(text):
    part = {"type": "output_text", "text": text, "annotations": []}
    item = {"id": "msg_relay", "type": "message", "role": "assistant",
            "status": "completed", "content": [part]}
    response = {"id": "resp_relay", "object": "response", "created_at": 1,
                "model": MODEL, "status": "completed", "output": [item],
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}
    return part, item, response


class SecretFilter:
    """Hold a suffix so literal auth echoed across delta boundaries is redacted."""
    def __init__(self, key):
        self.key = key
        self.pending = ""

    def feed(self, text, final=False):
        self.pending = (self.pending + text).replace(self.key, "[redacted]")
        size = len(self.pending) if final else max(0, len(self.pending) - len(self.key) + 1)
        ready, self.pending = self.pending[:size], self.pending[size:]
        return ready


class HTTPSInference:
    """Fixed direct TLS, no redirects/retries/proxy/env/custom worker headers.

    Construct this only in the operator. Tests inject a controlled socket transport,
    never a real service. The relay supplies the cancellation event and hard deadline.
    """
    def __init__(self, contract):
        self.contract = contract
        self.address = resolve_addresses(contract.host)[0]
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_verify_locations(cafile=CA_FILE)

    def connection(self):
        return FixedHTTPS(self.contract, self.address, self.context)

    def events(self, data, cancelled, deadline):
        # validate() already denied worker tools/media/state. Always replace model
        # and enforce storage/output policy again at the credential boundary.
        from imp002_relay import ROUTE, validate
        data = validate("POST", ROUTE, json.dumps(data).encode())
        body = dict(data, model=self.contract.deployment, stream=True, store=False,
                    max_output_tokens=min(data.get("max_output_tokens", 256), 1024))
        body.pop("prompt_cache_key", None)
        encoded = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode()
        if len(encoded) > MAX_REQUEST:
            raise Unavailable("normalized request bound")
        connection = self.connection()
        response = None
        finished = threading.Event()

        def guard():
            while not finished.wait(0.025):
                if cancelled.is_set() or time.monotonic() >= deadline:
                    connection.abort()
                    return

        watcher = threading.Thread(target=guard, daemon=True)
        watcher.start()
        try:
            if cancelled.is_set() or time.monotonic() >= deadline:
                raise Unavailable("cancelled")
            connection.request("POST", self.contract.route, encoded, {
                "api-key": self.contract.key, "Content-Type": "application/json",
                "Accept": "text/event-stream", "Accept-Encoding": "identity", "Connection": "close"})
            response = connection.getresponse()
            if (response.status != 200 or response.getheader("Content-Type", "").split(";", 1)[0] != "text/event-stream"
                    or response.getheader("Content-Encoding", "identity") != "identity"
                    or sum(len(key) + len(value) for key, value in response.getheaders()) > 8192):
                # Never read/forward error body, Location, cookies or provider IDs.
                raise Unavailable("upstream rejected")
            yield from self.normalize(response, cancelled, deadline)
        except (OSError, ValueError, http.client.HTTPException, Denied) as exc:
            raise Unavailable("inference unavailable") from exc
        finally:
            finished.set()
            connection.abort()
            if response is not None:
                response.close()
            connection.close()
            watcher.join(IO_TIMEOUT + 1)
            if watcher.is_alive():
                raise Unavailable("transport cleanup failed")

    def normalize(self, response, cancelled, deadline):
        """Incremental bounded Responses SSE -> fresh text-only native SSE.

        No upstream headers, errors, IDs, annotations, metadata or reasoning are exposed.
        Incomplete/malformed/unsupported output never produces response.completed.
        """
        _, item, complete = response_items("")
        started = False
        buffer = bytearray()
        total = 0
        text = ""
        redactor = SecretFilter(self.contract.key)
        lifecycle = {"response.created", "response.in_progress", "response.output_item.added",
                     "response.output_item.done", "response.content_part.added", "response.content_part.done",
                     "response.output_text.done", "response.reasoning_summary_part.added",
                     "response.reasoning_summary_part.done", "response.reasoning_summary_text.delta",
                     "response.reasoning_summary_text.done", "response.reasoning_text.delta",
                     "response.reasoning_text.done"}
        while True:
            if cancelled.is_set() or time.monotonic() >= deadline:
                raise Unavailable("cancelled")
            block = response.read1(4096)
            if not block:
                raise Unavailable("truncated inference stream")
            total += len(block)
            if total > MAX_RESPONSE:
                raise Unavailable("upstream output bound")
            buffer.extend(block)
            # Native providers may use CRLF; bounded normalization handles split
            # delimiters without decoding partial UTF-8 chunks.
            buffer = bytearray(bytes(buffer).replace(b"\r\n", b"\n"))
            while b"\n\n" in buffer:
                frame, _, rest = buffer.partition(b"\n\n")
                buffer = bytearray(rest)
                if len(frame) > MAX_FRAME:
                    raise Unavailable("SSE frame bound")
                lines = frame.decode("utf-8").split("\n")
                fields = [line for line in lines if line and not line.startswith(":")]
                if not fields:
                    continue
                names = [line[7:] for line in fields if line.startswith("event: ")]
                payloads = [line[6:] for line in fields if line.startswith("data: ")]
                if len(names) > 1 or len(payloads) != 1 or len(fields) != len(names) + len(payloads):
                    raise Unavailable("unsupported SSE framing")
                event = decode(payloads[0])
                if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                    raise Unavailable("unsupported SSE event")
                name = event["type"]
                if names and names[0] != name:
                    raise Unavailable("SSE event mismatch")
                if name not in lifecycle | {"response.output_text.delta", "response.completed"}:
                    raise Unavailable("unsupported/incomplete inference")
                output = event.get("item")
                if output and (not isinstance(output, dict) or output.get("type") not in ("message", "reasoning")):
                    raise Unavailable("nontext output")
                if not started:
                    started = True
                    yield native_event("response.created", {"response": dict(complete, status="in_progress", output=[])})
                    yield native_event("response.output_item.added", {"output_index": 0, "item": dict(item, content=[])})
                    yield native_event("response.content_part.added", {"item_id": "msg_relay", "output_index": 0,
                        "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}})
                if name == "response.output_text.delta":
                    if (not isinstance(event.get("delta"), str) or event.get("output_index") not in (0, 1)
                            or event.get("content_index") != 0):
                        raise Unavailable("unsupported text delta")
                    delta = redactor.feed(event["delta"])
                    text += delta
                    if delta:
                        yield native_event("response.output_text.delta", {"item_id": "msg_relay", "output_index": 0,
                            "content_index": 0, "delta": delta})
                if name == "response.completed":
                    final = event.get("response")
                    if not isinstance(final, dict) or final.get("status") != "completed":
                        raise Unavailable("incomplete inference")
                    outputs = final.get("output")
                    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 2:
                        raise Unavailable("unsupported final output")
                    final_text = []
                    for value in outputs:
                        if not isinstance(value, dict) or value.get("type") not in ("message", "reasoning"):
                            raise Unavailable("nontext final output")
                        if value["type"] == "message":
                            if value.get("role") != "assistant" or not isinstance(value.get("content"), list):
                                raise Unavailable("final message")
                            for part in value["content"]:
                                if not isinstance(part, dict) or part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                                    raise Unavailable("nontext final content")
                                final_text.append(part["text"])
                    delta = redactor.feed("", final=True)
                    text += delta
                    if text != "".join(final_text).replace(self.contract.key, "[redacted]") or not text:
                        raise Unavailable("inconsistent final text")
                    if delta:
                        yield native_event("response.output_text.delta", {"item_id": "msg_relay", "output_index": 0,
                            "content_index": 0, "delta": delta})
                    part, item, complete = response_items(text)
                    yield native_event("response.output_text.done", {"item_id": "msg_relay", "output_index": 0,
                        "content_index": 0, "text": text})
                    yield native_event("response.content_part.done", {"item_id": "msg_relay", "output_index": 0,
                        "content_index": 0, "part": part})
                    yield native_event("response.output_item.done", {"output_index": 0, "item": item})
                    yield native_event("response.completed", {"response": complete})
                    return
            if len(buffer) > MAX_FRAME:
                raise Unavailable("SSE frame bound")


class SyntheticStream:
    """Credential/network-free native normalization for pinned worker proof."""
    def events(self, data, cancelled, deadline):
        import io
        from imp002_relay import stub_response
        inference = object.__new__(HTTPSInference)
        inference.contract = Contract("https://unit.example.invalid/openai/v1/responses",
                                      "synthetic-deployment", "synthetic-not-a-secret")
        # read1 is deliberately small, including split UTF-8/framing boundaries.
        class Parts(io.BytesIO):
            def read1(self, _):
                return self.read(127)
        yield from inference.normalize(Parts(stub_response()), cancelled, deadline)
