# -*- coding: utf-8 -*-
__title__ = "Door Params Copy"

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# ==================================================

import clr
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ISelectionFilter
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import forms
from Autodesk.Revit.Exceptions import OperationCanceledException



clr.AddReference("System")
from System.Collections.Generic import List, ICollection

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
# ==================================================
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app = __revit__.Application
view = doc.ActiveView
selection = uidoc.Selection
phase = doc.Phases
parameter_name = "Mark"


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
# ==================================================
class DoorSelectionFilter(ISelectionFilter):
    """Filter to only allow door selection"""

    def AllowElement(self, element):
        # Only allow doors to be selected
        if element.Category and element.Category.Id.IntegerValue == int(BuiltInCategory.OST_Doors):
            return True
        return False

    def AllowReference(self, reference, position):
        return False

def select_doors():
    """
    Prompt user to select a door and print its ToRoom number.
    """
    try:

        # Create selection filter
        selection_filter = DoorSelectionFilter()

        # Prompt user to select a door
        reference = uidoc.Selection.PickObjects(ObjectType.Element,selection_filter,"Select Doors")

        # Get the selected element
        door_sel = [doc.GetElement(ref) for ref in reference]
        return door_sel

    except Exception as e:
        return None

def get_door_xy(door_element):
    """Get XY coordinates of door location, rounded for comparison."""
    loc = door_element.Location
    if isinstance(loc, LocationPoint):
        point = loc.Point
        # Round to 4 decimal places to handle floating point precision
        return round(point.X, 4), round(point.Y, 4)
    return None

def get_target_levels(source):
    try:
        source_lvl = doc.GetElement(source[0].LevelId).Name
        # Get all levels in the project
        levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
        level_dict = {level.Name: level for level in levels}

        sorted_levels = sorted(levels, key=lambda l: l.Elevation)
        level_names = [level.Name for level in sorted_levels]

        # Get source level
        target_levels = forms.SelectFromList.show(
            [name for name in level_names if name != source_lvl ],
            title="Select Target Level",
            button_name="Select", multiselect=True
        )

        levels = [level_dict[l] for l in target_levels]
        return levels

    except Exception as e:
        raise SystemExit


def copy_params(target):
    source_door = source_dict[target]
    source_param = source_door.LookupParameter(parameter_name).AsString()
    if source_param:
        if source_param.startswith("Unit"):
            if door.ToRoom[phase[1]]:
                room_number = door.ToRoom[phase[1]].Number
            elif door.FromRoom[phase[1]]:
                room_number = door.FromRoom[phase[1]].Number
            else:
                room_number = None
            if room_number:
                room_name = source_param.split()
                room_name[1] = str(room_number)
                new_room = " ".join(room_name)
                target_param = door.LookupParameter(parameter_name)
                target_param.Set(new_room)
        if source_param.startswith("L"):
            level_name = level.Name.split()
            level_num = level_name[1]
            mark = source_param.split(".")
            mark[0] = f"L{level_num}"
            new_mark = ".".join(mark)
            target_param = door.LookupParameter(parameter_name)
            target_param.Set(new_mark)
        # else:
        #     print(f"Door ID: {door.Id} has no {parameter_name} value.")


source_doors = select_doors()
levels = get_target_levels(source_doors)
source_dict = {}
for door in source_doors:
    source_xy = get_door_xy(door)
    source_dict[source_xy] = door

t = Transaction(doc, "Copy Params")
t.Start()
for level in levels:
    level_filter = ElementLevelFilter(level.Id)
    doors = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors).WherePasses(level_filter).ToElements()
    for door in doors:
        target_xy = get_door_xy(door)
        if target_xy in source_dict:
            copy_params(target_xy)
t.Commit()