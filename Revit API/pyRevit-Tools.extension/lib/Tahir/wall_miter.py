# -*- coding: utf-8 -*-
"""Mitring of offset wall centrelines at shared corners.

When a chain of walls is offset sideways -- as a SKIN wall is offset out
to the face of its parent -- the offset centrelines no longer meet at the
corners.  Each corner gains a gap on the outside and an overshoot on the
inside, and because the endpoints no longer coincide Revit will not join
the walls either.

The fix is to mitre: replace each pair of coincident endpoints with the
point where the two offset lines actually cross.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.  Everything here is plain 2D (x, y); the caller keeps track of Z.
"""

# Coincident-endpoint tolerance, in feet (about 1/64 inch)
TOL_JOIN = 0.0013


def line_intersection_2d(p1, d1, p2, d2, tol=1e-12):
    """Intersect two infinite 2D lines given as point + direction.

    Returns (x, y), or None when the lines are parallel or collinear.
    """
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < tol:
        return None

    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    t = (dx * d2[1] - dy * d2[0]) / cross
    return (p1[0] + d1[0] * t, p1[1] + d1[1] * t)


def _direction(seg):
    """Direction vector of a ((x0,y0),(x1,y1)) segment."""
    return (seg[1][0] - seg[0][0], seg[1][1] - seg[0][1])


def _is_close(a, b, tol):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def miter_chain(originals, offsets, tol=TOL_JOIN):
    """Close the corners of a chain of offset wall centrelines.

    *originals* and *offsets* are parallel lists of ((x0,y0),(x1,y1)).
    Adjacency is decided on the ORIGINAL curves -- those still share their
    endpoints -- while the intersection is computed on the OFFSET lines.

    Returns a new list of offsets; the inputs are left untouched.  Pairs
    whose offset lines are parallel (straight-on continuations, where
    there is no corner to mitre) are returned unchanged.
    """
    result = [[seg[0], seg[1]] for seg in offsets]

    count = len(originals)
    for i in range(count):
        for j in range(i + 1, count):
            hit = None
            for a in (0, 1):
                for b in (0, 1):
                    if _is_close(originals[i][a], originals[j][b], tol):
                        hit = (a, b)
                        break
                if hit:
                    break

            if hit is None:
                continue

            # Directions come from the ORIGINAL offset segments, so a wall
            # with corners at both ends does not skew the second corner
            # using an endpoint the first corner already moved.
            corner = line_intersection_2d(
                offsets[i][0], _direction(offsets[i]),
                offsets[j][0], _direction(offsets[j]),
            )
            if corner is None:
                continue  # parallel: nothing to mitre

            a, b = hit
            result[i][a] = corner
            result[j][b] = corner

    return [(seg[0], seg[1]) for seg in result]
