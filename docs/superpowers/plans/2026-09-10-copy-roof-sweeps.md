# Copy Roof Sweeps From Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pushbutton that rebuilds fascias and gutters picked in a linked model onto the host model's already-copied roofs, because Revit cannot copy them ("Can't copy part of element").

**Architecture:** A `Fascia`/`Gutter` is stored as REFERENCES to edges of its host roof, so it cannot cross documents. The tool reads each linked sweep's segment references, resolves them to edge curves, pushes those into host coordinates through the link transform, finds the corresponding host roof and then the corresponding edges of it, and calls `NewFascia`/`NewGutter` with fresh host references. Geometry that can be expressed as plain floats lives in a Revit-free module so it is unit-tested in CPython; everything that touches the API lives beside it and is verified by compiling, by an undefined-name pass, and by a manual checklist in Revit.

**Tech Stack:** IronPython 3 / pyRevit for Revit 2025, Revit API (`Autodesk.Revit.DB`, `Autodesk.Revit.DB.Architecture`), CPython `unittest` for the pure module.

**Spec:** `docs/superpowers/specs/2026-09-10-copy-roof-sweeps-design.md`

## Global Constraints

- Target Revit 2025 via pyRevit. Scripts run under IronPython 3 — **no f-strings**; use `.format()`, matching every existing script.
- Every file starts with `# -*- coding: utf-8 -*-`.
- `lib/BG/sweep_geom.py` MUST NOT import anything from `Autodesk.Revit`, and MUST NOT `import clr`. It is imported by `tests/` in ordinary CPython, where those imports do not exist. `lib/BG/roof_sweep.py` IS Revit-facing and may.
- Units are decimal feet. Two tolerances, and only two: `sweep_geom.EDGE_TOL` = 1/32 inch for edge endpoints, `sweep_geom.ROOF_TOL` = 1/12 foot (1 inch) for roof identity. Do not introduce a third.
- The linked model is NEVER modified.
- Reporting follows `CopyFromLink`: silent on a clean run beyond a one-line summary; anything worth saying goes in one table with columns `["Element", "Note"]`.
- All Revit dialogs — including the pick-a-roof fallback — are raised BEFORE the transaction opens.
- One `Transaction` for the whole run, rolled back on an unhandled exception.
- Reuse `BG.link_copy.type_key(elem)` for the (family name, type name) of an INSTANCE. Do not write a second one. Handed a TYPE element it answers `("", "")` — for those use `roof_sweep.type_names(elem_type)`, added in Task 4, which reads the names off the type itself. The two agree for the same type, which is what lets an existing type be compared with one keyed from an instance.
- The runner is `python -m unittest discover -s tests` from the repo root (pytest is NOT installed). The suite stands at **289 tests, all passing**, before this plan starts.
- Beyond `py_compile`, every task that writes Revit-facing code runs the undefined-name AST pass described in Task 2 Step 1. IronPython gives no other way to catch a NameError before the user does.
- **Do not open, drive, or probe a running Revit session.** The manual checklist in Task 6 is for the user to run.

Repo root is `C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools`. `EXT` below means `Revit API/pyRevit-Tools.extension`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `EXT/lib/BG/sweep_geom.py` | **Create.** Pure geometry: edge keys, point/box matching, the re-run rule. No Revit. |
| `EXT/lib/BG/roof_sweep.py` | **Create.** Revit-facing: read linked sweeps, match roofs and edges, ensure types, create sweeps. |
| `EXT/lib/BG/__init__.py` | **Modify.** Its docstring names which modules are Revit-free; add the two new ones. |
| `EXT/BG_Tools.tab/SKIN_Tools.panel/CopyRoofSweeps.pushbutton/script.py` | **Create.** Selection, prompt, transaction, report. |
| `EXT/BG_Tools.tab/SKIN_Tools.panel/bundle.yaml` | **Modify.** Add `CopyRoofSweeps` to the layout. |
| `tests/test_sweep_geom.py` | **Create.** Unit tests for `sweep_geom`. |

---

### Task 1: `BG.sweep_geom` — the geometry, with tests

The whole of the arithmetic, and the only task with real automated tests. Everything here is plain Python over tuples of three floats.

**Files:**
- Create: `EXT/lib/BG/sweep_geom.py`
- Create: `tests/test_sweep_geom.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `EDGE_TOL = 1.0 / 32.0 / 12.0` (feet), `ROOF_TOL = 1.0 / 12.0` (feet)
  - `round_point(p, tol)` → `(int, int, int)` grid cell
  - `edge_key(p, q, tol)` → `((int,int,int), (int,int,int))`, endpoints sorted
  - `edge_key_candidates(p, q, tol)` → `list` of such keys
  - `points_match(p, q, tol)` → `bool`
  - `box_of(points)` → `((minx,miny,minz), (maxx,maxy,maxz))`
  - `boxes_match(a, b, tol)` → `bool`
  - `centroid(points)` → `(x, y, z)`
  - `already_there(index, type_key, edge_keys)` → `bool`, where `index` is `{(family, type): set of edge_key}`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sweep_geom.py`:

