# -*- coding: utf-8 -*-
"""Plan geometry and reading order for Bulk Rooms.

Points are plain tuples and a box is ((minx, miny), (maxx, maxy)), all in
view coordinates (feet): to_view_xy turns a model point into the plan
view's own x (right) and y (up), so a rectangle the user drags in the
view can be compared with room boundary loops directly.  walk_order
sets the order areas are visited in: from the top-left one, each next
area shares a wall with the one before it wherever it can (reading_order
numbers them top-left to bottom-right, for the start and for ties).
filter_labels narrows the
room-name pick list as the user types; search_rows adds the matches
from the other sheets below it.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.
"""

from __future__ import division

# Kinds of row in the name list (search_rows).
ENTRY, HEADING, SEPARATOR, SHEET = 0, 1, 2, 3
SEPARATOR_TEXT = u"-" * 40

MIN_AREA_SQFT = 1.0
ROW_BAND_FT = 1.0
TOL = 1e-6

# Two areas share a wall when, for at least MIN_SHARED_FT, their
# boundaries run side by side no more than WALL_GAP_FT apart: room
# boundaries stop at wall faces, so neighbours never touch -- the wall's
# thickness lies between them.  A corridor is wider than the gap, so
# rooms across one are not neighbours.
WALL_GAP_FT = 2.0
MIN_SHARED_FT = 1.0
_PARALLEL_SIN = 0.26     # sides within ~15 degrees count as side by side


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def to_view_xy(pt, origin, right, up):
    """(x, y) of a model point in the view: pt - origin dotted with right, up."""
    d = (pt[0] - origin[0], pt[1] - origin[1], pt[2] - origin[2])
    return (_dot(d, right), _dot(d, up))


def box_from_corners(a, b):
    """Box from two (x, y) corners given in any order."""
    return ((min(a[0], b[0]), min(a[1], b[1])),
            (max(a[0], b[0]), max(a[1], b[1])))


def loop_bounds(loop):
    """Box around a loop of (x, y) points."""
    xs = [p[0] for p in loop]
    ys = [p[1] for p in loop]
    return ((min(xs), min(ys)), (max(xs), max(ys)))


def loop_inside_box(loop, box):
    """True when every point lies within the box, widened by TOL."""
    (minx, miny), (maxx, maxy) = box
    for x, y in loop:
        if (x < minx - TOL or x > maxx + TOL or
                y < miny - TOL or y > maxy + TOL):
            return False
    return True


