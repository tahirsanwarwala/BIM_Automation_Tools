# -*- coding: utf-8 -*-

from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BoundingBoxXYZ,
    Transaction
)

doc = revit.doc
view = doc.ActiveView

# -------------------------------------------------
# Validate view
# -------------------------------------------------
# if not view.CanHaveCropRegion:
#     forms.alert("Active view cannot be cropped.", exitscript=True)

# -------------------------------------------------
# Collect rooms visible in this view
# -------------------------------------------------
rooms = (
    FilteredElementCollector(doc, view.Id)
    .OfCategory(BuiltInCategory.OST_Rooms)
    .WhereElementIsNotElementType()
    .ToElements()
)

if not rooms:
    forms.alert("No rooms found in active view.", exitscript=True)

room_map = {f"{r.Number} - {r.Name}": r for r in rooms}

selection = forms.SelectFromList.show(
    sorted(room_map.keys()),
    title="Select Room",
    button_name="Crop View"
)

if not selection:
    forms.alert("No room selected.", exitscript=True)

room = room_map[selection]

# -------------------------------------------------
# Get bounding box
# -------------------------------------------------
bbox = room.get_BoundingBox(view)

if not bbox:
    forms.alert("Room bounding box not available.", exitscript=True)

# -------------------------------------------------
# Apply directly to crop box
# -------------------------------------------------
with Transaction(doc, "Crop View to Room") as t:
    t.Start()

    view.CropBoxActive = True
    view.CropBoxVisible = True

    new_box = BoundingBoxXYZ()
    new_box.Min = bbox.Min
    new_box.Max = bbox.Max

    view.CropBox = new_box

    t.Commit()
