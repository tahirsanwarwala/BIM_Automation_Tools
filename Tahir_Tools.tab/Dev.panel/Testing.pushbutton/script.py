# -*- coding: utf-8 -*-
__title__ = "Test Scripts"
__doc__ = """Date = 23.01.2026
________________________________________________________________
Description:
Aligns level leader elbows and ends to match a source leader
in a geometry-safe, view-independent way.
"""
# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from Tahir.LevelSelection import LevelSelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException


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
# -------------------------
# Select multiple target levels
# -------------------------
def select_levels():
    try:
        selection_filter = LevelSelectionFilter()
        references = uidoc.Selection.PickObjects(
            ObjectType.Element,
            selection_filter,
            "Select target Levels"
        )
        return [doc.GetElement(ref) for ref in references]

    except OperationCanceledException:
        return None

    except Exception as ex:
        print("Level selection failed:", ex)
        return None


# -------------------------
# Pick SOURCE datum
# -------------------------
try:
    ref_src = selection.PickObject(
        ObjectType.Element,
        "Pick SOURCE datum (with leader)"
    )
    src_datum = doc.GetElement(ref_src)
except OperationCanceledException:
    raise SystemExit

except Exception as ex:
    print("Failed to pick source datum:", ex)
    raise SystemExit


# -------------------------
# Get SOURCE leader safely
# -------------------------

for end in [DatumEnds.End0, DatumEnds.End1]:
    if src_datum.IsBubbleVisibleInView(end, view):
        src_end = end

if src_end is None:
    print("Source datum has no leader at End0 or End1 in this view.")
    raise SystemExit

