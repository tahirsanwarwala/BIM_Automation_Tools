# -*- coding: utf-8 -*-
"""Are these two walls in each other's way, and by enough to matter?

Revit's own warnings say yes to every hairline touch, which is why they
are ignored.  This answers a narrower question: how far would you have
to SHOVE one wall to get it clear of the other?  That distance is the
one number a tolerance can be set against, and it reads correctly for
every shape of mistake:

  two walls butting half an inch too far   -> half an inch, along the run
  a wall buried two inches past a face     -> two inches, across the face
  two skins biting into each other         -> the bite, sideways
  a wall sitting inside another            -> the wall's own thickness

WHY A SHOVE AND NOT A VOLUME.  A volume cannot be compared against a
tolerance a person can picture.  Half a cubic foot is a bad overlap
between two thin walls and a rounding error between two thick ones; an
inch is an inch.

THE CORNER PROBLEM.  Every L and every T in a building is, strictly,
two walls overlapping by half a thickness.  Reporting those buries the
real mistakes, so a junction between walls that are NOT parallel is
forgiven as long as the arriving end stops at or before the other
wall's centre line -- which is where walls are drawn to.  Going past
the centre line by more than the tolerance is not a junction any more,
it is an overshoot, and it is reported.

Parallel walls get no such forgiveness.  Two walls on one line should
meet at nothing, so any overlap there was a mistake, wherever it sits.

THE HOLE PROBLEM.  A footprint is a rectangle, and a wall is not: cut an
arch out of one and stand another wall in the opening and the two share
a footprint completely while sharing almost no space at all.  Footprints
alone call that swallowed.  So a caller holding real volumes passes them
to verify(), which throws out any claim of Duplicate or Contained the
built volume will not support.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.  Callers turn walls into plain (x, y) tuples in decimal feet and
a thickness, and these functions do the rest.
"""

import math


# ---------------------------------------------------------------------------
# What kind of mistake this is.  The report colours by these.
# ---------------------------------------------------------------------------

DUPLICATE = "Duplicate"     # two walls standing in the same place
CONTAINED = "Contained"     # one wall swallowed by another
COLLINEAR = "Collinear"     # parallel, overlapping along the run or sideways
CROSSING = "Crossing"       # meeting at an angle, one driven into the other

# How much of a wall the shared volume must cover before the wall counts
# as swallowed rather than merely clipped.  Nine tenths leaves room for
# the ends being trimmed by a join without the pair losing its name.
DUP_FRAC = 0.9

# Two walls within this many degrees are treated as parallel.  Drawn
# walls are rarely exact, and a wall two degrees off its neighbour is a
# collinear mistake, not a crossing.
ANG_TOL = 5.0

# Below this, two numbers are the same number.  Guards touching faces
# from reading as a bite of 1e-16 of a foot.
EPS = 1e-9


# ---------------------------------------------------------------------------
# Plain 2-tuple vector arithmetic
# ---------------------------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if n < EPS:
        return None
    return (v[0] / n, v[1] / n)


def _extent(points, axis):
    """How far a set of points reaches along an axis, as (low, high)."""
    vals = [_dot(p, axis) for p in points]
    return min(vals), max(vals)


def _span_overlap(a_lo, a_hi, b_lo, b_hi):
    """How much two ranges share.  Zero or less means they are apart."""
    return min(a_hi, b_hi) - max(a_lo, b_lo)


# ---------------------------------------------------------------------------
# A wall, as the box or boxes it occupies
# ---------------------------------------------------------------------------

class Prism(object):
    """One straight piece of a wall: a rectangle in plan, extruded.

    *p0* and *p1* are the piece's own centre line.  A straight wall is
    one of these; a curved or chained one is several, and only the very
    first and last carry a real END of the wall -- which is what the
    junction rule needs to know, so that a bend inside one wall is not
    mistaken for a place where the wall stopped.
    """

    def __init__(self, p0, p1, thickness, z0, z1,
                 starts_wall=True, ends_wall=True):
        self.p0 = (float(p0[0]), float(p0[1]))
        self.p1 = (float(p1[0]), float(p1[1]))
        self.thickness = float(thickness)
        self.half = self.thickness / 2.0
        self.z0 = float(min(z0, z1))
        self.z1 = float(max(z0, z1))
        self.starts_wall = starts_wall
        self.ends_wall = ends_wall

        d = _sub(self.p1, self.p0)
        self.u = _unit(d) or (1.0, 0.0)          # along the wall
        self.v = (-self.u[1], self.u[0])         # across it
        self.length = math.sqrt(d[0] * d[0] + d[1] * d[1])

    def corners(self):
        """The four plan corners of the piece."""
        hx, hy = self.v[0] * self.half, self.v[1] * self.half
        return [
            (self.p0[0] + hx, self.p0[1] + hy),
            (self.p1[0] + hx, self.p1[1] + hy),
            (self.p1[0] - hx, self.p1[1] - hy),
            (self.p0[0] - hx, self.p0[1] - hy),
        ]

    def plan_area(self):
        return self.length * self.thickness

    def ends(self):
        """The piece's endpoints that are genuinely ends OF THE WALL.

        Yields (endpoint, the other end) so the caller can tell which
        way the wall was travelling when it arrived.
        """
        out = []
        if self.starts_wall:
            out.append((self.p0, self.p1))
        if self.ends_wall:
            out.append((self.p1, self.p0))
        return out


