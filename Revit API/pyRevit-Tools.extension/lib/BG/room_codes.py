# -*- coding: utf-8 -*-
"""Read a B&G room-code workbook (.xlsx) into pick-list entries.

The workbook is opened as the zip it is and read with the standard
library only (zipfile + xml.etree), so Excel is never started and the
same code runs in IronPython 2.7 and CPython 3.  Sheet files are never
assumed to be sheetN in tab order: xl/workbook.xml names the sheets,
xl/_rels/workbook.xml.rels says which part holds each one.

WHY LABELS DIFFER FROM NAMES.  The pick list shows each room's B&G
name with its code after it, "Exam Room (03.60.110)".  Department and
group heading rows (codes ending 00) are in the list too, flagged as
headings so the window can show them in bold.  A name that repeats on one sheet ("Waiting Area" three times) also gets its
parent heading, "Waiting Area – Outpatient Clinic (03.60.160)".  The
label is only what the list shows; the room's Name is always the plain
name and its code is the code.

TWO NAMES PER CODE.  Where the header row's column C reads "NeevIQ Team
Input", that column is a second name for the same code, offered in the
window beside the B&G one.  A code with only a NeevIQ name still makes
an entry, labelled by that name.  Any other column C is ignored.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.
"""

import re
import zipfile
import posixpath
from collections import namedtuple
from xml.etree import ElementTree as ET

# name is the B&G name (column B), neev the NeevIQ one (column C);
# either may be None, never both.  heading is True for department
# (.000) and group heading (.x00) rows.
Entry = namedtuple("Entry", "label name code neev heading")

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RNS = ("{http://schemas.openxmlformats.org/officeDocument/2006/"
        "relationships}")
_CODE = re.compile(r"^\d{2}\.\d{2}\.\d{3}$")
_DASH = u" – "


def is_code(text):
    """True when the trimmed text looks like NN.NN.NNN."""
    return bool(text) and _CODE.match(text.strip()) is not None


def _text(value):
    """The trimmed text, or None when there is none."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _is_neev_header(text):
    text = (text or u"").lower()
    return u"neeviq" in text and u"input" in text


def parse_rows(rows):
    """Keep the (code, name, neev) rows from (column A, B[, C]) rows.

    Rows up to and including the first one whose A reads 'Codes' are
    skipped; with no such row nothing is skipped.  Column C is read
    only when that header row names it NeevIQ input; else neev is None.
    A row needs a code and at least one of the two names.
    """
    rows = [(tuple(r) + (None, None))[:3] for r in rows]
    start = 0
    use_c = False
    for i, (a, _b, c) in enumerate(rows):
        if a is not None and a.strip().lower() == u"codes":
            start = i + 1
            use_c = _is_neev_header(c)
            break
    out = []
    for a, b, c in rows[start:]:
        if a is None or not is_code(a):
            continue
        name = _text(b)
        neev = _text(c) if use_c else None
        if name or neev:
            out.append((a.strip(), name, neev))
    return out


def make_entries(rows):
    """Build Entry(label, name, code, neev, heading) for (code, name, neev)
    rows.

    Department (.000) and group heading (.x00) rows are entries with
    heading True, and also the parent a repeated name is told apart by:
    a room's parent is the nearest heading above it, a heading's the
    department.
    """
    dept = None
    group = None
    rows_out = []
    for code, name, neev in rows:
        shown = name or neev
        last = code.split(".")[-1]
        if last == "000":
            rows_out.append((code, name, neev, True, None))
            dept = shown
            group = None
        elif last.endswith("00"):
            rows_out.append((code, name, neev, True, dept))
            group = shown
        else:
            rows_out.append((code, name, neev, False,
                             group if group is not None else dept))
    counts = {}
    for _code, name, neev, _heading, _parent in rows_out:
        shown = name or neev
        counts[shown] = counts.get(shown, 0) + 1
    entries = []
    for code, name, neev, heading, parent in rows_out:
        base = name or neev
        if counts[base] > 1 and parent is not None and parent != base:
            base = base + _DASH + parent
        entries.append(Entry(base + u" (" + code + u")", name, code, neev,
                             heading))
    return entries


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
        got = {"A": None, "B": None, "C": None}
        for pos, cell in enumerate(row.findall(_NS + "c")):
            ref = cell.get("r")
            col = _column(ref) if ref else "ABC"[pos] if pos < 3 else ""
            if col in got:
                got[col] = _cell_value(cell, shared, col == "A")
        rows.append((got["A"], got["B"], got["C"]))
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
