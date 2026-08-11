# -*- coding: utf-8 -*-
__title__ = "Room No\nto Area No"
__doc__ = """Copies Room Number to Area Number for rooms and areas
that have identical area values (sq ft).
Compatible: Revit 2025 / pyRevit 4.8+"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    Transaction,
    UnitUtils,
    UnitTypeId,
)
from pyrevit import revit, script

doc    = revit.doc
output = script.get_output()

# ── CONFIG ────────────────────────────────────────────────────────────────────
AREA_TOLERANCE_SQF = 0.01   # sq ft — area values must match within this
# ─────────────────────────────────────────────────────────────────────────────


def collect_placed(category):
    return [
        e for e in
        FilteredElementCollector(doc)
            .OfCategory(category)
            .WhereElementIsNotElementType()
            .ToElements()
        if e.Area > 0
    ]


def get_param_string(element, bip):
    p = element.get_Parameter(bip)
    return p.AsString() if p else ""


def to_sqft(internal_value):
    """Convert Revit internal area units to sq ft (Revit 2025 API)."""
    return UnitUtils.ConvertFromInternalUnits(internal_value, UnitTypeId.SquareFeet)


def run():
    rooms = collect_placed(BuiltInCategory.OST_Rooms)
    areas = collect_placed(BuiltInCategory.OST_Areas)

    matched   = []
    unmatched = []

    # Track which areas have already been claimed to prevent duplicate matches
    available_areas = list(areas)

    for room in rooms:
        room_sqft = to_sqft(room.Area)
        found = None
        for i, area in enumerate(available_areas):
            area_sqft = to_sqft(area.Area)
            if abs(room_sqft - area_sqft) <= AREA_TOLERANCE_SQF:
                found = available_areas.pop(i)  # remove from pool so it can't match again
                break

        if found:
            matched.append((room, found))
        else:
            unmatched.append(room)

    # ── Transaction ────────────────────────────────────────────────────────
    updated = []
    errors  = []

    with Transaction(doc, "Copy Room Number to Area Number") as t:
        t.Start()
        for room, area in matched:
            r_num = get_param_string(room, BuiltInParameter.ROOM_NUMBER)
            try:
                param = area.get_Parameter(BuiltInParameter.ROOM_NUMBER)
                if param is None:
                    errors.append("Area {} — ROOM_NUMBER parameter not found.".format(area.Id.IntegerValue))
                elif param.IsReadOnly:
                    errors.append("Area {} — ROOM_NUMBER parameter is read-only.".format(area.Id.IntegerValue))
                else:
                    param.Set(r_num)
                    updated.append((r_num, r_num))
            except Exception as ex:
                errors.append("Room {} → Area {}: {}".format(r_num, area.Id.IntegerValue, str(ex)))
        t.Commit()

    # ── Results ────────────────────────────────────────────────────────────
    output.print_md("## Room Number → Area Number")
    output.print_md("---")

    if updated:
        output.print_table(
            table_data = updated,
            title      = "",
            columns    = ["Room No.", "Area No."],
        )

    output.print_md("\n✅ **{} area(s) updated successfully.**".format(len(updated)))

    if unmatched:
        output.print_md("\n⚠️ **{} room(s) skipped** — no area with matching sq ft found.".format(len(unmatched)))
        for r in unmatched:
            output.print_md("- Room **{}** – {}".format(
                get_param_string(r, BuiltInParameter.ROOM_NUMBER),
                get_param_string(r, BuiltInParameter.ROOM_NAME),
            ))

    if errors:
        output.print_md("\n### ⚠️ Errors ({})\n".format(len(errors)))
        for err in errors:
            output.print_md("- " + err)


run()