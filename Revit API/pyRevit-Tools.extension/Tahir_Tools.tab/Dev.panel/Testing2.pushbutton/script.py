# -*- coding: utf-8 -*-
__title__ = "Test Script 2"

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script


uidoc = revit.uidoc
doc = revit.doc
output = script.get_output()


# ---------------------------------------------------
# Filter
# ---------------------------------------------------
class RoomSelectionFilter(ISelectionFilter):
    def AllowElement(self, e):
        try:
            return isinstance(e, SpatialElement) and \
                   e.Category.Id.IntegerValue == int(BuiltInCategory.OST_Rooms)
        except Exception as ex:
            output.print_md("Filter error: {}".format(ex))
            return False

    def AllowReference(self, r, p):
        return True


# ---------------------------------------------------
# Helpers
# ---------------------------------------------------
def room_xy(room):
    try:
        loc = room.Location
        if isinstance(loc, LocationPoint):
            p = loc.Point
            return (round(p.X, 3), round(p.Y, 3))
        else:
            output.print_md("Room {} has no LocationPoint".format(room.Id))
    except Exception as ex:
        output.print_md("XY read failed for room {} : {}".format(room.Id, ex))
    return None


def get_param(room, name):
    try:
        p = room.LookupParameter(name)
        if not p:
            output.print_md("Missing parameter '{}' on room {}".format(name, room.Id))
            return None
        return p.AsString()
    except Exception as ex:
        output.print_md("Read failed '{}' on room {} : {}".format(name, room.Id, ex))
        return None


def set_param(room, name, value):
    try:
        if value is None:
            return

        p = room.LookupParameter(name)
        if not p:
            output.print_md("Missing target parameter '{}' on room {}".format(name, room.Id))
            return

        if p.IsReadOnly:
            output.print_md("Parameter '{}' read-only on room {}".format(name, room.Id))
            return

        p.Set(value)

    except Exception as ex:
        output.print_md("Write failed '{}' on room {} : {}".format(name, room.Id, ex))


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
except Exception as ex:
    output.print_md("Selection failed: {}".format(ex))
    raise SystemExit


try:
    source_rooms = [doc.GetElement(r.ElementId) for r in refs if doc.GetElement(r.ElementId)]
    if not source_rooms:
        output.print_md("No valid source rooms selected.")
        raise SystemExit
except Exception as ex:
    output.print_md("Source room processing failed: {}".format(ex))
    raise SystemExit


# ---------------------------------------------------
# Choose target levels
# ---------------------------------------------------
try:
    source_level = doc.GetElement(source_rooms[0].LevelId)

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

except Exception as ex:
    output.print_md("Target level selection failed: {}".format(ex))
    raise SystemExit


# ---------------------------------------------------
# Build source dictionary
# ---------------------------------------------------
source_dict = {}

try:
    for r in source_rooms:
        xy = room_xy(r)
        if not xy:
            continue

        pod_a = get_param(r, "POD Type A")
        pod_b = get_param(r, "POD Type B")

        source_dict[xy] = (pod_a, pod_b)

    if not source_dict:
        output.print_md("No valid source parameter values found.")
        raise SystemExit

except Exception as ex:
    output.print_md("Building source dictionary failed: {}".format(ex))
    raise SystemExit


# ---------------------------------------------------
# Copy values
# ---------------------------------------------------
t = Transaction(doc, "Copy POD Type Params By Location")

try:
    t.Start()

    for lvl in target_levels:

        try:
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

                pod_a, pod_b = source_dict[xy]

                set_param(room, "POD Type A", pod_a)
                set_param(room, "POD Type B", pod_b)

        except Exception as ex:
            output.print_md("Failed processing level {} : {}".format(lvl.Name, ex))

    t.Commit()

except Exception as ex:
    output.print_md("Transaction failed: {}".format(ex))
    if t.HasStarted():
        t.RollBack()
