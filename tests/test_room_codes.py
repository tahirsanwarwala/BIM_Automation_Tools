# -*- coding: utf-8 -*-
"""Reading B&G room-code workbooks for Bulk Rooms."""

import io
import os
import sys
import unittest
import zipfile
from xml.sax.saxutils import escape

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import room_codes as rc

DASH = u"–"

DUP_SHEET = [("03.60.000", "Healthcare - Ambulatory"),      # title row
             ("Codes", "B&G Input"), (None, None),
             ("03.60.000", "Ambulatory & Outpatient Services"),
             ("03.60.100", "Outpatient Clinic"),
             ("03.60.160", "Waiting Area"),
             ("03.60.300", "Oncology / Infusion"),
             ("03.60.360", "Waiting Area"),
             ("03.30.800", "Imaging Support"),
             ("03.30.831", "PACS / Server Room"),
             ("03.30.840", "PACS / Server Room")]
NEEV = [("02.10.000", "Hospitality - PODIUM"),
        ("Codes", "B&G Input", "NeevIQ Team Input"),
        ("02.10.100", "Circulation", "Circulation Common"),
        ("02.10.110", "Corridor", " Corridor Common "),
        ("02.10.120", "Public Elevator", None),
        ("02.10.160", None, "Refuge Area"),
        ("02.10.170", " ", "")]
NICU = [("Codes", "B&G Input"),
        ("03.50.000", "Women & Children"), ("03.50.500", "NICU"),
        ("03.50.540", "NICU Family Room"), ("03.50.600", "NICU Family Room")]


def make_xlsx(sheets):
    """sheets: list of (name, rows). Part numbers are reversed vs tab order."""
    shared = []

    def sst(xml):
        shared.append(xml)
        return len(shared) - 1

    n = len(sheets)
    parts = {}
    for tab, (name, rows) in enumerate(sheets):
        out = []
        for r, row in enumerate(rows, 1):
            cells = []
            for c, v in enumerate(row):
                if v is None:
                    continue
                ref = "%s%d" % ("ABC"[c], r)
                if isinstance(v, str):
                    i = sst("<si><t>%s</t></si>" % escape(v))
                    cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, i))
                elif isinstance(v, tuple) and v[0] == "rich":
                    runs = "".join("<r><t>%s</t></r>" % escape(t) for t in v[1])
                    i = sst("<si>%s</si>" % runs)
                    cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, i))
                elif isinstance(v, tuple) and v[0] == "inline":
                    cells.append('<c r="%s" t="inlineStr"><is><t>%s</t></is></c>'
                                 % (ref, escape(v[1])))
                else:
                    cells.append('<c r="%s"><v>%s</v></c>' % (ref, v))
            out.append('<row r="%d">%s</row>' % (r, "".join(cells)))
        parts[n - tab] = (
            '<worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>'
            % "".join(out))
    wb = "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>'
                 % (escape(name, {'"': "&quot;"}), tab + 1, tab + 1)
                 for tab, (name, _r) in enumerate(sheets))
    rels = "".join('<Relationship Id="rId%d" Type="x" '
                   'Target="worksheets/sheet%d.xml"/>' % (tab + 1, n - tab)
                   for tab in range(n))
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w")
    z.writestr("xl/workbook.xml",
               '<workbook xmlns="http://schemas.openxmlformats.org/'
               'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats'
               '.org/officeDocument/2006/relationships"><sheets>%s</sheets>'
               '</workbook>' % wb)
    z.writestr("xl/_rels/workbook.xml.rels",
               '<Relationships xmlns="http://schemas.openxmlformats.org/'
               'package/2006/relationships">%s</Relationships>' % rels)
    z.writestr("xl/sharedStrings.xml",
               '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
               '2006/main">%s</sst>' % "".join(shared))
    for num, xml in parts.items():
        z.writestr("xl/worksheets/sheet%d.xml" % num, xml)
    z.close()
    buf.seek(0)
    return buf


def labels(rows):
    return dict((e.code, e.label) for e in rc.make_entries(rc.parse_rows(rows)))


