# -*- coding: utf-8 -*-
"""
Merge Floors
Combines sketch boundaries of multiple floor elements (that share the same
type, reference level, and Height Offset from Level) into a single new floor,
then deletes the originals.
"""

__title__  = "Merge\nFloors"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Select 2 or more floor elements that share the same type, reference level, "
    "and Height Offset from Level. The script merges their sketch boundaries into "
    "a single new floor and deletes the originals."
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
output = script.get_output()
logger = script.get_logger()

# tolerance for coincident endpoint / edge comparison (feet)
TOLERANCE = 1e-6


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
    """Safely get the Name of any Revit element (handles IronPython attribute quirks)."""
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


def pt_equal(a, b, tol=TOLERANCE):
    """Check if two XYZ points are within tolerance."""
    return (abs(a.X - b.X) < tol and
            abs(a.Y - b.Y) < tol and
            abs(a.Z - b.Z) < tol)


def curves_share_edge(c1, c2, tol=TOLERANCE):
    """
    Return True if two curves are coincident with the same endpoints
    (in either direction), meaning they form a shared wall between two floors.
    """
    try:
        s1, e1 = c1.GetEndPoint(0), c1.GetEndPoint(1)
        s2, e2 = c2.GetEndPoint(0), c2.GetEndPoint(1)
        return ((pt_equal(s1, s2, tol) and pt_equal(e1, e2, tol)) or
                (pt_equal(s1, e2, tol) and pt_equal(e1, s2, tol)))
    except Exception:
        return False


# ===============================================================================
# STEP 1 - GET SELECTION
# ===============================================================================

def get_floors_from_selection():
    """
    Try pre-selection first; fall back to PickObjects prompt.
    Returns a list of Floor elements, or None if user cancelled.
    """
    pre_ids = list(uidoc.Selection.GetElementIds())
    floors  = [doc.GetElement(eid) for eid in pre_ids
               if isinstance(doc.GetElement(eid), Floor)]

    if len(floors) >= 2:
        return floors

    # Nothing useful pre-selected -> ask the user to pick
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            FloorFilter(),
            "Select 2 or more floors - press Finish when done",
        )
    except Exception:
        return None  # user pressed Escape

    floors = [doc.GetElement(r.ElementId) for r in refs]
    floors = [f for f in floors if isinstance(f, Floor)]
    return floors if floors else None


# ===============================================================================
# STEP 2 - VALIDATE SIMILARITY
# ===============================================================================

def validate_floors(floors):
    """
    Check that all floors share the same FloorType, Level, and Height Offset.

    Returns (True, reference_floor) on success, or
            (False, error_message_string) on failure.
    """
    ref    = floors[0]
    errors = []

    ref_type_id  = ref.FloorType.Id
    ref_level_id = ref.LevelId
    ref_offset   = get_height_offset(ref)

    for i, fl in enumerate(floors[1:], start=2):
        floor_label = "Floor #{} (id {})".format(i, fl.Id.IntegerValue)

        # Type check
        if fl.FloorType.Id != ref_type_id:
            errors.append(
                "{}: type '{}' != reference type '{}'".format(
                    floor_label, get_name(fl.FloorType), get_name(ref.FloorType))
            )

        # Level check
        if fl.LevelId != ref_level_id:
            ref_level = doc.GetElement(ref_level_id)
            fl_level  = doc.GetElement(fl.LevelId)
            errors.append(
                "{}: level '{}' != reference level '{}'".format(
                    floor_label,
                    get_name(fl_level)  if fl_level  else str(fl.LevelId.IntegerValue),
                    get_name(ref_level) if ref_level else str(ref_level_id.IntegerValue),
                )
            )

        # Height Offset check
        fl_offset = get_height_offset(fl)
        if abs(fl_offset - ref_offset) > TOLERANCE:
            errors.append(
                "{}: Height Offset {:.4f} ft != reference {:.4f} ft".format(
                    floor_label, fl_offset, ref_offset)
            )

    if errors:
        msg = (
            "The selected floors are NOT compatible for merging.\n\n"
            + "\n".join("- " + e for e in errors)
        )
        return False, msg

    return True, ref


