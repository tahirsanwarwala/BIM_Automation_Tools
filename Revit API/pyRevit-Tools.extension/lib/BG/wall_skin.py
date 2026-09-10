# -*- coding: utf-8 -*-
"""Placing a new skin wall against an existing wall's exterior face.

Extracted from the SplitWalls pushbutton so Multi Wall Creation can use
the same geometry rather than a second copy of it.  Behaviour is
unchanged from that script; the only differences are that *doc* is now
passed in rather than read off a module global, and skin_centreline
takes plain values rather than SplitWalls' WallData object.

Two things here are worth knowing before changing them.

The faces of a wall are MEASURED off its real solid, not inferred from
its Location Line parameter.  A wall whose layer build-up is asymmetric,
or whose Location Line is set to anything but Centreline, is placed
wrongly by inference and correctly by measurement.

A new wall is then re-centred after creation.  Revit applies whatever
Location Line the type happens to default to at creation time, which
moves the wall off the curve it was asked for; measuring the result and
cancelling the residual error is the only dependable fix.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    Arc,
    BuiltInParameter,
    ElementTransformUtils,
    GeometryInstance,
    Line,
    Options,
    Solid,
    Transform,
    ViewDetailLevel,
    Wall,
    XYZ,
)
from pyrevit import script

logger = script.get_logger()


def _iter_solid_points(elem, transform=None):
    """Yield every tessellated vertex of *elem*'s solid geometry.

    Deliberately not BG.wall_chain.iter_solid_points: this one asks
    for Medium detail, which is what SplitWalls has always measured at,
    and changing the detail level changes the measurements.
    """
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Medium

    geo_elem = elem.get_Geometry(opts)
    if geo_elem is None:
        return

    for gobj in geo_elem:
        solids = []
        if isinstance(gobj, Solid):
            solids.append(gobj)
        elif isinstance(gobj, GeometryInstance):
            try:
                for g2 in gobj.GetInstanceGeometry():
                    if isinstance(g2, Solid):
                        solids.append(g2)
            except Exception:
                continue

        for sol in solids:
            try:
                if sol.Volume <= 0:
                    continue
            except Exception:
                continue
            for edge in sol.Edges:
                try:
                    for pt in edge.Tessellate():
                        yield transform.OfPoint(pt) if transform else pt
                except Exception:
                    continue


def measure_face_offsets(elem, ref_pt, orient, transform=None):
    """Measure a wall's real face positions instead of inferring them.

    Projects every vertex of the wall's solid onto *orient* (the
    exterior normal), relative to *ref_pt* (a point on the wall's
    location curve).

    Returns (d_ext, d_int) where d_ext is the signed distance from the
    location curve to the EXTERIOR face and d_int the signed distance to
    the INTERIOR face, negative when that face is behind the curve.
    Returns None when the geometry could not be measured.
    """
    try:
        n = orient.Normalize()
    except Exception:
        return None

    hi = None
    lo = None
    for pt in _iter_solid_points(elem, transform):
        d = (pt - ref_pt).DotProduct(n)
        if hi is None or d > hi:
            hi = d
        if lo is None or d < lo:
            lo = d

    if hi is None or lo is None:
        return None
    return hi, lo


def layer_group_widths(cs, first_core, last_core):
    """Return (skin_w, gap_w, core_w, interior_w, ext_total_w) in feet."""
    skin_w = cs.GetLayerWidth(0)
    gap_w = sum(cs.GetLayerWidth(i) for i in range(1, first_core))
    core_w = sum(cs.GetLayerWidth(i)
                 for i in range(first_core, last_core + 1))
    int_w = sum(cs.GetLayerWidth(i)
                for i in range(last_core + 1, cs.LayerCount))
    return skin_w, gap_w, core_w, int_w, core_w + int_w


def dist_loc_to_exterior(loc_line, total_w, skin_w, gap_w, core_w):
    """Distance from a wall's location curve to its exterior face, feet.

    Only a fallback for when the solid could not be measured.  Covers
    all six WallLocationLine settings:

        0 = Wall Centerline          3 = Finish Face: Interior
        1 = Core Centerline          4 = Core Face: Exterior
        2 = Finish Face: Exterior    5 = Core Face: Interior
    """
    ext_shell = skin_w + gap_w
    mapping = {
        0: total_w / 2.0,
        1: ext_shell + core_w / 2.0,
        2: 0.0,
        3: total_w,
        4: ext_shell,
        5: ext_shell + core_w,
    }
    return mapping.get(loc_line, total_w / 2.0)


def offset_sideways(curve, orientation, distance):
    """Move *curve* *distance* along *orientation*, in its own plane.

    A line slides across, which is a translation.  An ARC does not: a
    translated arc is the same arc somewhere else, still curving about
    a centre it has left behind, and its ends no longer sit on the wall
    it is meant to line.  What an arc needs is a CONCENTRIC arc --
    same centre, radius larger or smaller by the offset -- and it is
    rebuilt here through three radially moved points, its ends and its
    middle, so nothing has to be known about which way it was drawn.

    Returns None for an offset that reaches the arc's own centre or
    passes it, which has no concentric answer.
    """
    orient = orientation.Normalize()

    if isinstance(curve, Line):
        vec = XYZ(orient.X * distance, orient.Y * distance,
                  orient.Z * distance)
        return curve.CreateTransformed(Transform.CreateTranslation(vec))

    try:
        centre = curve.Center
    except Exception:
        return None

    def moved(u):
        p = curve.Evaluate(u, True)
        out = XYZ(p.X - centre.X, p.Y - centre.Y, 0.0)
        if out.GetLength() < 1e-9:
            return None
        out = out.Normalize()
        if out.DotProduct(orient) < 0:
            out = XYZ(-out.X, -out.Y, 0.0)
        return XYZ(p.X + out.X * distance, p.Y + out.Y * distance, p.Z)

    a, mid, b = moved(0.0), moved(0.5), moved(1.0)
    if a is None or mid is None or b is None:
        return None

    try:
        return Arc.Create(a, b, mid)
    except Exception:
        return None


def skin_centreline(loc_curve, orientation, dist_to_exterior, skin_width):
    """Centreline for a skin wall sitting in the source wall's finish.

    *dist_to_exterior* is the distance from *loc_curve* to the source
    wall's exterior face, measured or inferred.  The skin wall occupies
    the outermost finish layer, so its centreline sits half its own
    thickness inboard of that face.

    Returns None where a curved wall's finish would have to be offset
    to or past its own centre -- a skin tighter than the radius it
    curves on, which no arc can be.
    """
    skin_off = dist_to_exterior - skin_width / 2.0
    return offset_sideways(loc_curve, orientation, skin_off)


def dist_loc_to_interior(dist_to_exterior, total_width):
    """Distance from the location curve to the wall's INTERIOR face.

    Orientation points outwards, so the interior face is one whole wall
    thickness back along it -- negative wherever the location curve sits
    inside the wall, which is most of the time.
    """
    return dist_to_exterior - total_width


def interior_skin_centreline(loc_curve, orientation, dist_to_interior,
                             skin_width):
    """Centreline for a skin wall in the source wall's INNERMOST finish.

    The mirror of skin_centreline.  That one steps half a thickness IN
    from the exterior face; this one steps half a thickness OUT from the
    interior face, which is the same move in the other direction, so
    both walls end up sitting in the layer they were cut from.

    Returns None on the same terms: a curved wall whose finish would
    have to be offset to or past its own centre has no concentric arc.
    """
    return offset_sideways(loc_curve, orientation,
                           dist_to_interior + skin_width / 2.0)


def _center_wall_on_curve(doc, wall, target_curve, orient):
    """Translate *wall* so its solid's mid-plane lands on *target_curve*.

    Rather than trusting whichever Location Line default Wall.Create()
    applied, this measures the wall's real faces and cancels out any
    residual perpendicular error.

    Only for a STRAIGHT wall.  The measurement projects every solid
    point onto one normal, which is the wall's own direction all the way
    along a line and nothing of the sort along an arc -- there it would
    read the bulge as an error and shift a correctly placed wall to
    "fix" it.  A curved wall is left where Wall.Create put it, which is
    on the curve it was given.
    """
    if not isinstance(target_curve, Line):
        return

    try:
        n = orient.Normalize()
        ref_pt = target_curve.GetEndPoint(0)

        meas = measure_face_offsets(wall, ref_pt, n)
        if not meas:
            return

        hi, lo = meas
        center_err = (hi + lo) / 2.0   # 0.0 when perfectly centred

        if abs(center_err) > 1e-7:
            move_vec = XYZ(n.X * -center_err,
                           n.Y * -center_err,
                           n.Z * -center_err)
            ElementTransformUtils.MoveElement(doc, wall.Id, move_vec)
            doc.Regenerate()
    except Exception as ex:
        logger.debug("Could not re-centre new wall: {}".format(ex))


def create_oriented_wall(doc, curve, type_id, level_id, height, base_off,
                         structural, orig_orient):
    """Create a wall on *curve* facing the same way as *orig_orient*.

    The curve is the wall's intended CENTRELINE.  Location Line is
    forced to Centreline so the curve means that whatever the type's
    default was, the wall is re-created reversed if it came out facing
    the wrong way, and the result is re-centred on the curve.
    """
    wall = Wall.Create(doc, curve, type_id, level_id, height, base_off,
                       False, structural)
    doc.Regenerate()

    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
        if p and p.HasValue:
            p.Set(0)  # 0 = Wall Centerline
        doc.Regenerate()
    except Exception:
        pass

    try:
        if orig_orient.DotProduct(wall.Orientation) < 0:
            doc.Delete(wall.Id)
            doc.Regenerate()
            curve = curve.CreateReversed()
            wall = Wall.Create(doc, curve, type_id, level_id, height,
                               base_off, False, structural)
            doc.Regenerate()
            p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
            if p and p.HasValue:
                p.Set(0)
            doc.Regenerate()
    except Exception:
        pass

    _center_wall_on_curve(doc, wall, curve, orig_orient)

    return wall
