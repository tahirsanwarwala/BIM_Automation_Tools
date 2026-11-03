# -*- coding: utf-8 -*-
"""Read a B&G room-code workbook (.xlsx) into pick-list entries.

The workbook is opened as the zip it is and read with the standard
library only (zipfile + xml.etree), so Excel is never started and the
same code runs in IronPython 2.7 and CPython 3.  Sheet files are never
assumed to be sheetN in tab order: xl/workbook.xml names the sheets,
xl/_rels/workbook.xml.rels says which part holds each one.

WHY LABELS DIFFER FROM NAMES.  The pick list shows the B&G name alone,
but some names repeat on one sheet ("Waiting Area" three times).  A
repeat is told apart by its parent heading, and if that is still not
enough the code is appended.  The label is only what the list shows;
the room's Name is always the plain name and its code is the code.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.
"""

import re
import zipfile
import posixpath
from collections import namedtuple
from xml.etree import ElementTree as ET

Entry = namedtuple("Entry", "label name code")

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RNS = ("{http://schemas.openxmlformats.org/officeDocument/2006/"
        "relationships}")
_CODE = re.compile(r"^\d{2}\.\d{2}\.\d{3}$")
_DASH = u" – "


def is_code(text):
    """True when the trimmed text looks like NN.NN.NNN."""
    return bool(text) and _CODE.match(text.strip()) is not None


def parse_rows(rows):
    """Keep the (code, name) rows from (column A, column B) pairs.

    Rows up to and including the first one whose A reads 'Codes' are
    skipped; with no such row nothing is skipped.
    """
    rows = list(rows)
    start = 0
    for i, (a, _b) in enumerate(rows):
        if a is not None and a.strip().lower() == u"codes":
            start = i + 1
            break
    out = []
    for a, b in rows[start:]:
        if a is None or b is None:
            continue
        if is_code(a) and b.strip():
            out.append((a.strip(), b.strip()))
    return out


def make_entries(pairs):
    """Build Entry(label, name, code) from (code, name) pairs."""
    pairs = list(pairs)
    dept = None
    heading = None
    parents = []
    for code, name in pairs:
        last = code.split(".")[-1]
        if last == "000":
            dept = name
            heading = None
            parents.append(None)
        elif last.endswith("00"):
            heading = name
            parents.append(dept)
        else:
            parents.append(heading if heading is not None else dept)
    counts = {}
    for _code, name in pairs:
        counts[name] = counts.get(name, 0) + 1
    labels = []
    for (code, name), parent in zip(pairs, parents):
        if counts[name] == 1 or parent is None:
            labels.append(name)
        else:
            labels.append(name + _DASH + parent)
    seen = {}
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
    return [Entry(label if seen[label] == 1
                  else label + u" (" + code + u")", name, code)
            for label, (code, name) in zip(labels, pairs)]


def resolve_label(entries, text):
    """The entry whose label equals the text, ignoring case and edge spaces."""
    want = text.strip().lower()
    for entry in entries:
        if entry.label.strip().lower() == want:
            return entry
    return None


def _all_text(node):
    return u"".join(t.text or u"" for t in node.iter(_NS + "t"))


def _shared_strings(zf):
    try:
        data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(data)
    return [_all_text(si) for si in root.iter(_NS + "si")]


def _column(ref):
    return re.match(r"[A-Za-z]*", ref).group(0).upper()


def _cell_value(cell, shared, is_a):
    kind = cell.get("t")
    v = cell.find(_NS + "v")
    vtext = v.text if v is not None else None
    if kind == "s":
        try:
            return shared[int(vtext)]
        except (TypeError, ValueError, IndexError):
            return None
    if kind == "inlineStr":
        node = cell.find(_NS + "is")
        return _all_text(node) if node is not None else None
    if kind == "str":
        return vtext
    return None if is_a else vtext


def _sheet_rows(data, shared):
    root = ET.fromstring(data)
    rows = []
    for row in root.iter(_NS + "row"):
        got = {"A": None, "B": None}
        for pos, cell in enumerate(row.findall(_NS + "c")):
            ref = cell.get("r")
            col = _column(ref) if ref else "AB"[pos] if pos < 2 else ""
            if col in got:
                got[col] = _cell_value(cell, shared, col == "A")
        rows.append((got["A"], got["B"]))
    return rows


def _sheet_parts(zf):
    """[(sheet_name, part_path)] in tab order."""
    rels = {}
    for rel in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels")):
        target = rel.get("Target") or u""
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join("xl", target))
        rels[rel.get("Id")] = path
    out = []
    book = ET.fromstring(zf.read("xl/workbook.xml"))
    for sheet in book.iter(_NS + "sheet"):
        path = rels.get(sheet.get(_RNS + "id"))
        if path:
            out.append((sheet.get("name") or u"", path))
    return out


def read_workbook(fileobj):
    """[(sheet_name, [Entry])] in tab order, minus Summary and empty sheets."""
    zf = zipfile.ZipFile(fileobj)
    shared = _shared_strings(zf)
    result = []
    for name, path in _sheet_parts(zf):
        if name.strip().lower() == u"summary":
            continue
        entries = make_entries(parse_rows(_sheet_rows(zf.read(path), shared)))
        if entries:
            result.append((name, entries))
    return result
