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
                ref = "%s%d" % ("AB"[c], r)
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
                         ("03.60.000", "Ambulatory & Outpatient Services"))

    def test_no_header_row_reads_everything(self):
        self.assertEqual(rc.parse_rows([("03.10.100", "Triage")]),
                         [("03.10.100", "Triage")])

    def test_blank_note_and_column_c_rows_dropped(self):
        rows = [(None, None), ("NOTE : - New additions", ""),
                ("02.30.210", ""), ("03.10.100", " Triage ")]
        self.assertEqual(rc.parse_rows(rows), [("03.10.100", "Triage")])

    def test_unique_name_label_is_plain(self):
        self.assertEqual(labels(DUP_SHEET)["03.60.100"], "Outpatient Clinic")

    def test_repeat_gets_parent_heading(self):
        entries = dict((e.code, e) for e in
                       rc.make_entries(rc.parse_rows(DUP_SHEET)))
        self.assertEqual(entries["03.60.160"].label,
                         u"Waiting Area " + DASH + u" Outpatient Clinic")
        self.assertEqual(entries["03.60.360"].label,
                         u"Waiting Area " + DASH + u" Oncology / Infusion")
        self.assertEqual(entries["03.60.160"].name, "Waiting Area")
        self.assertEqual(entries["03.60.360"].name, "Waiting Area")

    def test_heading_parent_is_department(self):
        l = labels(NICU)
        self.assertEqual(l["03.50.540"], u"NICU Family Room " + DASH + u" NICU")
        self.assertEqual(l["03.50.600"],
                         u"NICU Family Room " + DASH + u" Women & Children")

    def test_still_identical_gets_code(self):
        l = labels(DUP_SHEET)
        base = u"PACS / Server Room " + DASH + u" Imaging Support"
        self.assertEqual(l["03.30.831"], base + u" (03.30.831)")
        self.assertEqual(l["03.30.840"], base + u" (03.30.840)")

    def test_read_workbook_order_and_summary_skip(self):
        f = make_xlsx([("Summary", DUP_SHEET),
                       ("10. Emergency Services", DUP_SHEET),
                       ("Empty", [("Codes", "B&G Input")])])
        self.assertEqual([n for n, _e in rc.read_workbook(f)],
                         ["10. Emergency Services"])

    def test_entities_rich_inline_numeric(self):
        f = make_xlsx([("20. Surgical & Procedural ",
                        [("Codes", "B&G Input"),
                         (("rich", ["03.", "10.100"]), "Triage"),
                         ("03.10.200", ("inline", "Bay & Co")),
                         (3.1, "Numeric")])])
        res = rc.read_workbook(f)
        self.assertEqual(res[0][0], "20. Surgical & Procedural ")
        self.assertEqual([(e.code, e.name) for e in res[0][1]],
                         [("03.10.100", "Triage"), ("03.10.200", "Bay & Co")])

    def test_resolve_label_ignores_case_and_spaces(self):
        entries = rc.make_entries(rc.parse_rows(DUP_SHEET))
        hit = rc.resolve_label(
            entries, u"  waiting area " + DASH + u" OUTPATIENT clinic ")
        self.assertEqual(hit.code, "03.60.160")
        self.assertIsNone(rc.resolve_label(entries, "Waiting"))


if __name__ == "__main__":
    unittest.main()
