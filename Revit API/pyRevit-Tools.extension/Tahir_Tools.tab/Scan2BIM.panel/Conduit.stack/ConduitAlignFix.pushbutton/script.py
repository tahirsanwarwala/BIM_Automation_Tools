# -*- coding: utf-8 -*-
"""
Conduit Align Fix
Aligns the facing endpoint of a target conduit to the centerline axis of a
source conduit, and resolves gaps or excessive overlaps according to standard
tolerances:
  - Gaps are closed with a secure 1/32" (0.03125") overlap into the source.
  - Excessive overlaps (> 1/4") are reduced to a maximum 1/4" (0.25") overlap.
  - Lateral/angular misalignments are snapped directly onto the source axis.
Only the target's facing endpoint is adjusted; the rest of the target conduit
and the source conduit remain untouched.

Runs in a continuous loop: pick Source -> Target -> Source -> Target...
Press Escape at any pick prompt to exit.
"""

__title__  = "Conduit\nAlign Fix"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick a SOURCE conduit (reference, remains untouched) and a TARGET conduit "
    "to align. Stretches/shrinks and aligns only the facing end of the target conduit "
    "to match the source centerline axis, fixing gaps and excessive overlaps.\n\n"
    "Runs in a continuous loop until you press Escape."
)

import clr
import math

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    Line,
    XYZ,
)
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import revit, forms, script

doc   = revit.doc
uidoc = revit.uidoc


# =============================================================================
# TOLERANCE CONSTANTS
# =============================================================================

# Maximum allowable overlap (1/4 inch = 0.25 / 12 ft)
MAX_OVERLAP_FT = 0.25 / 12.0

# Overlap depth to apply when resolving a gap (1/32 inch = 0.03125 / 12 ft)
GAP_FIX_OVERLAP_FT = 0.03125 / 12.0


# =============================================================================
# SELECTION FILTER
# =============================================================================

class ConduitSelectionFilter(ISelectionFilter):
    """Allow selection of Electrical Conduit elements only."""

    def AllowElement(self, elem):
        if elem is None:
            return False
        if isinstance(elem, Conduit):
            return True
        if elem.Category and elem.Category.Id.IntegerValue == int(BuiltInCategory.OST_Conduit):
            return True
        return False

    def AllowReference(self, ref, point):
        return False


# =============================================================================
# GEOMETRY HELPERS
# =============================================================================

def _dot(a, b):
    """Dot product of two XYZ vectors."""
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def _vec_length(v):
    """Length of an XYZ vector."""
    return math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)


def _distance(a, b):
    """Euclidean distance between two XYZ points."""
    dx = a.X - b.X
    dy = a.Y - b.Y
    dz = a.Z - b.Z
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def find_facing_endpoints(src_curve, tgt_curve):
    """
    Find which endpoints of the source and target conduits face each other.
    Returns:
        (src_idx, tgt_idx, src_facing_pt, tgt_facing_pt, outward_src)
    where:
        src_idx, tgt_idx: 0 (start) or 1 (end)
        outward_src: unit vector pointing away from source body at facing end
    """
    src_pt0 = src_curve.GetEndPoint(0)
    src_pt1 = src_curve.GetEndPoint(1)
    tgt_pt0 = tgt_curve.GetEndPoint(0)
    tgt_pt1 = tgt_curve.GetEndPoint(1)

    # Unit direction vectors (start -> end)
    v_src = XYZ(src_pt1.X - src_pt0.X, src_pt1.Y - src_pt0.Y, src_pt1.Z - src_pt0.Z)
    len_src = _vec_length(v_src)
    dir_src = XYZ(v_src.X / len_src, v_src.Y / len_src, v_src.Z / len_src) if len_src > 1e-9 else XYZ(1, 0, 0)

    v_tgt = XYZ(tgt_pt1.X - tgt_pt0.X, tgt_pt1.Y - tgt_pt0.Y, tgt_pt1.Z - tgt_pt0.Z)
    len_tgt = _vec_length(v_tgt)
    dir_tgt = XYZ(v_tgt.X / len_tgt, v_tgt.Y / len_tgt, v_tgt.Z / len_tgt) if len_tgt > 1e-9 else XYZ(1, 0, 0)

    # Candidate pairs
    pairs = []
    for s_idx, p_s in ((0, src_pt0), (1, src_pt1)):
        # Vector pointing away from source body
        out_s = XYZ(-dir_src.X, -dir_src.Y, -dir_src.Z) if s_idx == 0 else dir_src

        for t_idx, p_t in ((0, tgt_pt0), (1, tgt_pt1)):
            # Vector pointing away from target body
            out_t = XYZ(-dir_tgt.X, -dir_tgt.Y, -dir_tgt.Z) if t_idx == 0 else dir_tgt

            dist = _distance(p_s, p_t)
            # Facing condition: outward vectors point towards each other (dot < 0)
            is_facing = _dot(out_s, out_t) < 0.2

            pairs.append({
                "s_idx": s_idx,
                "t_idx": t_idx,
                "p_s": p_s,
                "p_t": p_t,
                "out_s": out_s,
                "dist": dist,
                "is_facing": is_facing,
            })

    # Prioritize facing pairs, then by minimum distance
    facing_candidates = [p for p in pairs if p["is_facing"]]
    if facing_candidates:
        best = min(facing_candidates, key=lambda x: x["dist"])
    else:
        best = min(pairs, key=lambda x: x["dist"])

    return (
        best["s_idx"],
        best["t_idx"],
        best["p_s"],
        best["p_t"],
        best["out_s"],
    )


