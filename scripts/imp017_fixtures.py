"""Deterministic owned synthetic PDFs. No parser invocation, OCR or external assets.

Generate large/expansion fixtures lazily during coordinator runtime verification,
not checked-in 50MB binaries. Object-stream fixture has active escaped names in
compressed objects and an xref stream, not just raw /JavaScript string matches.
"""

import json
import os
import stat
import struct
import zlib


CLIENT_PREFIX = "imp017-client-failure:"
CLIENT_FIXTURES = frozenset({"unknown", "initialization", "valid", "mixed", "scanned",
    "zero", "punctuation", "spoof", "malformed", "escaped_action", "compressed_action",
    "embedded", "xfa", "richmedia", "external", "page_limit", "decimal50MB", "expansion",
    "encrypted", "busy-short-body", "counted-overrun", "deadline-trigger", "deadline-recovery",
    "restart-readiness"})
CLIENT_STAGES = frozenset({"unknown", "imports", "fixture-build", "fixture-read", "extract",
    "status-check", "text-check", "size-check", "channel-connect", "channel-send",
    "channel-receive", "channel-shutdown", "deadline-eof", "listener-check"})
CLIENT_ERRORS = frozenset({"client-unknown", "assertion", "pdf-error", "timeout", "os-error",
    "connection-error"})
CLIENT_STATUSES = frozenset({"unknown", "ready", "rejected", "accepted"})
CLIENT_CODES = frozenset({"unknown", "busy", "invalid", "encrypted", "active_content",
    "no_text", "limit", "timeout", "unavailable"})
CLIENT_PASSES = ("representative-rejections: PASS", "decimal50MB: PASS", "expansion: PASS",
    "encrypted: PASS", "busy-short-body-recovery: PASS", "counted-overrun-recovery: PASS")


def fixed(value, allowed, fallback="unknown"):
    return value if type(value) is str and value in allowed else fallback


def client_record(fixture="unknown", stage="unknown", error="client-unknown", value=None, code="unknown"):
    """Project fixed fields only; never serialize a PDF result or exception."""
    status = "unknown"
    if type(value) is dict:
        status = fixed(value.get("status"), CLIENT_STATUSES)
        if status == "rejected":
            code = value.get("code")
    detail = {"fixture": fixed(fixture, CLIENT_FIXTURES), "stage": fixed(stage, CLIENT_STAGES),
        "error": fixed(error, CLIENT_ERRORS, "client-unknown"), "status": status,
        "code": fixed(code, CLIENT_CODES)}
    return CLIENT_PREFIX + json.dumps(detail, separators=(",", ":")) + "\n"


def client_error_record(exc, fixture, stage, value=None, pdf_error=()):
    """Exception TYPE and fixed PDFError.code only; never format the exception."""
    error, code = "client-unknown", "unknown"
    if isinstance(exc, AssertionError):
        error = "assertion"
    elif isinstance(exc, pdf_error):
        error, code = "pdf-error", exc.code
    elif isinstance(exc, TimeoutError):
        error = "timeout"
    elif isinstance(exc, ConnectionError):
        error = "connection-error"
    elif isinstance(exc, OSError):
        error = "os-error"
    return client_record(fixture, stage, error, value, code)


def client_projection(output):
    """Strictly consume existing captured stdout, not stderr or another runtime call.

    Only a canonical terminal record after an exact prefix of known PASS lines is
    trusted. Extra keys, unknown enums, duplicate keys and trailing data fail closed.
    """
    unknown = {"fixture": "unknown", "stage": "unknown", "error": "client-unknown",
        "status": "unknown", "code": "unknown"}
    if type(output) is not bytes or len(output) > 1024:
        return unknown, ()
    try:
        lines = output.decode("ascii").splitlines(keepends=True)
        if not lines or lines[:-1] != [line + "\n" for line in CLIENT_PASSES[:len(lines)-1]]:
            return unknown, ()
        record = lines[-1]
        if not record.startswith(CLIENT_PREFIX):
            return unknown, ()
        detail = json.loads(record[len(CLIENT_PREFIX):])
        if type(detail) is not dict or set(detail) != set(unknown):
            return unknown, ()
        for key, allowed in (("fixture", CLIENT_FIXTURES), ("stage", CLIENT_STAGES),
                ("error", CLIENT_ERRORS), ("status", CLIENT_STATUSES), ("code", CLIENT_CODES)):
            if type(detail[key]) is not str or detail[key] not in allowed:
                return unknown, ()
        canonical = client_record(detail["fixture"], detail["stage"], detail["error"],
            {"status": detail["status"], "code": detail["code"]}, detail["code"])
        return (detail, CLIENT_PASSES[:len(lines)-1]) if record == canonical else (unknown, ())
    except (UnicodeError, ValueError, RecursionError):
        return unknown, ()


