# -*- coding: utf-8 -*-
"""Shared machinery for building chains of new walls alongside existing ones.

Three things the wall tools both need: working out which host level a piece
of geometry belongs to, reading a wall's real faces off its solid, and
turning a set of sideways-offset wall centrelines into a chain whose corners
actually meet.

The corner problem is the important one.  Offsetting each wall's centreline
sideways leaves the offset lines no longer meeting at a corner -- there is a
gap on the outside and an overshoot on the inside -- and because the
endpoints no longer coincide Revit will not join the walls either.  The fix
is to mitre: replace each pair of coincident endpoints with the point where
the two offset lines actually cross.  That is Tahir.wall_miter; this module
puts Revit geometry in and out of it.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    FilteredElementCollector,
    GeometryInstance,
    Level,
    Line,
    Options,
    Solid,
    ViewDetailLevel,
    XYZ,
)

from Tahir import wall_miter

# Matching a level to an elevation, in feet.
LEVEL_TOL = 1e-4


# ===========================================================================
# LEVELS
# ===========================================================================

def project_base_elevation(doc):
    """Return the offset between level elevations and model geometry.

    Levels report their elevation relative to the Project Base Point, while
    solid geometry comes back in internal model coordinates.  When the base
    point sits at elevation 0 the two spaces coincide and this returns 0.0,
    so the conversion is harmless in ordinary projects.

    Measured example: a project base point at 895 ft makes LEVEL 04 report
    995 ft while its geometry sits at 100 ft.
    """
    try:
        col = FilteredElementCollector(doc) \
            .OfCategory(BuiltInCategory.OST_ProjectBasePoint) \
            .WhereElementIsNotElementType()
        for bp in col:
            p = bp.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)
            if p and p.HasValue:
                return p.AsDouble()
    except Exception:
        pass
    return 0.0


class LevelFinder(object):
    """Host levels, converted once into geometry space."""

    def __init__(self, doc):
        delta = project_base_elevation(doc)
        self.pairs = sorted(
            ((lvl, lvl.Elevation - delta)
             for lvl in FilteredElementCollector(doc).OfClass(Level)),
            key=lambda p: p[1])

    def below(self, elevation):
        """Return (Level, its geometry-space elevation) at or below
        *elevation*, falling back to the lowest level.  (None, 0.0) if the
        model has no levels at all.
        """
        if not self.pairs:
            return None, 0.0

        found = None
        for pair in self.pairs:
            if pair[1] <= elevation + LEVEL_TOL:
                found = pair
            else:
                break
        return found or self.pairs[0]


# ===========================================================================
# GEOMETRY
# ===========================================================================

def iter_solids(elem):
    """Yield the solid geometry of *elem*, unwrapping geometry instances."""
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Fine

    try:
        geo_elem = elem.get_Geometry(opts)
    except Exception:
        return
    if geo_elem is None:
        return

    for gobj in geo_elem:
        found = []
        if isinstance(gobj, Solid):
            found.append(gobj)
        elif isinstance(gobj, GeometryInstance):
            try:
                for g2 in gobj.GetInstanceGeometry():
                    if isinstance(g2, Solid):
                        found.append(g2)
            except Exception:
                continue

        for sol in found:
            try:
                if sol.Volume <= 0:
                    continue
            except Exception:
                continue
            yield sol


def iter_solid_points(elem, transform=None):
    """Yield every tessellated vertex of *elem*'s solids."""
    for sol in iter_solids(elem):
        for edge in sol.Edges:
            try:
                for pt in edge.Tessellate():
                    yield transform.OfPoint(pt) if transform else pt
            except Exception:
                continue


# ===========================================================================
# WALL FRAMES
# ===========================================================================

