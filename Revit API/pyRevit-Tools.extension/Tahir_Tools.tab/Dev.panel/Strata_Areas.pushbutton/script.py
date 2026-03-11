# -*- coding: utf-8 -*-
__title__ = "Strata Areas\nfrom Excel"

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# ==================================================

import clr
import re
import zipfile
import xml.etree.ElementTree as ET

clr.AddReference("System")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    Transaction,
    StorageType,
    UnitUtils,
    UnitTypeId,
)

from pyrevit import forms, script

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
# ==================================================

doc = __revit__.ActiveUIDocument.Document  # type: ignore
uidoc = __revit__.ActiveUIDocument  # type: ignore

# Parameter names (same in Excel headers and Revit)
PARAM_SHEET_NUMBER = "Sheet Numbers"
PARAM_UNIT_NUMBER = "Unit Numbers"
PARAM_INTERNAL = "Internal Strata Areas"
PARAM_EXTERNAL = "External Strata Areas"
PARAM_TOTAL = "Total Strata Area"

STRATA_PARAMS = [PARAM_INTERNAL, PARAM_EXTERNAL, PARAM_TOTAL]

XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


# ╔═╗╦ ╦╔╗╔╔═╗╔╦╗╦╔═╗╔╗╔╔═╗
# ╠╣ ║ ║║║║║   ║ ║║ ║║║║╚═╗
# ╚  ╚═╝╝╚╝╚═╝ ╩ ╩╚═╝╝╚╝╚═╝ FUNCTIONS
# ==================================================


def col_letter_to_index(col_str):
    """Convert Excel column letter(s) to 0-based index."""
    result = 0
    for ch in col_str.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def parse_cell_ref(cell_ref):
    """Split a cell reference like 'B12' into (col_index, row_number)."""
    m = re.match(r"([A-Za-z]+)(\d+)", cell_ref)
    if not m:
        return None, None
    return col_letter_to_index(m.group(1)), int(m.group(2))


def read_excel_data(file_path):
    """Read .xlsx using zipfile + XML. Returns list of row dicts."""
    with zipfile.ZipFile(file_path, "r") as zf:
        # Shared strings
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            tree = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in tree.findall("{%s}si" % XLSX_NS):
                t = si.find("{%s}t" % XLSX_NS)
                if t is not None and t.text:
                    shared.append(t.text)
                else:
                    parts = []
                    for r in si.findall("{%s}r" % XLSX_NS):
                        t2 = r.find("{%s}t" % XLSX_NS)
                        if t2 is not None and t2.text:
                            parts.append(t2.text)
                    shared.append("".join(parts))

        # Parse first worksheet
        sheet_tree = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
        sheet_data = sheet_tree.find("{%s}sheetData" % XLSX_NS)

        raw_rows = {}
        for row_el in sheet_data.findall("{%s}row" % XLSX_NS):
            rn = int(row_el.get("r"))
            cells = {}
            for c_el in row_el.findall("{%s}c" % XLSX_NS):
                ci, _ = parse_cell_ref(c_el.get("r"))
                v_el = c_el.find("{%s}v" % XLSX_NS)
                val = v_el.text if v_el is not None else None
                if c_el.get("t") == "s" and val is not None:
                    val = shared[int(val)]
                cells[ci] = val
            raw_rows[rn] = cells

    if not raw_rows:
        return []

    # Headers from first row
    min_r = min(raw_rows)
    col_map = {ci: h.strip() for ci, h in raw_rows[min_r].items() if h}

    # Validate
    required = [PARAM_SHEET_NUMBER, PARAM_UNIT_NUMBER,
                PARAM_INTERNAL, PARAM_EXTERNAL, PARAM_TOTAL]
    missing = [c for c in required if c not in col_map.values()]
    if missing:
        forms.alert("Missing columns in Excel:\n{}".format(
            "\n".join(missing)), exitscript=True)

    # Data rows
    data = []
    for rn in sorted(raw_rows):
        if rn == min_r:
            continue
        rc = raw_rows[rn]
        data.append({h: rc.get(ci) for ci, h in col_map.items()})
    return data


def is_param_empty(element, name):
    """Check if a parameter is null/empty/zero."""
    p = element.LookupParameter(name)
    if p is None or not p.HasValue:
        return True
    st = p.StorageType
    if st == StorageType.String:
        v = p.AsString()
        return v is None or v.strip() == ""
    elif st == StorageType.Double:
        return p.AsDouble() == 0.0
    elif st == StorageType.Integer:
        return p.AsInteger() == 0
    return False


