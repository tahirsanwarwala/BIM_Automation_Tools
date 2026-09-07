# -*- coding: utf-8 -*-
"""Is this wall already standing here?

Run Multi Wall Creation twice over the same facade and, without this,
you get two of everything: a second skin wall inside the first, a
second coping on top of the first, invisible in any view and wrong in
every schedule.

The test is per WALL, and that matters more than it looks.  One sweep
becomes a run of walls -- a course along four elevations is four of
them -- and only the ones standing where a wall already stands are
dropped.  The rest of that sweep is built as if nothing had happened,
because the question is never "has this sweep been done" but "is there
already a wall HERE".

A wall counts as already here when the host holds one of the SAME TYPE
whose centreline runs between the same two points and whose base and
top sit at the same elevations.  All three earn their keep:

  * the type, because a stone coping and an EIFS cornice can run the
    same line at the same height and are not each other;
  * the ends, because that is what "here" means in plan -- and for a
    curved wall the middle as well, since two arcs on one chord can
    bulge opposite ways;
  * BOTH elevations, because the bands of one skin wall stack directly
    above each other on identical plan lines, and base alone would read
    the second storey as a duplicate of the first.

An inch of tolerance.  A wall built by a previous run of this tool sits
at exactly the same computed numbers, so nothing this loose is needed
for that -- it is there for one placed or nudged by hand.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    Level,
    Line,
    Wall,
)
from pyrevit import script

from BG import wall_bands, window_cw

logger = script.get_logger()

# How far out a wall may be, in feet, and still be the same wall.
TOL = 1.0 / 12.0


def _level_elevation(doc, level_id, delta):
    """A host level's elevation in GEOMETRY space, or None.

    The same space the tool works its bands out in, which is why the
    project base point is subtracted here rather than left to the
    caller to remember.
    """
    if level_id is None or level_id == ElementId.InvalidElementId:
        return None
    level = doc.GetElement(level_id)
    if not isinstance(level, Level):
        return None
    return level.Elevation - delta


def wall_span(doc, wall, delta):
    """(base_z, top_z) for a host wall, from its constraints.

    From the CONSTRAINTS and not the bounding box.  A wall joined to
    its neighbours, or carrying a sweep, has a box larger than the wall
    -- and the numbers this is compared against come from constraints,
    so reading the same thing at both ends is what makes the comparison
    mean anything.
    """
    base_p = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
    base_elev = _level_elevation(
        doc, base_p.AsElementId(), delta) if base_p else None
    if base_elev is None:
        return None, None

    bo_p = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    base_offset = bo_p.AsDouble() if (bo_p and bo_p.HasValue) else 0.0

    top_p = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
    top_elev = None
    if top_p and top_p.HasValue:
        top_elev = _level_elevation(doc, top_p.AsElementId(), delta)

    to_p = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
    top_offset = to_p.AsDouble() if (to_p and to_p.HasValue) else 0.0

    h_p = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
    height = h_p.AsDouble() if (h_p and h_p.HasValue) else 0.0

    try:
        return wall_bands.wall_span(base_elev, base_offset,
                                    top_elev, top_offset, height)
    except Exception:
        return None, None


def _curve_marks(curve):
    """The (start, end, middle) of a curve, as plain 2D pairs, or None.

    The middle is what tells two arcs on one chord apart.  A line's
    middle is the midpoint of its ends and says nothing new, which
    costs one comparison and keeps the record one shape.
    """
    if curve is None:
        return None
    try:
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        mid = (curve.Evaluate(0.5, True) if not isinstance(curve, Line)
               else None)
    except Exception:
        return None

    if mid is None:
        mid_xy = ((p0.X + p1.X) / 2.0, (p0.Y + p1.Y) / 2.0)
    else:
        mid_xy = (mid.X, mid.Y)

    return (p0.X, p0.Y), (p1.X, p1.Y), mid_xy


def host_index(doc):
    """{type id: [record]} for every wall already in the host model.

    Built once for a whole run.  A wall whose span or curve cannot be
    read is left out: it can never be matched, so the worst it costs is
    a wall built beside it, which is the outcome without any of this.
    """
    delta = window_cw.project_base_elevation(doc)
    index = {}

    for wall in (FilteredElementCollector(doc)
                 .OfClass(Wall)
                 .WhereElementIsNotElementType()):
        try:
            loc = wall.Location
            marks = _curve_marks(loc.Curve if loc is not None else None)
        except Exception:
            marks = None
        if marks is None:
            continue

        base_z, top_z = wall_span(doc, wall, delta)
        if base_z is None or top_z is None:
            continue

        try:
            type_id = wall.WallType.Id.IntegerValue
        except Exception:
            continue

        index.setdefault(type_id, []).append(
            (marks[0], marks[1], marks[2], base_z, top_z, wall))

    return index


def _near(a, b, tol):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def find(index, type_id, curve, base_z, top_z, tol=TOL):
    """The host wall already standing here, or None.

    Returns the WALL rather than a yes, because a caller that skips
    building one still has work for it: a window has to be hosted on
    something, and the thing already standing there is what it is
    hosted on.
    """
    marks = _curve_marks(curve)
    if marks is None:
        return None
    a, b, mid = marks

    for rec_a, rec_b, rec_mid, rec_base, rec_top, wall in index.get(
            type_id, ()):
        if abs(rec_base - base_z) > tol or abs(rec_top - top_z) > tol:
            continue
        # Either way round: which end Revit calls the start is not
        # something the building has an opinion about.
        same_way    = _near(rec_a, a, tol) and _near(rec_b, b, tol)
        other_way   = _near(rec_a, b, tol) and _near(rec_b, a, tol)
        if not (same_way or other_way):
            continue
        if not _near(rec_mid, mid, tol):
            continue
        return wall

    return None


def register(index, type_id, curve, base_z, top_z, wall):
    """Add a wall this run just built, so nothing lands on top of it.

    Two picked sources can resolve to the same wall in the same place
    -- a sweep hosted on two walls the link drew separately, say -- and
    without this the second would be built inside the first.
    """
    marks = _curve_marks(curve)
    if marks is None:
        return
    index.setdefault(type_id, []).append(
        (marks[0], marks[1], marks[2], base_z, top_z, wall))