class Wall(object):
    """A wall as the caller knows it, plus the boxes it occupies.

    *key* is whatever the caller wants back in the report -- an element
    id, usually.  Nothing here looks inside it.
    """

    def __init__(self, key, prisms, label=None):
        self.key = key
        self.label = label
        self.prisms = list(prisms)
        self.z0 = min(p.z0 for p in self.prisms)
        self.z1 = max(p.z1 for p in self.prisms)
        self.height = max(self.z1 - self.z0, EPS)
        self.plan_area = sum(p.plan_area() for p in self.prisms) or EPS

    def bounds(self):
        """Plan bounding box (x_lo, y_lo, x_hi, y_hi), for the broad pass."""
        xs, ys = [], []
        for p in self.prisms:
            for c in p.corners():
                xs.append(c[0])
                ys.append(c[1])
        return min(xs), min(ys), max(xs), max(ys)


def straight_wall(key, p0, p1, thickness, z0, z1, label=None):
    """The ordinary case: one line, one thickness, one height."""
    return Wall(key, [Prism(p0, p1, thickness, z0, z1)], label=label)


def polyline_wall(key, points, thickness, z0, z1, label=None):
    """A curved or chained wall, as the run of straight pieces it tessellates to.

    Only the outermost pieces are marked as carrying the wall's ends, so
    that a bend part way along cannot be forgiven as a junction.
    """
    pts = [(float(x), float(y)) for x, y in points]
    prisms = []
    last = len(pts) - 2
    for i in range(len(pts) - 1):
        if _unit(_sub(pts[i + 1], pts[i])) is None:
            continue                              # a repeated point
        prisms.append(Prism(pts[i], pts[i + 1], thickness, z0, z1,
                            starts_wall=(i == 0), ends_wall=(i == last)))
    if not prisms:
        raise ValueError("wall {0} has no length".format(key))
    return Wall(key, prisms, label=label)


# ---------------------------------------------------------------------------
# How far apart they would have to be moved
# ---------------------------------------------------------------------------

def _candidate_axes(a, b):
    """Every direction along which two rectangles could be pulled apart.

    For rectangles this list is complete -- their own two directions
    each -- so the smallest overlap found across it is exactly the
    shortest shove, not an estimate.
    """
    return [a.u, a.v, b.u, b.v]


def separation_depth(a, b):
    """The shortest shove that clears prism *a* of prism *b*, or None.

    None means they are already apart, touching included.
    """
    z = _span_overlap(a.z0, a.z1, b.z0, b.z1)
    if z <= EPS:
        return None

    ca, cb = a.corners(), b.corners()
    best = z
    for axis in _candidate_axes(a, b):
        a_lo, a_hi = _extent(ca, axis)
        b_lo, b_hi = _extent(cb, axis)
        share = _span_overlap(a_lo, a_hi, b_lo, b_hi)
        if share <= EPS:
            return None
        if share < best:
            best = share
    return best


def run_overlap(a, b):
    """How much of *a*'s length is shared with *b*, measured along *a*."""
    a_lo, a_hi = _extent(a.corners(), a.u)
    b_lo, b_hi = _extent(b.corners(), a.u)
    return max(0.0, _span_overlap(a_lo, a_hi, b_lo, b_hi))


def angle_between(a, b):
    """The angle between two pieces in plan, folded into 0-90 degrees.

    Folded because a wall drawn backwards is the same wall.
    """
    c = abs(_dot(a.u, b.u))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


# ---------------------------------------------------------------------------
# The shared footprint, for deciding whether one wall swallowed another
# ---------------------------------------------------------------------------