def set_area_param(element, name, value):
    """Set an Area parameter, converting from sqm to internal units."""
    p = element.LookupParameter(name)
    if p is None or p.IsReadOnly:
        return False
    try:
        if p.StorageType == StorageType.String:
            p.Set(str(value) if value else "")
        elif p.StorageType == StorageType.Double:
            p.Set(UnitUtils.ConvertToInternalUnits(
                float(value), UnitTypeId.SquareMeters))
        elif p.StorageType == StorageType.Integer:
            p.Set(int(float(value)))
        return True
    except:
        return False


def get_param_string(element, name):
    """Get the string value of a parameter."""
    p = element.LookupParameter(name)
    if p is None:
        return None
    v = p.AsString()
    return v if v else p.AsValueString()


# ╔═╗╦ ╦╔═╗╔═╗╔╦╗   ╔═╗╔═╗╦  ╔═╗╔═╗╔╦╗╦╔═╗╔╗╔
# ╚═╗╠═╣║╣ ║╣  ║    ╚═╗║╣ ║  ║╣ ║   ║ ║║ ║║║║
# ╚═╝╩ ╩╚═╝╚═╝ ╩    ╚═╝╚═╝╩═╝╚═╝╚═╝ ╩ ╩╚═╝╝╚╝ SHEET SELECTION
# ==================================================


class SheetOption(forms.TemplateListItem):
    @property
    def name(self):
        return "{} - {}".format(self.item.SheetNumber, self.item.Name)


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
# ==================================================


def main():
    # 1. Select sheets
    all_sheets = (FilteredElementCollector(doc)
                  .OfCategory(BuiltInCategory.OST_Sheets)
                  .WhereElementIsNotElementType()
                  .ToElements())

    if not all_sheets:
        forms.alert("No sheets found in the document.", exitscript=True)

    options = sorted([SheetOption(s) for s in all_sheets],
                     key=lambda x: x.item.SheetNumber)

    selected = forms.SelectFromList.show(
        options, title="Select Sheets",
        button_name="Select", multiselect=True)

    if not selected:
        script.exit()

    # 2. Pick Excel file
    excel_path = forms.pick_file(file_ext="xlsx",
                                  title="Select the Strata Areas Excel File")
    if not excel_path:
        script.exit()

    # 3. Read Excel
    excel_data = read_excel_data(excel_path)
    if not excel_data:
        forms.alert("The Excel file contains no data rows.", exitscript=True)

    # Build lookup: (sheet_num, unit_num) -> row for fast matching
    excel_lookup = {}
    for row in excel_data:
        sn = str(row.get(PARAM_SHEET_NUMBER, "") or "").strip()
        un = str(row.get(PARAM_UNIT_NUMBER, "") or "").strip()
        if sn and un:
            excel_lookup[(sn, un)] = row

    # 4-6. Match and copy
    updated = 0
    skipped_filled = 0
    skipped_no_match = 0
    errors = []

    t = Transaction(doc, "Copy Strata Areas from Excel")
    t.Start()

    try:
        for sheet in selected:
            sheet_num = sheet.SheetNumber
            unit_num = get_param_string(sheet, PARAM_UNIT_NUMBER)

            # Skip if any strata param already filled
            if not all(is_param_empty(sheet, p) for p in STRATA_PARAMS):
                skipped_filled += 1
                continue

            # Find matching Excel row
            matched = None
            for (ex_sn, ex_un), row in excel_lookup.items():
                if ex_sn in sheet_num and unit_num and ex_un in unit_num:
                    matched = row
                    break

            if not matched:
                skipped_no_match += 1
                continue

            # Copy values
            ok = all(
                set_area_param(sheet, p, matched.get(p, "") or "")
                for p in STRATA_PARAMS
            )

            if ok:
                updated += 1
            else:
                errors.append(sheet_num)

        t.Commit()
    except Exception as e:
        t.RollBack()
        forms.alert("Error:\n{}".format(str(e)), exitscript=True)

    # Report
    msg = ("Strata Areas Update Complete\n"
           "===========================\n"
           "Updated:              {}\n"
           "Skipped (filled):     {}\n"
           "Skipped (no match):   {}").format(
               updated, skipped_filled, skipped_no_match)
    if errors:
        msg += "\n\nFailed sheets: " + ", ".join(errors)

    forms.alert(msg)


main()
