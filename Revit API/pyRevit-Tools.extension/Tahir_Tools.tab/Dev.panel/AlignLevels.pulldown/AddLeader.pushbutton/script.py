# -*- coding: utf-8 -*-
__title__   = "Add Elbows"
__author__ = ""
__doc__     = """Date    = 23.01.2026
________________________________________________________________
Description:

"""
# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *

#.NET Imports
import clr

clr.AddReference('System')
from System.Collections.Generic import List



# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
app    = __revit__.Application
uidoc  = __revit__.ActiveUIDocument
doc    = __revit__.ActiveUIDocument.Document #type:Document
view = doc.ActiveView
selection = uidoc.Selection



# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
#==================================================
# -------------------------------
# Pick SOURCE datum (with leader)
# -------------------------------
class LevelSelectionFilter(ISelectionFilter):
    """Filter to only allow level selection"""

    def AllowElement(self, element):
        # Only allow levels to be selected
        if element.Category and element.Category.Id.IntegerValue == int(BuiltInCategory.OST_Levels):
            return True
        return False

    def AllowReference(self, reference, position):
        return False

def select_levels():
    try:

        # Create selection filter
        selection_filter = LevelSelectionFilter()

        # Prompt user to select a level
        reference = uidoc.Selection.PickObjects(ObjectType.Element,selection_filter,"Select Levels")

        # Get the selected element
        level_sel = [doc.GetElement(ref) for ref in reference]
        return level_sel

    except Exception as e:
        return None

def get_bubble_end(datum, view):
    """
    Returns the DatumEnds value (End0 or End1) that currently
    has a leader in the given view, or None if neither does.
    """
    for end in [DatumEnds.End0, DatumEnds.End1]:
        try:
            if datum.IsBubbleVisibleInView(end, view):
                return end
        except:
            pass
    return None

t = Transaction(doc, "Add Level Elbow")

offset = 3
right = view.RightDirection
up = view.UpDirection

target_levels = select_levels()

try:
    t.Start()
    for level in target_levels:
        src_end = get_bubble_end(level, view)
        level.ShowBubbleInView(src_end, view)
        if level.GetLeader(src_end, view) is None:
            level.AddLeader(src_end, view)
        else:
            new_leader = level.GetLeader(src_end, view)
            if new_leader.Elbow.Z == new_leader.End.Z:
                new_leader.Elbow += right.Multiply(offset)
                new_leader.Elbow += up.Multiply(offset)
            level.SetLeader(src_end, view, new_leader)
    t.Commit()
except Exception as e:
    print(e)
    t.RollBack()