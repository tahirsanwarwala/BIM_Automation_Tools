# -*- coding: utf-8 -*-
"""
Split SKIN Wall at Opening

Select a door, window, or wall opening, then select the SKIN wall
running in front of it. The SKIN wall is split into a left and right
segment at the opening, and a short perpendicular "return" wall is
added on each side, running back to the EXT wall the opening is
hosted on - clearing the opening of the SKIN wall in front of it.

The original SKIN wall is deleted and replaced by the two trimmed
segments (instance parameters carried over); the two return walls use
the same wall type.
"""

__title__  = "Split Skin\nAt Opening"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Select a door, window, or opening, then select the SKIN wall "
    "running in front of it.\n"
    "The SKIN wall is split at the opening and returned back to the "
    "EXT wall on both sides, clearing the opening."
)

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    FamilyInstance,
    Line,
    LocationPoint,
    Opening,
    Transaction,
    Wall,
    XYZ,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()

PARALLEL_TOLERANCE = 0.02   # ~1.1 degrees, via 1 - |dot|
MIN_SEGMENT_LENGTH = 0.05   # feet (~5/8"), below this a segment is skipped


# ===============================================================================
# SELECTION FILTERS
# ===============================================================================

class OpeningPickFilter(ISelectionFilter):
    """Allow a door/window family instance or a wall Opening, hosted on a Wall."""

    def AllowElement(self, elem):
        try:
            if isinstance(elem, FamilyInstance):
                return isinstance(elem.Host, Wall)
            if isinstance(elem, Opening):
                return isinstance(elem.Host, Wall)
        except Exception:
            pass
        return False

    def AllowReference(self, ref, point):
        return False


class WallPickFilter(ISelectionFilter):
    """Allow any Wall."""

    def AllowElement(self, elem):
        return isinstance(elem, Wall)

    def AllowReference(self, ref, point):
        return False


# ===============================================================================
# SELECTION
# ===============================================================================

def pick_opening():
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element,
            OpeningPickFilter(),
            "Select a door, window, or opening",
        )
    except Exception:
        return None
    return doc.GetElement(ref.ElementId)


def pick_wall(prompt):
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element,
            WallPickFilter(),
            prompt,
        )
    except Exception:
        return None
    return doc.GetElement(ref.ElementId)


# ===============================================================================
# GEOMETRY HELPERS
# ===============================================================================

def flatten(pt, z):
    """Return a copy of *pt* with its Z coordinate replaced by *z*."""
    return XYZ(pt.X, pt.Y, z)


def get_opening_center_and_width(opening, dir_vec):
    """Return (center XYZ, width in feet) for a door/window/Opening,
    measured along *dir_vec*. Returns (None, None) if it can't be
    determined.
    """
    if isinstance(opening, FamilyInstance):
        loc = opening.Location
        center = loc.Point if isinstance(loc, LocationPoint) else None

        width = None
        for src in (opening, getattr(opening, "Symbol", None)):
            if src is None:
                continue
            try:
                p = src.LookupParameter("Width")
                if p and p.HasValue:
                    width = p.AsDouble()
                    break
            except Exception:
                pass

        bbox = None
        if center is None or width is None:
            try:
                bbox = opening.get_BoundingBox(None)
            except Exception:
                bbox = None

        if center is None and bbox is not None:
            center = XYZ(
                (bbox.Min.X + bbox.Max.X) / 2.0,
                (bbox.Min.Y + bbox.Max.Y) / 2.0,
                (bbox.Min.Z + bbox.Max.Z) / 2.0,
            )

        if width is None and bbox is not None:
            diag = bbox.Max - bbox.Min
            width = abs(diag.DotProduct(dir_vec))

        if center is None or width is None or width <= 0:
            return None, None
        return center, width

    if isinstance(opening, Opening):
        try:
            pts = list(opening.BoundaryRect)
        except Exception:
            return None, None
        if len(pts) < 2:
            return None, None
        p0, p1 = pts[0], pts[1]
        center = XYZ((p0.X + p1.X) / 2.0, (p0.Y + p1.Y) / 2.0, (p0.Z + p1.Z) / 2.0)
        width  = abs((p1 - p0).DotProduct(dir_vec))
        if width <= 0:
            return None, None
        return center, width

    return None, None


# ===============================================================================
# ORIENTED WALL CREATION (avoids Wall.Flip() mirroring asymmetric layers)
# ===============================================================================

