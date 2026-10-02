"""Fresh confined job driver. Never invoke directly on the host/API.

Only immutable fixed parser commands and job-cwd input.pdf; no CLI or wire options.
"""

import hashlib
import os
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, "/worker")
from bounded_json import MAX_JSON
from pdf_protocol import (JOB_SECONDS, LABEL, MAX_ORIGINAL, MAX_TEXT, PDFError,
    POLICY, coverage, encode, rejected, require)
from process import run
from structure import pages


def convert(deadline):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CPU, (JOB_SECONDS, JOB_SECONDS))
    digest = hashlib.sha256()
    size = 0
    with open("input.pdf", "xb") as output:
        while True:
            require(time.monotonic() < deadline, "timeout")
            block = sys.stdin.buffer.read(65536)
            if not block:
                break
            size += len(block)
            require(size <= MAX_ORIGINAL, "limit")
            digest.update(block)
            output.write(block)
    require(size > 0)
    original = "input.pdf"
    raw, diagnostics = run(["/usr/bin/qpdf", "--suppress-recovery", "--json=2",
        "--json-key=qpdf", "--json-key=encrypt", "--json-stream-data=none",
        "--decode-level=none", original], deadline, MAX_JSON)
    require(not diagnostics)  # No warnings (exit 3), quiet repair, or diagnostic success.
    count = pages(raw)
    _, diagnostics = run(["/usr/bin/qpdf", "--suppress-recovery", "--check", original], deadline, 8192)
    require(not diagnostics)
    raw, diagnostics = run(["/usr/bin/pdftotext", "-enc", "UTF-8", "-eol", "unix",
        original, "-"], deadline, MAX_TEXT)
    require(not diagnostics)
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise PDFError() from exc
    missing = coverage(text, count)
    return {"v": 1, "status": "ready", "size": size, "sha256": digest.hexdigest(),
        "text": text, "text_sha256": hashlib.sha256(raw).hexdigest(), "pages": count,
        "missing_pages": missing, "label": LABEL, "provenance": {
            "policy": POLICY, "qpdf": "11.3.0", "pdftotext": "22.12.0",
            "build_sha256": hashlib.sha256(Path("/worker/build.json").read_bytes()).hexdigest()}}


def main():
    os.umask(0o077)
    try:
        value = convert(time.monotonic() + JOB_SECONDS)
    except PDFError as exc:
        value = rejected(exc.code)
    except Exception:
        value = rejected("invalid")
    sys.stdout.buffer.write(encode(value))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