```python
# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import sweep_geom as sg


class TestEdgeKey(unittest.TestCase):

    def test_same_edge_either_way_round(self):
        a = sg.edge_key((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), sg.EDGE_TOL)
        b = sg.edge_key((10.0, 0.0, 0.0), (0.0, 0.0, 0.0), sg.EDGE_TOL)
        self.assertEqual(a, b)

    def test_edges_a_foot_apart_differ(self):
        a = sg.edge_key((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), sg.EDGE_TOL)
        b = sg.edge_key((0.0, 1.0, 0.0), (10.0, 1.0, 0.0), sg.EDGE_TOL)
        self.assertNotEqual(a, b)


class TestEdgeKeyCandidates(unittest.TestCase):
    """A lookup must find an edge that is there, grid cell or no.

    Rounding to a grid puts two points a hair apart in DIFFERENT cells
    when they happen to straddle a cell boundary.  The index is built
    with one key; the lookup tries every key the edge could have been
    filed under, which is what makes the straddle harmless.
    """

    def test_finds_edge_within_tolerance(self):
        index = {sg.edge_key((0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                             sg.EDGE_TOL): "ref"}
        drift = sg.EDGE_TOL / 4.0
        hits = [index[k] for k
                in sg.edge_key_candidates((drift, 0.0, 0.0),
                                          (10.0 + drift, 0.0, 0.0),
                                          sg.EDGE_TOL)
                if k in index]
        self.assertEqual(hits[:1], ["ref"])

    def test_finds_edge_across_a_grid_boundary(self):
        # 1.5 cells rounds to 2, a hair under it rounds to 1, so these
        # two points really do land in different cells.  This is the
        # case edge_key_candidates exists for; without it the lookup
        # below finds nothing.
        on_boundary = sg.EDGE_TOL * 1.5
        index = {sg.edge_key((on_boundary, 0.0, 0.0), (10.0, 0.0, 0.0),
                             sg.EDGE_TOL): "ref"}
        nudged = on_boundary - sg.EDGE_TOL / 1000.0
        hits = [index[k] for k
                in sg.edge_key_candidates((nudged, 0.0, 0.0),
                                          (10.0, 0.0, 0.0), sg.EDGE_TOL)
                if k in index]
        self.assertEqual(hits[:1], ["ref"])

    def test_does_not_find_an_edge_that_is_not_there(self):
        index = {sg.edge_key((0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                             sg.EDGE_TOL): "ref"}
        hits = [k for k in sg.edge_key_candidates((0.0, 1.0, 0.0),
                                                  (10.0, 1.0, 0.0),
                                                  sg.EDGE_TOL)
                if k in index]
        self.assertEqual(hits, [])


class TestPointsAndBoxes(unittest.TestCase):

    def test_points_match_inside_tolerance(self):
        self.assertTrue(sg.points_match((0.0, 0.0, 0.0),
                                        (0.0, 0.05, 0.0), sg.ROOF_TOL))

    def test_points_do_not_match_outside_tolerance(self):
        self.assertFalse(sg.points_match((0.0, 0.0, 0.0),
                                         (0.0, 1.0, 0.0), sg.ROOF_TOL))

    def test_box_of_encloses_every_point(self):
        low, high = sg.box_of([(1.0, 2.0, 3.0), (-1.0, 5.0, 0.0),
                               (0.0, 0.0, 9.0)])
        self.assertEqual(low, (-1.0, 0.0, 0.0))
        self.assertEqual(high, (1.0, 5.0, 9.0))

    def test_boxes_match_accepts_an_inch_of_drift(self):
        a = ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
        b = ((0.05, 0.0, 0.0), (10.0, 10.05, 10.0))
        self.assertTrue(sg.boxes_match(a, b, sg.ROOF_TOL))

    def test_boxes_do_not_match_a_foot_out(self):
        a = ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
        b = ((0.0, 0.0, 0.0), (11.0, 10.0, 10.0))
        self.assertFalse(sg.boxes_match(a, b, sg.ROOF_TOL))

    def test_centroid_of_a_square(self):
        c = sg.centroid([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0),
                         (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)])
        self.assertAlmostEqual(c[0], 1.0)
        self.assertAlmostEqual(c[1], 1.0)
        self.assertAlmostEqual(c[2], 0.0)

    def test_centroid_of_nothing_is_none(self):
        self.assertIsNone(sg.centroid([]))


class TestAlreadyThere(unittest.TestCase):
    """One shared edge, same type, is proof enough.  See the spec."""

    def setUp(self):
        self.index = {("Fascia", "6 inch"): set(["edgeA", "edgeB"])}

    def test_shared_edge_and_same_type_is_already_there(self):
        self.assertTrue(sg.already_there(
            self.index, ("Fascia", "6 inch"), ["edgeB", "edgeC"]))

    def test_shared_edge_but_other_type_is_not(self):
        self.assertFalse(sg.already_there(
            self.index, ("Fascia", "8 inch"), ["edgeB"]))

    def test_same_type_but_no_shared_edge_is_not(self):
        self.assertFalse(sg.already_there(
            self.index, ("Fascia", "6 inch"), ["edgeC", "edgeD"]))

    def test_no_edges_at_all_is_not(self):
        self.assertFalse(sg.already_there(
            self.index, ("Fascia", "6 inch"), []))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && python -m unittest tests.test_sweep_geom -v
```

Expected: an `ImportError`/`ModuleNotFoundError` — `cannot import name 'sweep_geom' from 'BG'`.

- [ ] **Step 3: Write the implementation**

Create `EXT/lib/BG/sweep_geom.py`:

```python
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
        options = [low, low + 1]
        per_axis.append(sorted(set(options)))

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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && python -m unittest tests.test_sweep_geom -v
```

Expected: PASS, 16 tests.

- [ ] **Step 5: Run the whole suite**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && python -m unittest discover -s tests
```

Expected: `Ran 305 tests`, `OK`. (289 before, 16 added.)

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && git add "Revit API/pyRevit-Tools.extension/lib/BG/sweep_geom.py" tests/test_sweep_geom.py && git commit -m "feat: the arithmetic for matching a linked roof edge to a host one" -- "Revit API/pyRevit-Tools.extension/lib/BG/sweep_geom.py" tests/test_sweep_geom.py
```

Note the trailing `-- <paths>`: this branch carries unrelated uncommitted work, and no task in this plan may sweep it into a commit. Every commit in this plan names its paths explicitly.

---

### Task 2: `BG.roof_sweep` — reading the linked sweeps

The half that talks to the link. Nothing here can be unit-tested; it is verified by compiling and by the undefined-name pass, which is why that pass is set up first.

**Files:**
- Create: `EXT/lib/BG/roof_sweep.py`

**Interfaces:**
- Consumes: `BG.sweep_geom` (Task 1) — `EDGE_TOL`, `edge_key`.
- Produces:
  - `FASCIA = "Fascia"`, `GUTTER = "Gutter"`
  - `sweep_kind(elem)` → `"Fascia"`, `"Gutter"`, or `None`
  - `xyz_tuple(p)` → `(x, y, z)`
  - `Segment` — a plain class with `.roof` (linked roof `Element`), `.p`, `.q` (host-coordinate tuples), `.key` (an `edge_key`)
  - `segment_edges(sweep, transform)` → `(list of Segment, unread_count)`

- [ ] **Step 1: Set up the undefined-name checker**