class TestRoomCodes(unittest.TestCase):

    def test_is_code(self):
        self.assertTrue(rc.is_code("03.10.100"))
        self.assertTrue(rc.is_code(" 03.10.100 "))
        for bad in ("Codes", "3.10.100", "03.10.1000", ""):
            self.assertFalse(rc.is_code(bad))

    def test_title_and_header_rows_skipped(self):
        self.assertEqual(rc.parse_rows(DUP_SHEET)[0],
                         ("03.60.000", "Ambulatory & Outpatient Services", None))

    def test_no_header_row_reads_everything(self):
        self.assertEqual(rc.parse_rows([("03.10.100", "Triage")]),
                         [("03.10.100", "Triage", None)])

    def test_blank_note_and_column_c_rows_dropped(self):
        rows = [(None, None), ("NOTE : - New additions", ""),
                ("02.30.210", ""), ("03.10.100", " Triage ")]
        self.assertEqual(rc.parse_rows(rows), [("03.10.100", "Triage", None)])

    def test_headings_are_flagged_entries(self):
        entries = rc.make_entries(rc.parse_rows(DUP_SHEET))
        self.assertEqual([(e.code, e.heading) for e in entries],
                         [("03.60.000", True), ("03.60.100", True),
                          ("03.60.160", False), ("03.60.300", True),
                          ("03.60.360", False), ("03.30.800", True),
                          ("03.30.831", False), ("03.30.840", False)])

    def test_unique_name_label_gets_code(self):
        self.assertEqual(labels(DUP_SHEET)["03.60.100"],
                         u"Outpatient Clinic (03.60.100)")

    def test_heading_and_room_of_same_name_told_apart(self):
        l = labels(NICU)
        self.assertEqual(l["03.50.540"],
                         u"NICU Family Room " + DASH + u" NICU (03.50.540)")
        self.assertEqual(l["03.50.600"], u"NICU Family Room " + DASH
                         + u" Women & Children (03.50.600)")

    def test_repeat_gets_parent_heading_and_code(self):
        entries = dict((e.code, e) for e in
                       rc.make_entries(rc.parse_rows(DUP_SHEET)))
        self.assertEqual(entries["03.60.160"].label,
                         u"Waiting Area " + DASH + u" Outpatient Clinic (03.60.160)")
        self.assertEqual(entries["03.60.360"].label,
                         u"Waiting Area " + DASH + u" Oncology / Infusion (03.60.360)")
        self.assertEqual(entries["03.60.160"].name, "Waiting Area")
        self.assertEqual(entries["03.60.360"].name, "Waiting Area")

    def test_same_heading_repeat_told_apart_by_code(self):
        l = labels(DUP_SHEET)
        base = u"PACS / Server Room " + DASH + u" Imaging Support"
        self.assertEqual(l["03.30.831"], base + u" (03.30.831)")
        self.assertEqual(l["03.30.840"], base + u" (03.30.840)")

    def test_neeviq_column_read(self):
        entries = dict((e.code, e) for e in rc.make_entries(rc.parse_rows(NEEV)))
        self.assertEqual(sorted(entries), ["02.10.100", "02.10.110", "02.10.120",
                                           "02.10.160"])
        self.assertEqual(entries["02.10.110"].name, "Corridor")
        self.assertEqual(entries["02.10.110"].neev, "Corridor Common")
        self.assertIsNone(entries["02.10.120"].neev)

    def test_neeviq_only_row_labelled_by_neeviq_name(self):
        e = [x for x in rc.make_entries(rc.parse_rows(NEEV))
             if x.code == "02.10.160"][0]
        self.assertIsNone(e.name)
        self.assertEqual(e.neev, "Refuge Area")
        self.assertEqual(e.label, u"Refuge Area (02.10.160)")

    def test_column_c_ignored_without_neeviq_header(self):
        rows = [("Codes", "B&G Input", "Comments"),
                ("03.10.110", "Triage", "see note"), ("03.10.120", None, "x")]
        self.assertEqual(rc.parse_rows(rows), [("03.10.110", "Triage", None)])

    def test_read_workbook_reads_column_c(self):
        f = make_xlsx([("Podium", NEEV)])
        e = rc.read_workbook(f)[0][1]
        self.assertEqual([(x.code, x.name, x.neev) for x in e],
                         [("02.10.100", "Circulation", "Circulation Common"),
                          ("02.10.110", "Corridor", "Corridor Common"),
                          ("02.10.120", "Public Elevator", None),
                          ("02.10.160", None, "Refuge Area")])

    def test_read_workbook_order_and_summary_skip(self):
        f = make_xlsx([("Summary", DUP_SHEET),
                       ("10. Emergency Services", DUP_SHEET),
                       ("Empty", [("Codes", "B&G Input")])])
        self.assertEqual([n for n, _e in rc.read_workbook(f)],
                         ["10. Emergency Services"])

    def test_entities_rich_inline_numeric(self):
        f = make_xlsx([("20. Surgical & Procedural ",
                        [("Codes", "B&G Input"),
                         (("rich", ["03.", "10.110"]), "Triage"),
                         ("03.10.210", ("inline", "Bay & Co")),
                         (3.1, "Numeric")])])
        res = rc.read_workbook(f)
        self.assertEqual(res[0][0], "20. Surgical & Procedural ")
        self.assertEqual([(e.code, e.name) for e in res[0][1]],
                         [("03.10.110", "Triage"), ("03.10.210", "Bay & Co")])

    def test_resolve_label_ignores_case_and_spaces(self):
        entries = rc.make_entries(rc.parse_rows(DUP_SHEET))
        hit = rc.resolve_label(
            entries, u"  waiting area " + DASH + u" OUTPATIENT clinic (03.60.160) ")
        self.assertEqual(hit.code, "03.60.160")
        self.assertIsNone(rc.resolve_label(entries, "Waiting"))


if __name__ == "__main__":
    unittest.main()
