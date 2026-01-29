# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List
from pyrevit import forms
from select_elements import *
app       = __revit__.Application
uidoc     = __revit__.ActiveUIDocument
doc       = __revit__.ActiveUIDocument.Document
view      = doc.ActiveView
selection = uidoc.Selection

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

source = select_element()
print(source)