def client_detail(output):
    return client_projection(output)[0]


def channel_stat():
    """Exact existing channel metadata; coordinator-image fixture only."""
    from app.pdf_protocol import API_UID, EXTRACTOR_UID, SOCKET_PATH, require
    directory = os.lstat(os.path.dirname(SOCKET_PATH))
    require(stat.S_ISDIR(directory.st_mode) and directory.st_uid == EXTRACTOR_UID
        and stat.S_IMODE(directory.st_mode) == 0o711, "unavailable")
    info = os.lstat(SOCKET_PATH)
    require(stat.S_ISSOCK(info.st_mode) and info.st_uid == EXTRACTOR_UID
        and info.st_gid == API_UID and stat.S_IMODE(info.st_mode) == 0o660, "unavailable")
    return info


def socket_identity(info):
    return info.st_dev, info.st_ino


def stream(data, extra=b""):
    return b"<< /Length " + str(len(data)).encode() + b" " + extra + b">>\nstream\n" + data + b"\nendstream"


def document(objects, trailer=b"", pad=0):
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    if pad:
        # Valid inert comments before xref, not junk trailing EOF or stream abuse.
        while pad:
            size = min(pad, 4096)
            output.extend(b"%" + b"x" * (size - 2) + b"\n" if size >= 2 else b"\n")
            pad -= size
    xref = len(output)
    output.extend(b"xref\n0 " + str(len(offsets)).encode() + b"\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(b"trailer\n<< /Size " + str(len(offsets)).encode()
        + b" /Root 1 0 R " + trailer + b">>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n")
    return bytes(output)


def text_pdf(texts=(b"Synthetic PDF reference 017",), catalog=b"", extra=(), pad=0):
    kids = b" ".join(f"{4 + index * 2} 0 R".encode() for index in range(len(texts)))
    objects = [b"<< /Type /Catalog /Pages 2 0 R " + catalog + b">>",
        b"<< /Type /Pages /Count " + str(len(texts)).encode() + b" /Kids [" + kids + b"] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    for index, text in enumerate(texts):
        number = 4 + index * 2
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
            + str(number + 1).encode() + b" 0 R >>")
        literal = text.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        content = b"BT /F1 12 Tf 72 720 Td (" + literal + b") Tj ET" if text else b""
        objects.append(stream(content))
    objects.extend(extra)
    return document(objects, pad=pad)


