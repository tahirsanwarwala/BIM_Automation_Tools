# -*- coding: utf-8 -*-
"""
Merge Floors / Roofs
Combines sketch boundaries of multiple floor elements (that share the same
type, reference level, and Height Offset from Level) into a single new floor,
then deletes the originals. Footprint roofs are merged the same way (same
type, base level, and Base Offset From Level).
"""

__title__  = "Merge\nFloors/Roofs"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Select 2 or more floor elements that share the same type, reference level, "
    "and Height Offset from Level - or 2 or more footprint roofs that share the "
    "same type, base level, and Base Offset From Level. The script merges their "
    "sketch boundaries into a single new element and deletes the originals."
)

import clr
import math
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    CurveArray,
    CurveLoop,
    ElementId,
    Floor,
    FootPrintRoof,
    ModelCurveArray,
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

def is_mergeable(elem):
    """True for elements this tool can merge: floors and footprint roofs."""
    return isinstance(elem, (Floor, FootPrintRoof))


class FloorRoofFilter(ISelectionFilter):
    """Allow only Floor and FootPrintRoof elements to be selected."""

    def AllowElement(self, elem):
        return is_mergeable(elem)

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


def get_roof_base_offset(roof):
    """Return the 'Base Offset From Level' value (in feet) for a roof, or 0.0."""
    p = roof.get_Parameter(BuiltInParameter.ROOF_LEVEL_OFFSET_PARAM)
    if p and p.HasValue:
        return p.AsDouble()
    return 0.0


def get_offset(elem):
    """Offset from the reference level, for either a floor or a roof."""
    if isinstance(elem, FootPrintRoof):
        return get_roof_base_offset(elem)
    return get_height_offset(elem)


def get_type_element(elem):
    """The FloorType or RoofType of the element."""
    if isinstance(elem, FootPrintRoof):
        return elem.RoofType
    return elem.FloorType


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

def get_elements_from_selection():
    """
    Try pre-selection first; fall back to PickObjects prompt.
    Returns a list of Floor / FootPrintRoof elements, or None if user cancelled.
    """
    pre_ids  = list(uidoc.Selection.GetElementIds())
    elements = [doc.GetElement(eid) for eid in pre_ids
                if is_mergeable(doc.GetElement(eid))]

    if len(elements) >= 2:
        return elements

    # Nothing useful pre-selected -> ask the user to pick
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            FloorRoofFilter(),
            "Select 2 or more floors or 2 or more roofs - press Finish when done",
        )
    except Exception:
        return None  # user pressed Escape

    elements = [doc.GetElement(r.ElementId) for r in refs]
    elements = [e for e in elements if is_mergeable(e)]
    return elements if elements else None


# ===============================================================================
# STEP 2 - VALIDATE SIMILARITY
# ===============================================================================

