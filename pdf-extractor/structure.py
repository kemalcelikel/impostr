"""Inspect ALL qpdf-v2 objects, including unreferenced/object-stream dictionaries.

qpdf 11.3 emits canonical names: /Java#53cript in a PDF becomes /JavaScript
here; do not double-unescape canonical '#' characters. String prefixes are NOT
names/references. Unsupported newer n:/ syntax fails closed, not guessed.
"""

import re

from bounded_json import MAX_DEPTH, parse
from pdf_protocol import MAX_PAGES, require

MAX_OBJECTS = 10_000
REFERENCE = re.compile(r"([1-9][0-9]{0,9}) (0|[1-9][0-9]{0,4}) R\Z")
DENIED_KEYS = frozenset({"/A", "/AA", "/OpenAction", "/JS", "/JavaScript",
    "/EmbeddedFiles", "/EF", "/AF", "/XFA", "/RichMediaContent", "/RichMediaSettings",
    "/Launch", "/URI", "/SubmitForm", "/ImportData", "/GoToR", "/GoToE", "/Encrypt",
    "/Collection", "/SpiderInfo", "/OPI", "/Ref"})
DENIED_NAMES = frozenset({"/Action", "/JavaScript", "/EmbeddedFile", "/Filespec", "/RichMedia",
    "/Movie", "/Sound", "/Screen", "/3D", "/Rendition", "/Launch", "/URI", "/GoToR",
    "/GoToE", "/SubmitForm", "/ImportData", "/SetOCGState", "/Hide", "/Trans",
    "/GoTo", "/Named", "/ResetForm", "/Thread", "/Crypt"})


def pages(data: bytes) -> int:
    value = parse(data)
    require(isinstance(value, dict) and value.get("version") == 2)
    require(isinstance(value.get("encrypt"), dict))
    require(value["encrypt"].get("encrypted") is False, "encrypted")
    qpdf = value.get("qpdf")
    require(isinstance(qpdf, list) and len(qpdf) == 2)
    header, raw = qpdf
    require(isinstance(header, dict) and header.get("jsonversion") == 2)
    require(header.get("calledgetallpages") is False
            and header.get("pushedinheritedpageresources") is False)
    require(isinstance(raw, dict) and "trailer" in raw and len(raw) <= MAX_OBJECTS + 1, "limit")
    objects = {}
    streams = set()
    for key, wrapper in raw.items():
        require(key == "trailer" or (key.startswith("obj:") and REFERENCE.fullmatch(key[4:])))
        require(isinstance(wrapper, dict))
        if set(wrapper) == {"value"}:
            objects[key] = wrapper["value"]
        else:
            require(set(wrapper) == {"stream"} and key != "trailer")
            require(isinstance(wrapper["stream"], dict) and set(wrapper["stream"]) == {"dict"})
            require(isinstance(wrapper["stream"]["dict"], dict))
            objects[key] = wrapper["stream"]["dict"]
            streams.add(key)

    def resolve(item):
        seen = set()
        while isinstance(item, str) and REFERENCE.fullmatch(item):
            key = "obj:" + item
            require(key in objects and key not in seen and len(seen) < MAX_DEPTH)
            require(key not in streams)
            seen.add(key)
            item = objects[key]
        return item

    def inspect(item, depth=0):
        require(depth <= MAX_DEPTH, "limit")
        if isinstance(item, dict):
            for key, child in item.items():
                require(key.startswith("/"))
                require(key not in DENIED_KEYS, "active_content")
                inspect(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                inspect(child, depth + 1)
        elif isinstance(item, str):
            if REFERENCE.fullmatch(item):
                # All target dictionaries are inspected separately; allow stream refs.
                require("obj:" + item in objects)
            elif item.startswith("/"):
                require(item not in DENIED_NAMES, "active_content")
            else:
                require(item.startswith("u:") or (item.startswith("b:")
                    and re.fullmatch(r"(?:[0-9a-fA-F]{2})*", item[2:])))

    for key, item in objects.items():
        inspect(item)
        if key in streams:
            require(not any(name in item for name in ("/F", "/FFilter", "/FDecodeParms")),
                    "active_content")
        if isinstance(item, dict) and "/S" in item:
            require(resolve(item["/S"]) not in DENIED_NAMES, "active_content")

    trailer = objects["trailer"]
    require(isinstance(trailer, dict))
    catalog = resolve(trailer.get("/Root"))
    require(isinstance(catalog, dict) and resolve(catalog.get("/Type")) == "/Catalog")
    root = catalog.get("/Pages")
    visited = set()

    def tree(reference, parent=None, depth=0):
        require(isinstance(reference, str) and REFERENCE.fullmatch(reference))
        require(reference not in visited and depth <= MAX_DEPTH, "limit")
        visited.add(reference)
        require(len(visited) <= MAX_OBJECTS, "limit")
        node = resolve(reference)
        require(isinstance(node, dict))
        if parent is None:
            require("/Parent" not in node)
        else:
            require(node.get("/Parent") == parent)
        kind = resolve(node.get("/Type"))
        if kind == "/Page":
            require(parent is not None and "/Kids" not in node)
            return 1
        require(kind == "/Pages")
        kids = resolve(node.get("/Kids"))
        require(isinstance(kids, list) and 0 < len(kids) <= MAX_PAGES, "limit")
        count = 0
        for child in kids:
            count += tree(child, reference, depth + 1)
            require(count <= MAX_PAGES, "limit")
        claimed = resolve(node.get("/Count"))
        require(type(claimed) is int and claimed == count)
        return count

    count = tree(root)
    # Do not accept disconnected page objects or a second catalog/page tree.
    for key, item in objects.items():
        if isinstance(item, dict):
            kind = resolve(item.get("/Type"))
            if kind in ("/Page", "/Pages"):
                require(key.startswith("obj:") and key[4:] in visited)
            if kind == "/Catalog":
                require(item is catalog)
    return count
