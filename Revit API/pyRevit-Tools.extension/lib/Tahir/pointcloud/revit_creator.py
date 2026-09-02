# -*- coding: utf-8 -*-
"""
Revit MEP Element Creation Helpers.
Creates native Revit Conduit elements from fitted geometry data.
Handles level detection, type selection, and diameter parameter setting.

Targeted at Revit 2025 (.NET 8 / API 2025).
"""

try:
    import clr
    clr.AddReference('RevitAPI')
    from Autodesk.Revit.DB import (
        XYZ, ElementId, BuiltInParameter,
        FilteredElementCollector, Level,
    )
    from Autodesk.Revit.DB.Electrical import Conduit, ConduitType
    HAS_REVIT = True
except ImportError:
    HAS_REVIT = False


def get_nearest_level(doc, elevation_ft):
    """
    Find the Level closest to a given elevation.

    Args:
        doc:           Revit Document.
        elevation_ft:  Target elevation in feet.

    Returns:
        Level element closest to the given elevation.
    """
    levels = list(
        FilteredElementCollector(doc)
        .OfClass(Level)
        .ToElements()
    )
    if not levels:
        return None

    return min(levels, key=lambda lv: abs(lv.Elevation - elevation_ft))


def get_conduit_type_id(doc, type_name=None):
    """
    Find a ConduitType by name, or return the first available type.

    Args:
        doc:       Revit Document.
        type_name: Optional conduit type family name to match.

    Returns:
        ElementId of the matching ConduitType, or InvalidElementId.
    """
    types = list(
        FilteredElementCollector(doc)
        .OfClass(ConduitType)
        .ToElements()
    )
    if not types:
        return ElementId.InvalidElementId

    if type_name:
        for ct in types:
            if type_name.lower() in ct.Name.lower():
                return ct.Id

    return types[0].Id


def create_conduit(doc, start_xyz, end_xyz, diameter_ft, level_id,
                   conduit_type_id=None):
    """
    Create a single Revit Conduit element.

    Args:
        doc:              Revit Document.
        start_xyz:        [x, y, z] list/tuple in feet.
        end_xyz:          [x, y, z] list/tuple in feet.
        diameter_ft:      Nominal diameter in feet.
        level_id:         ElementId of the reference Level.
        conduit_type_id:  Optional ElementId of ConduitType.

    Returns:
        Created Conduit element, or None on failure.
    """
    if not HAS_REVIT:
        return None

    if conduit_type_id is None or conduit_type_id == ElementId.InvalidElementId:
        conduit_type_id = get_conduit_type_id(doc)

    p1 = XYZ(float(start_xyz[0]), float(start_xyz[1]), float(start_xyz[2]))
    p2 = XYZ(float(end_xyz[0]), float(end_xyz[1]), float(end_xyz[2]))

    conduit = Conduit.Create(doc, conduit_type_id, p1, p2, level_id)

    # Set diameter
    dia_param = conduit.get_Parameter(
        BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM
    )
    if dia_param and not dia_param.IsReadOnly:
        dia_param.Set(diameter_ft)

    return conduit


def create_conduits_from_candidates(doc, candidates, level_id=None,
                                    conduit_type_id=None):
    """
    Batch-create Conduit elements from a list of candidate dicts.

    Each candidate dict must have keys:
        start_point, end_point, nominal_diameter_ft

    Args:
        doc:              Revit Document.
        candidates:       List of candidate dicts from the pipeline.
        level_id:         Optional Level ElementId (auto-detected if None).
        conduit_type_id:  Optional ConduitType ElementId.

    Returns:
        list of (candidate_dict, conduit_element_or_None, error_message_or_None)
    """
    results = []

    if conduit_type_id is None:
        conduit_type_id = get_conduit_type_id(doc)

    for cand in candidates:
        start = cand['start_point']
        end = cand['end_point']
        dia_ft = cand['nominal_diameter_ft']

        # Auto-detect level from midpoint Z
        if level_id is None:
            mid_z = (start[2] + end[2]) / 2.0
            lv = get_nearest_level(doc, mid_z)
            lvl_id = lv.Id if lv else ElementId.InvalidElementId
        else:
            lvl_id = level_id

        try:
            elem = create_conduit(
                doc, start, end, dia_ft, lvl_id, conduit_type_id
            )
            results.append((cand, elem, None))
        except Exception as ex:
            results.append((cand, None, str(ex)))

    return results