def point_in_loop(pt, loop):
    """Even-odd ray cast.  The loop is open: its first point is not repeated."""
    x, y = pt
    inside = False
    n = len(loop)
    j = n - 1
    for i in range(n):
        xi, yi = loop[i]
        xj, yj = loop[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def reading_order(bounds):
    """Indices into bounds (boxes), ordered top-left to bottom-right.

    Items are sorted by top (max y) descending; a new row opens when an
    item's top is more than ROW_BAND_FT below the first item of the
    current row.  Each row is sorted by left (min x).
    """
    idx = sorted(range(len(bounds)), key=lambda i: -bounds[i][1][1])
    rows = []
    row_top = None
    for i in idx:
        top = bounds[i][1][1]
        if row_top is None or row_top - top > ROW_BAND_FT:
            rows.append([])
            row_top = top
        rows[-1].append(i)
    out = []
    for row in rows:
        row.sort(key=lambda i: bounds[i][0][0])
        out.extend(row)
    return out


def _sides(loop):
    n = len(loop)
    return [(loop[i], loop[(i + 1) % n]) for i in range(n)]


def _side_contact(a0, a1, b0, b1, gap):
    """Length of side a lying alongside side b within gap of it."""
    ux, uy = a1[0] - a0[0], a1[1] - a0[1]
    length = (ux * ux + uy * uy) ** 0.5
    vx, vy = b1[0] - b0[0], b1[1] - b0[1]
    blen = (vx * vx + vy * vy) ** 0.5
    if length < TOL or blen < TOL:
        return 0.0
    ux, uy = ux / length, uy / length
    if abs(ux * vy - uy * vx) / blen > _PARALLEL_SIN:
        return 0.0
    d0 = ux * (b0[1] - a0[1]) - uy * (b0[0] - a0[0])
    d1 = ux * (b1[1] - a0[1]) - uy * (b1[0] - a0[0])
    if max(abs(d0), abs(d1)) > gap:
        return 0.0
    t0 = ux * (b0[0] - a0[0]) + uy * (b0[1] - a0[1])
    t1 = ux * (b1[0] - a0[0]) + uy * (b1[1] - a0[1])
    lo = max(0.0, min(t0, t1))
    hi = min(length, max(t0, t1))
    return max(0.0, hi - lo)


def shared_wall(loop_a, loop_b, gap=WALL_GAP_FT):
    """How long (feet) loop_a's boundary runs alongside loop_b's."""
    total = 0.0
    sides_b = [(b0, b1, min(b0[0], b1[0]) - gap, max(b0[0], b1[0]) + gap,
                min(b0[1], b1[1]) - gap, max(b0[1], b1[1]) + gap)
               for b0, b1 in _sides(loop_b)]
    for a0, a1 in _sides(loop_a):
        ax0, ax1 = min(a0[0], a1[0]), max(a0[0], a1[0])
        ay0, ay1 = min(a0[1], a1[1]), max(a0[1], a1[1])
        for b0, b1, bx0, bx1, by0, by1 in sides_b:
            # Sides whose boxes are more than gap apart cannot touch.
            if ax1 < bx0 or ax0 > bx1 or ay1 < by0 or ay0 > by1:
                continue
            total += _side_contact(a0, a1, b0, b1, gap)
    return total


def _near(box_a, box_b, gap):
    (ax0, ay0), (ax1, ay1) = box_a
    (bx0, by0), (bx1, by1) = box_b
    return not (ax1 + gap < bx0 or bx1 + gap < ax0 or
                ay1 + gap < by0 or by1 + gap < ay0)


def walk_order(loops):
    """Indices into loops (outer loops in view (x, y)), in visiting order.

    The walk starts at the first area in reading order.  Next comes the
    unvisited area sharing the longest wall with the current one.  At a
    dead end it moves to the unvisited area nearest the current one
    (box centres) among those sharing a wall with any area already
    visited, or, with none of those left, among all unvisited areas.
    Ties go to reading order.
    """
    n = len(loops)
    if n == 0:
        return []
    bounds = [loop_bounds(lp) for lp in loops]
    rank = [0] * n
    for pos, i in enumerate(reading_order(bounds)):
        rank[i] = pos
    neighbours = [dict() for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if not _near(bounds[i], bounds[j], WALL_GAP_FT):
                continue
            length = max(shared_wall(loops[i], loops[j]),
                         shared_wall(loops[j], loops[i]))
            if length >= MIN_SHARED_FT:
                neighbours[i][j] = length
                neighbours[j][i] = length
    centre = [((b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2)
              for b in bounds]

    def dist2(i, j):
        dx = centre[i][0] - centre[j][0]
        dy = centre[i][1] - centre[j][1]
        return dx * dx + dy * dy

    current = min(range(n), key=lambda i: rank[i])
    order = [current]
    seen = set(order)
    while len(order) < n:
        nxt = [j for j in neighbours[current] if j not in seen]
        if nxt:
            current = min(nxt, key=lambda j: (-neighbours[current][j], rank[j]))
        else:
            pool = [j for j in range(n) if j not in seen
                    and any(k in seen for k in neighbours[j])]
            if not pool:
                pool = [j for j in range(n) if j not in seen]
            here = current
            current = min(pool, key=lambda j: (dist2(here, j), rank[j]))
        order.append(current)
        seen.add(current)
    return order


def filter_labels(labels, text):
    """Labels containing text.strip(), case-insensitive, in original order."""
    want = text.strip().lower()
    if not want:
        return list(labels)
    return [lab for lab in labels if want in lab.lower()]


def search_rows(sheets, current, text):
    """[(text, kind)] rows of the name list.

    sheets is [(sheet name, [(label, is heading)])] and current the
    index of the chosen sheet.  Its matching labels come first, as
    ENTRY or HEADING rows.  While text is not blank, every other sheet
    with a match follows in workbook order, as a SEPARATOR row, a SHEET
    row holding the sheet's name, then its matching labels.
    """
    def matches(items):
        heads = set(lab for lab, is_heading in items if is_heading)
        return [(lab, HEADING if lab in heads else ENTRY)
                for lab in filter_labels([lab for lab, _h in items], text)]

    rows = []
    if 0 <= current < len(sheets):
        rows.extend(matches(sheets[current][1]))
    if not text.strip():
        return rows
    for i, (name, items) in enumerate(sheets):
        if i == current:
            continue
        found = matches(items)
        if found:
            rows.append((SEPARATOR_TEXT, SEPARATOR))
            rows.append((name, SHEET))
            rows.extend(found)
    return rows