# ===============================================================================
# STEP 3 - EXTRACT SKETCH BOUNDARY LOOPS
# ===============================================================================

def extract_curve_loops(floors):
    """
    For each floor, read its Sketch and return all CurveLoop objects
    (one per closed boundary loop in the sketch profile).

    Returns list of CurveLoop, or raises RuntimeError if any sketch is missing.
    """
    all_loops = []

    for fl in floors:
        sketch_id = fl.SketchId
        if sketch_id is None or sketch_id == ElementId.InvalidElementId:
            raise RuntimeError(
                "Floor id {} has no sketch - cannot extract boundary.".format(
                    fl.Id.IntegerValue)
            )

        sketch = doc.GetElement(sketch_id)
        if sketch is None:
            raise RuntimeError(
                "Could not retrieve Sketch for floor id {}.".format(
                    fl.Id.IntegerValue)
            )

        # sketch.Profile is a CurveArrArray; each CurveArray is one closed loop
        profile = sketch.Profile
        for curve_arr in profile:
            loop = CurveLoop()
            for crv in curve_arr:
                loop.Append(crv)
            all_loops.append(loop)

    return all_loops


# ===============================================================================
# STEP 4 - SHARED-EDGE CLEANUP
# ===============================================================================

def remove_shared_edges(loops):
    """
    When two adjacent floors share an edge, that edge appears twice in the
    combined loop set (once in each floor's boundary). Removing both copies
    gives Revit a single clean outer perimeter.

    Returns (cleaned_loops, warning_flag).
    """
    # Flatten all curves from all loops
    all_curves = []
    for loop in loops:
        for crv in loop:
            all_curves.append(crv)

    # Find pairs of exactly coincident curves (shared edges)
    n         = len(all_curves)
    to_remove = set()

    for i in range(n):
        if i in to_remove:
            continue
        for j in range(i + 1, n):
            if j in to_remove:
                continue
            if curves_share_edge(all_curves[i], all_curves[j]):
                to_remove.add(i)
                to_remove.add(j)
                break

    if not to_remove:
        return loops, False

    remaining = [c for k, c in enumerate(all_curves) if k not in to_remove]

    if not remaining:
        return loops, True

    try:
        rebuilt_loops = _chain_into_loops(remaining)
        return rebuilt_loops, False
    except Exception as ex:
        logger.warning("Shared-edge cleanup failed to rebuild loops: {}".format(ex))
        return loops, True


def _chain_into_loops(curves):
    """
    Given an unordered list of curves, chain them into one or more closed
    CurveLoop objects by matching endpoints.
    """
    unused = list(range(len(curves)))
    loops  = []

    while unused:
        loop_curves = [curves[unused.pop(0)]]

        extended = True
        while extended:
            extended = False
            tail_pt  = loop_curves[-1].GetEndPoint(1)
            head_pt  = loop_curves[0].GetEndPoint(0)

            if pt_equal(tail_pt, head_pt):
                break

            for idx in list(unused):
                crv = curves[idx]
                sp  = crv.GetEndPoint(0)
                ep  = crv.GetEndPoint(1)

                if pt_equal(tail_pt, sp):
                    loop_curves.append(crv)
                    unused.remove(idx)
                    extended = True
                    break
                elif pt_equal(tail_pt, ep):
                    loop_curves.append(crv.CreateReversed())
                    unused.remove(idx)
                    extended = True
                    break

        cl = CurveLoop()
        for c in loop_curves:
            cl.Append(c)
        loops.append(cl)

    return loops


# ===============================================================================
# SPAN DIRECTION
# ===============================================================================

def get_span_direction_angle(curve_loops):
    """
    Iterate over every curve in every loop, find the longest one,
    and return its orientation angle in radians (measured from the +X axis).
    This angle is used to set Floor.SpanDirectionAngle on the new floor.
    """
    longest_len = -1.0
    angle       = 0.0

    for loop in curve_loops:
        for crv in loop:
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


