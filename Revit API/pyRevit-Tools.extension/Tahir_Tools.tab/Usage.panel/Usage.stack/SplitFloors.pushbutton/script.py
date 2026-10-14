# -*- coding: utf-8 -*-
"""
Split Floors
For each selected floor that contains multiple closed sketch loops,
creates one new individual floor per loop (same type and parameters),
then deletes the original. Floors with only a single loop are skipped.
"""

__title__  = "Split\nFloors"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Select one or more floor elements. Each floor whose sketch contains "
    "multiple closed loops is split into individual floors (one per loop) "
    "of the same type, level, and parameters. The original floor is deleted. "
    "Floors with only a single loop are skipped silently."
)

import clr
import math
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    CurveLoop,
    ElementId,
    Floor,
    Transaction,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()

TOLERANCE = 1e-6  # feet


# ===============================================================================
# SELECTION FILTER
# ===============================================================================

class FloorFilter(ISelectionFilter):
    """Allow only Floor elements to be selected."""

    def AllowElement(self, elem):
        return isinstance(elem, Floor)

    def AllowReference(self, ref, point):
        return False


# ===============================================================================
# HELPER UTILITIES
# ===============================================================================

def get_height_offset(floor):
    """Return the 'Height Offset From Level' value (in feet) for a floor, or 0.0."""
    p = floor.LookupParameter("Height Offset From Level")
    if p and p.HasValue:
        return p.AsDouble()
    return 0.0


def get_is_structural(floor):
    """Return True if the floor's 'Structural' flag is set."""
    p = floor.LookupParameter("Structural")
    if p and p.HasValue:
        return bool(p.AsInteger())
    return False


def get_name(element):
    """Safely get the Name of any Revit element (handles IronPython quirks)."""
    if element is None:
        return "<null>"
    try:
        return element.Name
    except Exception:
        pass
    try:
        p = element.LookupParameter("Type Name")
        if p:
            return p.AsString()
    except Exception:
        pass
    try:
        return str(element.Id.IntegerValue)
    except Exception:
        return "<unknown>"


def get_loop_span_angle(curve_loop):
    """
    Find the longest curve within a single CurveLoop and return its
    orientation angle in radians (from +X axis). Used to set SpanDirectionAngle
    on each individually created split floor.
    """
    longest_len = -1.0
    angle       = 0.0

    for crv in curve_loop:
        try:
            length = crv.Length
            if length > longest_len:
                longest_len = length
                sp = crv.GetEndPoint(0)
                ep = crv.GetEndPoint(1)
                dx = ep.X - sp.X
                dy = ep.Y - sp.Y
                angle = math.atan2(dy, dx)
        except Exception:
            continue

    return angle


# ===============================================================================
# SELECTION
# ===============================================================================

def get_floors_from_selection():
    """
    Use pre-selected elements if 1+ floors are present; otherwise prompt
    the user to pick. Returns a list of Floor elements, or None on cancel.
    """
    pre_ids = list(uidoc.Selection.GetElementIds())
    floors  = [doc.GetElement(eid) for eid in pre_ids
               if isinstance(doc.GetElement(eid), Floor)]

    if floors:
        return floors

    # Nothing useful pre-selected -> go straight to PickObjects
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            FloorFilter(),
            "Select floors to split - press Finish when done",
        )
    except Exception:
        return None  # user pressed Escape

    floors = [doc.GetElement(r.ElementId) for r in refs]
    floors = [f for f in floors if isinstance(f, Floor)]
    return floors if floors else None


# ===============================================================================
# SKETCH EXTRACTION
# ===============================================================================

def extract_curve_loops(floor):
    """
    Read the floor's Sketch and return a list of CurveLoop objects,
    one per closed boundary loop in the sketch profile.
    Raises RuntimeError if the sketch is missing.
    """
    sketch_id = floor.SketchId
    if sketch_id is None or sketch_id == ElementId.InvalidElementId:
        raise RuntimeError(
            "Floor id {} has no sketch.".format(floor.Id.IntegerValue)
        )

    sketch = doc.GetElement(sketch_id)
    if sketch is None:
        raise RuntimeError(
            "Could not retrieve Sketch for floor id {}.".format(
                floor.Id.IntegerValue)
        )

    loops = []
    for curve_arr in sketch.Profile:
        loop = CurveLoop()
        for crv in curve_arr:
            loop.Append(crv)
        loops.append(loop)

    return loops


# ===============================================================================
# SPLIT ONE FLOOR
# ===============================================================================

def split_floor(floor):
    """
    Split a single floor into one new floor per sketch loop.
    Returns (True, n_created) on success, or (False, error_message) on failure.
    Skips floors with only 1 loop (returns (True, 0)).
    """
    # Extract loops
    try:
        loops = extract_curve_loops(floor)
    except RuntimeError as ex:
        return False, str(ex)

    # Skip single-loop floors silently
    if len(loops) < 2:
        return True, 0

    # Cache all properties before the transaction (floor will be deleted)
    floor_type_id = floor.FloorType.Id
    level_id      = floor.LevelId
    height_offset = get_height_offset(floor)
    is_structural = get_is_structural(floor)
    floor_id_int  = floor.Id.IntegerValue

    # One transaction per source floor so failures don't affect other floors
    with Transaction(doc, "Split Floor {}".format(floor_id_int)) as t:
        t.Start()
        try:
            from System.Collections.Generic import List as NetList

            created = 0
            for loop in loops:
                # Build a single-loop list for Floor.Create
                loop_list = NetList[CurveLoop]()
                loop_list.Add(loop)

                new_floor = Floor.Create(doc, loop_list, floor_type_id, level_id)

                # Height offset
                offset_param = new_floor.LookupParameter("Height Offset From Level")
                if offset_param and not offset_param.IsReadOnly:
                    offset_param.Set(height_offset)

                # Structural flag
                struct_param = new_floor.LookupParameter("Structural")
                if struct_param and not struct_param.IsReadOnly:
                    struct_param.Set(1 if is_structural else 0)

                # Span direction: longest line within THIS loop
                try:
                    span_angle = get_loop_span_angle(loop)
                    new_floor.SpanDirectionAngle = span_angle
                except Exception as ex:
                    logger.warning(
                        "Could not set SpanDirectionAngle on split floor: {}".format(ex)
                    )

                created += 1

            # Delete the original floor
            doc.Delete(floor.Id)

            t.Commit()
            return True, created

        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            return False, str(ex)


# ===============================================================================
# MAIN
# ===============================================================================

def main():
    # Step 1: Selection
    floors = get_floors_from_selection()

    if not floors:
        script.exit()

    # Step 2: Process each floor
    failed = []   # list of (floor_id_int, error_message) tuples

    for floor in floors:
        success, result = split_floor(floor)
        if not success:
            failed.append((floor.Id.IntegerValue, result))

    # Step 3: Report errors only
    if failed:
        lines = ["Floor id {}: {}".format(fid, msg) for fid, msg in failed]
        forms.alert(
            "The following floor(s) could not be split and were kept intact:\n\n"
            + "\n".join("- " + l for l in lines),
            title="Split Floors - Errors",
        )


main()