`py_compile` cannot see a NameError, and none of this can be executed outside Revit. The checker already exists in this repo, written for an earlier plan. Copy it out of that plan into the scratchpad — **not into the repo**:

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && python - <<'PY'
import io, os
plan = "docs/superpowers/plans/2026-09-05-multi-wall-creation-v2.md"
text = io.open(plan, encoding="utf-8").read()
start = text.index('"""Report names a module uses but never defines')
start = text.rindex("```python", 0, start) + len("```python")
end = text.index("```", start)
body = "# -*- coding: utf-8 -*-\n" + text[start:end].strip() + "\n"
out = os.path.join(os.environ.get("TEMP", "."), "undefined_names.py")
io.open(out, "w", encoding="utf-8").write(body)
print(out)
print(body.count("\n"), "lines")
PY
```

Expected: a path is printed and the file is around 95 lines. If the extraction fails, open that plan, find the fenced Python block under **Step 2: Write the undefined-name checker**, and save it by hand. Call it as `python "$TEMP/undefined_names.py" <file>`; it prints `OK - <name>` or one line per undefined name.

- [ ] **Step 2: Write the module**

Create `EXT/lib/BG/roof_sweep.py`:

```python
# -*- coding: utf-8 -*-
"""Rebuilding a linked fascia or gutter on a roof in the host model.

A Fascia or a Gutter cannot be copied out of a link.  Revit says so
plainly -- "Can't copy part of element" -- and it is right to.  The
element is not geometry standing next to a roof; it is a profile swept
along a list of REFERENCES to edges of its host roof, and those
references point into the linked file.  There is nothing in this model
for them to name, so there is nothing to copy.

So it is rebuilt instead.  Read the linked sweep's segment references,
turn each into the endpoints of an edge in host coordinates, find the
host roof that corresponds to the linked one, find the edges of it that
correspond to those endpoints, and create a new sweep on them.

The arithmetic is next door in sweep_geom, which imports no Revit and
is unit-tested.  This module is the Revit half and is verified by
running the tool.

The linked model is never modified.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    CopyPasteOptions,
    ElementId,
    ElementTransformUtils,
    Edge,
    FilteredElementCollector,
    GeometryInstance,
    Options,
    Reference,
    ReferenceArray,
    Solid,
    Transform,
    ViewDetailLevel,
    XYZ,
)

# Fascia, Gutter and their types live in the Architecture namespace, and
# have since long before 2025 -- but the import is guarded because being
# wrong about it would break the module at load, taking the button with
# it, for a name that costs nothing to look for in both places.
try:
    from Autodesk.Revit.DB.Architecture import (
        Fascia, FasciaType, Gutter, GutterType)
except ImportError:                                   # pragma: no cover
    from Autodesk.Revit.DB import (
        Fascia, FasciaType, Gutter, GutterType)

from System.Collections.Generic import List
from pyrevit import script

from BG import link_copy, sweep_geom

logger = script.get_logger()

FASCIA = "Fascia"
GUTTER = "Gutter"


# ===========================================================================
# READING THE LINK
# ===========================================================================

def sweep_kind(elem):
    """"Fascia", "Gutter", or None for anything else."""
    if isinstance(elem, Fascia):
        return FASCIA
    if isinstance(elem, Gutter):
        return GUTTER
    return None


def xyz_tuple(p):
    """An XYZ as a plain tuple, which is all sweep_geom wants."""
    return (p.X, p.Y, p.Z)


class Segment(object):
    """One run of a sweep: the roof it stands on, and the edge it follows.

    The endpoints are already in HOST coordinates -- the link transform
    was applied when this was read -- so nothing downstream has to
    remember whether it is holding link or host numbers.
    """

    def __init__(self, roof, p, q):
        self.roof = roof
        self.p = p
        self.q = q
        self.key = sweep_geom.edge_key(p, q, sweep_geom.EDGE_TOL)


def _roof_of(reference, link_doc):
    """The linked element a segment reference is hosted on, or None."""
    try:
        return link_doc.GetElement(reference.ElementId)
    except Exception:
        return None


def _is_roof(elem):
    try:
        cat = elem.Category
    except Exception:
        return False
    if cat is None:
        return False
    return link_copy.eid_value(cat.Id) == int(BuiltInCategory.OST_Roofs)


def segment_edges(sweep, transform):
    """Every segment of *sweep*, as host-coordinate edges.

    Returns (segments, unread).  *unread* counts the segments that could
    not be turned into a roof edge -- hosted on a soffit or a model line
    rather than a roof, or geometry Revit would not resolve.  They are
    counted rather than raised, because one odd segment must not cost
    the user the other six.
    """
    link_doc = sweep.Document
    segments = []
    unread = 0

    try:
        segment_ids = list(sweep.GetSegmentIds())
    except Exception as ex:
        logger.debug("no segments on {}: {}".format(sweep.Id, ex))
        return [], 0

    for segment_id in segment_ids:
        try:
            reference = sweep.GetSegmentReference(segment_id)
        except Exception:
            unread += 1
            continue

        roof = _roof_of(reference, link_doc)
        if roof is None or not _is_roof(roof):
            unread += 1
            continue

        try:
            geometry = roof.GetGeometryObjectFromReference(reference)
        except Exception:
            geometry = None

        if not isinstance(geometry, Edge):
            unread += 1
            continue

        try:
            curve = geometry.AsCurve()
            p = transform.OfPoint(curve.GetEndPoint(0))
            q = transform.OfPoint(curve.GetEndPoint(1))
        except Exception:
            unread += 1
            continue

        segments.append(Segment(roof, xyz_tuple(p), xyz_tuple(q)))

    return segments, unread
```

Note `link_copy.eid_value` is used above. `lib/BG/link_copy.py` does NOT currently define it — the function of that name lives in `CopyFromLink.pushbutton/script.py`. Add it to `link_copy.py` in this task, and leave the script's own copy alone (the script is in daily use and this plan does not touch it):

```python
def eid_value(element_id):
    """An ElementId as a plain number, whichever Revit version this is.

    2024 and later expose Value; earlier ones only IntegerValue.
    """
    for attr in ("Value", "IntegerValue"):
        try:
            return getattr(element_id, attr)
        except Exception:
            continue
    return element_id
```

Put it in `link_copy.py` immediately after the `TOL` constant, before `link_instances`.

- [ ] **Step 3: Compile and check for undefined names**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit API/pyRevit-Tools.extension/lib/BG" && python -m py_compile roof_sweep.py link_copy.py && python "$TEMP/undefined_names.py" roof_sweep.py && python "$TEMP/undefined_names.py" link_copy.py
```

Expected: no compile output, then `OK - roof_sweep.py` and `OK - link_copy.py`.

- [ ] **Step 4: Confirm the pure module is still importable in CPython**

The one way this task can break Task 1: putting a Revit import somewhere `tests/` reaches.

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && python -m unittest discover -s tests
```

Expected: `Ran 305 tests`, `OK`.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && git add "Revit API/pyRevit-Tools.extension/lib/BG/roof_sweep.py" "Revit API/pyRevit-Tools.extension/lib/BG/link_copy.py" && git commit -m "feat: read a linked fascia or gutter as host-coordinate roof edges" -- "Revit API/pyRevit-Tools.extension/lib/BG/roof_sweep.py" "Revit API/pyRevit-Tools.extension/lib/BG/link_copy.py"
```

---

### Task 3: Matching the host roof and its edges

**Files:**
- Modify: `EXT/lib/BG/roof_sweep.py` (append; do not disturb Task 2's code)

**Interfaces:**
- Consumes: Task 2's `xyz_tuple`, `Segment`; `sweep_geom.box_of`, `boxes_match`, `centroid`, `edge_key`, `edge_key_candidates`, `EDGE_TOL`, `ROOF_TOL`.
- Produces:
  - `HostRoof` — plain class with `.element`, `.type_name`, `.box`, `.centre`
  - `host_roofs(doc)` → `list of HostRoof`
  - `box_corners(bbox, transform)` → `list` of 8 host-coordinate tuples
  - `linked_roof_box(roof, transform)` → box, or `None`
  - `match_roof(linked_roof, transform, roofs)` → `HostRoof` or `None`
  - `edge_index(roof)` → `{edge_key: Reference}`
  - `lookup_edge(index, segment)` → `Reference` or `None`
  - `roof_label(elem, box)` → a string naming a roof for a report row

- [ ] **Step 1: Append the roof-matching code**

Add to `EXT/lib/BG/roof_sweep.py`:

```python
# ===========================================================================
# MATCHING THE HOST ROOF
# ===========================================================================

class HostRoof(object):
    """A roof in this model, with what is needed to recognise it."""

    def __init__(self, element, type_name, box):
        self.element = element
        self.type_name = type_name
        self.box = box
        self.centre = sweep_geom.centroid(list(box)) if box else None


def _type_name(elem):
    """The name of an element's type, or ""."""
    return link_copy.type_key(elem)[1]