def create_oriented_wall(curve, type_id, level_id, height, base_off,
                          structural, orig_orient):
    wall = Wall.Create(doc, curve, type_id, level_id, height, base_off,
                        False, structural)
    doc.Regenerate()
    try:
        if orig_orient.DotProduct(wall.Orientation) < 0:
            doc.Delete(wall.Id)
            doc.Regenerate()
            wall = Wall.Create(doc, curve.CreateReversed(), type_id,
                                level_id, height, base_off, False,
                                structural)
            doc.Regenerate()
    except Exception:
        pass
    return wall


# ===============================================================================
# COPY INSTANCE PARAMETERS
# ===============================================================================

def copy_instance_params(source, target):
    bip_list = [
        BuiltInParameter.WALL_BASE_OFFSET,
        BuiltInParameter.WALL_TOP_OFFSET,
        BuiltInParameter.WALL_USER_HEIGHT_PARAM,
        BuiltInParameter.WALL_HEIGHT_TYPE,
        BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT,
    ]
    for bip in bip_list:
        try:
            sp = source.get_Parameter(bip)
            tp = target.get_Parameter(bip)
            if sp and tp and sp.HasValue and not tp.IsReadOnly:
                st = sp.StorageType.ToString()
                if st == "Double":
                    tp.Set(sp.AsDouble())
                elif st == "Integer":
                    tp.Set(sp.AsInteger())
                elif st == "ElementId":
                    tp.Set(sp.AsElementId())
                elif st == "String":
                    val = sp.AsString()
                    if val is not None:
                        tp.Set(val)
        except Exception:
            pass

    for pname in ("Comments", "Mark"):
        try:
            sp = source.LookupParameter(pname)
            tp = target.LookupParameter(pname)
            if sp and tp and sp.HasValue and not tp.IsReadOnly:
                val = sp.AsString()
                if val is not None:
                    tp.Set(val)
        except Exception:
            pass


# ===============================================================================
# CORE OPERATION
# ===============================================================================