def _clip(poly, axis, limit, keep_below):
    """Sutherland-Hodgman against one straight edge."""
    if not poly:
        return poly

    def inside(p):
        d = _dot(p, axis)
        return (d <= limit + EPS) if keep_below else (d >= limit - EPS)

    out = []
    for i in range(len(poly)):
        cur, prv = poly[i], poly[i - 1]
        cur_in, prv_in = inside(cur), inside(prv)
        if cur_in != prv_in:
            dc, dp = _dot(cur, axis), _dot(prv, axis)
            denom = dc - dp
            if abs(denom) > EPS:
                t = (limit - dp) / denom
                out.append((prv[0] + (cur[0] - prv[0]) * t,
                            prv[1] + (cur[1] - prv[1]) * t))
        if cur_in:
            out.append(cur)
    return out


def shared_area(a, b):
    """The plan area two prisms have in common."""
    poly = a.corners()
    along = _dot(b.p0, b.u)
    across = _dot(b.p0, b.v)
    for axis, limit, below in (
        (b.u, along + b.length, True),
        (b.u, along, False),
        (b.v, across + b.half, True),
        (b.v, across - b.half, False),
    ):
        poly = _clip(poly, axis, limit, below)
        if not poly:
            return 0.0

    total = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i - 1]
        x1, y1 = poly[i]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


# ---------------------------------------------------------------------------
# Is this a corner, or a mistake?
# ---------------------------------------------------------------------------

def crosses_centre_line(arriving, host, tol):
    """How far *arriving* pushed past *host*'s centre line, in feet.

    Zero when it stopped at or before the line -- which is a junction.
    None when this end never reached the host's body at all, so it has
    nothing to say about the pair.
    """
    worst = None
    for end, other in arriving.ends():
        here = _dot(_sub(end, host.p0), host.v)
        if abs(here) > host.half + tol:
            continue                        # stopped outside, or went clean through
        there = _dot(_sub(other, host.p0), host.v)
        if abs(there) <= EPS:
            continue                        # both ends on the line: no approach to read
        past = abs(here) if (here * there) < 0.0 else 0.0
        if worst is None or past < worst:
            worst = past                    # the kindest reading of the pair
    return worst


def is_junction(a, b, tol):
    """True when this pair is an L or a T rather than an overlap.

    Read from both sides: either wall may be the one that arrived.
    """
    for arriving, host in ((a, b), (b, a)):
        past = crosses_centre_line(arriving, host, tol)
        if past is not None and past <= tol + EPS:
            return True
    return False


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------

class Overlap(object):
    """What two walls are doing to each other, and by how much."""

    def __init__(self, kind, depth, run, shared, a, b, pieces=None):
        self.kind = kind
        self.depth = depth      # the shortest shove, feet
        self.run = run          # shared length along the run, feet
        self.shared = shared    # shared plan area, square feet
        self.a = a
        self.b = b
        # The two straight pieces that overlap most deeply.  A caller
        # holding real solids re-measures the shove in THEIR frame, so
        # it has to be told which pair of frames to use.
        self.pieces = pieces
        # Set when real volumes overruled a claim of Duplicate or
        # Contained, so a report can say the label was second-guessed.
        self.demoted = False

    def __repr__(self):
        return "<Overlap {0} depth={1:.4f}ft run={2:.4f}ft>".format(
            self.kind, self.depth, self.run)


def _kind(a, b, shared, deepest, ang_tol, dup_frac):
    z = max(0.0, _span_overlap(a.z0, a.z1, b.z0, b.z1))
    cover_a = min(shared / a.plan_area, z / a.height)
    cover_b = min(shared / b.plan_area, z / b.height)

    if cover_a >= dup_frac and cover_b >= dup_frac:
        return DUPLICATE
    if max(cover_a, cover_b) >= dup_frac:
        return CONTAINED
    if angle_between(deepest[0], deepest[1]) <= ang_tol:
        return COLLINEAR
    return CROSSING


