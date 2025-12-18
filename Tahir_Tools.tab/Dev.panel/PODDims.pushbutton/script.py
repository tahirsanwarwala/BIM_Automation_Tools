# -*- coding: utf-8 -*-
__title__ = "POD Dimension"
__doc__ = """"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# ==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import Selection, ObjectType
from Autodesk.Revit.Creation import ItemFactoryBase
from pyrevit import revit, forms
import clr

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
options = Options()

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
# ==================================================

all_grids = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Grids).WhereElementIsNotElementType().ToElements()
for grid in all_grids:
    if grid.Name == "3":
        grid1 = grid
    elif grid.Name == "4":
        grid2 = grid

plum_fix = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_PlumbingFixtures).WhereElementIsNotElementType().ToElements()
floor_traps = [plum for plum in plum_fix if "FWS" in plum.Name]

ref1 = Reference(grid1)
ref2 = Reference(grid2)
ref3 = floor_traps[0].GetReferences(FamilyInstanceReferenceType.CenterLeftRight)[0]
ref4 = floor_traps[1].GetReferences(FamilyInstanceReferenceType.CenterLeftRight)[0]

options.View = view
pod = selection.PickObject(ObjectType.Element, "Select POD")
sel_pod = doc.GetElement(pod)
setout = sel_pod.get_Geometry(options)

# for e in setout:
#     set2 = e.GetInstanceGeometry()
#     for el in set2:
#         if isinstance(el, Line):
#             if round(el.Length,10) == round(0.00328083989,10):
#                 # print(el)

# setout_line = setout.GetInstanceGeometry("Line")
# print(setout_line)

refArray = ReferenceArray()
refArray.Append(ref1)
refArray.Append(ref2)
refArray.Append(ref3)
refArray.Append(ref4)

mid1 = grid1.Curve.Evaluate(0.5,True)
mid2 = grid2.Curve.Evaluate(0.5,True)
dim_line = Line.CreateBound(mid1,mid2)

t = Transaction(doc, "Create POD Dimension")
t.Start()
new_dim = doc.Create.NewDimension(view, dim_line, refArray)
t.Commit()



