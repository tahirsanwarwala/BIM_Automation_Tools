# -*- coding: utf-8 -*-
"""Plan geometry and reading order for Bulk Rooms.

Points are plain tuples and a box is ((minx, miny), (maxx, maxy)), all in
view coordinates (feet): to_view_xy turns a model point into the plan
view's own x (right) and y (up), so a rectangle the user drags in the
view can be compared with room boundary loops directly.  reading_order
numbers areas top-left to bottom-right, and filter_labels narrows the
room-name pick list as the user types.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.
"""

from __future__ import division

MIN_AREA_SQFT = 1.0
ROW_BAND_FT = 1.0
TOL = 1e-6


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


def filter_labels(labels, text):
    """Labels containing text.strip(), case-insensitive, in original order."""
    want = text.strip().lower()
    if not want:
        return list(labels)
    return [lab for lab in labels if want in lab.lower()]
