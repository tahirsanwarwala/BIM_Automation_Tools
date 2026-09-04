# -*- coding: utf-8 -*-
"""Closing the corners and junctions of offset wall centrelines.

When a chain of walls is offset sideways -- as a SKIN wall is offset out
to the face of its parent -- the offset centrelines no longer meet at the
corners.  Each corner gains a gap on the outside and an overshoot on the
inside, and because the endpoints no longer coincide Revit will not join
the walls either.

The fix is to mitre: replace each pair of coincident endpoints with the
point where the two offset lines actually cross.

Not every junction is a corner.  A wall that ends partway along another
-- a return, a party wall, a pier off a long elevation -- shares no
endpoint with it at all, and matching endpoints alone left the two
running straight through each other.  That case is a TEE, and it is
one-sided: the wall that ends moves to meet the one that carries on,
and the one that carries on is not shortened.

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


def _touches_interior(point, seg, tol):
    """True when *point* lands on *seg* but not at either of its ends.

    The ends are excluded because a point there is a CORNER, which is
    already handled and handled differently -- both walls move for a
    corner, only one for a tee.
    """
    (ax, ay), (bx, by) = seg
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return False

    px, py = point
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    if t <= 0.0 or t >= 1.0:
        return False

    foot = (ax + dx * t, ay + dy * t)
    if not _is_close(point, foot, tol):
        return False

    return not (_is_close(point, (ax, ay), tol)
                or _is_close(point, (bx, by), tol))


def _corner_hit(originals, i, j, tol):
    """Which ends of i and j coincide, as (a, b), or None."""
    for a in (0, 1):
        for b in (0, 1):
            if _is_close(originals[i][a], originals[j][b], tol):
                return (a, b)
    return None


def junction_pairs(originals, tol=TOL_JOIN):
    """Index pairs of segments that meet, whether at a corner or a tee.

    The same adjacency miter_chain acts on, handed back so a caller can
    do something else with it -- joining the two walls in Revit, say, so
    it cleans the junction itself.  Each pair appears once, lower index
    first, in index order.
    """
    pairs = []
    count = len(originals)
    for i in range(count):
        for j in range(i + 1, count):
            if _corner_hit(originals, i, j, tol) is not None:
                pairs.append((i, j))
                continue
            if (_touches_interior(originals[i][0], originals[j], tol)
                    or _touches_interior(originals[i][1], originals[j], tol)
                    or _touches_interior(originals[j][0], originals[i], tol)
                    or _touches_interior(originals[j][1], originals[i], tol)):
                pairs.append((i, j))
    return pairs


def miter_chain(originals, offsets, tol=TOL_JOIN):
    """Close the corners of a chain of offset wall centrelines.

    *originals* and *offsets* are parallel lists of ((x0,y0),(x1,y1)).
    Adjacency is decided on the ORIGINAL curves -- those still share their
    endpoints -- while the intersection is computed on the OFFSET lines.

    A segment that ends partway along another is trimmed to it instead:
    only the ending segment moves, because the one running past has no
    corner there to close.

    Returns a new list of offsets; the inputs are left untouched.  Pairs
    whose offset lines are parallel (straight-on continuations, where
    there is no corner to mitre) are returned unchanged.
    """
    result = [[seg[0], seg[1]] for seg in offsets]

    count = len(originals)

    # Corners first.  A wall can both corner into one neighbour and tee
    # into another, and a corner is the stronger claim on an end: it is
    # backed by two walls agreeing on where they stop, where a tee is
    # one wall arriving at a line.
    cornered = set()
    for i in range(count):
        for j in range(i + 1, count):
            hit = _corner_hit(originals, i, j, tol)
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
            cornered.add((i, a))
            cornered.add((j, b))

    # Then tees, on whatever ends the corners did not claim.
    for i in range(count):
        for a in (0, 1):
            if (i, a) in cornered:
                continue
            for j in range(count):
                if j == i:
                    continue
                if not _touches_interior(originals[i][a], originals[j], tol):
                    continue

                meeting = line_intersection_2d(
                    offsets[i][0], _direction(offsets[i]),
                    offsets[j][0], _direction(offsets[j]),
                )
                if meeting is None:
                    continue  # parallel: it runs alongside, not into

                result[i][a] = meeting
                break

    return [(seg[0], seg[1]) for seg in result]
