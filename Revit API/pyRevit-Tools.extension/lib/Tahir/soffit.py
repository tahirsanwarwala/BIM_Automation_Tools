# -*- coding: utf-8 -*-
"""Reading a roof soffit as a plan outline and a height.

A soffit is never built by these tools.  It is picked only to say where
a wall has to stop, so all that is wanted of it is two numbers and a
shape: how high its underside sits, how high its top sits, and what
patch of plan it covers.

Which walls it then limits is a question for Tahir.plan_shapes, which
knows nothing of Revit; this module is the part that has to talk to it.

The outline comes off the soffit's DOWNWARD faces, so a soffit with a
lightwell through it reports the well as a hole and the wall standing
in that well is not limited by it.  A soffit whose underside cannot be
read as flat faces -- one meshed, or pitched so steeply its underside
faces sideways -- falls back to its own bounding rectangle and says so,
because a soffit that limits a wall crudely is worth more than one
silently dropped.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    ElementId,
    GeometryInstance,
    Options,
    PlanarFace,
    Solid,
    ViewDetailLevel,
)
from pyrevit import script

from Tahir import plan_shapes

logger = script.get_logger()

# A face is part of the underside when it looks downwards at all.
DOWNWARD_MAX_Z = -0.5

# ...and the underside is FLAT when it looks straight down, to within
# about two and a half degrees.  Anything shallower than that is a
# drafting wobble, not a pitch.
FLAT_MIN_Z = 0.999


class SoffitShape(object):
    """One soffit, reduced to what a wall limit needs.

    *outlines* is a list of (outer_ring, holes), each ring a closed
    list of (x, y) in HOST coordinates.  *base_z* and *top_z* are the
    soffit's whole vertical extent, so a wall stopped by it stops below
    the LOWEST point of its underside and never pokes through.
    """

    __slots__ = ("base_z", "top_z", "outlines", "sloped", "approximate")

    def __init__(self):
        self.base_z      = None
        self.top_z       = None
        self.outlines    = []
        self.sloped      = False
        self.approximate = False


def is_soffit(elem):
    """True when *elem* is in the Roof Soffits category.

    The CATEGORY, not the class: which class Revit returns a soffit as
    is not something this tool should have an opinion about, and the
    category is what the user picks by in the first place.
    """
    if elem is None:
        return False
    try:
        cat = elem.Category
        if cat is None:
            return False
        return cat.Id == ElementId(BuiltInCategory.OST_RoofSoffit)
    except Exception:
        return False


def _solids(elem):
    """Yield *elem*'s solids, instance geometry included."""
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Medium

    try:
        geo_elem = elem.get_Geometry(opts)
    except Exception:
        return
    if geo_elem is None:
        return

    for gobj in geo_elem:
        if isinstance(gobj, Solid):
            candidates = [gobj]
        elif isinstance(gobj, GeometryInstance):
            try:
                candidates = [g for g in gobj.GetInstanceGeometry()
                              if isinstance(g, Solid)]
            except Exception:
                continue
        else:
            continue

        for sol in candidates:
            try:
                if sol.Volume <= 0:
                    continue
            except Exception:
                continue
            yield sol


def _loop_ring(loop, transform):
    """One CurveLoop as a closed ring of (x, y) in host coordinates."""
    ring = []
    for curve in loop:
        try:
            pts = curve.Tessellate()
        except Exception:
            return None
        # Every curve's last point is the next curve's first, so drop
        # it and let the ring close itself.
        for p in list(pts)[:-1]:
            w = transform.OfPoint(p)
            ring.append((w.X, w.Y))
    return ring if len(ring) >= 3 else None


def _face_outline(face, transform):
    """A planar face's (outer_ring, holes), or None.

    The outer loop is the one enclosing the most area.  Which loop
    GetEdgesAsCurveLoops returns first is not documented as being the
    outer one, and a soffit whose lightwell was mistaken for its
    boundary would limit exactly the walls it should not.
    """
    try:
        loops = face.GetEdgesAsCurveLoops()
    except Exception:
        return None

    rings = []
    for loop in loops:
        ring = _loop_ring(loop, transform)
        if ring is None:
            # One unreadable loop discredits the whole face.  Keeping
            # the rest would be worse than keeping none: if it was the
            # boundary that failed, the largest surviving ring is a
            # lightwell, and the soffit would then limit exactly the
            # walls it should not.
            return None
        rings.append(ring)

    if not rings:
        return None

    rings.sort(key=lambda r: abs(plan_shapes.ring_area(r)), reverse=True)
    return (rings[0], rings[1:])


def measure(elem, transform):
    """Measure a soffit.  Returns (SoffitShape or None, list of notes)."""
    notes  = []
    points = []
    shape  = SoffitShape()

    curved = False

    for sol in _solids(elem):
        try:
            edges = sol.Edges
        except Exception:
            edges = []
        for edge in edges:
            try:
                pts = edge.Tessellate()
            except Exception:
                continue
            for p in pts:
                w = transform.OfPoint(p)
                points.append((w.X, w.Y, w.Z))

        try:
            faces = sol.Faces
        except Exception:
            continue

        for face in faces:
            if not isinstance(face, PlanarFace):
                curved = True
                continue
            try:
                normal = transform.OfVector(face.FaceNormal)
            except Exception:
                continue
            if normal.Z >= DOWNWARD_MAX_Z:
                continue
            if normal.Z > -FLAT_MIN_Z:
                shape.sloped = True

            outline = _face_outline(face, transform)
            if outline is not None:
                shape.outlines.append(outline)

    if not points:
        return None, ["no usable soffit geometry (check the link's "
                      "view detail level)"]

    shape.base_z = min(p[2] for p in points)
    shape.top_z  = max(p[2] for p in points)

    if not shape.outlines:
        ring = plan_shapes.bbox_ring([(p[0], p[1]) for p in points])
        if ring is None:
            return None, ["soffit has no plan area"]
        shape.outlines = [(ring, [])]
        shape.approximate = True
        notes.append(
            "could not read the soffit's underside{} - limiting walls "
            "by its bounding rectangle instead".format(
                ", which is curved or meshed" if curved else ""))

    if shape.sloped:
        notes.append(
            "soffit is pitched - walls under it stop at its lowest "
            "point, {} below its highest".format(
                _feet(shape.top_z - shape.base_z)))

    return shape, notes


def _feet(value):
    """A bare decimal-feet string, for a note that only needs a size."""
    return "{:.2f} ft".format(value)


def limits_wall(shape, p0, p1, reach=0.0):
    """True when the wall segment *p0*-*p1* runs under this soffit."""
    for outer, holes in shape.outlines:
        if plan_shapes.segment_meets_outline(p0, p1, outer, holes,
                                             reach=reach):
            return True
    return False
