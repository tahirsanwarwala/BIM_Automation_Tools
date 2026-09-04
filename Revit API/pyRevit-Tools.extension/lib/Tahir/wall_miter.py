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

# Below this sine of the angle between two walls -- about 5.7 degrees --
# one is running ALONGSIDE the other, not into it.  Their offset lines
# still cross, but far away: at two degrees a foot of offset puts the
# crossing fifty-seven feet off, and trimming a wall to it would stretch
# it across the building.
MIN_TEE_SINE = 0.1


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


def _touches_interior(point, seg, tol, reach=None):
    """True when *point* lands on *seg* but not at either of its ends.

    The ends are excluded because a point there is a CORNER, which is
    already handled and handled differently -- both walls move for a
    corner, only one for a tee.

    *reach* is how far short of the segment *point* may stop and still
    count, and it defaults to *tol*.  A wall is often modelled to the
    FACE of the wall it meets rather than to its centreline, which
    leaves its end half a thickness short; a caller that knows the
    thickness can say so and have those found.
    """
    if reach is None:
        reach = tol

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
    if abs(px - foot[0]) > reach or abs(py - foot[1]) > reach:
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


def _unit(seg):
    """Unit direction of a segment, or None when it has no length."""
    dx, dy = _direction(seg)
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0.0:
        return None
    return (dx / length, dy / length)


def _side_of(point, seg):
    """Which side of *seg*'s infinite line *point* falls, as a sign."""
    (ax, ay), (bx, by) = seg
    return ((bx - ax) * (point[1] - ay)) - ((by - ay) * (point[0] - ax))


def _tee_target(originals, offsets, i, a, j):
    """Where end *a* of segment *i* should go, teeing into *j*, or None.

    Two things it refuses to do.

    It will not trim a wall THROUGH the wall it meets.  The offset lines
    of the two cross on whichever side *j*'s own offset lies, and when
    the arriving wall comes from the other side that crossing is past
    *j* altogether -- trimming to it would bury the wall in its host and
    push it out the far face.  In that case the wall stops at *j*'s
    centreline instead, which is as far as it can go without going
    through.

    It will not act on two walls that are nearly parallel: they are
    running alongside each other, and their offset lines cross so far
    away that trimming would stretch the wall across the building.
    """
    u_i = _unit(offsets[i])
    u_j = _unit(offsets[j])
    if u_i is None or u_j is None:
        return None
    if abs(u_i[0] * u_j[1] - u_i[1] * u_j[0]) < MIN_TEE_SINE:
        return None

    hit = line_intersection_2d(
        offsets[i][0], _direction(offsets[i]),
        offsets[j][0], _direction(offsets[j]))
    if hit is None:
        return None

    # The arriving wall's body is its OTHER end; that is the side of the
    # through wall it lives on, and the side its trimmed end must stay.
    body = originals[i][1 - a]
    if _side_of(hit, originals[j]) * _side_of(body, originals[j]) < 0.0:
        return line_intersection_2d(
            offsets[i][0], _direction(offsets[i]),
            originals[j][0], _direction(originals[j]))

    return hit


def junction_pairs(originals, tol=TOL_JOIN, tee_reach=None):
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
            if (_touches_interior(originals[i][0], originals[j], tol,
                                  tee_reach)
                    or _touches_interior(originals[i][1], originals[j], tol,
                                         tee_reach)
                    or _touches_interior(originals[j][0], originals[i], tol,
                                         tee_reach)
                    or _touches_interior(originals[j][1], originals[i], tol,
                                         tee_reach)):
                pairs.append((i, j))
    return pairs


def miter_chain(originals, offsets, tol=TOL_JOIN, tees=False,
                tee_reach=None):
    """Close the corners of a chain of offset wall centrelines.

    *originals* and *offsets* are parallel lists of ((x0,y0),(x1,y1)).
    Adjacency is decided on the ORIGINAL curves -- those still share their
    endpoints -- while the intersection is computed on the OFFSET lines.

    With *tees* on, a segment that ends partway along another is trimmed
    to it instead: only the ending segment moves, because the one
    running past has no corner there to close.  It is OFF by default
    because this module is shared, and a caller that mitres a whole
    selection in one go would start trimming every interior wall whose
    end lands on an exterior wall -- a change it never asked for.
    *tee_reach* widens how far short of a wall an end may stop and still
    count as meeting it; see _touches_interior.

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
            a, b = hit
            if corner is None:
                # Straight-on continuation: nothing to mitre, but these
                # ends have still met each other, and letting a tee
                # claim one afterwards would move only that one.
                cornered.add((i, a))
                cornered.add((j, b))
                continue

            result[i][a] = corner
            result[j][b] = corner
            cornered.add((i, a))
            cornered.add((j, b))

    if not tees:
        return [(seg[0], seg[1]) for seg in result]

    # Then tees, on whatever ends the corners did not claim.
    for i in range(count):
        for a in (0, 1):
            if (i, a) in cornered:
                continue
            for j in range(count):
                if j == i:
                    continue
                if not _touches_interior(originals[i][a], originals[j], tol,
                                         tee_reach):
                    continue

                meeting = _tee_target(originals, offsets, i, a, j)
                if meeting is None:
                    continue  # alongside, not into

                result[i][a] = meeting
                break

    return [(seg[0], seg[1]) for seg in result]


def _straddles(seg, other):
    """True when *seg*'s ends fall on opposite sides of *other*'s line."""
    first = _side_of(seg[0], other)
    second = _side_of(seg[1], other)
    return (first <= 0.0 <= second) or (second <= 0.0 <= first)


def segments_meet(a, b, tol=TOL_JOIN):
    """True when two FINISHED centrelines actually touch.

    junction_pairs answers a different question: which junctions exist
    in the source walls, and so what ought to be mitred.  Whether the
    walls that came out of that mitring ended up touching is not the
    same thing -- a corner the mitring did not reach leaves two walls a
    foot apart, and asking Revit to join those is what produces
    "elements joined but do not intersect".

    Touching means either the two share an end, or they genuinely cross
    within both their lengths.  An intersection of the infinite lines
    beyond one of the ends is not contact.
    """
    for end_a in (0, 1):
        for end_b in (0, 1):
            if _is_close(a[end_a], b[end_b], tol):
                return True

    length_a = _unit(a)
    length_b = _unit(b)
    if length_a is None or length_b is None:
        return False

    # Each must straddle the other's line, or they cross only where one
    # of them has already ended.
    return _straddles(a, b) and _straddles(b, a)
