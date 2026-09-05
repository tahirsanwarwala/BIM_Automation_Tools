# -*- coding: utf-8 -*-
"""Flat plan shapes: is this wall under that soffit?

A wall sweep knows which walls it belongs to, because the link records
it -- GetHostIds() answers outright.  A roof soffit records nothing of
the kind.  It is a slab hanging in space, and the only honest way to
say which walls it limits is to look at where it sits in plan.

So this is the plan half of that question, and only the plan half: a
ring is a closed list of (x, y), an outline is one ring with any number
of holes in it, and a wall is the 2D segment of its centreline.  The
caller keeps track of Z, of which ring came off which face, and of what
to do with the answer.

The one thing here that is not plain geometry is *reach*.  A soffit
usually stops at a wall's face, not at its centreline, so testing the
bare centreline would miss a soffit that plainly covers the wall.
Passing half the wall's thickness as *reach* asks the question the
building asks: is any part of this wall under that soffit?

Deliberately free of any Revit import so it can be unit-tested outside
Revit.
"""

# Coincidence tolerance, in feet.  Small: this decides "touching", and
# the caller's *reach* is what decides "near enough".
TOL = 1e-9


def _cross(ox, oy, ax, ay, bx, by):
    """Z of (a - o) x (b - o)."""
    return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)


def point_segment_distance(p, a, b):
    """Distance from point *p* to the segment *a*-*b*."""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    span = dx * dx + dy * dy

    if span <= 0.0:
        return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** 0.5

    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span
    t = max(0.0, min(1.0, t))
    return ((p[0] - a[0] - t * dx) ** 2 + (p[1] - a[1] - t * dy) ** 2) ** 0.5


def segment_distance(a0, a1, b0, b1):
    """Distance between two 2D segments; zero where they cross."""
    d1x = a1[0] - a0[0]
    d1y = a1[1] - a0[1]
    d2x = b1[0] - b0[0]
    d2y = b1[1] - b0[1]

    den = d1x * d2y - d1y * d2x
    if abs(den) > 1e-15:
        ox = b0[0] - a0[0]
        oy = b0[1] - a0[1]
        t = (ox * d2y - oy * d2x) / den
        u = (ox * d1y - oy * d1x) / den
        if -TOL <= t <= 1.0 + TOL and -TOL <= u <= 1.0 + TOL:
            return 0.0

    return min(point_segment_distance(a0, b0, b1),
               point_segment_distance(a1, b0, b1),
               point_segment_distance(b0, a0, a1),
               point_segment_distance(b1, a0, a1))


def segments_cross(a0, a1, b0, b1, tol=TOL):
    """True when two segments meet -- crossing, touching or overlapping.

    Distance rather than orientation signs, so an end landing on the
    other segment and two collinear segments overlapping both count,
    which is what a wall running into a soffit's edge looks like.
    """
    return segment_distance(a0, a1, b0, b1) <= tol


def ring_edges(ring):
    """Yield a closed ring's edges as (a, b) pairs."""
    n = len(ring)
    for i in range(n):
        yield ring[i], ring[(i + 1) % n]


def point_in_ring(point, ring, tol=TOL):
    """True when *point* is inside the closed *ring*, edges included.

    A point ON an edge counts as inside.  A soffit drawn exactly to a
    wall's centreline is a real drawing, not a near miss, and calling
    it outside would drop the soffit for that wall.
    """
    if len(ring) < 3:
        return False

    for a, b in ring_edges(ring):
        if point_segment_distance(point, a, b) <= tol:
            return True

    x, y = point[0], point[1]
    inside = False

    # Half-open crossing rule: an edge counts while its lower end is at
    # or below y and its upper end above.  That is what stops a ray
    # grazing a vertex from being counted once for each edge meeting
    # there -- which would put an L-shaped soffit's own corner outside
    # itself.
    for a, b in ring_edges(ring):
        if (a[1] > y) != (b[1] > y):
            cut = b[0] + (y - b[1]) * (a[0] - b[0]) / (a[1] - b[1])
            if x < cut:
                inside = not inside

    return inside


def segment_ring_distance(p0, p1, ring):
    """Shortest distance from segment *p0*-*p1* to a ring's boundary."""
    if len(ring) < 2:
        return float("inf")
    return min(segment_distance(p0, p1, a, b) for a, b in ring_edges(ring))


def segment_meets_outline(p0, p1, outer, holes=None, reach=0.0, tol=TOL):
    """True when the segment lies on the outline, or within *reach* of it.

    *outer* is the outline's boundary ring and *holes* the rings cut out
    of it.  A segment wholly inside a hole is outside the outline, which
    is the whole reason holes are carried at all: a soffit with a
    lightwell through it does not limit the wall standing in that well.

    *reach* widens the outline outwards -- half a wall's thickness, so
    a soffit stopping at the wall's face still counts as covering it.
    It widens the holes the same way, since a wall grazing the edge of
    a lightwell is still partly under the soffit.
    """
    if len(outer) < 3:
        return False

    span = reach + tol

    # Touching or crossing the boundary settles it: part of the segment
    # is on the solid side.
    if segment_ring_distance(p0, p1, outer) <= span:
        return True

    # Clear of the boundary, so the segment is wholly in or wholly out,
    # and either end answers for both.
    if not point_in_ring(p0, outer, tol):
        return False

    for hole in holes or []:
        if len(hole) < 3:
            continue
        if segment_ring_distance(p0, p1, hole) <= span:
            return True
        if point_in_ring(p0, hole, tol):
            return False

    return True


def bbox_ring(points, tol=TOL):
    """The rectangle enclosing *points*, as a ring, or None.

    The fallback outline for a soffit whose real one could not be read.
    Returns None for a cloud with no area, which no wall can be under.
    """
    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)

    if x1 - x0 <= tol or y1 - y0 <= tol:
        return None

    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
