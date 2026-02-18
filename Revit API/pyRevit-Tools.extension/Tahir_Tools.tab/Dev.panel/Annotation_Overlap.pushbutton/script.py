# -*- coding: utf-8 -*-
__title__ = "Anno Overlap Check"

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script
import clr
from System.Collections.Generic import List

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
active_view = uidoc.ActiveView

if active_view.IsTemplate:
    forms.alert("Active view is a View Template. Open a normal view.", exitscript=True)

tags = list(
    FilteredElementCollector(doc, active_view.Id)
    .WhereElementIsNotElementType()
    .OfClass(IndependentTag)
    .ToElements()
)

dims = list(
    FilteredElementCollector(doc, active_view.Id)
    .WhereElementIsNotElementType()
    .OfClass(Dimension)
    .ToElements()
)

text = list(
    FilteredElementCollector(doc, active_view.Id)
    .WhereElementIsNotElementType()
    .OfClass(TextNote)
    .ToElements()
)
all_annotations = tags + dims + text

annotation_boxes = []
for el in all_annotations:
    bbox = el.get_BoundingBox(active_view)
    if bbox is None:
        continue

    anno_dict = {
        "id": el.Id.IntegerValue,
        "category": el.Category.Name if el.Category else "Unknown",
        "minX": bbox.Min.X,
        "minY": bbox.Min.Y,
        "maxX": bbox.Max.X,
        "maxY": bbox.Max.Y
    }
    annotation_boxes.append(anno_dict)

overlapping_ids = set()
tolerance = 0.01
for i in range(len(annotation_boxes)):
    for j in range(i+1, len(annotation_boxes)):
        r1 = annotation_boxes[i]
        r2 = annotation_boxes[j]

        if not (
            r1["maxX"] < r2["minX"] - tolerance or
            r1["minX"] > r2["maxX"] + tolerance or
            r1["maxY"] < r2["minY"] - tolerance or
            r1["minY"] > r2["maxY"] + tolerance
        ):
            overlapping_ids.add(r1["id"])
            overlapping_ids.add(r2["id"])

if overlapping_ids:

    element_ids = List[ElementId]()

    for id_int in overlapping_ids:
        element_ids.Add(ElementId(id_int))

    uidoc.Selection.SetElementIds(element_ids)

    print("Selected {} overlapping elements.".format(len(overlapping_ids)))

else:
    print("No overlapping annotations found.")