class WallFrame(object):
    """A wall's location and orientation, ready to offset from."""

    __slots__ = ("wall", "curve", "normal", "width", "is_line",
                 "origin", "direction", "length")

    def __init__(self, wall, curve, normal, width):
        self.wall    = wall
        self.curve   = curve
        self.normal  = normal
        self.width   = width
        self.is_line = isinstance(curve, Line)

        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        self.origin = p0
        self.length = p0.DistanceTo(p1) if self.is_line else curve.Length
        self.direction = (p1 - p0).Normalize() if self.is_line else None

    def point_at(self, along):
        """Point on the wall's location curve *along* feet from its start."""
        return XYZ(self.origin.X + self.direction.X * along,
                   self.origin.Y + self.direction.Y * along,
                   self.origin.Z + self.direction.Z * along)


def wall_frame(wall, transform=None):
    """Build a WallFrame for *wall*, or None.

    Pass a link's total transform for a wall inside a link; leave it out for
    a wall in the current model.
    """
    try:
        loc = wall.Location
        if loc is None or not hasattr(loc, "Curve"):
            return None

        curve  = loc.Curve
        normal = wall.Orientation
        if transform is not None:
            curve  = curve.CreateTransformed(transform)
            normal = transform.OfVector(normal)

        return WallFrame(wall, curve, normal.Normalize(), wall.WallType.Width)
    except Exception:
        return None


def wall_exterior_offset(frame, transform=None):
    """Distance from a wall's LOCATION CURVE to its exterior finish face.

    Measured off the wall's real solid rather than inferred, so it is right
    whatever the wall's Location Line is set to and however asymmetric its
    layer build-up is -- the location curve is only the centreline when the
    wall happens to be set that way, and these tools routinely meet walls
    that are not.

    Falls back to half the wall's thickness when the geometry cannot be read.
    """
    try:
        ref_pt = frame.curve.GetEndPoint(0)
        normal = frame.normal

        far = None
        for pt in iter_solid_points(frame.wall, transform):
            d = (pt - ref_pt).DotProduct(normal)
            if far is None or d > far:
                far = d

        if far is not None:
            return far
    except Exception:
        pass

    return frame.width / 2.0


# ===========================================================================
# CHAIN ASSEMBLY
# ===========================================================================

class Segment(object):
    """One wall's worth of a chain, ready to be mitred and built."""

    __slots__ = ("frame", "centre_ends", "offset_ends", "z")

    def __init__(self, frame, offset_distance, along_min=0.0, along_max=None):
        self.frame = frame

        if along_max is None:
            along_max = frame.length

        start = frame.point_at(along_min)
        end   = frame.point_at(along_max)

        vec = XYZ(frame.normal.X * offset_distance,
                  frame.normal.Y * offset_distance,
                  frame.normal.Z * offset_distance)

        # Adjacency is judged on the ends of the stretch being built, not on
        # the wall's own endpoints, so a partial stretch is never stretched
        # to a corner it does not actually reach.
        self.centre_ends = ((start.X, start.Y), (end.X, end.Y))
        self.offset_ends = ((start.X + vec.X, start.Y + vec.Y),
                            (end.X + vec.X, end.Y + vec.Y))
        self.z = (start.Z + vec.Z, end.Z + vec.Z)


def mitre_segments(segments, tol=wall_miter.TOL_JOIN, tees=False,
                   tee_reach=None):
    """Return a mitred bound Line for each segment, corners closed.

    Segments whose ends do not coincide with any neighbour come back
    unchanged, unless *tees* is on -- then a segment ending partway
    along another is trimmed to it.  Off by default so a caller that
    never asked for tee trimming does not silently start getting it;
    see wall_miter.miter_chain.
    """
    if not segments:
        return []

    originals = [seg.centre_ends for seg in segments]
    offsets   = [seg.offset_ends for seg in segments]
    mitred    = wall_miter.miter_chain(originals, offsets, tol,
                                       tees, tee_reach)

    curves = []
    for seg, ends in zip(segments, mitred):
        (x0, y0), (x1, y1) = ends
        z0, z1 = seg.z
        try:
            curves.append(Line.CreateBound(XYZ(x0, y0, z0), XYZ(x1, y1, z1)))
        except Exception:
            curves.append(None)
    return curves
