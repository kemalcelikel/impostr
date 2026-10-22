"""Deterministic public synthetic PDFs for native input; no parser or external assets.

Reuse the useful IMP-017 PDF construction bytes, not its extraction/channel fixtures.
"""


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
