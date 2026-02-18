# -*- coding: utf-8 -*-
__title__ = "Place Views\non Sheets"
__doc__ = """Select views and sheets, then place views on matched sheets by Level number."""

import re
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from pyrevit import revit, DB, forms
from Autodesk.Revit.DB import (
    FilteredElementCollector, View, ViewSheet,
    Viewport, XYZ, Transaction, BuiltInParameter,
    BuiltInCategory
)

doc = revit.doc

# ─────────────────────────────────────────────
# HELPER: Extract level number from a string
# e.g. "Level 7" → "7", "Level 10" → "10"
# ─────────────────────────────────────────────
def extract_level_number(name):
    match = re.search(r'[Ll]evel\s+(\d+)', name)
    if match:
        return match.group(1)
    return None


# ─────────────────────────────────────────────
# STEP 1: Collect ALL placeable views
# ─────────────────────────────────────────────
all_views = FilteredElementCollector(doc)\
    .OfClass(View)\
    .ToElements()

placeable_view_types = [
    DB.ViewType.FloorPlan,
    DB.ViewType.CeilingPlan,
    DB.ViewType.Elevation,
    DB.ViewType.Section,
    DB.ViewType.Detail,
    DB.ViewType.DraftingView,
    DB.ViewType.ThreeD,
    DB.ViewType.AreaPlan,
]

placeable_views = [v for v in all_views if not v.IsTemplate
                   and v.ViewType in placeable_view_types]

if not placeable_views:
    forms.alert("No placeable views found in the project.", exitscript=True)


# ─────────────────────────────────────────────
# STEP 2: Collect ALL sheets
# ─────────────────────────────────────────────
all_sheets = list(
    FilteredElementCollector(doc)
    .OfClass(ViewSheet)
    .ToElements()
)

if not all_sheets:
    forms.alert("No sheets found in the project.", exitscript=True)


# ─────────────────────────────────────────────
# STEP 3: Ask user to select views (ALL views shown)
# ─────────────────────────────────────────────
view_dict = {}
for v in sorted(placeable_views, key=lambda x: x.Name):
    view_dict[v.Name] = v

selected_view_names = forms.SelectFromList.show(
    sorted(view_dict.keys()),
    title="Select Views to Place",
    multiselect=True,
    button_name="Select Views"
)

if not selected_view_names:
    forms.alert("No views selected. Exiting.", exitscript=True)

selected_views = [view_dict[name] for name in selected_view_names]


# ─────────────────────────────────────────────
# STEP 4: Ask user to select sheets (ALL sheets shown)
# ─────────────────────────────────────────────
sheet_dict = {}
for s in sorted(all_sheets, key=lambda x: x.Name):
    display_name = "{0} - {1}".format(s.SheetNumber, s.Name)
    sheet_dict[display_name] = s

selected_sheet_names = forms.SelectFromList.show(
    sorted(sheet_dict.keys()),
    title="Select Target Sheets",
    multiselect=True,
    button_name="Select Sheets"
)

if not selected_sheet_names:
    forms.alert("No sheets selected. Exiting.", exitscript=True)

selected_sheets = [sheet_dict[name] for name in selected_sheet_names]


# ─────────────────────────────────────────────
# STEP 5: Build Level number → sheet map
# Only from user-selected sheets
# ─────────────────────────────────────────────
sheet_level_map = {}
sheets_without_level = []

for sheet in selected_sheets:
    lvl = extract_level_number(sheet.Name)
    if lvl:
        if lvl not in sheet_level_map:
            sheet_level_map[lvl] = sheet
        else:
            print("WARNING: Multiple sheets found for Level {0}. Using: {1}".format(
                lvl, sheet_level_map[lvl].Name))
    else:
        sheets_without_level.append(sheet.Name)

if sheets_without_level:
    print("INFO: These selected sheets have no Level number and will be skipped:")
    for name in sheets_without_level:
        print("  - " + name)