def box_corners(bbox, transform=None):
    """The eight corners of a bounding box, in host coordinates.

    All eight, not just Min and Max: a link may be ROTATED, and a
    rotated box's Min and Max do not transform into the new box's Min
    and Max.  Taking every corner across and re-enclosing them does.
    """
    if bbox is None:
        return []

    lo, hi = bbox.Min, bbox.Max
    corners = []
    for x in (lo.X, hi.X):
        for y in (lo.Y, hi.Y):
            for z in (lo.Z, hi.Z):
                p = XYZ(x, y, z)
                if bbox.Transform is not None:
                    p = bbox.Transform.OfPoint(p)
                if transform is not None:
                    p = transform.OfPoint(p)
                corners.append(xyz_tuple(p))
    return corners


def linked_roof_box(roof, transform):
    """The host-coordinate box around a linked roof, or None."""
    try:
        bbox = roof.get_BoundingBox(None)
    except Exception:
        return None
    return sweep_geom.box_of(box_corners(bbox, transform))


def host_roofs(doc):
    """Every roof in the host model, ready to be matched against."""
    found = []
    for elem in (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Roofs)
                 .WhereElementIsNotElementType()):
        try:
            bbox = elem.get_BoundingBox(None)
        except Exception:
            continue
        box = sweep_geom.box_of(box_corners(bbox))
        if box is None:
            continue
        found.append(HostRoof(elem, _type_name(elem), box))
    return found


def match_roof(linked_roof, transform, roofs):
    """The host roof that IS the linked one, or None.

    Same type name, and a bounding box agreeing corner for corner to an
    inch.  A plain scan rather than an index: a model holds tens of
    roofs, and a scan cannot suffer the grid-boundary problem a rounded
    key would.
    """
    box = linked_roof_box(linked_roof, transform)
    if box is None:
        return None

    wanted = _type_name(linked_roof)
    for roof in roofs:
        if roof.type_name != wanted:
            continue
        if sweep_geom.boxes_match(roof.box, box, sweep_geom.ROOF_TOL):
            return roof
    return None


def roof_label(elem, box=None):
    """A roof named for a report row: its id, and where it stands."""
    name = "roof {}".format(link_copy.eid_value(elem.Id))
    centre = sweep_geom.centroid(list(box)) if box else None
    if centre is None:
        return name
    return "{} at ({:.1f}, {:.1f}, {:.1f})".format(
        name, centre[0], centre[1], centre[2])


# ===========================================================================
# MATCHING THE HOST ROOF'S EDGES
# ===========================================================================

def _solids(geometry):
    """Every solid in a GeometryElement, instances walked into."""
    for obj in geometry:
        if isinstance(obj, Solid):
            if obj.Edges.Size > 0:
                yield obj
        elif isinstance(obj, GeometryInstance):
            for inner in _solids(obj.GetInstanceGeometry()):
                yield inner


def edge_index(roof):
    """{edge_key: Reference} for every edge of a host roof.

    ComputeReferences is the whole point of the options: without it
    Edge.Reference is null and there is nothing to host a sweep on.

    Built once per roof per run.  The alternative is regenerating a
    roof's geometry for every sweep standing on it.
    """
    options = Options()
    options.ComputeReferences = True
    options.IncludeNonVisibleObjects = False
    options.DetailLevel = ViewDetailLevel.Fine

    index = {}
    try:
        geometry = roof.get_Geometry(options)
    except Exception as ex:
        logger.debug("no geometry for {}: {}".format(roof.Id, ex))
        return index

    if geometry is None:
        return index

    for solid in _solids(geometry):
        for edge in solid.Edges:
            reference = edge.Reference
            if reference is None:
                # Revit does not produce a reference for every edge even
                # with ComputeReferences on.  Nothing can be hosted on
                # one that has none, so it simply is not in the index.
                continue
            try:
                curve = edge.AsCurve()
                p = xyz_tuple(curve.GetEndPoint(0))
                q = xyz_tuple(curve.GetEndPoint(1))
            except Exception:
                continue
            index.setdefault(
                sweep_geom.edge_key(p, q, sweep_geom.EDGE_TOL), reference)

    return index