# =============================================================================
# ALIGNMENT ACTION
# =============================================================================

def align_conduits(src_elem, tgt_elem):
    """Align facing endpoint of target conduit to source centerline axis."""
    src_curve = src_elem.Location.Curve
    tgt_curve = tgt_elem.Location.Curve

    # 1. Identify facing endpoints
    s_idx, t_idx, p_src_facing, p_tgt_facing, outward_src = find_facing_endpoints(src_curve, tgt_curve)

    # Fixed opposite end of target conduit
    p_tgt_fixed = tgt_curve.GetEndPoint(1 if t_idx == 0 else 0)

    # 2. Geometry projection onto Source Axis
    # Vector from source facing end to target facing end
    v = XYZ(
        p_tgt_facing.X - p_src_facing.X,
        p_tgt_facing.Y - p_src_facing.Y,
        p_tgt_facing.Z - p_src_facing.Z,
    )

    # Longitudinal position along source outward axis (t > 0 = gap, t < 0 = overlap)
    t = _dot(v, outward_src)

    # 3. Determine target longitudinal adjustment
    if t > 0:
        # GAP detected -> overlap into source by 1/32"
        t_new = -GAP_FIX_OVERLAP_FT
    elif t < -MAX_OVERLAP_FT:
        # EXCESSIVE OVERLAP detected -> cap overlap at 1/4"
        t_new = -MAX_OVERLAP_FT
    else:
        # Overlap is within 0 - 1/4", snap to axis preserving overlap depth
        t_new = t if t <= 0 else -GAP_FIX_OVERLAP_FT

    # New coordinates for target facing endpoint
    p_tgt_new = XYZ(
        p_src_facing.X + t_new * outward_src.X,
        p_src_facing.Y + t_new * outward_src.Y,
        p_src_facing.Z + t_new * outward_src.Z,
    )

    # 4. Validate new conduit length
    new_len = _distance(p_tgt_fixed, p_tgt_new)
    if new_len < 0.01:  # Less than ~1/8 inch
        forms.alert(
            "Calculated target conduit length would be too short ({:.4f} ft).\nOperation skipped.".format(new_len),
            title="Conduit Align Fix"
        )
        return False

    # 5. Create new line curve for target conduit
    if t_idx == 0:
        new_curve = Line.CreateBound(p_tgt_new, p_tgt_fixed)
    else:
        new_curve = Line.CreateBound(p_tgt_fixed, p_tgt_new)

    # 6. Apply Transaction in Revit
    t_name = "Align Conduit Ends ({})".format(tgt_elem.Id.IntegerValue)
    with revit.Transaction(t_name):
        tgt_elem.Location.Curve = new_curve

    return True


# =============================================================================
# MAIN LOOP
# =============================================================================

def main():
    sel_filter = ConduitSelectionFilter()

    # Continuous loop until user presses Escape / Cancels
    while True:
        # 1. Pick Source Conduit (Reference)
        try:
            src_ref = uidoc.Selection.PickObject(
                ObjectType.Element,
                sel_filter,
                "Select SOURCE Conduit (Reference) [Esc to Finish]"
            )
        except OperationCanceledException:
            break

        if not src_ref:
            break

        src_elem = doc.GetElement(src_ref)
        if not src_elem or not hasattr(src_elem, "Location") or not hasattr(src_elem.Location, "Curve"):
            forms.alert("Invalid source conduit selected.", title="Conduit Align Fix")
            continue

        # 2. Pick Target Conduit (To be modified)
        try:
            tgt_ref = uidoc.Selection.PickObject(
                ObjectType.Element,
                sel_filter,
                "Select TARGET Conduit (to Align) [Esc to Finish]"
            )
        except OperationCanceledException:
            break

        if not tgt_ref:
            break

        tgt_elem = doc.GetElement(tgt_ref)
        if not tgt_elem or not hasattr(tgt_elem, "Location") or not hasattr(tgt_elem.Location, "Curve"):
            forms.alert("Invalid target conduit selected.", title="Conduit Align Fix")
            continue

        # Check that user didn't pick the same conduit twice
        if src_elem.Id == tgt_elem.Id:
            forms.alert("Source and Target conduits cannot be the same element. Please pick two different conduits.", title="Conduit Align Fix")
            continue

        # 3. Perform Alignment
        align_conduits(src_elem, tgt_elem)


if __name__ == "__main__":
    main()