def split_skin_at_opening(opening, skin_wall):
    """Split *skin_wall* around *opening* and return to its host (EXT) wall.

    Returns (True, summary) on success, or (False, error_msg) on failure.
    """
    ext_wall = opening.Host
    if not isinstance(ext_wall, Wall):
        return False, "Opening's host is not a wall"
    if ext_wall.Id == skin_wall.Id:
        return False, "Selected wall is the opening's own host, not a SKIN wall in front of it"

    ext_curve  = ext_wall.Location.Curve
    skin_curve = skin_wall.Location.Curve
    if not isinstance(ext_curve, Line) or not isinstance(skin_curve, Line):
        return False, "Only straight walls are supported"

    ext_p0, ext_p1   = ext_curve.GetEndPoint(0), ext_curve.GetEndPoint(1)
    skin_p0, skin_p1 = skin_curve.GetEndPoint(0), skin_curve.GetEndPoint(1)

    dir_vec  = (ext_p1 - ext_p0).Normalize()
    skin_dir = (skin_p1 - skin_p0).Normalize()

    if 1.0 - abs(dir_vec.DotProduct(skin_dir)) > PARALLEL_TOLERANCE:
        return False, "SKIN wall is not parallel to the opening's host wall"

    center, width = get_opening_center_and_width(opening, dir_vec)
    if center is None:
        return False, "Could not determine the opening's width"

    base_z = skin_p0.Z

    jamb_a = flatten(center - dir_vec * (width / 2.0), base_z)
    jamb_b = flatten(center + dir_vec * (width / 2.0), base_z)

    def project_to_skin(pt):
        t = (pt - skin_p0).DotProduct(skin_dir)
        return t, flatten(skin_p0 + skin_dir * t, base_z)

    t_a, s_a = project_to_skin(jamb_a)
    t_b, s_b = project_to_skin(jamb_b)
    skin_len = skin_curve.Length

    if t_a > t_b:
        t_a, t_b   = t_b, t_a
        s_a, s_b   = s_b, s_a
        jamb_a, jamb_b = jamb_b, jamb_a

    if t_a < -MIN_SEGMENT_LENGTH or t_b > skin_len + MIN_SEGMENT_LENGTH:
        return False, "Opening is not spanned by the selected SKIN wall"

    skin_p0_flat = flatten(skin_p0, base_z)
    skin_p1_flat = flatten(skin_p1, base_z)

    # ── Cache SKIN wall instance data ───────────────────────────────────
    wall_type_id = skin_wall.WallType.Id
    level_id     = skin_wall.LevelId
    orig_orient  = skin_wall.Orientation

    h_param  = skin_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
    height   = h_param.AsDouble() if (h_param and h_param.HasValue) else 10.0

    bo_param = skin_wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    base_off = bo_param.AsDouble() if (bo_param and bo_param.HasValue) else 0.0

    st_param   = skin_wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
    structural = bool(st_param.AsInteger()) if (st_param and st_param.HasValue) else False

    # The return walls are centerline-based, so half their own thickness
    # sits on either side of their curve. Left as-is, that puts half the
    # return's thickness past the opening's jamb line, encroaching into
    # the opening. Shift each return segment's whole curve by half the
    # SKIN wall's thickness, back towards its own straight segment, so
    # the return's face (not its centerline) lands flush on the jamb.
    half_w = skin_wall.Width / 2.0
    return_a_shift = -skin_dir * half_w  # toward skin_p0 / "left"
    return_b_shift =  skin_dir * half_w  # toward skin_p1 / "right"

    # ── Build the curves for the 4 replacement segments ─────────────────
    curves = {}
    if t_a > MIN_SEGMENT_LENGTH:
        curves["left"] = Line.CreateBound(skin_p0_flat, s_a)
    if (skin_len - t_b) > MIN_SEGMENT_LENGTH:
        curves["right"] = Line.CreateBound(s_b, skin_p1_flat)
    if s_a.DistanceTo(jamb_a) > MIN_SEGMENT_LENGTH:
        curves["return_a"] = Line.CreateBound(
            flatten(s_a + return_a_shift, base_z),
            flatten(jamb_a + return_a_shift, base_z),
        )
    if s_b.DistanceTo(jamb_b) > MIN_SEGMENT_LENGTH:
        curves["return_b"] = Line.CreateBound(
            flatten(s_b + return_b_shift, base_z),
            flatten(jamb_b + return_b_shift, base_z),
        )

    if not curves:
        return False, "Computed wall segments are degenerate (too short)"

    # ── Create the new walls ────────────────────────────────────────────
    new_walls = {}
    for key, curve in curves.items():
        new_walls[key] = create_oriented_wall(
            curve, wall_type_id, level_id, height, base_off, structural,
            orig_orient,
        )

    # All 4 walls are Wall Centerline; the return segments already have
    # their curves shifted by half-thickness above, so their face lands
    # on the jamb without needing a location-line change.
    for w in new_walls.values():
        try:
            p = w.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
            if p and not p.IsReadOnly:
                p.Set(0)  # Wall Centerline
        except Exception:
            pass

    for key in ("left", "right"):
        if key in new_walls:
            copy_instance_params(skin_wall, new_walls[key])

    # ── Delete the original SKIN wall ───────────────────────────────────
    doc.Delete(skin_wall.Id)
    doc.Regenerate()

    # ── Join adjacent segments for clean mitred/T corners ───────────────
    from Autodesk.Revit.DB import JoinGeometryUtils
    join_pairs = [
        ("left", "return_a"),
        ("right", "return_b"),
    ]
    for a, b in join_pairs:
        if a in new_walls and b in new_walls:
            try:
                JoinGeometryUtils.JoinGeometry(doc, new_walls[a], new_walls[b])
            except Exception:
                pass

    for key in ("return_a", "return_b"):
        if key in new_walls:
            try:
                JoinGeometryUtils.JoinGeometry(doc, new_walls[key], ext_wall)
            except Exception:
                pass

    return True, "Split SKIN wall around opening {} ({} segment(s) created)".format(
        opening.Id.IntegerValue, len(new_walls),
    )


# ===============================================================================
# MAIN
# ===============================================================================

def main():
    opening = pick_opening()
    if opening is None:
        script.exit()

    skin_wall = pick_wall("Select the SKIN wall running in front of the opening")
    if skin_wall is None:
        script.exit()

    with Transaction(doc, "Split SKIN Wall at Opening") as t:
        t.Start()
        try:
            success, msg = split_skin_at_opening(opening, skin_wall)
            if success:
                t.Commit()
                forms.alert(msg, title="Split Skin At Opening")
            else:
                t.RollBack()
                forms.alert(msg, title="Split Skin At Opening - Failed")
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            forms.alert(
                "Transaction failed:\n{}".format(str(ex)),
                title="Split Skin At Opening - Error",
            )


main()
