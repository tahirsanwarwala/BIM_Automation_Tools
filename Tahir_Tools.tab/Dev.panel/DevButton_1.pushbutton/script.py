# -*- coding: utf-8 -*-
__title__ = "Levels Align"
__doc__ = """Version = 1.0
Date    = 15.07.2024"""

# IMPORTS
#==================================================
# Regular + Autodesk
from Autodesk.Revit.DB import *

# .NET Imports (You often need List import)
import clr
clr.AddReference("System")
from System.Collections.Generic import List
from Autodesk.Revit.UI import UIDocument
from Autodesk.Revit.ApplicationServices import Application


# VARIABLES
#==================================================
doc   = __revit__.ActiveUIDocument.Document #type: Document
active = doc.ActiveView
uidoc = __revit__.ActiveUIDocument          #type: UIDocument
app   = __revit__.Application               #type: Application

# MAIN
#==================================================
# correct_level    = doc.GetElement(ElementId(762033))
# reference_leader = correct_level.GetLeader(DatumEnds.End1, active)
# ref_end = reference_leader.End
# ref_elbow = reference_leader.Elbow
# ref_anchor = reference_leader.Anchor
selected_element_ids = uidoc.Selection.GetElementIds()
selected_elements    = [doc.GetElement(e_id) for e_id in selected_element_ids]

with Transaction(doc, "Level Change") as t:
    t.Start()
    for e in selected_elements:
        # e.ShowBubbleInView(DatumEnds.End1, active)
        # e.HideBubbleInView(DatumEnds.End0, active)
        e.AddLeader(DatumEnds.End1, active)
        # new_leader = e.GetLeader(DatumEnds.End1, active)
        # # new_leader.End = ref_end
        # new_leader.Elbow = XYZ(290.368710829, 122.113768781, 478.879593176)
    t.Commit()