def lookup_edge(index, segment):
    """The host Reference for a segment's edge, or None.

    Every cell the edge could have been filed under is tried, so a pair
    of points straddling a grid boundary still finds its edge.
    """
    for key in sweep_geom.edge_key_candidates(
            segment.p, segment.q, sweep_geom.EDGE_TOL):
        reference = index.get(key)
        if reference is not None:
            return reference
    return None
```

- [ ] **Step 2: Compile and check for undefined names**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit API/pyRevit-Tools.extension/lib/BG" && python -m py_compile roof_sweep.py && python "$TEMP/undefined_names.py" roof_sweep.py
```

Expected: `OK - roof_sweep.py`.

- [ ] **Step 3: Confirm the suite still runs**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && python -m unittest discover -s tests
```

Expected: `Ran 305 tests`, `OK`.

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && git add "Revit API/pyRevit-Tools.extension/lib/BG/roof_sweep.py" && git commit -m "feat: find the host roof and the host edges a linked sweep wants" -- "Revit API/pyRevit-Tools.extension/lib/BG/roof_sweep.py"
```

---

### Task 4: Types, the re-run index, and creation

**Files:**
- Modify: `EXT/lib/BG/roof_sweep.py` (append)

**Interfaces:**
- Consumes: Task 2's `FASCIA`, `GUTTER`, `sweep_kind`, `xyz_tuple`; Task 3's `edge_index`; `sweep_geom.already_there`, `edge_key`, `EDGE_TOL`; `link_copy.type_key`.
- Produces:
  - `type_names(elem_type)` → `(family, type name)` read off a TYPE element
  - `ensure_type(link_doc, doc, linked_sweep)` → `(type element, copied_bool, reason_or_None)`
  - `existing_index(doc)` → `{(family, type): set of edge_key}`
  - `create_sweep(doc, kind, sweep_type, references)` → `(new element or None, reason_or_None)`
  - `apply_offsets(new_sweep, linked_sweep)` → `None`

- [ ] **Step 1: Append the code**

Add to `EXT/lib/BG/roof_sweep.py`:

```python
# ===========================================================================
# TYPES
# ===========================================================================

def type_names(elem_type):
    """(family name, type name) read off a TYPE element itself.

    NOT link_copy.type_key: that takes an INSTANCE and looks its type
    up.  Handed a type it asks the type for ITS type, gets nothing, and
    answers ("", "") -- which would make every type match every other.
    The two agree on their answer for the same type, which is what lets
    a type found here be compared with one keyed from an instance.
    """
    family = ""
    name = ""
    for getter in (lambda e: e.FamilyName, lambda e: e.Family.Name):
        try:
            value = getter(elem_type)
        except Exception:
            continue
        if value:
            family = value
            break
    try:
        name = elem_type.Name
    except Exception:
        name = ""
    return family or "", name or ""


def _type_class(kind):
    return FasciaType if kind == FASCIA else GutterType


def _sweep_class(kind):
    return Fascia if kind == FASCIA else Gutter


def ensure_type(link_doc, doc, linked_sweep):
    """The host's copy of a linked sweep's type.  (type, copied, reason).

    Matched on family AND type name together, which is the only thing
    the two documents share -- the ids never match and never will.

    Where the host has no such type, the TYPE ELEMENT ALONE is copied
    out of the link.  That works where copying the instance cannot: a
    type holds a profile and some numbers, not references into the
    link.  It is the instance, and only the instance, that is "part of
    element".

    MUST run inside a transaction on *doc* when a copy may happen.
    """
    kind = sweep_kind(linked_sweep)
    if kind is None:
        return None, False, "not a fascia or a gutter"

    try:
        linked_type = link_doc.GetElement(linked_sweep.GetTypeId())
    except Exception:
        linked_type = None
    if linked_type is None:
        return None, False, "its type could not be read from the link"

    wanted = type_names(linked_type)

    for candidate in (FilteredElementCollector(doc)
                      .OfClass(_type_class(kind))):
        if type_names(candidate) == wanted:
            return candidate, False, None

    ids = List[ElementId]()
    ids.Add(linked_type.Id)
    try:
        copied = ElementTransformUtils.CopyElements(
            link_doc, ids, doc, Transform.Identity, CopyPasteOptions())
    except Exception as ex:
        return None, False, "its type could not be copied over: {}".format(ex)

    for new_id in list(copied or []):
        new_type = doc.GetElement(new_id)
        if new_type is not None:
            return new_type, True, None

    return None, False, "its type could not be copied over"


# ===========================================================================
# WHAT IS ALREADY HERE
# ===========================================================================

def existing_index(doc):
    """{(family, type): set of edge_key} for the sweeps the host holds.

    The edges are read off each existing sweep's OWN segment references,
    which are host references, so no transform is involved -- and they
    key exactly the way a candidate's matched edges will.
    """
    index = {}
    for kind in (FASCIA, GUTTER):
        for sweep in (FilteredElementCollector(doc)
                      .OfClass(_sweep_class(kind))
                      .WhereElementIsNotElementType()):
            try:
                type_key = link_copy.type_key(sweep)
                segment_ids = list(sweep.GetSegmentIds())
            except Exception:
                continue

            keys = index.setdefault(type_key, set())
            for segment_id in segment_ids:
                try:
                    reference = sweep.GetSegmentReference(segment_id)
                    host = doc.GetElement(reference.ElementId)
                    edge = host.GetGeometryObjectFromReference(reference)
                    curve = edge.AsCurve()
                    keys.add(sweep_geom.edge_key(
                        xyz_tuple(curve.GetEndPoint(0)),
                        xyz_tuple(curve.GetEndPoint(1)),
                        sweep_geom.EDGE_TOL))
                except Exception:
                    continue
    return index


# ===========================================================================
# CREATING
# ===========================================================================

def create_sweep(doc, kind, sweep_type, references):
    """Make the sweep on *references*.  Returns (element, reason).

    MUST run inside a transaction on *doc*.
    """
    if not references:
        return None, "no host edge matched any of its segments"

    array = ReferenceArray()
    for reference in references:
        array.Append(reference)

    try:
        if kind == FASCIA:
            return doc.Create.NewFascia(sweep_type, array), None
        return doc.Create.NewGutter(sweep_type, array), None
    except Exception as ex:
        return None, "Revit refused to create it: {}".format(ex)


def apply_offsets(new_sweep, linked_sweep):
    """Carry the whole-element offsets and angle across.

    Per-segment overrides are deliberately not carried -- see the spec.
    Each is set on its own: one that will not take must not cost the
    other two.
    """
    for name in ("HorizontalOffset", "VerticalOffset", "Angle"):
        try:
            setattr(new_sweep, name, getattr(linked_sweep, name))
        except Exception as ex:
            logger.debug("{} not carried: {}".format(name, ex))
```