def compressed_active():
    # Objects1/2/3/6 compressed into7. Font4 and content5 remain ordinary streams.
    members = [(1, b"<< /Type /Catalog /Pages 2 0 R /Open#41ction 6 0 R >>"),
        (2, b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>"),
        (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
             b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"),
        (6, br"<< /S /Java#53cript /J#53 (app.alert\(1\)) >>")]
    bodies = bytearray()
    header = bytearray()
    for number, obj in members:
        header.extend(f"{number} {len(bodies)} ".encode())
        bodies.extend(obj + b"\n")
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    values = [(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        (5, stream(b"BT /F1 12 Tf 72 720 Td (Compressed active fixture) Tj ET")),
        (7, stream(zlib.compress(header + bodies), b"/Type /ObjStm /N 4 /First "
                   + str(len(header)).encode() + b" /Filter /FlateDecode "))]
    for number, value in values:
        offsets[number] = len(output)
        output.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    offsets[8] = len(output)
    compressed = {number: index for index, (number, _) in enumerate(members)}
    entries = bytearray()
    for number in range(9):
        if number == 0:
            entries.extend(struct.pack("!BIH", 0, 0, 65535))
        elif number in compressed:
            entries.extend(struct.pack("!BIH", 2, 7, compressed[number]))
        else:
            entries.extend(struct.pack("!BIH", 1, offsets[number], 0))
    output.extend(b"8 0 obj\n" + stream(bytes(entries),
        b"/Type /XRef /Size 9 /W [1 4 2] /Root 1 0 R ") + b"\nendobj\nstartxref\n"
        + str(offsets[8]).encode() + b"\n%%EOF\n")
    return bytes(output)


def near_cap():
    # A genuine one-page text + referenced raster PDF, not 50MB of trailing junk
    # or comments alone. No claim that the raster was interpreted by extraction.
    width, height = 10_000, 4_999
    image = b"\x80" * (width * height)
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [4 0 R] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 3 0 R >> /XObject << /Im1 6 0 R >> >> /Contents 5 0 R >>",
        stream(b"q 500 0 0 500 50 50 cm /Im1 Do Q\n"
               b"BT /F1 12 Tf 72 720 Td (Synthetic PDF reference 017) Tj ET"),
        stream(image, b"/Type /XObject /Subtype /Image /Width 10000 /Height 4999 "
                      b"/ColorSpace /DeviceGray /BitsPerComponent 8 ")]
    del image
    # Only ~9KB valid inert comments adjust exact decimal cap/xref digit length.
    pad = 50_000_000 - len(document(objects))
    for _ in range(3):
        value = document(objects, pad=pad)
        pad += 50_000_000 - len(value)
    return document(objects, pad=pad)


def expansion():
    # Bounded, ordinary layout: 32 pages of 48 non-overlapping visible lines.
    # The old 100,000 overprints at one coordinate exercised pathological layout,
    # not reliable output growth. These <1MB Flate streams contain >128KiB text
    # without duplicate glyph positions, excessive page count or huge page geometry.
    count = 32
    line = b"Expansion reference 017 " * 4
    content = b"BT /F1 8 Tf 36 756 Td 14 TL\n" + (b"(" + line + b") Tj T*\n") * 48 + b"ET\n"
    compressed = zlib.compress(content)
    kids = b" ".join(f"{4 + index * 2} 0 R".encode() for index in range(count))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 32 /Kids [" + kids + b"] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"]
    for index in range(count):
        number = 4 + index * 2
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
            + str(number + 1).encode() + b" 0 R >>")
        objects.append(stream(compressed, b"/Filter /FlateDecode "))
    return document(objects)


def raster_pdf(mixed=False):
    texts = (b"Readable first page", b"", b"Readable third page") if mixed else (b"",)
    kids = b" ".join(f"{4 + index * 2} 0 R".encode() for index in range(len(texts)))
    image_number = 4 + len(texts) * 2
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count " + str(len(texts)).encode() + b" /Kids [" + kids + b"] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for index, text in enumerate(texts):
        number = 4 + index * 2
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> /XObject << /Im1 "
            + str(image_number).encode() + b" 0 R >> >> /Contents "
            + str(number + 1).encode() + b" 0 R >>")
        content = b"q 500 0 0 500 50 50 cm /Im1 Do Q"
        if text:
            content += b"\nBT /F1 12 Tf 72 720 Td (" + text + b") Tj ET"
        objects.append(stream(content))
    objects.append(stream(b"\x00\xff\xff\x00", b"/Type /XObject /Subtype /Image /Width 2 /Height 2 "
        b"/ColorSpace /DeviceGray /BitsPerComponent 8 "))
    return document(objects)


def fixtures():
    """Small fixtures only. Real encryption/near-cap/expansion generated later."""
    return {
        "valid": text_pdf(),
        "mixed": raster_pdf(mixed=True),
        "scanned": raster_pdf(),
        "zero": text_pdf((b"",)),
        "punctuation": text_pdf((b"... !!!",)),
        "spoof": b"Not a PDF, even with an application/pdf Content-Type",
        "malformed": text_pdf().replace(b"startxref\n", b"startxref\n999999999"),
        "escaped_action": text_pdf(catalog=b"/Open#41ction << /S /Java#53cript /J#53 (alert) >>"),
        "compressed_action": compressed_active(),
        "embedded": text_pdf(extra=(b"<< /Type /EmbeddedFile >>",)),
        "xfa": text_pdf(catalog=b"/AcroForm << /XFA (synthetic) >>"),
        "richmedia": text_pdf(extra=(b"<< /Subtype /RichMedia >>",)),
        "external": text_pdf(extra=(stream(b"", b"/F (https://invalid.example/no-fetch) "),)),
        "page_limit": text_pdf(tuple(b"Page" for _ in range(501))),
    }