# ─────────────────────────────────────────────
# STEP 6: Get sheet center from title block
# ─────────────────────────────────────────────
def get_sheet_center(sheet):
    title_blocks = FilteredElementCollector(doc, sheet.Id)\
        .OfCategory(BuiltInCategory.OST_TitleBlocks)\
        .ToElements()

    if title_blocks:
        tb = title_blocks[0]
        bbox = tb.get_BoundingBox(sheet)
        if bbox:
            center_x = (bbox.Min.X + bbox.Max.X) / 2.0
            center_y = (bbox.Min.Y + bbox.Max.Y) / 2.0
            return XYZ(center_x, center_y, 0)

    # Fallback: approximate center of an A1 sheet in feet
    return XYZ(0.9, 0.6, 0)


# ─────────────────────────────────────────────
# STEP 7: Find "Title_None" viewport type once
# ─────────────────────────────────────────────
all_vp_types = FilteredElementCollector(doc)\
    .OfClass(DB.ElementType)\
    .ToElements()

title_none_type = None
for vt in all_vp_types:
    if vt.FamilyName == "Viewport" and vt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == "Title_None":
        title_none_type = vt
        break

if not title_none_type:
    forms.alert(
        "Viewport type 'Title_None' was not found in this project.\n"
        "Views will be placed with the default viewport type.",
        title="Warning - Title_None Not Found"
    )


# ─────────────────────────────────────────────
# STEP 8: Match selected views to selected sheets
# and place them
# ─────────────────────────────────────────────
placed   = []
skipped  = []
no_match = []

for view in selected_views:
    view_level = extract_level_number(view.Name)

    if not view_level:
        no_match.append((view.Name, "No 'Level X' found in view name"))
        continue

    if view_level not in sheet_level_map:
        no_match.append((view.Name, "No selected sheet matches Level {0}".format(view_level)))
        continue

    target_sheet = sheet_level_map[view_level]

    # Check if already placed on this sheet
    already_placed = False
    for vp_id in target_sheet.GetAllViewports():
        vp = doc.GetElement(vp_id)
        if vp.ViewId == view.Id:
            already_placed = True
            break

    if already_placed:
        skipped.append((view.Name, "Already on sheet '{0}'".format(target_sheet.Name)))
        continue

    # Check if view can be added to sheet
    if not Viewport.CanAddViewToSheet(doc, target_sheet.Id, view.Id):
        skipped.append((view.Name, "Already placed on another sheet"))
        continue

    # Place the view and set viewport type
    try:
        with Transaction(doc, "Place: {0}".format(view.Name)) as t:
            t.Start()

            # Create viewport at sheet center
            center = get_sheet_center(target_sheet)
            new_vp = Viewport.Create(doc, target_sheet.Id, view.Id, center)

            # Set viewport type to Title_None if found
            if title_none_type:
                new_vp.ChangeTypeId(title_none_type.Id)

            t.Commit()
        placed.append((view.Name, target_sheet.Name))

    except Exception as ex:
        skipped.append((view.Name, "Error: {0}".format(str(ex))))


# ─────────────────────────────────────────────
# STEP 9: Report results
# ─────────────────────────────────────────────
report_lines = []

if placed:
    report_lines.append("PLACED ({0}):".format(len(placed)))
    for v_name, s_name in placed:
        report_lines.append("  + {0}  ->  {1}".format(v_name, s_name))

if no_match:
    report_lines.append("\nNO MATCH FOUND ({0}):".format(len(no_match)))
    for v_name, reason in no_match:
        report_lines.append("  ? {0}  ({1})".format(v_name, reason))

if skipped:
    report_lines.append("\nSKIPPED ({0}):".format(len(skipped)))
    for v_name, reason in skipped:
        report_lines.append("  x {0}  ({1})".format(v_name, reason))

if not report_lines:
    report_lines.append("Nothing was placed.")

forms.alert("\n".join(report_lines), title="Place Views - Result")