- [ ] **Step 2: Compile and check for undefined names**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit API/pyRevit-Tools.extension/lib/BG" && python -m py_compile roof_sweep.py && python "$TEMP/undefined_names.py" roof_sweep.py
```

Expected: `OK - roof_sweep.py`.

- [ ] **Step 3: Check that every name the module imports is actually used, and every name it uses is imported**

`Reference` and `Edge` are imported for `isinstance` tests; `Solid`, `GeometryInstance`, `Options`, `ViewDetailLevel`, `XYZ`, `Transform`, `ElementId`, `ReferenceArray`, `CopyPasteOptions`, `ElementTransformUtils`, `FilteredElementCollector`, `BuiltInCategory` are all used. Confirm nothing is dead:

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit API/pyRevit-Tools.extension/lib/BG" && python - <<'PY'
import ast, io
tree = ast.parse(io.open("roof_sweep.py", encoding="utf-8").read())
imported = set()
for node in ast.walk(tree):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for a in node.names:
            imported.add(a.asname or a.name.split(".")[0])
used = set(n.id for n in ast.walk(tree) if isinstance(n, ast.Name))
used |= set(n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute))
unused = sorted(imported - used - {"clr"})
print("unused imports:", unused if unused else "none")
PY
```

Expected: `unused imports: none`. If `Reference` shows as unused, delete it from the import list — it is there for readers, not for the code.

- [ ] **Step 4: Confirm the suite still runs**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && python -m unittest discover -s tests
```

Expected: `Ran 305 tests`, `OK`.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && git add "Revit API/pyRevit-Tools.extension/lib/BG/roof_sweep.py" && git commit -m "feat: bring the sweep type over, and build the sweep on host edges" -- "Revit API/pyRevit-Tools.extension/lib/BG/roof_sweep.py"
```

---

### Task 5: The pushbutton

**Files:**
- Create: `EXT/BG_Tools.tab/SKIN_Tools.panel/CopyRoofSweeps.pushbutton/script.py`
- Modify: `EXT/BG_Tools.tab/SKIN_Tools.panel/bundle.yaml`
- Modify: `EXT/lib/BG/__init__.py`

**Interfaces:**
- Consumes: everything `BG.roof_sweep` produces in Tasks 2–4, and `sweep_geom.already_there`.
- Produces: the tool.

- [ ] **Step 1: Write the script**

Create `EXT/BG_Tools.tab/SKIN_Tools.panel/CopyRoofSweeps.pushbutton/script.py`:

```python
# -*- coding: utf-8 -*-
"""Rebuild fascias and gutters from a linked model onto this model's roofs.

Pick the fascias and gutters you want in a LINKED model -- drag a box or
click, then Finish -- and each one is built again here, standing on the
roof of yours that matches the one it stood on in the link.

They are REBUILT rather than copied because they cannot be copied.
Revit says "Can't copy part of element", and it means it: a fascia is a
profile swept along references to edges of its host roof, and those
references point into the linked file.  Copy has nothing to work with.

THE ROOFS MUST ALREADY BE HERE.  This tool does not bring them over.
Where it cannot find the roof a sweep stood on, it asks you to point at
it, once, and remembers your answer for every other sweep on that roof.

WHERE A ROOF IS NOT QUITE THE ONE IN THE LINK, the sweep is still built
-- from the edges that did match -- and the report says how many
segments it got.  Two edges to add by hand beats starting again, and
this is the failure that actually happens: a roof copied over and then
joined, attached or reshaped is no longer edge-for-edge the original.

WHAT IS ALREADY HERE IS LEFT ALONE.  A sweep of the same family and type
already standing on any one of the edges wanted is taken as this one,
already done, so the tool is safe to run twice.

The linked model is never modified.
"""

__title__  = "Copy Roof\nSweeps"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick fascias and gutters in a LINKED model and click Finish.  Each "
    "one is rebuilt in this model on the matching roof.\n"
    "They cannot be copied -- Revit's \"Can't copy part of element\" -- "
    "so they are recreated on this model's own roof edges.\n"
    "The roofs must already be here; where one cannot be found you are "
    "asked to pick it.  A sweep already standing on the same edges is "
    "left alone.\n"
    "The linked model is left untouched."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import BuiltInCategory, RevitLinkInstance, Transaction
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from BG import link_copy, roof_sweep, sweep_geom

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TOOL_TITLE = "Copy Roof Sweeps"

SWEEP_CATEGORIES = (int(BuiltInCategory.OST_Fascia),
                    int(BuiltInCategory.OST_Gutter))


# ===========================================================================
# HELPERS
# ===========================================================================

def note(notes, label, text):
    """Record one thing worth saying, for the report at the end."""
    notes.append([label, text])


def report(notes):
    """Print the run's notes, or nothing at all when there are none."""
    if not notes:
        return
    output.print_md("### {} - {} note(s)".format(TOOL_TITLE, len(notes)))
    output.print_table([["Element", "Note"]] + notes,
                       columns=["Element", "Note"])


def label_for(elem):
    """A row label naming a sweep and what it is."""
    family, type_name = link_copy.type_key(elem)
    return "{} ({}: {})".format(link_copy.eid_value(elem.Id),
                                family or "?", type_name or "?")


# ===========================================================================
# SELECTION
# ===========================================================================

class LinkedSweepFilter(ISelectionFilter):
    """Allow linked fascias and gutters, and nothing else.

    For linked elements Revit calls AllowElement() on the
    RevitLinkInstance and AllowReference() on each candidate reference
    within it, so the real test has to live in AllowReference.
    """

    def AllowElement(self, elem):
        return isinstance(elem, RevitLinkInstance)

    def AllowReference(self, ref, point):
        try:
            link_inst = doc.GetElement(ref.ElementId)
            if not isinstance(link_inst, RevitLinkInstance):
                return False
            link_doc = link_inst.GetLinkDocument()
            if link_doc is None:
                return False
            elem = link_doc.GetElement(ref.LinkedElementId)
            cat = elem.Category if elem is not None else None
            if cat is None:
                return False
            return link_copy.eid_value(cat.Id) in SWEEP_CATEGORIES
        except Exception:
            return False


def pick_sweeps():
    """Pick linked fascias and gutters, then Finish.

    PickObjects rather than a loop of PickObject: it is what gives the
    selection Revit's own behaviour -- a rubber-band box as well as
    clicks, and a Finish button to run with what is picked.

    Whether a drag catches LINKED elements is Revit's own call: the
    "Select links" toggle at the bottom right must be on, or a box
    ignores link geometry.  Clicking works either way.

    Returns [(RevitLinkInstance, link doc, sweep element)].
    """
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement, LinkedSweepFilter(),
            "Select the fascias and gutters to copy, then click Finish")
    except OperationCanceledException:
        return []
    except Exception as ex:
        logger.debug("Selection ended: {}".format(ex))
        return []

    picked = []
    for ref in refs or []:
        link_inst = doc.GetElement(ref.ElementId)
        link_doc = link_inst.GetLinkDocument()
        if link_doc is None:
            continue
        elem = link_doc.GetElement(ref.LinkedElementId)
        if elem is None or roof_sweep.sweep_kind(elem) is None:
            continue
        picked.append((link_inst, link_doc, elem))
    return picked


def ask_for_roof(linked_roof, box):
    """Ask the user to point at the host roof.  Returns it, or None.

    Raised BEFORE the transaction, like every other dialog in this
    extension.
    """
    forms.alert(
        "No roof in this model matches the linked {}.\n\n"
        "Pick the roof here that it corresponds to, or press Escape to "
        "skip every sweep standing on it.".format(
            roof_sweep.roof_label(linked_roof, box)),
        title=TOOL_TITLE)
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, "Pick the matching roof in THIS model")
    except OperationCanceledException:
        return None
    except Exception:
        return None
    return doc.GetElement(ref.ElementId) if ref is not None else None


# ===========================================================================
# PLANNING -- everything decided before the transaction opens
# ===========================================================================

class Plan(object):
    """One sweep, resolved as far as it can be without writing."""

    def __init__(self, link_doc, sweep, kind, references, keys, total):
        self.link_doc = link_doc
        self.sweep = sweep
        self.kind = kind
        self.references = references
        # The edge keys of the references, kept from when the segments
        # were read.  Recomputing them later would mean resolving every
        # reference's geometry a second time for no new information.
        self.keys = keys
        self.matched = len(references)
        self.total = total


def plan_one(sweep, transform, roofs, chosen, indexes, notes):
    """Work out which host edges a sweep wants.  Returns a Plan or None."""
    segments, unread = roof_sweep.segment_edges(sweep, transform)
    total = len(segments) + unread

    if unread:
        note(notes, label_for(sweep),
             "{} of its {} segments are not hosted on a roof, and were "
             "left out".format(unread, total))

    if not segments:
        note(notes, label_for(sweep),
             "none of its segments are hosted on a roof, so there was "
             "nothing to rebuild")
        return None

    references = []
    keys = []
    for segment in segments:
        roof_id = link_copy.eid_value(segment.roof.Id)

        if roof_id in chosen:
            host_roof = chosen[roof_id]
        else:
            match = roof_sweep.match_roof(segment.roof, transform, roofs)
            host_roof = match.element if match is not None else None
            if host_roof is None:
                host_roof = ask_for_roof(
                    segment.roof,
                    roof_sweep.linked_roof_box(segment.roof, transform))
            # Remembered either way, the refusal included, so a dozen
            # sweeps on one roof cost one prompt rather than a dozen.
            chosen[roof_id] = host_roof

        if host_roof is None:
            continue

        host_id = link_copy.eid_value(host_roof.Id)
        if host_id not in indexes:
            indexes[host_id] = roof_sweep.edge_index(host_roof)

        reference = roof_sweep.lookup_edge(indexes[host_id], segment)
        if reference is not None:
            references.append(reference)
            keys.append(segment.key)

    return Plan(sweep.Document, sweep, roof_sweep.sweep_kind(sweep),
                references, keys, total)


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    picked = pick_sweeps()
    if not picked:
        return          # cancelled, or nothing picked

    notes = []
    roofs = roof_sweep.host_roofs(doc)
    if not roofs:
        note(notes, "-",
             "this model holds no roofs, so there is nothing to build on "
             "- copy the roofs over first")
        report(notes)
        return

    # Both remembered across the whole run: chosen so one unmatched roof
    # costs one prompt, indexes so a roof's geometry is regenerated once
    # however many sweeps stand on it.
    chosen  = {}
    indexes = {}

    plans = []
    for link_inst, _link_doc, sweep in picked:
        transform = link_inst.GetTotalTransform()
        plan = plan_one(sweep, transform, roofs, chosen, indexes, notes)
        if plan is not None:
            plans.append(plan)

    if not plans:
        report(notes)
        return

    index = roof_sweep.existing_index(doc)

    created  = 0
    partial  = 0
    skipped  = 0

    t = Transaction(doc, "Copy roof sweeps from link")
    t.Start()
    try:
        for plan in plans:
            type_key = link_copy.type_key(plan.sweep)

            if sweep_geom.already_there(index, type_key, plan.keys):
                skipped += 1
                continue

            sweep_type, copied, reason = roof_sweep.ensure_type(
                plan.link_doc, doc, plan.sweep)
            if sweep_type is None:
                note(notes, label_for(plan.sweep), reason)
                continue
            if copied:
                note(notes, label_for(plan.sweep),
                     "its type was not in this model and was brought over")

            new_sweep, reason = roof_sweep.create_sweep(
                doc, plan.kind, sweep_type, plan.references)
            if new_sweep is None:
                note(notes, label_for(plan.sweep), reason)
                continue

            roof_sweep.apply_offsets(new_sweep, plan.sweep)
            created += 1

            # Recorded so a second picked sweep on the same edges does
            # not follow this one in.
            index.setdefault(type_key, set()).update(plan.keys)

            if plan.matched < plan.total:
                partial += 1
                note(notes, label_for(plan.sweep),
                     "partial: built on {} of its {} segments - the rest "
                     "have no matching edge on the host roof".format(
                         plan.matched, plan.total))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    summary = "{} rebuilt, {} already here".format(created, skipped)
    if partial:
        summary += ", {} of them only partly".format(partial)

    if not created:
        note(notes, "-", summary)
    else:
        output.print_md("### {} - {}".format(TOOL_TITLE, summary))

    report(notes)


try:
    main()
except Exception:
    forms.alert("Copy Roof Sweeps failed:\n\n{}".format(traceback.format_exc()),
                title=TOOL_TITLE)
```