def validate_elements(elements, kind):
    """
    Check that all elements share the same type, Level, and level offset.

    Returns (True, reference_element) on success, or
            (False, error_message_string) on failure.
    """
    ref    = elements[0]
    errors = []

    ref_type_id  = get_type_element(ref).Id
    ref_level_id = ref.LevelId
    ref_offset   = get_offset(ref)
    offset_name  = ("Base Offset" if kind == "Roof" else "Height Offset")

    for i, el in enumerate(elements[1:], start=2):
        label = "{} #{} (id {})".format(kind, i, el.Id.IntegerValue)

        # Type check
        if get_type_element(el).Id != ref_type_id:
            errors.append(
                "{}: type '{}' != reference type '{}'".format(
                    label, get_name(get_type_element(el)),
                    get_name(get_type_element(ref)))
            )

        # Level check
        if el.LevelId != ref_level_id:
            ref_level = doc.GetElement(ref_level_id)
            el_level  = doc.GetElement(el.LevelId)
            errors.append(
                "{}: level '{}' != reference level '{}'".format(
                    label,
                    get_name(el_level)  if el_level  else str(el.LevelId.IntegerValue),
                    get_name(ref_level) if ref_level else str(ref_level_id.IntegerValue),
                )
            )

        # Offset check
        el_offset = get_offset(el)
        if abs(el_offset - ref_offset) > TOLERANCE:
            errors.append(
                "{}: {} {:.4f} ft != reference {:.4f} ft".format(
                    label, offset_name, el_offset, ref_offset)
            )

    if errors:
        msg = (
            "The selected {}s are NOT compatible for merging.\n\n".format(kind.lower())
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


def extract_roof_loops(roofs):
    """
    For each footprint roof, read its footprint profiles and return
    (curve_loops, edge_props).

    edge_props is a list of (curve, props_dict) recording each original
    footprint edge's slope settings, so they can be carried over to the
    matching edge of the merged roof.

    Raises RuntimeError if a roof has no footprint.
    """
    all_loops  = []
    edge_props = []

    for rf in roofs:
        profiles = rf.GetProfiles()
        if profiles is None or profiles.Size == 0:
            raise RuntimeError(
                "Roof id {} has no footprint - cannot extract boundary.".format(
                    rf.Id.IntegerValue)
            )

        # GetProfiles() is a ModelCurveArrArray; each ModelCurveArray is one loop
        for model_curve_arr in profiles:
            loop = CurveLoop()
            for mc in model_curve_arr:
                crv = mc.GeometryCurve
                loop.Append(crv)
                edge_props.append((crv, read_roof_edge_props(rf, mc)))
            all_loops.append(loop)

    return all_loops, edge_props


def read_roof_edge_props(roof, model_curve):
    """Read the slope-related settings of one footprint edge."""
    props = {}
    for key, getter in (
        ("defines_slope", roof.get_DefinesSlope),
        ("slope_angle",   roof.get_SlopeAngle),
        ("offset",        roof.get_Offset),
        ("overhang",      roof.get_Overhang),
    ):
        try:
            props[key] = getter(model_curve)
        except Exception:
            pass  # not every property applies to every edge
    return props


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


def create_merged_roof(curve_loops, ref_roof, edge_props):
    """
    Create a new footprint roof using Document.Create.NewFootPrintRoof().
    Set Base Offset to match the source roofs, and copy each original
    edge's slope settings onto the matching edge of the new footprint.
    Returns the new FootPrintRoof element.
    """
    roof_type   = ref_roof.RoofType
    level       = doc.GetElement(ref_roof.LevelId)
    base_offset = get_roof_base_offset(ref_roof)

    footprint = CurveArray()
    for cl in curve_loops:
        for crv in cl:
            footprint.Append(crv)

    model_curves_ref = clr.Reference[ModelCurveArray]()
    new_roof = doc.Create.NewFootPrintRoof(
        footprint, level, roof_type, model_curves_ref)
    model_curves = model_curves_ref.Value

    # Apply base offset
    offset_param = new_roof.get_Parameter(BuiltInParameter.ROOF_LEVEL_OFFSET_PARAM)
    if offset_param and not offset_param.IsReadOnly:
        offset_param.Set(base_offset)

    # Carry over slope settings edge by edge
    for mc in model_curves:
        props = _find_edge_props(mc.GeometryCurve, edge_props)
        if props is None:
            continue
        for key, setter in (
            ("defines_slope", new_roof.set_DefinesSlope),
            ("slope_angle",   new_roof.set_SlopeAngle),
            ("offset",        new_roof.set_Offset),
            ("overhang",      new_roof.set_Overhang),
        ):
            if key not in props:
                continue
            try:
                setter(mc, props[key])
            except Exception as ex:
                logger.debug("Could not set {} on roof edge: {}".format(key, ex))

    return new_roof


def _find_edge_props(curve, edge_props):
    """Return the slope settings of the original edge matching this curve."""
    for orig_curve, props in edge_props:
        if curves_share_edge(curve, orig_curve):
            return props
    return None


# ===============================================================================
# MAIN
# ===============================================================================

def main():
    # Step 1: Selection
    elements = get_elements_from_selection()

    if not elements:
        script.exit()

    floors = [e for e in elements if isinstance(e, Floor)]
    roofs  = [e for e in elements if isinstance(e, FootPrintRoof)]

    if floors and roofs:
        forms.alert(
            "Floors and roofs cannot be merged together.\n"
            "Select only floors, or only roofs.\n\n"
            "Selected: {} floor(s), {} roof(s).".format(len(floors), len(roofs)),
            title="Merge Floors/Roofs - Mixed Selection",
        )
        script.exit()

    kind     = "Roof" if roofs else "Floor"
    elements = roofs or floors
    title    = "Merge {}s".format(kind)

    if len(elements) < 2:
        forms.alert(
            "Please select at least 2 {0} elements.\n"
            "Only {1} {0}(s) were found in the selection.".format(
                kind.lower(), len(elements)),
            title="{} - Not Enough {}s".format(title, kind),
        )
        script.exit()

    # Step 2: Validation
    valid, result = validate_elements(elements, kind)

    if not valid:
        forms.alert(result, title="{} - Incompatible Elements".format(title))
        script.exit()

    ref_element = result

    # Step 3: Extract sketch loops
    edge_props = []
    try:
        if kind == "Roof":
            curve_loops, edge_props = extract_roof_loops(elements)
        else:
            curve_loops = extract_curve_loops(elements)
    except RuntimeError as ex:
        forms.alert(
            "Failed to extract {} sketch:\n{}".format(kind.lower(), str(ex)),
            title="{} - Sketch Error".format(title),
        )
        script.exit()

    # Step 4: Shared-edge cleanup
    curve_loops, cleanup_warning = remove_shared_edges(curve_loops)

    if cleanup_warning:
        logger.warning(
            "Shared-edge cleanup could not fully resolve topology. "
            "Attempting {} creation with original loops.".format(kind.lower())
        )

    # Step 5 & 6: Create new element + delete originals
    original_ids   = [el.Id for el in elements]
    creation_error = None

    with Transaction(doc, title) as t:
        t.Start()
        try:
            if kind == "Roof":
                create_merged_roof(curve_loops, ref_element, edge_props)
            else:
                create_merged_floor(curve_loops, ref_element)

            # Delete originals
            for eid in original_ids:
                try:
                    doc.Delete(eid)
                except Exception as del_ex:
                    logger.warning(
                        "Could not delete {} id {}: {}".format(
                            kind.lower(), eid.IntegerValue, str(del_ex))
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
            "{0} creation failed:\n\n{1}\n\n"
            "The original {2}s have NOT been deleted.".format(
                kind, creation_error, kind.lower()),
            title="{} - Error".format(title),
        )


main()
