# -*- coding: utf-8 -*-
"""Export all sheets to CSV with Sheet Name, Number, Size, and Scale.
Excludes linked model sheets. Uses SHEET_NUMBER parameter on title block
instances for reliable matching instead of OwnerViewId.
"""

import csv
import os
from pyrevit import revit, DB, forms

doc = revit.doc
doc_title = doc.Title

# ---------------------------------------------------------------------------
# USER CONFIG
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.path.expanduser("~\\Desktop")
OUTPUT_FILE = "sheets_export CD.csv"

# ---------------------------------------------------------------------------
# PRE-FETCH: key title blocks by their SHEET_NUMBER parameter value
# This is more reliable than OwnerViewId which can return wrong elements
# ---------------------------------------------------------------------------
tb_map = {}
for tb in (
    DB.FilteredElementCollector(doc)
    .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
    .WhereElementIsNotElementType()
    .ToElements()
):
    if tb.Document.Title != doc_title:
        continue
    sheet_num_param = tb.get_Parameter(DB.BuiltInParameter.SHEET_NUMBER)
    if sheet_num_param:
        sheet_num = sheet_num_param.AsString()
        if sheet_num:
            tb_map[sheet_num] = tb

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
SKIP_VIEW_TYPES = {
    DB.ViewType.Legend,
    DB.ViewType.Schedule,
    DB.ViewType.DrawingSheet,
    DB.ViewType.ProjectBrowser,
    DB.ViewType.SystemBrowser,
}

def get_title_block_size(sheet):
    tb = tb_map.get(sheet.SheetNumber)
    if not tb:
        return "No Title Block"
    return tb.Symbol.Family.Name


def get_sheet_scale(sheet):
    scales = set()
    for vp_id in sheet.GetAllViewports():
        vp = doc.GetElement(vp_id)
        view = doc.GetElement(vp.ViewId)
        if view is None or view.ViewType in SKIP_VIEW_TYPES:
            continue
        if view.Scale and view.Scale > 0:
            scales.add(view.Scale)

    if not scales:
        return "No Views"
    if len(scales) == 1:
        return "1:{}".format(scales.pop())
    return "Varies"


# ---------------------------------------------------------------------------
# MAIN
# Host document sheets only
# ---------------------------------------------------------------------------
sheets = sorted(
    [s for s in
        DB.FilteredElementCollector(doc)
        .OfClass(DB.ViewSheet)
        .WhereElementIsNotElementType()
        .ToElements()
     if s.Document.Title == doc_title],
    key=lambda s: s.SheetNumber
)

output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)

with open(output_path, "wb") as f:
    writer = csv.writer(f)
    writer.writerow(["Sheet Name", "Sheet Number", "Sheet Size", "Scale"])
    for sheet in sheets:
        writer.writerow([
            sheet.Name,
            sheet.SheetNumber,
            get_title_block_size(sheet),
            get_sheet_scale(sheet),
        ])

forms.alert(
    "Exported {} sheets to:\n{}".format(len(sheets), output_path),
    title="Export Complete"
)