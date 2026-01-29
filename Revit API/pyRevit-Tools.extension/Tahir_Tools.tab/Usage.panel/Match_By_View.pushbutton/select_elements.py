# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

app       = __revit__.Application
uidoc     = __revit__.ActiveUIDocument
doc       = __revit__.ActiveUIDocument.Document
view      = doc.ActiveView
selection = uidoc.Selection

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def select_element():
    try:
        selected_element_ids = selection.GetElementIds()
        selected_elements = [doc.GetElement(e_id) for e_id in selected_element_ids]
        if not selected_elements or len(selected_elements) > 1:
            ref = uidoc.Selection.PickObject(
                ObjectType.Element,
                "Select source element"
            )
            return doc.GetElement(ref.ElementId)
        return selected_elements[0]
    except OperationCanceledException:
        return None