def create_merged_floor(curve_loops, ref_floor):
    """
    Create a new Floor using Floor.Create() (Revit 2022+ API).
    Set Height Offset, structural flag, and span direction to match the
    source floors. Span direction is aligned to the longest sketch line.
    Returns the new Floor element.
    """
    floor_type_id = ref_floor.FloorType.Id
    level_id      = ref_floor.LevelId
    is_structural = get_is_structural(ref_floor)
    height_offset = get_height_offset(ref_floor)

    # Compute span direction from the longest curve in the combined sketch
    span_angle = get_span_direction_angle(curve_loops)

    # Convert list -> .NET generic list for the API
    from System.Collections.Generic import List as NetList
    curve_loop_list = NetList[CurveLoop]()
    for cl in curve_loops:
        curve_loop_list.Add(cl)

    # Revit 2022+ Floor.Create signature:
    # Floor.Create(Document, IList<CurveLoop>, ElementId floorTypeId, ElementId levelId)
    new_floor = Floor.Create(doc, curve_loop_list, floor_type_id, level_id)

    # Apply height offset
    offset_param = new_floor.LookupParameter("Height Offset From Level")
    if offset_param and not offset_param.IsReadOnly:
        offset_param.Set(height_offset)

    # Apply structural flag
    struct_param = new_floor.LookupParameter("Structural")
    if struct_param and not struct_param.IsReadOnly:
        struct_param.Set(1 if is_structural else 0)

    # Set span direction to the angle of the longest sketch line
    try:
        new_floor.SpanDirectionAngle = span_angle
        logger.debug("SpanDirectionAngle set to {:.4f} rad ({:.1f} deg)".format(
            span_angle, math.degrees(span_angle)))
    except Exception as ex:
        logger.warning(
            "Could not set SpanDirectionAngle ({:.4f} rad): {}".format(span_angle, ex)
        )

    return new_floor



# ===============================================================================
# MAIN
# ===============================================================================

def main():
    # Step 1: Selection
    floors = get_floors_from_selection()

    if not floors:
        script.exit()

    if len(floors) < 2:
        forms.alert(
            "Please select at least 2 floor elements.\n"
            "Only {} floor(s) were found in the selection.".format(len(floors)),
            title="Merge Floors - Not Enough Floors",
        )
        script.exit()

    # Step 2: Validation
    valid, result = validate_floors(floors)

    if not valid:
        forms.alert(result, title="Merge Floors - Incompatible Elements")
        script.exit()

    ref_floor = result

    # Step 3: Extract sketch loops
    try:
        curve_loops = extract_curve_loops(floors)
    except RuntimeError as ex:
        forms.alert(
            "Failed to extract floor sketch:\n{}".format(str(ex)),
            title="Merge Floors - Sketch Error",
        )
        script.exit()

    # Step 4: Shared-edge cleanup
    curve_loops, cleanup_warning = remove_shared_edges(curve_loops)

    if cleanup_warning:
        logger.warning(
            "Shared-edge cleanup could not fully resolve topology. "
            "Attempting floor creation with original loops."
        )

    # Step 5 & 6: Create new floor + delete originals
    original_ids   = [fl.Id for fl in floors]
    creation_error = None

    with Transaction(doc, "Merge Floors") as t:
        t.Start()
        try:
            new_floor = create_merged_floor(curve_loops, ref_floor)

            # Delete originals
            for eid in original_ids:
                try:
                    doc.Delete(eid)
                except Exception as del_ex:
                    logger.warning(
                        "Could not delete floor id {}: {}".format(
                            eid.IntegerValue, str(del_ex))
                    )

            t.Commit()

        except Exception as ex:
            creation_error = str(ex)
            try:
                t.RollBack()
            except Exception:
                pass  # transaction may already be in a terminal state

    # Only show a dialog on failure
    if creation_error is not None:
        forms.alert(
            "Floor creation failed:\n\n{}\n\n"
            "The original floors have NOT been deleted.".format(creation_error),
            title="Merge Floors - Error",
        )


main()
