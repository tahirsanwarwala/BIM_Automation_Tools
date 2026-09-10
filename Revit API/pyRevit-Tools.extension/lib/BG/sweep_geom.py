# -*- coding: utf-8 -*-
"""The arithmetic behind rebuilding a hosted sweep on a host roof.

No Revit here at all, so this is unit-tested in ordinary CPython.
Points are plain (x, y, z) tuples in decimal feet; the Revit-facing
half converts XYZ at the boundary.

The one idea worth explaining is the EDGE KEY.  To rebuild a fascia we
must decide, for an edge read out of a linked roof, which edge of the
host roof is the same one.  The roofs came over by Revit's own copy, so
the two edges are the same numbers give or take the floating-point cost
of pushing a point through the link transform -- which means a
dictionary keyed on the endpoints, rounded, answers it in one lookup
instead of a scan.

Rounding to a grid has exactly one flaw, and it is worth being careful
about because the failure is silent: two points a hair apart land in
DIFFERENT cells whenever they straddle a cell boundary.  So the index
is built with edge_key(), and looked up with edge_key_candidates(),
which offers every cell the edge could have been filed under -- each
coordinate rounded both down and up.  Building is one key; looking up
is a few dozen dictionary probes, which costs nothing and removes the
only way an edge that IS there could be missed.

Two tolerances, and they are deliberately far apart:

EDGE_TOL is a thirty-second of an inch, because the host roof's edges
should be bit-for-bit what the link holds.  It absorbs transform noise
and nothing else.  Loosening it until it could bridge a roof that is
genuinely different would mean hosting a fascia on the wrong edge --
worse than not hosting it.

ROOF_TOL is an inch, the same inch link_copy uses, because a roof may
have been nudged by hand after it was copied and is still that roof.
"""

# A thirty-second of an inch, in feet.
EDGE_TOL = 1.0 / 32.0 / 12.0

# An inch, in feet.
ROOF_TOL = 1.0 / 12.0


def round_point(p, tol):
    """The grid cell *p* falls in, as three integers."""
    return (int(round(p[0] / tol)),
            int(round(p[1] / tol)),
            int(round(p[2] / tol)))


def edge_key(p, q, tol):
    """One key for the edge from *p* to *q*, direction ignored.

    The rounded endpoints are SORTED, so an edge read one way round
    keys the same as the same edge read the other way round -- which
    matters because nothing guarantees Revit hands us the two roofs'
    edges wound the same way.
    """
    a = round_point(p, tol)
    b = round_point(q, tol)
    return (a, b) if a <= b else (b, a)


def _cell_candidates(p, tol):
    """Every grid cell *p* might have been filed under.

    Each coordinate rounded down and up: eight cells, or fewer when the
    two agree, which is the usual case.
    """
    per_axis = []
    for value in p:
        scaled = value / tol
        low = int(scaled // 1)
        per_axis.append(sorted(set([low, low + 1])))

    cells = []
    for x in per_axis[0]:
        for y in per_axis[1]:
            for z in per_axis[2]:
                cells.append((x, y, z))

    # The plain rounding first: it is nearly always the right one, and
    # trying it first means the usual lookup stops at the first probe.
    exact = round_point(p, tol)
    if exact in cells:
        cells.remove(exact)
    return [exact] + cells


def edge_key_candidates(p, q, tol):
    """Every key the edge from *p* to *q* could have been filed under."""
    keys = []
    seen = set()
    for a in _cell_candidates(p, tol):
        for b in _cell_candidates(q, tol):
            key = (a, b) if a <= b else (b, a)
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def points_match(p, q, tol):
    """True when *p* and *q* are the same point, to *tol*."""
    return (abs(p[0] - q[0]) <= tol
            and abs(p[1] - q[1]) <= tol
            and abs(p[2] - q[2]) <= tol)


def box_of(points):
    """The axis-aligned box enclosing *points*, or None if there are none.

    Used on the eight transformed corners of a linked roof's bounding
    box: a rotated link turns a box into a box at an angle, and the box
    around that is what can be compared with the host's.
    """
    points = list(points)
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


def boxes_match(a, b, tol):
    """True when two boxes agree corner for corner, to *tol*.

    Both corners, not the centre: comparing low and high fixes the size
    and the position together, so nothing else needs testing.
    """
    if a is None or b is None:
        return False
    return points_match(a[0], b[0], tol) and points_match(a[1], b[1], tol)


def centroid(points):
    """The middle of *points*, or None.  For naming a roof in a report."""
    points = list(points)
    if not points:
        return None
    n = float(len(points))
    return (sum(p[0] for p in points) / n,
            sum(p[1] for p in points) / n,
            sum(p[2] for p in points) / n)


def already_there(index, type_key, edge_keys):
    """True when the host already holds this sweep.

    *index* is {(family, type): set of edge_key} for the sweeps the host
    holds.  A sweep is already there when one of the same family and
    type stands on ANY ONE of the edges this one wants.

    One shared edge is proof enough.  Two fascias of a single type on
    one roof edge is never something anybody meant, so a shared edge
    cannot be coincidence -- and demanding the whole segment list match
    would let a re-run double up a sweep somebody had since extended.
    """
    held = index.get(type_key)
    if not held:
        return False
    for key in edge_keys:
        if key in held:
            return True
    return False
