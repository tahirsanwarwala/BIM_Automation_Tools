# -*- coding: utf-8 -*-
__title__ = "Shift CW Marks"
__doc__ = "Shifts curtain wall Mark parameters from a selected entry upward by a user-defined amount - Active View only."

from pyrevit import revit, DB, forms
import re

doc = revit.doc

# Collect curtain walls visible in the active view only
active_view = doc.ActiveView
cw_elements = DB.FilteredElementCollector(doc, active_view.Id)\
    .OfCategory(DB.BuiltInCategory.OST_Walls)\
    .WhereElementIsNotElementType()\
    .ToElements()

cw_elements = [e for e in cw_elements if e.WallType.Kind == DB.WallKind.Curtain]

# Build mark -> element map
mark_map = {}
for e in cw_elements:
    mark_param = e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
    if mark_param and mark_param.AsString():
        mark = mark_param.AsString().strip()
        mark_map[mark] = e

if not mark_map:
    forms.alert("No curtain walls with Mark values found in the active view.", exitscript=True)

# Sort marks naturally
def mark_sort_key(m):
    parts = re.split(r'(\d+)', m)
    return [int(p) if p.isdigit() else p for p in parts]

sorted_marks = sorted(mark_map.keys(), key=mark_sort_key)

# Ask user for direction
direction = forms.SelectFromList.show(
    ["+ (Increment)", "- (Decrement)"],
    title="Select Operation",
    multiselect=False
)

if not direction:
    forms.alert("No operation selected.", exitscript=True)

sign = 1 if direction.startswith("+") else -1

# Ask user for the amount
amount_input = forms.ask_for_string(
    prompt="Enter the amount to {} marks by:".format("increment" if sign == 1 else "decrement"),
    title="Shift Amount"
)

if not amount_input:
    forms.alert("No amount entered.", exitscript=True)

if not amount_input.strip().isdigit() or int(amount_input.strip()) == 0:
    forms.alert("Please enter a positive whole number greater than 0.", exitscript=True)

delta = sign * int(amount_input.strip())

# Ask user to select starting mark
selected = forms.SelectFromList.show(
    sorted_marks,
    title="Select Starting Mark (this and above will be shifted {:+d})".format(delta),
    multiselect=False
)

if not selected:
    forms.alert("No selection made.", exitscript=True)

start_idx = sorted_marks.index(selected)
marks_to_shift = sorted_marks[start_idx:]

# Validate decrement won't produce negative suffix
if delta < 0:
    for mark in marks_to_shift:
        match = re.match(r'^(.*?)(\d+)$', mark)
        if match and int(match.group(2)) + delta < 0:
            forms.alert(
                "Operation would produce a negative number for '{}'.\nAborting.".format(mark),
                exitscript=True
            )

# Shift suffix by delta, preserving zero-padding
def shift_mark(mark, delta):
    match = re.match(r'^(.*?)(\d+)$', mark)
    if match:
        prefix = match.group(1)
        num = int(match.group(2))
        width = len(match.group(2))
        return "{}{}".format(prefix, str(num + delta).zfill(width))
    return mark

# Reverse for increment, forward for decrement — avoids collisions
ordered = reversed(marks_to_shift) if delta > 0 else iter(marks_to_shift)

with DB.Transaction(doc, "Shift Curtain Wall Marks") as t:
    t.Start()
    for mark in ordered:
        elem = mark_map[mark]
        new_mark = shift_mark(mark, delta)
        mark_param = elem.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
        mark_param.Set(new_mark)
    t.Commit()

forms.alert(
    "Done! {} mark(s) shifted by {:+d} starting from {}.".format(
        len(marks_to_shift), delta, selected
    ),
    title="Success"
)