- [ ] **Step 2: Add the button to the panel layout**

Edit `EXT/BG_Tools.tab/SKIN_Tools.panel/bundle.yaml` so the layout reads:

```yaml
title: "SKIN Tools"
layout:
  - Walls
  - Windows
  - CopyFromLink
  - CopyRoofSweeps
  - SplitWallHorizontal
```

- [ ] **Step 3: Record the Revit-free split in the library docstring**

`EXT/lib/BG/__init__.py` lists which modules import Revit and which do not, and the list is now wrong. Change the second paragraph's two sentences to name the new modules:

```python
Two halves, and the split is deliberate.  wall_bands, wall_constraints,
wall_limits, wall_miter, wall_naming, plan_shapes and sweep_geom import
nothing from Revit at all, so they are unit-tested in ordinary CPython
outside it.  soffit, wall_chain, wall_materials, wall_sketch, wall_skin,
window_cw, link_copy and roof_sweep do talk to the Revit API, and are
verified by running the tools.
```

- [ ] **Step 4: Compile and check for undefined names**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit API/pyRevit-Tools.extension/BG_Tools.tab/SKIN_Tools.panel/CopyRoofSweeps.pushbutton" && python -m py_compile script.py && python "$TEMP/undefined_names.py" script.py
```

Expected: `OK - script.py`. If it reports `sweep_geom` or `roof_sweep` as undefined inside a function, the import line at the top was mistyped.

- [ ] **Step 5: Check the YAML parses and names a real folder**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit API/pyRevit-Tools.extension/BG_Tools.tab/SKIN_Tools.panel" && python - <<'PY'
import io, os, re
text = io.open("bundle.yaml", encoding="utf-8").read()
names = re.findall(r"^\s*-\s*(\S+)\s*$", text, re.M)
print("layout:", names)
for n in names:
    ok = any(os.path.isdir(d) and d.startswith(n + ".")
             for d in os.listdir("."))
    print(("  OK   " if ok else "  MISSING ") + n)
PY
```

Expected: every entry prints `OK`, `CopyRoofSweeps` among them.

- [ ] **Step 6: Confirm the suite still runs**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && python -m unittest discover -s tests
```

Expected: `Ran 305 tests`, `OK`.

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && git add "Revit API/pyRevit-Tools.extension/BG_Tools.tab/SKIN_Tools.panel/CopyRoofSweeps.pushbutton/script.py" "Revit API/pyRevit-Tools.extension/BG_Tools.tab/SKIN_Tools.panel/bundle.yaml" "Revit API/pyRevit-Tools.extension/lib/BG/__init__.py" && git commit -m "feat: a button to rebuild linked fascias and gutters on host roofs" -- "Revit API/pyRevit-Tools.extension/BG_Tools.tab/SKIN_Tools.panel/CopyRoofSweeps.pushbutton/script.py" "Revit API/pyRevit-Tools.extension/BG_Tools.tab/SKIN_Tools.panel/bundle.yaml" "Revit API/pyRevit-Tools.extension/lib/BG/__init__.py"
```

---

### Task 6: Verification in Revit — for the user, not the agent

**Do not do this task. Hand it to the user.** No agent may drive a running Revit session.

Reload pyRevit (`pyRevit` tab → `Reload`), open the host model with the link loaded and the roofs already copied, and work down this list. Each line says what to do and what should happen.

- [ ] The button appears on **BG Tools → SKIN Tools**, labelled `Copy Roof Sweeps`, between `Copy From Link` and `Split Wall Horizontal`.
- [ ] Click it and press Escape at the pick prompt. Nothing happens, nothing is printed.
- [ ] Turn on **Select links** (bottom right). Click one fascia in the link, Finish. It appears in this model in the same place, on your roof, with the right type and the same offsets. The output says `1 rebuilt, 0 already here`.
- [ ] Run it again on the same fascia. It says `0 rebuilt, 1 already here` and no second fascia is created. Check with a section — a doubled sweep is invisible in plan.
- [ ] Pick a fascia and a gutter together. Both come over.
- [ ] Pick a fascia whose type is not in this model. The report says its type was brought over, and the type appears in the project browser.
- [ ] Pick a fascia standing on a roof you have NOT copied. You are asked to pick the roof; press Escape. The report says it was skipped, and nothing is created.
- [ ] Same again, but pick a roof. It builds on that roof.
- [ ] Pick several fascias on one uncopied roof. You are asked ONCE, not once each.
- [ ] Take a copied roof, attach a wall to it or reshape one corner, then pick its fascia. It builds on the edges that still match and the report says `partial: N of M segments`.
- [ ] Undo (Ctrl+Z) once. The whole run disappears in one step.

Report anything that does not match. In particular: if `NewFascia` throws on a valid-looking set of edges, capture the message from the report — that is the one thing this plan could not verify without Revit.

---

## Notes for whoever executes this

**Two things this plan could not check, and where they would bite.**

The `Fascia`/`Gutter`/`FasciaType`/`GutterType` import is guarded (Task 2) because the namespace could not be confirmed against a live Revit — the memory rule forbids probing the open session. If both import paths fail, the module raises at load and the button dies with an ImportError naming the class; the fix is one import line, not a redesign.

`HostedSweep.GetSegmentIds()` and `GetSegmentReference()` are read in Task 2 and again in Task 4's `existing_index`. If either name is wrong, every sweep reports "nothing to rebuild" and nothing is created — a loud, safe failure, and the fix is again local.

**Why the plan writes to `roof_sweep.py` in three tasks rather than one.** Each of Tasks 2, 3 and 4 leaves the module compiling, name-clean and committed, and each is a thing a reviewer could reject on its own: reading the link, matching the host, writing to the model. Splitting the file instead would put a boundary where the code has none.
