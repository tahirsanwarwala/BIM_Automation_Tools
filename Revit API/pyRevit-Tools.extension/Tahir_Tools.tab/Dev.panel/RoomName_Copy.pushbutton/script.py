# -*- coding: utf-8 -*-
__title__ = "Room Name Copy"

# pyRevit | Revit 2024 | IronPython 3
#
# Logic exactly as requested:
# 1. strip()
# 2. convert to list
# 3. replace first index with full level number
# 4. join()
#
# Example
#   804B  -> ['8','0','4','B']
#   level 12
#   -> ['12','0','4','B']
#   -> 1204B

import re

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms


uidoc = revit.uidoc
doc = revit.doc


# ---------------------------------------------------
# Filters
# ---------------------------------------------------
class RoomSelectionFilter(ISelectionFilter):
    def AllowElement(self, e):
        return isinstance(e, SpatialElement) and \
               e.Category.Id.IntegerValue == int(BuiltInCategory.OST_Rooms)

    def AllowReference(self, r, p):
        return True


# ---------------------------------------------------
# Helpers
# ---------------------------------------------------
def room_xy(room):
    loc = room.Location
    if isinstance(loc, LocationPoint):
        p = loc.Point
        return (round(p.X, 4), round(p.Y, 4))
    return None


def level_number(level):
    m = re.search(r"\d+", level.Name)
    return m.group(0) if m else None


def replace_first_index(number_str, lvl_str):
    """
    EXACT routine:
    strip → list → replace first index → join
    """
    s = number_str.strip()
    chars = list(s)          # ['8','0','4','B'] or ['1','2','0','4','B']
    if len(s) < 5:
        chars[0] = lvl_str          # ['12','0','4','B']
    else:
        s.pop(0)
        chars[0] = lvl_str  # ['12','0','4','B']

    return "".join(chars)   # '1204B'

# ---------------------------------------------------
# Select source rooms
# ---------------------------------------------------
try:
    refs = uidoc.Selection.PickObjects(
        ObjectType.Element,
        RoomSelectionFilter(),
        "Select SOURCE rooms"
    )
except OperationCanceledException:
    raise SystemExit


source_rooms = [doc.GetElement(r.ElementId) for r in refs]

if not source_rooms:
    raise Exception("No rooms selected.")


source_level = doc.GetElement(source_rooms[0].LevelId)


# ---------------------------------------------------
# Target levels list
# ---------------------------------------------------
levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
levels = sorted(levels, key=lambda l: l.Elevation)

level_map = {l.Name: l for l in levels}

selected = forms.SelectFromList.show(
    [l.Name for l in levels if l.Id != source_level.Id],
    title="Select Target Levels",
    multiselect=True
)

if not selected:
    raise SystemExit

target_levels = [level_map[n] for n in selected]


# ---------------------------------------------------
# Build source dictionary (XY → number)
# ---------------------------------------------------
source_dict = {}

for r in source_rooms:
    xy = room_xy(r)
    if xy:
        num = r.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString()
        source_dict[xy] = num


# ---------------------------------------------------
# Copy parameters
# ---------------------------------------------------
t = Transaction(doc, "Copy Room Numbers By Location")
t.Start()

for lvl in target_levels:

    lvl_str = level_number(lvl)
    if not lvl_str:
        continue

    level_filter = ElementLevelFilter(lvl.Id)

    target_rooms = (FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_Rooms)
                    .WherePasses(level_filter)
                    .WhereElementIsNotElementType()
                    .ToElements())

    for room in target_rooms:

        xy = room_xy(room)
        if xy not in source_dict:
            continue

        src_number = source_dict[xy]
        if not src_number:
            continue

        new_number = replace_first_index(src_number, lvl_str)

        param = room.get_Parameter(BuiltInParameter.ROOM_NUMBER)
        param.Set(new_number)

t.Commit()
