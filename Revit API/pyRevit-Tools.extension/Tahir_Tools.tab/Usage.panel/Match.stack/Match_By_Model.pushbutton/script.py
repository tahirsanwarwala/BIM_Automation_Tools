# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    Level,
    ElementLevelFilter,
    LocationPoint,
    LocationCurve,
    ElementId
)
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List
from pyrevit import forms

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
selection = uidoc.Selection


# ------------------------------------------------------------
# Select source element
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


# ------------------------------------------------------------
# Universal location signature
# ------------------------------------------------------------
def get_location_signature(element, precision=4):
    loc = element.Location
    if not loc:
        return None

    if isinstance(loc, LocationPoint):
        pt = loc.Point
        return (
            'POINT',
            (round(pt.X, precision), round(pt.Y, precision))
        )

    if isinstance(loc, LocationCurve):
        curve = loc.Curve
        p1 = curve.GetEndPoint(0)
        p2 = curve.GetEndPoint(1)

        pt1 = (round(p1.X, precision), round(p1.Y, precision))
        pt2 = (round(p2.X, precision), round(p2.Y, precision))

        return (
            'CURVE',
            tuple(sorted([pt1, pt2]))
        )

    return None


# ------------------------------------------------------------
# Single-pass model element matching
# ------------------------------------------------------------
def get_level_element_map(source_elm):

    source_sig = get_location_signature(source_elm)
    if not source_sig:
        return {}

    source_category = source_elm.Category.BuiltInCategory
    source_level_id = source_elm.LevelId

    levels = (
        FilteredElementCollector(doc)
        .OfClass(Level)
        .ToElements()
    )

    level_element_map = {}

    for level in levels:

        level_filter = ElementLevelFilter(level.Id)

        elements = (
            FilteredElementCollector(doc)
            .OfCategory(source_category)
            .WherePasses(level_filter)
            .ToElements()
        )

        matched_ids = []

        for e in elements:
            if get_location_signature(e) == source_sig:
                matched_ids.append(e.Id)

        if matched_ids:
            level_element_map[level] = matched_ids

    return level_element_map


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
def match_by_model(source):

    if not source:
        forms.alert("No element selected.", title="Cancelled")
        raise SystemExit

    level_data = get_level_element_map(source)

    if not level_data:
        forms.alert("No matching elements found.", title="Result")
        raise SystemExit


    # UI (sorted)
    sorted_levels = sorted(level_data.keys(), key=lambda l: l.Elevation)
    level_dict = {lvl.Name: lvl for lvl in sorted_levels}
    level_names = [lvl.Name for lvl in sorted_levels]

    selected_names = forms.SelectFromList.show(
        level_names,
        title="Select Target Levels",
        multiselect=True,
        button_name="Select"
    )

    if not selected_names:
        raise SystemExit

    selected_ids = List[ElementId]()
    for name in selected_names:
        lvl = level_dict[name]
        for eid in level_data[lvl]:
            selected_ids.Add(eid)

    selection.SetElementIds(selected_ids)

source_elm = select_element()
if not source_elm.ViewSpecific:
    match_by_model(source_elm)
else:
    forms.alert("View Specific Element.", title="Cancelled")
    raise SystemExit