def check_walls(a, b, tol, ang_tol=ANG_TOL, dup_frac=DUP_FRAC):
    """What, if anything, is wrong between two walls.

    Returns an Overlap, or None when the pair is clean, is an ordinary
    junction, or overlaps by no more than *tol* feet.

    Duplicates and swallowed walls come back whatever the tolerance: two
    walls in one place is not a matter of degree.
    """
    hits = []
    shared = 0.0
    run = 0.0
    depth = 0.0
    deepest = None

    for pa in a.prisms:
        for pb in b.prisms:
            d = separation_depth(pa, pb)
            if d is None:
                continue
            hits.append((pa, pb))
            shared += shared_area(pa, pb)
            run = max(run, run_overlap(pa, pb))
            if d > depth or deepest is None:
                depth, deepest = d, (pa, pb)

    if not hits:
        return None

    kind = _kind(a, b, shared, deepest, ang_tol, dup_frac)

    if kind in (DUPLICATE, CONTAINED):
        return Overlap(kind, depth, run, shared, a, b, deepest)

    # Corners are forgiven, but only where the walls meet at an angle,
    # and only when every piece that touches is behaving like a corner.
    if kind == CROSSING:
        if all(is_junction(pa, pb, tol) for pa, pb in hits):
            return None

    if depth <= tol + EPS:
        return None
    return Overlap(kind, depth, run, shared, a, b, deepest)


def _swallowed_by_volume(hit, shared, vol_a, vol_b, dup_frac):
    """Do the volumes actually built agree that one wall ate the other?

    Answered three ways, in falling order of confidence:

      the shared volume is known -- then it must cover the smaller wall;
      only the walls' own volumes are known -- then neither wall may be
        much emptier than the box its footprint claims, because a wall
        with a hole in it is exactly the one whose footprint lies;
      nothing is known -- the footprint keeps its word.
    """
    if vol_a is None or vol_b is None:
        return True

    if shared is not None:
        return shared >= dup_frac * min(vol_a, vol_b)

    box_a = hit.a.plan_area * hit.a.height
    box_b = hit.b.plan_area * hit.b.height
    return (vol_a >= dup_frac * box_a) and (vol_b >= dup_frac * box_b)


def verify(hit, tol, shared=None, vol_a=None, vol_b=None,
           dup_frac=DUP_FRAC, ang_tol=ANG_TOL):
    """Re-judge a footprint verdict against the volumes actually built.

    Volumes in cubic feet, or None where the caller could not read them.
    Returns the Overlap -- its kind possibly knocked down to what the
    volumes do support -- or None when it no longer counts at all.

    A demoted pair stops being exempt from the tolerance, and if it has
    become a crossing it faces the junction rule again, because a pair
    that was never swallowed was never asked either of those questions.
    """
    if hit.kind in (DUPLICATE, CONTAINED):
        if not _swallowed_by_volume(hit, shared, vol_a, vol_b, dup_frac):
            pa, pb = hit.pieces
            hit.kind = (COLLINEAR if angle_between(pa, pb) <= ang_tol
                        else CROSSING)
            hit.demoted = True

    if hit.kind in (DUPLICATE, CONTAINED):
        return hit
    if hit.kind == CROSSING and is_junction(hit.pieces[0], hit.pieces[1], tol):
        return None
    if hit.depth <= tol + EPS:
        return None
    return hit


# ---------------------------------------------------------------------------
# Finding the pairs worth asking about
# ---------------------------------------------------------------------------

def candidate_pairs(walls, margin=0.0):
    """Index (i, j) for every pair whose plan bounding boxes touch.

    A grid rather than every wall against every other, because a view
    holding a few thousand walls would otherwise be millions of tests
    for a handful of answers.  The cell is sized to the walls actually
    present, so a model of short partitions does not pay for a grid
    built around one long facade.
    """
    if len(walls) < 2:
        return []

    boxes = [w.bounds() for w in walls]
    spans = sorted(max(x1 - x0, y1 - y0) for x0, y0, x1, y1 in boxes)
    cell = max(spans[len(spans) // 2], 1.0)

    grid = {}
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        for cx in range(int(math.floor((x0 - margin) / cell)),
                        int(math.floor((x1 + margin) / cell)) + 1):
            for cy in range(int(math.floor((y0 - margin) / cell)),
                            int(math.floor((y1 + margin) / cell)) + 1):
                grid.setdefault((cx, cy), []).append(i)

    pairs = set()
    for bucket in grid.values():
        for m in range(len(bucket)):
            for n in range(m + 1, len(bucket)):
                i, j = bucket[m], bucket[n]
                if j < i:
                    i, j = j, i
                if (i, j) in pairs:
                    continue
                ax0, ay0, ax1, ay1 = boxes[i]
                bx0, by0, bx1, by1 = boxes[j]
                if (_span_overlap(ax0, ax1, bx0, bx1) < -margin
                        or _span_overlap(ay0, ay1, by0, by1) < -margin):
                    continue
                if _span_overlap(walls[i].z0, walls[i].z1,
                                 walls[j].z0, walls[j].z1) <= EPS:
                    continue
                pairs.add((i, j))
    return sorted(pairs)
