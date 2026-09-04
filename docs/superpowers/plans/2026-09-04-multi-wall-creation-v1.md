# Multi Wall Creation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pyRevit tool that turns one mixed selection of linked walls and linked wall sweeps into host-model skin walls, deriving each wall's vertical extent from the sweeps running on it instead of asking the user to pick base and top limits.

**Architecture:** All decision-making arithmetic (span subtraction, wall extent from constraint parameters, the STONE/EIFS type rule, mitre grouping) lives in a new pure-Python module `Tahir.wall_bands` that imports nothing from Revit and is unit-tested in CPython. Revit-facing geometry shared with `SplitWalls` is extracted into `Tahir.wall_skin`. The pushbutton script is thin glue: pick, measure, plan, then one transaction that builds.

**Tech Stack:** IronPython 3 / pyRevit for Revit 2025, Revit API (`Autodesk.Revit.DB`), CPython `unittest` for the pure modules.

**Spec:** `docs/superpowers/specs/2026-09-04-multi-wall-creation-v1-design.md`

## Global Constraints

- Target Revit 2025 via pyRevit. Scripts run under IronPython 3 — no f-strings in files that must also run in the extension; use `.format()`, matching every existing script.
- Every file starts with `# -*- coding: utf-8 -*-`.
- Modules under `lib/Tahir/` named `wall_bands.py`, `wall_limits.py`, `wall_constraints.py`, `wall_miter.py`, `wall_naming.py` MUST NOT import anything from `Autodesk.Revit` — they are unit-tested outside Revit.
- Units are decimal feet throughout. Elevations are host-model geometry space (level elevation minus the project base elevation).
- Tolerance is `Tahir.wall_limits.TOL_LEVEL_MATCH` = 1/16 inch = `0.0052083333` ft. Do not introduce a second tolerance constant.
- Exact wall type names, verbatim, including the inch mark:
  - `SKIN_CAST STONE PROFILE_0' 2"`
  - `SKIN_EIFS PROFILE_0' 2"`
- Nothing is rounded to the inch. `wall_constraints.plan_wall` is always called with `allow_round=False`.
- The linked model is never modified.
- Reporting is silent on success. Failures print one table with columns `["Element", "Note"]`.
- Tests run from the repo root with `python -m pytest tests/ -v` (the tests are plain `unittest`, so `python -m unittest discover -s tests -v` works too).

---

## File Structure

| Path | Responsibility |
|---|---|
| `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_bands.py` | **Create.** Pure arithmetic: span subtraction, wall extent from parameters, STONE/EIFS type rule, mitre grouping key. |
| `tests/test_wall_bands.py` | **Create.** Unit tests for the above. |
| `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_skin.py` | **Create.** Revit-facing skin-wall geometry extracted from `SplitWalls`: face measurement, skin centreline, oriented wall creation. |
| `.../Walls.panel/SplitWalls.pushbutton/script.py` | **Modify.** Delete the extracted functions; import them from `Tahir.wall_skin`. No behaviour change. |
| `.../Walls.panel/MultiWallCreationV1.pushbutton/script.py` | **Create.** The tool: selection, measurement, type resolution, banding, build, report. |
| `.../Walls.panel/bundle.yaml` | **Modify.** Add `MultiWallCreationV1` to the layout. |

---

### Task 1: `wall_bands.subtract_spans` — cutting a wall span with sweeps

**Files:**
- Create: `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_bands.py`
- Test: `tests/test_wall_bands.py`

**Interfaces:**
- Consumes: `Tahir.wall_limits.TOL_LEVEL_MATCH` (float, 1/16 inch in feet).
- Produces:
  - `TOL` — float, re-exported tolerance.
  - `clip(span, lo, hi)` → `(float, float)` or `None`.
  - `merge_spans(spans)` → `list[(float, float)]`, low to high.
  - `subtract_spans(span, cutters, tol=TOL)` → `(gaps, dropped)`, each a `list[(float, float)]` low to high.

- [ ] **Step 1: Write the failing test**

Create `tests/test_wall_bands.py`:

```python
# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from Tahir import wall_bands as wb


IN = 1.0 / 12.0


class TestSubtractSpans(unittest.TestCase):

    def test_no_cutters_gives_the_whole_span(self):
        gaps, dropped = wb.subtract_spans((0.0, 30.0), [])
        self.assertEqual(gaps, [(0.0, 30.0)])
        self.assertEqual(dropped, [])

    def test_one_cutter_mid_span_gives_two_gaps(self):
        gaps, dropped = wb.subtract_spans((0.0, 30.0), [(10.0, 11.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (11.0, 30.0)])
        self.assertEqual(dropped, [])

    def test_two_cutters_give_three_gaps(self):
        gaps, _d = wb.subtract_spans(
            (0.0, 30.0), [(10.0, 11.0), (20.0, 21.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (11.0, 20.0), (21.0, 30.0)])

    def test_cutters_are_order_independent(self):
        gaps, _d = wb.subtract_spans(
            (0.0, 30.0), [(20.0, 21.0), (10.0, 11.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (11.0, 20.0), (21.0, 30.0)])

    def test_exactly_touching_cutters_leave_no_gap_and_no_drop(self):
        gaps, dropped = wb.subtract_spans(
            (0.0, 30.0), [(10.0, 11.0), (11.0, 12.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (12.0, 30.0)])
        self.assertEqual(dropped, [])

    def test_sliver_gap_between_cutters_is_dropped_and_reported(self):
        gaps, dropped = wb.subtract_spans(
            (0.0, 30.0), [(10.0, 11.0), (11.0 + 0.02 * IN, 12.0)])
        self.assertEqual(len(gaps), 2)
        self.assertEqual(len(dropped), 1)
        self.assertAlmostEqual(dropped[0][0], 11.0)

    def test_overlapping_cutters_are_merged(self):
        gaps, dropped = wb.subtract_spans(
            (0.0, 30.0), [(10.0, 15.0), (12.0, 18.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (18.0, 30.0)])
        self.assertEqual(dropped, [])

    def test_cutter_flush_with_span_base_gives_one_gap(self):
        gaps, dropped = wb.subtract_spans((0.0, 30.0), [(0.0, 2.0)])
        self.assertEqual(gaps, [(2.0, 30.0)])
        self.assertEqual(dropped, [])

    def test_cutter_flush_with_span_top_gives_one_gap(self):
        gaps, dropped = wb.subtract_spans((0.0, 30.0), [(28.0, 30.0)])
        self.assertEqual(gaps, [(0.0, 28.0)])
        self.assertEqual(dropped, [])

    def test_cutter_covering_the_span_gives_no_gaps(self):
        gaps, dropped = wb.subtract_spans((0.0, 30.0), [(-5.0, 35.0)])
        self.assertEqual(gaps, [])
        self.assertEqual(dropped, [])

    def test_cutter_wholly_outside_the_span_is_ignored(self):
        gaps, _d = wb.subtract_spans((0.0, 30.0), [(40.0, 42.0)])
        self.assertEqual(gaps, [(0.0, 30.0)])

    def test_cutter_partly_outside_the_span_is_clipped(self):
        gaps, _d = wb.subtract_spans((0.0, 30.0), [(-3.0, 4.0)])
        self.assertEqual(gaps, [(4.0, 30.0)])

    def test_reversed_cutter_is_normalised(self):
        gaps, _d = wb.subtract_spans((0.0, 30.0), [(11.0, 10.0)])
        self.assertEqual(gaps, [(0.0, 10.0), (11.0, 30.0)])

    def test_degenerate_span_gives_nothing(self):
        gaps, dropped = wb.subtract_spans((5.0, 5.0), [])
        self.assertEqual(gaps, [])
        self.assertEqual(dropped, [])


class TestClip(unittest.TestCase):

    def test_span_inside_bounds_is_unchanged(self):
        self.assertEqual(wb.clip((2.0, 4.0), 0.0, 10.0), (2.0, 4.0))

    def test_span_outside_bounds_is_none(self):
        self.assertIsNone(wb.clip((20.0, 24.0), 0.0, 10.0))

    def test_span_straddling_a_bound_is_trimmed(self):
        self.assertEqual(wb.clip((-2.0, 4.0), 0.0, 10.0), (0.0, 4.0))


class TestMergeSpans(unittest.TestCase):

    def test_disjoint_spans_are_kept_apart(self):
        self.assertEqual(
            wb.merge_spans([(5.0, 6.0), (1.0, 2.0)]),
            [(1.0, 2.0), (5.0, 6.0)])

    def test_nested_span_is_absorbed(self):
        self.assertEqual(wb.merge_spans([(1.0, 9.0), (3.0, 4.0)]),
                         [(1.0, 9.0)])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_wall_bands.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Tahir.wall_bands'`

- [ ] **Step 3: Write the implementation**

Create `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_bands.py`:

```python
# -*- coding: utf-8 -*-
"""Pure arithmetic and naming rules for the Multi Wall Creation tool.

Like Tahir.wall_limits and Tahir.wall_constraints this module imports
nothing from Revit, so every rule below can be unit-tested outside it.

What lives here is the part of the tool that decides things:

  * where a wall stops, given the sweeps running on it;
  * how tall a linked wall is, read off its constraint parameters;
  * which wall type a sweep's profile calls for;
  * which new walls sit at the same elevation and may be mitred together.

A *span* is an ``(low_z, high_z)`` pair of elevations in decimal feet,
in host-model geometry space.
"""

from Tahir.wall_limits import TOL_LEVEL_MATCH

# 1/16 inch in feet.  Shared with wall_limits and wall_constraints so all
# three tools agree on what "the same elevation" means.
TOL = TOL_LEVEL_MATCH

# The two wall types the sweep naming rule can resolve to.  Written out
# in full because they are matched against wall type names by equality,
# not by pattern.
CAST_STONE_TYPE_NAME = "SKIN_CAST STONE PROFILE_0' 2\""
EIFS_TYPE_NAME = "SKIN_EIFS PROFILE_0' 2\""


def clip(span, lo, hi):
    """Return *span* trimmed to the range [lo, hi], or None.

    A span given the wrong way round is normalised first, so a caller
    need not care which end of a sweep envelope came out larger.  None
    means nothing of the span survives inside the range.
    """
    a, b = span
    if b < a:
        a, b = b, a
    a = max(a, lo)
    b = min(b, hi)
    if b <= a:
        return None
    return (a, b)


def merge_spans(spans):
    """Return *spans* sorted low to high, overlaps and touches merged.

    Two sweeps that overlap must not each cut the wall separately -- the
    stretch between them does not exist, and reporting it as a dropped
    band would be noise.
    """
    merged = []
    for lo, hi in sorted(spans):
        if merged and lo <= merged[-1][1]:
            prev_lo, prev_hi = merged[-1]
            merged[-1] = (prev_lo, max(prev_hi, hi))
        else:
            merged.append((lo, hi))
    return merged


def subtract_spans(span, cutters, tol=TOL):
    """Cut *span* with every span in *cutters*.

    Returns ``(gaps, dropped)``, both low to high:

        gaps     the stretches of *span* left over, each at least *tol*
                 tall -- one new wall will be built per gap
        dropped  stretches thinner than *tol* that were left over but
                 are too thin to build.  The caller reports these, so a
                 sliver is never lost silently.

    Cutters outside *span* are ignored and cutters straddling its ends
    are clipped, so a sweep that runs past the top of its host wall does
    not extend the wall.  An exactly zero-height leftover is neither a
    gap nor a drop -- two sweeps meeting face to face leave nothing, and
    there is nothing to report about it.
    """
    base_z, top_z = span
    if top_z - base_z <= tol:
        return [], []

    clipped = []
    for cutter in cutters:
        piece = clip(cutter, base_z, top_z)
        if piece is not None:
            clipped.append(piece)

    gaps = []
    dropped = []
    cursor = base_z

    for lo, hi in merge_spans(clipped):
        _record(gaps, dropped, cursor, lo, tol)
        cursor = max(cursor, hi)

    _record(gaps, dropped, cursor, top_z, tol)
    return gaps, dropped


def _record(gaps, dropped, lo, hi, tol):
    """File one leftover stretch as a gap, a drop, or nothing at all."""
    height = hi - lo
    if height > tol:
        gaps.append((lo, hi))
    elif height > 0.0:
        dropped.append((lo, hi))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_wall_bands.py -v`
Expected: PASS, 19 tests.

- [ ] **Step 5: Commit**

```bash
git add "tests/test_wall_bands.py" "Revit API/pyRevit-Tools.extension/lib/Tahir/wall_bands.py"
git commit -m "feat: add wall_bands.subtract_spans for cutting wall spans at sweeps"
```

---

### Task 2: `wall_bands` — wall extent, sweep type rule, mitre grouping

**Files:**
- Modify: `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_bands.py`
- Test: `tests/test_wall_bands.py`

**Interfaces:**
- Consumes: `wall_bands.CAST_STONE_TYPE_NAME`, `wall_bands.EIFS_TYPE_NAME`, `wall_bands.TOL` from Task 1.
- Produces:
  - `wall_span(base_elev, base_offset, top_elev, top_offset, unconnected_height)` → `(float, float)`. `top_elev` is `None` for an unconnected wall.
  - `sweep_wall_type_name(*names)` → `str` or `None`.
  - `elevation_group_key(base_z, top_z, tol=TOL)` → hashable `(int, int)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wall_bands.py`, above the `if __name__` block:

```python
class TestWallSpan(unittest.TestCase):

    def test_level_bound_wall_uses_its_top_level(self):
        self.assertEqual(
            wb.wall_span(0.0, 0.0, 10.0, 0.0, 99.0), (0.0, 10.0))

    def test_offsets_are_applied_to_both_ends(self):
        self.assertEqual(
            wb.wall_span(10.0, 0.5, 20.0, -1.5, 99.0), (10.5, 18.5))

    def test_unconnected_wall_uses_its_height(self):
        self.assertEqual(
            wb.wall_span(10.0, 0.5, None, 0.0, 8.0), (10.5, 18.5))

    def test_negative_base_offset_lowers_the_base(self):
        self.assertEqual(
            wb.wall_span(10.0, -2.0, 20.0, 0.0, 99.0), (8.0, 20.0))


class TestSweepWallTypeName(unittest.TestCase):

    def test_stone_in_the_type_name_wins(self):
        self.assertEqual(
            wb.sweep_wall_type_name("Cast Stone Band", "Concrete"),
            wb.CAST_STONE_TYPE_NAME)

    def test_eifs_in_the_type_name_wins(self):
        self.assertEqual(
            wb.sweep_wall_type_name("EIFS Cornice", "Foam"),
            wb.EIFS_TYPE_NAME)

    def test_match_is_case_insensitive(self):
        self.assertEqual(
            wb.sweep_wall_type_name("eifs cornice"), wb.EIFS_TYPE_NAME)

    def test_material_name_is_used_when_the_type_name_says_nothing(self):
        self.assertEqual(
            wb.sweep_wall_type_name("Band 6in", "CAST STONE - Buff"),
            wb.CAST_STONE_TYPE_NAME)

    def test_type_name_beats_material_name(self):
        self.assertEqual(
            wb.sweep_wall_type_name("EIFS Band", "Cast Stone"),
            wb.EIFS_TYPE_NAME)

    def test_stone_beats_eifs_within_one_name(self):
        self.assertEqual(
            wb.sweep_wall_type_name("Cast Stone over EIFS"),
            wb.CAST_STONE_TYPE_NAME)

    def test_no_match_is_none(self):
        self.assertIsNone(wb.sweep_wall_type_name("Brick Soldier", "Brick"))

    def test_missing_names_are_tolerated(self):
        self.assertIsNone(wb.sweep_wall_type_name(None, None))


class TestElevationGroupKey(unittest.TestCase):

    def test_identical_extents_share_a_key(self):
        self.assertEqual(wb.elevation_group_key(0.0, 10.0),
                         wb.elevation_group_key(0.0, 10.0))

    def test_extents_within_tolerance_share_a_key(self):
        self.assertEqual(wb.elevation_group_key(0.0, 10.0),
                         wb.elevation_group_key(0.0, 10.0 + 1e-9))

    def test_different_extents_do_not_share_a_key(self):
        self.assertNotEqual(wb.elevation_group_key(0.0, 10.0),
                            wb.elevation_group_key(11.0, 20.0))

    def test_same_base_different_top_does_not_share_a_key(self):
        self.assertNotEqual(wb.elevation_group_key(0.0, 10.0),
                            wb.elevation_group_key(0.0, 20.0))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_wall_bands.py -v`
Expected: FAIL — `AttributeError: module 'Tahir.wall_bands' has no attribute 'wall_span'`

- [ ] **Step 3: Write the implementation**

Append to `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_bands.py`:

```python
def wall_span(base_elev, base_offset, top_elev, top_offset,
              unconnected_height):
    """Return ``(base_z, top_z)`` for a wall, from its constraints.

    *base_elev* and *top_elev* are the elevations of the wall's Base and
    Top Constraint levels; *top_elev* is None when the wall has no top
    constraint, and the top then comes from *unconnected_height* above
    the base.

    Constraint parameters are used rather than the wall's solid because
    a wall attached to a sloping roof would otherwise report the highest
    point of that slope as its top, and every wall under it would be
    built to the wrong height.
    """
    base_z = base_elev + base_offset
    if top_elev is None:
        return base_z, base_z + unconnected_height
    return base_z, top_elev + top_offset


def sweep_wall_type_name(*names):
    """Return the wall type name a sweep's profile calls for, or None.

    *names* are searched in the order given -- the sweep's type name
    first, then its dominant material name -- so a type name that says
    what the profile is beats a material that says something else.
    Within one name STONE is tested before EIFS, so 'Cast Stone over
    EIFS' is stone.  Matching is a case-insensitive substring.

    None means the rule cannot tell, and the caller must ask.
    """
    for name in names:
        text = (name or "").upper()
        if "STONE" in text:
            return CAST_STONE_TYPE_NAME
        if "EIFS" in text:
            return EIFS_TYPE_NAME
    return None


def elevation_group_key(base_z, top_z, tol=TOL):
    """Return a key shared by bands at the same vertical extent.

    Only walls that actually sit at the same height may have their
    corners mitred together: mitring a band at 11-20 ft against its
    neighbour at 0-10 ft would drag a corner between two walls that
    never touch.  Elevations are quantised to *tol* so two bands cut by
    the same sweep group together despite floating-point drift.
    """
    return (int(round(base_z / tol)), int(round(top_z / tol)))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS — the 19 tests from Task 1, the 16 added here, and the pre-existing `test_wall_constraints`, `test_wall_limits`, `test_wall_miter`, `test_wall_naming` suites.

- [ ] **Step 5: Commit**

```bash
git add "tests/test_wall_bands.py" "Revit API/pyRevit-Tools.extension/lib/Tahir/wall_bands.py"
git commit -m "feat: add wall extent, sweep type rule and mitre grouping to wall_bands"
```

---

### Task 3: Extract `Tahir.wall_skin` from `SplitWalls`

Behaviour must not change. `SplitWalls` keeps working exactly as it does today; the new tool gets the same geometry code without copying it.

**Files:**
- Create: `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_skin.py`
- Modify: `Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `measure_face_offsets(elem, ref_pt, orient, transform=None)` → `(hi, lo)` floats or `None`.
  - `layer_group_widths(cs, first_core, last_core)` → `(skin_w, gap_w, core_w, int_w, ext_total_w)`.
  - `dist_loc_to_exterior(loc_line, total_w, skin_w, gap_w, core_w)` → `float`.
  - `skin_centreline(loc_curve, orientation, dist_to_exterior, skin_width)` → `Curve`.
  - `create_oriented_wall(doc, curve, type_id, level_id, height, base_off, structural, orig_orient)` → `Wall`.

- [ ] **Step 1: Create the new module**

Create `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_skin.py`:

```python
# -*- coding: utf-8 -*-
"""Placing a new skin wall against an existing wall's exterior face.

Extracted from the SplitWalls pushbutton so Multi Wall Creation can use
the same geometry rather than a second copy of it.  Behaviour is
unchanged from that script; the only differences are that *doc* is now
passed in rather than read off a module global, and skin_centreline
takes plain values rather than SplitWalls' WallData object.

Two things here are worth knowing before changing them.

The faces of a wall are MEASURED off its real solid, not inferred from
its Location Line parameter.  A wall whose layer build-up is asymmetric,
or whose Location Line is set to anything but Centreline, is placed
wrongly by inference and correctly by measurement.

A new wall is then re-centred after creation.  Revit applies whatever
Location Line the type happens to default to at creation time, which
moves the wall off the curve it was asked for; measuring the result and
cancelling the residual error is the only dependable fix.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    ElementTransformUtils,
    GeometryInstance,
    Options,
    Solid,
    Transform,
    ViewDetailLevel,
    Wall,
    XYZ,
)


def _iter_solid_points(elem, transform=None):
    """Yield every tessellated vertex of *elem*'s solid geometry.

    Deliberately not Tahir.wall_chain.iter_solid_points: this one asks
    for Medium detail, which is what SplitWalls has always measured at,
    and changing the detail level changes the measurements.
    """
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Medium

    geo_elem = elem.get_Geometry(opts)
    if geo_elem is None:
        return

    for gobj in geo_elem:
        solids = []
        if isinstance(gobj, Solid):
            solids.append(gobj)
        elif isinstance(gobj, GeometryInstance):
            try:
                for g2 in gobj.GetInstanceGeometry():
                    if isinstance(g2, Solid):
                        solids.append(g2)
            except Exception:
                continue

        for sol in solids:
            try:
                if sol.Volume <= 0:
                    continue
            except Exception:
                continue
            for edge in sol.Edges:
                try:
                    for pt in edge.Tessellate():
                        yield transform.OfPoint(pt) if transform else pt
                except Exception:
                    continue


def measure_face_offsets(elem, ref_pt, orient, transform=None):
    """Measure a wall's real face positions instead of inferring them.

    Projects every vertex of the wall's solid onto *orient* (the
    exterior normal), relative to *ref_pt* (a point on the wall's
    location curve).

    Returns (d_ext, d_int) where d_ext is the signed distance from the
    location curve to the EXTERIOR face and d_int the signed distance to
    the INTERIOR face, negative when that face is behind the curve.
    Returns None when the geometry could not be measured.
    """
    try:
        n = orient.Normalize()
    except Exception:
        return None

    hi = None
    lo = None
    for pt in _iter_solid_points(elem, transform):
        d = (pt - ref_pt).DotProduct(n)
        if hi is None or d > hi:
            hi = d
        if lo is None or d < lo:
            lo = d

    if hi is None or lo is None:
        return None
    return hi, lo


def layer_group_widths(cs, first_core, last_core):
    """Return (skin_w, gap_w, core_w, interior_w, ext_total_w) in feet."""
    skin_w = cs.GetLayerWidth(0)
    gap_w = sum(cs.GetLayerWidth(i) for i in range(1, first_core))
    core_w = sum(cs.GetLayerWidth(i)
                 for i in range(first_core, last_core + 1))
    int_w = sum(cs.GetLayerWidth(i)
                for i in range(last_core + 1, cs.LayerCount))
    return skin_w, gap_w, core_w, int_w, core_w + int_w


def dist_loc_to_exterior(loc_line, total_w, skin_w, gap_w, core_w):
    """Distance from a wall's location curve to its exterior face, feet.

    Only a fallback for when the solid could not be measured.  Covers
    all six WallLocationLine settings:

        0 = Wall Centerline          3 = Finish Face: Interior
        1 = Core Centerline          4 = Core Face: Exterior
        2 = Finish Face: Exterior    5 = Core Face: Interior
    """
    ext_shell = skin_w + gap_w
    mapping = {
        0: total_w / 2.0,
        1: ext_shell + core_w / 2.0,
        2: 0.0,
        3: total_w,
        4: ext_shell,
        5: ext_shell + core_w,
    }
    return mapping.get(loc_line, total_w / 2.0)


def skin_centreline(loc_curve, orientation, dist_to_exterior, skin_width):
    """Centreline for a skin wall sitting in the source wall's finish.

    *dist_to_exterior* is the distance from *loc_curve* to the source
    wall's exterior face, measured or inferred.  The skin wall occupies
    the outermost finish layer, so its centreline sits half its own
    thickness inboard of that face.
    """
    skin_off = dist_to_exterior - skin_width / 2.0

    orient = orientation.Normalize()
    vec = XYZ(orient.X * skin_off, orient.Y * skin_off, orient.Z * skin_off)

    return loc_curve.CreateTransformed(Transform.CreateTranslation(vec))


def _center_wall_on_curve(doc, wall, target_curve, orient):
    """Translate *wall* so its solid's mid-plane lands on *target_curve*.

    Rather than trusting whichever Location Line default Wall.Create()
    applied, this measures the wall's real faces and cancels out any
    residual perpendicular error.
    """
    try:
        n = orient.Normalize()
        ref_pt = target_curve.GetEndPoint(0)

        meas = measure_face_offsets(wall, ref_pt, n)
        if not meas:
            return

        hi, lo = meas
        center_err = (hi + lo) / 2.0   # 0.0 when perfectly centred

        if abs(center_err) > 1e-7:
            move_vec = XYZ(n.X * -center_err,
                           n.Y * -center_err,
                           n.Z * -center_err)
            ElementTransformUtils.MoveElement(doc, wall.Id, move_vec)
            doc.Regenerate()
    except Exception:
        pass


def create_oriented_wall(doc, curve, type_id, level_id, height, base_off,
                         structural, orig_orient):
    """Create a wall on *curve* facing the same way as *orig_orient*.

    The curve is the wall's intended CENTRELINE.  Location Line is
    forced to Centreline so the curve means that whatever the type's
    default was, the wall is re-created reversed if it came out facing
    the wrong way, and the result is re-centred on the curve.
    """
    wall = Wall.Create(doc, curve, type_id, level_id, height, base_off,
                       False, structural)
    doc.Regenerate()

    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
        if p and p.HasValue:
            p.Set(0)  # 0 = Wall Centerline
        doc.Regenerate()
    except Exception:
        pass

    try:
        if orig_orient.DotProduct(wall.Orientation) < 0:
            doc.Delete(wall.Id)
            doc.Regenerate()
            curve = curve.CreateReversed()
            wall = Wall.Create(doc, curve, type_id, level_id, height,
                               base_off, False, structural)
            doc.Regenerate()
            p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
            if p and p.HasValue:
                p.Set(0)
            doc.Regenerate()
    except Exception:
        pass

    _center_wall_on_curve(doc, wall, curve, orig_orient)

    return wall
```

- [ ] **Step 2: Check it compiles**

Run: `python -m py_compile "Revit API/pyRevit-Tools.extension/lib/Tahir/wall_skin.py"`
Expected: no output, exit 0. (`py_compile` checks syntax without executing, so the Revit imports are irrelevant here.)

- [ ] **Step 3: Point `SplitWalls` at the new module**

In `.../Walls.panel/SplitWalls.pushbutton/script.py`:

1. Add `wall_skin` to the existing Tahir import:

```python
from Tahir import wall_limits, wall_miter, wall_materials, wall_naming, wall_skin
```

2. Delete these five definitions outright: `_iter_solid_points`, `measure_face_offsets`, `_layer_group_widths`, `_dist_loc_to_exterior`, `_center_wall_on_curve`, and `create_oriented_wall`.

3. Add a module-level alias immediately after the `doc/uidoc/logger/output` block, so the three remaining call sites in `_wall_data_from_host_wall`, `_wall_data_from_linked_ref` and `compute_skin_curve` need no edit:

```python
measure_face_offsets = wall_skin.measure_face_offsets
```

4. Replace the body of `compute_skin_curve` (keep its docstring and signature) with:

```python
def compute_skin_curve(wd, first_core, last_core):
    """Compute the host-coordinate centerline for the new SKIN wall.

    The SKIN wall occupies the outermost finish layer of the original
    wall, so its centerline sits half its own thickness inboard of the
    original wall's exterior face.

    Returns (skin_curve, gap_width).
    """
    skin_w, gap_w, core_w, _int_w, _ext_total_w = \
        wall_skin.layer_group_widths(wd.cs, first_core, last_core)

    # Prefer the offset measured off the wall's real solid.  Fall back to
    # deriving it from the Location Line parameter only when the geometry
    # could not be read.
    if wd.loc_to_ext is not None:
        d = wd.loc_to_ext
    else:
        d = wall_skin.dist_loc_to_exterior(
            wd.loc_line, wd.total_width, skin_w, gap_w, core_w)

    skin_curve = wall_skin.skin_centreline(
        wd.loc_curve, wd.orientation, d, skin_w)

    return skin_curve, gap_w
```

5. In `create_skin`, change the one call:

```python
    skin_wall = wall_skin.create_oriented_wall(
        doc, item["curve"], item["type"].Id, limits["base_level_id"],
        limits["height"], limits["base_offset"],
        wd.structural, wd.orientation,
    )
```

6. Remove now-unused names from the `Autodesk.Revit.DB` import list in `SplitWalls`: `ElementTransformUtils`, `GeometryInstance`, `Options`, `Solid`, `Transform`, `ViewDetailLevel`. Leave every other import alone.

- [ ] **Step 4: Verify the extraction**

Run all three checks:

```bash
python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py"
grep -nE "^def (_iter_solid_points|_layer_group_widths|_dist_loc_to_exterior|_center_wall_on_curve|create_oriented_wall)\b" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py"
grep -nE "GeometryInstance|ViewDetailLevel|ElementTransformUtils" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py"
```

Expected: `py_compile` silent and exit 0; both `grep`s find nothing and exit 1.

- [ ] **Step 5: Verify in Revit**

Run **Split Walls** on a linked wall exactly as before and confirm the new skin wall lands in the same place it did prior to this task. This is a refactor — any visible difference is a bug in the extraction, not a new behaviour.

- [ ] **Step 6: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/Tahir/wall_skin.py" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py"
git commit -m "refactor: extract skin wall geometry from SplitWalls into Tahir.wall_skin"
```

---

### Task 4: The pushbutton — selection and measurement

The button exists, picks a mixed selection, measures everything, and prints what it found. It creates nothing yet. The diagnostic table it prints is temporary and Task 7 replaces it.

**Files:**
- Create: `.../Walls.panel/MultiWallCreationV1.pushbutton/script.py`
- Modify: `.../Walls.panel/bundle.yaml`

**Interfaces:**
- Consumes: `wall_bands.wall_span` (Task 2); `wall_chain.wall_frame`, `wall_chain.wall_exterior_offset`, `wall_chain.iter_solids`; `wall_skin.measure_face_offsets` (Task 3).
- Produces, for later tasks in the same file:
  - `class SweepJob` with attributes `label, sweep, frames, offsets, host_ids, base_z, top_z, material, type_mark, type_name, wall_type`.
  - `class WallJob` with attributes `label, wall_id, cs, source_doc, loc_curve, orientation, total_width, loc_line, loc_to_ext, base_z, top_z, structural, bands`.
  - `pick_sources()` → `(list[(link_inst, Wall)], list[(link_inst, WallSweep)])`.
  - `plan_sweep(link_inst, sweep)` → `(SweepJob or None, notes)`.
  - `plan_wall(link_inst, wall)` → `(WallJob or None, notes)`.
  - `host_levels()` → `list[(ElementId, float)]`.
  - `note(notes, element_label, text)` — appends `[element_label, text]`.

- [ ] **Step 1: Create the script**

Create `.../Walls.panel/MultiWallCreationV1.pushbutton/script.py`:

```python
# -*- coding: utf-8 -*-
"""Create host-model skin walls and sweep walls from one linked selection.

Pick any mix of walls and wall sweeps in a LINKED model.  Each sweep
becomes a wall in the host model, exactly as Sweep To Wall makes one.
Each wall becomes one or more skin walls, exactly as Split Walls makes
them -- except that nobody picks a base and a top.

A wall's height comes from the sweeps running on it:

  * its top is the bottom of the sweep above it,
  * its base is the top of the sweep below it,
  * a sweep part-way up cuts it in two, and every level it crosses cuts
    it again, so no new wall crosses either,
  * with no sweep above or below, that end falls back to the source
    wall's own Base and Top Constraint.

Only sweeps you actually pick cut a wall, and only sweeps hosted on that
wall -- the link's own GetHostIds() decides, so a sweep running along a
neighbouring wall never shortens this one.

Nothing is rounded.  A band end has to sit exactly on a sweep face or a
level, or a gap opens up in the elevation.

Sweep wall types are automatic: a sweep whose type name or material name
says STONE gets SKIN_CAST STONE PROFILE_0' 2", one that says EIFS gets
SKIN_EIFS PROFILE_0' 2".  Anything the rule cannot read is asked about
once, per sweep type.  Wall skins resolve their type from the finish
material's Mark, as Split Walls does.

KNOWN LIMITATION: a sweep is measured as one vertical envelope across
all its host walls, as Sweep To Wall measures it.  A stepped sweep that
runs at different heights on different walls is therefore built, and
cuts, at its overall extent.  Split such a sweep in the link first.

The linked model is never modified.
"""

__title__  = "Multi Wall\nCreation V1"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick any mix of walls and wall sweeps in a LINKED model, then "
    "press Esc.\n"
    "Each sweep becomes a wall in the host model; each wall becomes "
    "skin walls that stop at the sweeps running on it.\n"
    "Walls are cut again at every level they cross.  A wall with no "
    "sweep above or below falls back to its own constraints.\n"
    "Sweep wall types come from STONE / EIFS in the sweep's type or "
    "material name; you are only asked about what that cannot read.\n"
    "The linked model is left untouched."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    Level,
    Line,
    RevitLinkInstance,
    Transaction,
    Wall,
    WallKind,
    WallSweep,
    WallSweepType,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from Tahir import (
    wall_bands,
    wall_chain,
    wall_constraints,
    wall_materials,
    wall_naming,
    wall_skin,
)

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

# Shorter than this, in feet, and there is no wall worth making (~16 mm).
MIN_RUN_LENGTH = 0.05

# WallLocationLine values.
LOC_LINE_CENTRELINE           = 0
LOC_LINE_FINISH_FACE_INTERIOR = 3

# The sweep type's Type Mark is carried onto each sweep wall here.
BG_PROFILE_PARAM = "BG_PROFILE"

TOOL_TITLE = "Multi Wall Creation V1"


# ===========================================================================
# HELPERS
# ===========================================================================

def get_element_name(element):
    """Safely get the Name of any Revit element.

    Element.Name is not dependable from IronPython, so this falls back
    to the Type Name parameter the way the other wall tools do.
    """
    if element is None:
        return "<null>"
    try:
        return element.Name
    except Exception:
        pass
    try:
        p = element.LookupParameter("Type Name")
        if p:
            return p.AsString()
    except Exception:
        pass
    return "<unknown>"


def find_parameter(elem, name):
    """Return *elem*'s parameter called *name*, ignoring case, or None.

    LookupParameter is case-sensitive, which is a poor match for
    parameter names written one way in a shared parameter file and
    another in the model -- BG_PROFILE against BG_Profile, say.
    """
    try:
        p = elem.LookupParameter(name)
        if p is not None:
            return p
    except Exception:
        pass

    wanted = (name or "").strip().lower()
    try:
        for p in elem.Parameters:
            try:
                if p.Definition.Name.strip().lower() == wanted:
                    return p
            except Exception:
                continue
    except Exception:
        pass
    return None


def note(notes, element_label, text):
    """Record one thing that went wrong, for the report at the end."""
    notes.append([element_label, text])


def feet_text(value):
    """A short, readable elevation for the report."""
    return "{0:.4f}".format(value)


def project_base_elevation(target_doc):
    """Return the offset between level elevations and model geometry.

    Levels report their elevation relative to the Project Base Point
    while solid geometry comes back in internal model coordinates.  When
    the base point sits at elevation 0 the two coincide and this returns
    0.0, so the conversion is harmless in ordinary projects.
    """
    try:
        col = FilteredElementCollector(target_doc) \
            .OfCategory(BuiltInCategory.OST_ProjectBasePoint) \
            .WhereElementIsNotElementType()
        for bp in col:
            p = bp.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)
            if p and p.HasValue:
                return p.AsDouble()
    except Exception as ex:
        logger.debug("Could not read project base elevation: {}".format(ex))
    return 0.0


def host_levels():
    """Return [(ElementId, elevation)] for every host Level.

    Elevations are converted into geometry space so they can be compared
    with sweep envelopes and wall spans directly.
    """
    delta = project_base_elevation(doc)
    return [(lvl.Id, lvl.Elevation - delta)
            for lvl in FilteredElementCollector(doc).OfClass(Level)]


# ===========================================================================
# SELECTION
# ===========================================================================

def sweep_is_convertible(sweep):
    """Return (ok, reason).  Reveals and vertical sweeps are not.

    A reveal is a void cut into the wall, so turning one into a solid
    wall would model the opposite of what is there.
    """
    try:
        info = sweep.GetWallSweepInfo()
    except Exception:
        return True, None          # cannot tell; let the geometry decide

    if info is None:
        return True, None
    try:
        if info.WallSweepType == WallSweepType.Reveal:
            return False, "reveal (a void, not a sweep)"
    except Exception:
        pass
    try:
        if info.IsVertical:
            return False, "vertical sweep"
    except Exception:
        pass
    return True, None


class LinkedWallOrSweepFilter(ISelectionFilter):
    """Allow Basic Walls and horizontal wall sweeps inside a link.

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

            if isinstance(elem, WallSweep):
                return sweep_is_convertible(elem)[0]
            if isinstance(elem, Wall):
                return elem.WallType.Kind == WallKind.Basic
            return False
        except Exception:
            return False


def pick_sources():
    """Pick walls and sweeps in links until Esc.

    Returns (wall_picks, sweep_picks), each a de-duplicated list of
    (RevitLinkInstance, element).
    """
    walls  = []
    sweeps = []
    seen   = set()
    filt   = LinkedWallOrSweepFilter()

    while True:
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.LinkedElement, filt,
                "Pick walls and wall sweeps in a linked model "
                "(Esc when done)")
        except OperationCanceledException:
            break
        except Exception as ex:
            logger.debug("Pick ended: {}".format(ex))
            break

        if ref is None:
            break

        key = (ref.ElementId.IntegerValue, ref.LinkedElementId.IntegerValue)
        if key in seen:
            continue
        seen.add(key)

        link_inst = doc.GetElement(ref.ElementId)
        link_doc  = link_inst.GetLinkDocument()
        elem      = link_doc.GetElement(ref.LinkedElementId)

        if isinstance(elem, WallSweep):
            sweeps.append((link_inst, elem))
        elif isinstance(elem, Wall):
            walls.append((link_inst, elem))

    return walls, sweeps


# ===========================================================================
# SWEEPS
# ===========================================================================

class SweepJob(object):
    """One sweep, measured and ready to build once its type is known."""

    __slots__ = ("label", "sweep", "frames", "offsets", "host_ids",
                 "base_z", "top_z", "material", "type_mark", "type_name",
                 "wall_type")


def sweep_host_walls(sweep):
    """Return the walls *sweep* is hosted on, from the sweep's own doc."""
    try:
        ids = list(sweep.GetHostIds())
    except Exception:
        return []

    link_doc = sweep.Document
    walls    = []
    for wid in ids:
        elem = link_doc.GetElement(wid)
        if isinstance(elem, Wall):
            walls.append(elem)
    return walls


def sweep_extent(sweep, transform):
    """Return (base_z, top_z, material_name) measured off the sweep.

    Elevations come back in HOST coordinates.  Only the vertical
    envelope is taken from the sweep -- where each wall goes in plan
    comes from the host wall itself, which is far more dependable than
    working out which stretch of a sweep belongs to which host wall.
    """
    z_min = z_max = None
    areas = {}

    for sol in wall_chain.iter_solids(sweep):
        for edge in sol.Edges:
            try:
                for pt in edge.Tessellate():
                    z = transform.OfPoint(pt).Z
                    if z_min is None or z < z_min:
                        z_min = z
                    if z_max is None or z > z_max:
                        z_max = z
            except Exception:
                continue

        for face in sol.Faces:
            try:
                mid = face.MaterialElementId
                if mid is None or mid == ElementId.InvalidElementId:
                    continue
                areas[mid.IntegerValue] = \
                    areas.get(mid.IntegerValue, 0.0) + face.Area
            except Exception:
                continue

    if z_min is None:
        return None, None, None

    material_name = None
    if areas:
        best = max(areas.keys(), key=lambda k: areas[k])
        material_name = get_element_name(
            sweep.Document.GetElement(ElementId(best)))

    return z_min, z_max, material_name


def sweep_type_mark(sweep):
    """Return the Type Mark of the sweep's type, or None when blank."""
    try:
        sweep_type = sweep.Document.GetElement(sweep.GetTypeId())
    except Exception:
        return None
    if sweep_type is None:
        return None

    getters = (
        lambda e: e.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_MARK),
        lambda e: find_parameter(e, "Type Mark"),
    )
    for getter in getters:
        try:
            p = getter(sweep_type)
        except Exception:
            continue
        if p is None:
            continue
        try:
            if not p.HasValue:
                continue
            value = p.AsString()
        except Exception:
            continue
        if value and value.strip():
            return value.strip()
    return None


def sweep_type_name(sweep):
    """Return the name of *sweep*'s type, for the STONE/EIFS rule."""
    try:
        return get_element_name(sweep.Document.GetElement(sweep.GetTypeId()))
    except Exception:
        return None


def plan_sweep(link_inst, sweep):
    """Measure one sweep.  Returns (SweepJob or None, notes)."""
    notes     = []
    transform = link_inst.GetTotalTransform()
    label     = "sweep id {}".format(sweep.Id.IntegerValue)

    ok, reason = sweep_is_convertible(sweep)
    if not ok:
        return None, [[label, reason]]

    walls = sweep_host_walls(sweep)
    if not walls:
        return None, [[label, "sweep is not hosted on any wall"]]

    base_z, top_z, material_name = sweep_extent(sweep, transform)
    if base_z is None or (top_z - base_z) < MIN_RUN_LENGTH:
        return None, [[label,
                       "no usable sweep geometry (check the link's view "
                       "detail level)"]]

    frames  = []
    offsets = []
    for host in walls:
        host_label = "{} (id {})".format(get_element_name(host.WallType),
                                         host.Id.IntegerValue)

        frame = wall_chain.wall_frame(host, transform)
        if frame is None:
            note(notes, host_label, "wall has no location curve")
            continue
        if not frame.is_line:
            note(notes, host_label, "curved wall - not supported")
            continue
        if frame.length < MIN_RUN_LENGTH:
            note(notes, host_label, "wall too short")
            continue

        frames.append(frame)
        offsets.append(wall_chain.wall_exterior_offset(frame, transform))

    if not frames:
        return None, notes

    job = SweepJob()
    job.label     = label
    job.sweep     = sweep
    job.frames    = frames
    job.offsets   = offsets
    job.host_ids  = set(w.Id.IntegerValue for w in walls)
    job.base_z    = base_z
    job.top_z     = top_z
    job.material  = material_name
    job.type_mark = sweep_type_mark(sweep)
    job.type_name = sweep_type_name(sweep)
    job.wall_type = None          # filled in by resolve_sweep_types
    return job, notes


# ===========================================================================
# WALLS
# ===========================================================================

class WallJob(object):
    """One linked wall, measured and ready to band."""

    __slots__ = ("label", "wall_id", "cs", "source_doc", "loc_curve",
                 "orientation", "total_width", "loc_line", "loc_to_ext",
                 "base_z", "top_z", "structural", "bands")


def _level_elevation(link_doc, level_id, link_tf):
    """Elevation of a LINKED level, in host geometry space.

    Read from the linked document and pushed through the link transform,
    rather than matched to a host level by name: a link whose levels are
    named differently would otherwise silently bind to the wrong storey.
    """
    lvl = link_doc.GetElement(level_id)
    if lvl is None:
        return None
    raw = lvl.Elevation - project_base_elevation(link_doc)
    return link_tf.OfPoint(XYZ(0.0, 0.0, raw)).Z


def plan_wall(link_inst, wall):
    """Measure one linked wall.  Returns (WallJob or None, notes)."""
    label = "wall id {} ({})".format(wall.Id.IntegerValue,
                                     get_element_name(wall.WallType))

    if wall.WallType.Kind != WallKind.Basic:
        return None, [[label, "not a Basic Wall"]]

    cs = wall.WallType.GetCompoundStructure()
    if cs is None:
        return None, [[label, "wall type has no compound structure"]]
    if cs.LayerCount < 2:
        return None, [[label, "fewer than 2 layers - nothing to split"]]
    if cs.GetFirstCoreLayerIndex() < 1:
        return None, [[label,
                       "no exterior finish layer before the core boundary"]]

    link_doc = wall.Document
    link_tf  = link_inst.GetTotalTransform()

    raw_curve = wall.Location.Curve if wall.Location is not None else None
    if raw_curve is None:
        return None, [[label, "wall has no location curve"]]
    if not isinstance(raw_curve, Line):
        return None, [[label, "curved wall - not supported"]]

    pt0 = link_tf.OfPoint(raw_curve.GetEndPoint(0))
    pt1 = link_tf.OfPoint(raw_curve.GetEndPoint(1))
    if pt0.DistanceTo(pt1) < MIN_RUN_LENGTH:
        return None, [[label, "wall too short"]]
    loc_curve = Line.CreateBound(pt0, pt1)

    # Rotate the orientation vector: transforming origin+direction and
    # subtracting the transformed origin isolates the rotation.
    raw_orient  = wall.Orientation
    origin_tf   = link_tf.OfPoint(XYZ.Zero)
    orient_tip  = link_tf.OfPoint(
        XYZ(raw_orient.X, raw_orient.Y, raw_orient.Z))
    orientation = XYZ(orient_tip.X - origin_tf.X,
                      orient_tip.Y - origin_tf.Y,
                      orient_tip.Z - origin_tf.Z).Normalize()

    loc_to_ext = None
    try:
        meas = wall_skin.measure_face_offsets(
            wall, pt0, orientation, link_tf)
        if meas:
            loc_to_ext = meas[0]
    except Exception as ex:
        logger.debug("Face measurement failed on {}: {}".format(label, ex))

    # ---- Vertical extent, from the constraint parameters only.
    base_p = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
    base_elev = _level_elevation(
        link_doc, base_p.AsElementId(), link_tf) if base_p else None
    if base_elev is None:
        return None, [[label, "wall has no readable Base Constraint"]]

    bo_p = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    base_offset = bo_p.AsDouble() if (bo_p and bo_p.HasValue) else 0.0

    top_p = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
    top_elev = None
    if top_p and top_p.HasValue:
        top_id = top_p.AsElementId()
        if top_id is not None and top_id != ElementId.InvalidElementId:
            top_elev = _level_elevation(link_doc, top_id, link_tf)

    to_p = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
    top_offset = to_p.AsDouble() if (to_p and to_p.HasValue) else 0.0

    h_p = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
    height = h_p.AsDouble() if (h_p and h_p.HasValue) else 0.0

    base_z, top_z = wall_bands.wall_span(
        base_elev, base_offset, top_elev, top_offset, height)

    if top_z - base_z <= wall_bands.TOL:
        return None, [[label, "wall constraints give no height"]]

    st_p = wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
    structural = bool(st_p.AsInteger()) if (st_p and st_p.HasValue) else False

    job = WallJob()
    job.label       = label
    job.wall_id     = wall.Id.IntegerValue
    job.cs          = cs
    job.source_doc  = link_doc
    job.loc_curve   = loc_curve
    job.orientation = orientation
    job.total_width = wall.Width
    job.loc_line    = (wall.get_Parameter(
        BuiltInParameter.WALL_KEY_REF_PARAM).AsInteger()
        if wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM) else 0)
    job.loc_to_ext  = loc_to_ext
    job.base_z      = base_z
    job.top_z       = top_z
    job.structural  = structural
    job.bands       = []          # filled in by band_walls
    return job, notes_none()


def notes_none():
    """An empty note list, spelled out so plan_wall reads symmetrically."""
    return []


# ===========================================================================
# REPORTING
# ===========================================================================

def report(notes):
    """Print the notes table, or nothing when there is nothing to say."""
    if not notes:
        return
    output.print_md("### {} - {} note(s)".format(TOOL_TITLE, len(notes)))
    output.print_table(table_data=notes, columns=["Element", "Note"])


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    wall_picks, sweep_picks = pick_sources()
    if not wall_picks and not sweep_picks:
        return          # cancelled: create nothing, report nothing

    notes       = []
    sweep_jobs  = []
    wall_jobs   = []

    for link_inst, sweep in sweep_picks:
        job, job_notes = plan_sweep(link_inst, sweep)
        notes.extend(job_notes)
        if job is not None:
            sweep_jobs.append(job)

    for link_inst, wall in wall_picks:
        job, job_notes = plan_wall(link_inst, wall)
        notes.extend(job_notes)
        if job is not None:
            wall_jobs.append(job)

    # TEMPORARY diagnostic, replaced in Task 7 by the build.
    rows = []
    for job in sweep_jobs:
        rows.append([job.label,
                     "sweep {} to {} on {} wall(s), type '{}'".format(
                         feet_text(job.base_z), feet_text(job.top_z),
                         len(job.frames), job.type_name)])
    for job in wall_jobs:
        rows.append([job.label,
                     "wall {} to {}".format(
                         feet_text(job.base_z), feet_text(job.top_z))])
    output.print_md("### {} - measured".format(TOOL_TITLE))
    output.print_table(table_data=rows, columns=["Element", "Measured"])

    report(notes)


try:
    main()
except Exception as ex:
    logger.error("{} failed: {}".format(TOOL_TITLE, ex))
    output.print_md("**{} - unexpected error**".format(TOOL_TITLE))
    output.print_code(traceback.format_exc())
    forms.alert("Unexpected error:\n{}\n\nSee the output window for "
                "details.".format(ex), title=TOOL_TITLE)
```

- [ ] **Step 2: Register the button**

Replace `.../Walls.panel/bundle.yaml` with:

```yaml
layout:
  - WallConstraints
  - SplitWalls
  - SweepToWall
  - MultiWallCreationV1
  - WindowToCurtainWall
  - CurtainWallTrim
```

- [ ] **Step 3: Check it compiles**

Run: `python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"`
Expected: no output, exit 0.

- [ ] **Step 4: Verify in Revit**

Reload pyRevit. The **Multi Wall Creation V1** button appears in the Walls panel between Sweep To Wall and Window To Curtain Wall. Run it, pick two linked walls and a linked sweep that runs on one of them, press Esc. The output window lists all three with their measured elevations. Check by hand that the wall spans match those walls' Base/Top Constraints in the link, and that the sweep's elevations match where the sweep actually sits.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/bundle.yaml"
git commit -m "feat: add Multi Wall Creation V1 selection and measurement"
```

---

### Task 5: Wall type resolution

Every dialog the run needs, raised before any transaction opens.

**Files:**
- Modify: `.../Walls.panel/MultiWallCreationV1.pushbutton/script.py`

**Interfaces:**
- Consumes: `SweepJob`, `WallJob`, `note` (Task 4); `wall_bands.sweep_wall_type_name` (Task 2).
- Produces:
  - `find_wall_type_by_name(name)` → `WallType` or `None`.
  - `resolve_sweep_types(sweep_jobs, notes)` → `list[SweepJob]` — those with `wall_type` set; the rest are dropped with a note.
  - `skin_plan_key(cs, source_doc)` → hashable.
  - `collect_skin_plans(wall_jobs)` → `dict`.

- [ ] **Step 1: Add the functions**

Insert after the `plan_wall` / `notes_none` block, before `# REPORTING`:

```python
# ===========================================================================
# WALL TYPES
# ===========================================================================

def find_wall_type_by_name(name):
    """Return the host WallType named exactly *name*, or None."""
    from Autodesk.Revit.DB import WallType
    for wt in FilteredElementCollector(doc).OfClass(WallType):
        if get_element_name(wt) == name:
            return wt
    return None


def resolve_sweep_types(sweep_jobs, notes):
    """Give every sweep job a wall type, asking only where it must.

    The STONE / EIFS name rule answers most of them outright.  What it
    cannot read -- and any profile whose named type is missing from this
    model -- falls back to one dialog per sweep TYPE, so a run with
    twenty identical sweeps asks once.

    Returns the jobs that ended up with a type.  A sweep left without
    one is dropped: it neither becomes a wall nor cuts one, and it is
    reported.
    """
    asked = {}          # sweep type name -> WallType or None
    resolved = []

    for job in sweep_jobs:
        wanted = wall_bands.sweep_wall_type_name(job.type_name, job.material)

        if wanted is not None:
            wall_type = find_wall_type_by_name(wanted)
            if wall_type is not None:
                job.wall_type = wall_type
                resolved.append(job)
                continue
            note(notes, job.label,
                 "wall type '{}' is not in this model - asking "
                 "instead".format(wanted))

        key = job.type_name or "<unnamed sweep type>"
        if key not in asked:
            asked[key] = wall_materials.pick_skin_wall_type(
                doc,
                "Pick the wall type for sweep type '{}'".format(key),
                job.material or "<unknown>",
                wall_naming.feet_to_imperial(job.top_z - job.base_z))

        if asked[key] is None:
            note(notes, job.label,
                 "no wall type chosen for sweep type '{}' - skipped, and "
                 "it does not cut any wall".format(key))
            continue

        job.wall_type = asked[key]
        resolved.append(job)

    return resolved


def _material_of_layer(cs, layer_index, source_doc):
    """Return the Material element for a layer, or None.

    The material belongs to *source_doc*, which is the linked document.
    """
    try:
        mat_id = cs.GetMaterialId(layer_index)
    except Exception:
        return None
    if mat_id and mat_id != ElementId.InvalidElementId:
        return source_doc.GetElement(mat_id)
    return None


def skin_plan_key(cs, source_doc):
    """Key a wall by the SKIN type it needs, so each is resolved once.

    Walls whose finishes share a Mark share a wall type; a finish with
    no Mark falls back to its material name, so those are still only
    asked about once each.
    """
    source_mat = _material_of_layer(cs, 0, source_doc)
    mark       = wall_materials.material_mark(source_mat)
    if not mark:
        mark = "name:{}".format(
            wall_materials.element_name(source_mat) or "Unknown")
    return wall_materials.type_match_key(mark, cs.GetLayerWidth(0))


def collect_skin_plans(wall_jobs):
    """Resolve the SKIN wall type once per Mark across the selection.

    Returns {skin_plan_key: plan}.  Called before the transaction opens
    so the dialogs do not appear mid-transaction.
    """
    plans = {}
    for job in wall_jobs:
        key = skin_plan_key(job.cs, job.source_doc)
        if key in plans:
            continue
        plans[key] = wall_materials.plan_skin_wall_type(
            doc, _material_of_layer(job.cs, 0, job.source_doc),
            job.source_doc, job.cs.GetLayerWidth(0), TOOL_TITLE)
    return plans
```

- [ ] **Step 2: Call them from `main`**

In `main()`, after the two planning loops and before the temporary diagnostic, insert:

```python
    sweep_jobs = resolve_sweep_types(sweep_jobs, notes)
    skin_plans = collect_skin_plans(wall_jobs)
```

and extend the temporary diagnostic's sweep row to show the resolved type:

```python
    for job in sweep_jobs:
        rows.append([job.label,
                     "sweep {} to {} on {} wall(s), type '{}' -> {}".format(
                         feet_text(job.base_z), feet_text(job.top_z),
                         len(job.frames), job.type_name,
                         get_element_name(job.wall_type))])
```

and after building `rows`, add one line so the skin plans are visibly resolved:

```python
    rows.append(["-", "{} skin type plan(s) resolved".format(
        len(skin_plans))])
```

- [ ] **Step 3: Check it compiles**

Run: `python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"`
Expected: no output, exit 0.

- [ ] **Step 4: Verify in Revit**

Run the tool and pick, in one go: a sweep whose type or material name contains STONE, one containing EIFS, and one containing neither. Expected — no dialog for the first two, and the diagnostic shows them resolved to `SKIN_CAST STONE PROFILE_0' 2"` and `SKIN_EIFS PROFILE_0' 2"`; exactly one dialog for the third. Pick two more sweeps of that same unmatched type and confirm the dialog still appears only once. Cancel the dialog on a repeat run and confirm those sweeps are reported as skipped rather than the run failing.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"
git commit -m "feat: resolve sweep and skin wall types before the transaction"
```

---

### Task 6: Banding the walls

**Files:**
- Modify: `.../Walls.panel/MultiWallCreationV1.pushbutton/script.py`

**Interfaces:**
- Consumes: `WallJob`, `SweepJob`, `host_levels`, `note` (Task 4); `wall_bands.subtract_spans` (Task 1); `wall_constraints.plan_wall` (existing).
- Produces:
  - `band_walls(wall_jobs, sweep_jobs, levels, notes)` — fills each `WallJob.bands` with a list of `wall_constraints` band dicts (keys `base_level_id, base_offset, top_level_id, top_offset, height, base_z, top_z`).

- [ ] **Step 1: Add the function**

Insert after `collect_skin_plans`, before `# REPORTING`:

```python
# ===========================================================================
# BANDING
# ===========================================================================

def band_walls(wall_jobs, sweep_jobs, levels, notes):
    """Work out the bands each wall is cut into.

    Two things cut a wall.  The sweeps hosted on it, which come from the
    link's own GetHostIds() so a sweep on a neighbouring wall is never
    mistaken for one on this one; and every level a leftover stretch
    crosses, because a wall crossing a level is the one thing the house
    rule never allows.

    Nothing is rounded: wall_constraints.plan_wall is called with
    allow_round=False so a band end stays exactly on the sweep face or
    the level that produced it.  Rounding it to the nearest inch would
    open a gap between the band and the sweep wall above it.

    Fills job.bands in place.
    """
    for job in wall_jobs:
        cutters = [(s.base_z, s.top_z) for s in sweep_jobs
                   if job.wall_id in s.host_ids]

        gaps, dropped = wall_bands.subtract_spans(
            (job.base_z, job.top_z), cutters)

        for lo, hi in dropped:
            note(notes, job.label,
                 "sliver between sweeps at {} to {} is too thin to "
                 "build".format(feet_text(lo), feet_text(hi)))

        if not gaps:
            note(notes, job.label,
                 "sweeps cover the whole wall - nothing left to build")
            continue

        for lo, hi in gaps:
            try:
                plan = wall_constraints.plan_wall(
                    lo, hi, levels, allow_round=False)
            except ValueError as ex:
                note(notes, job.label,
                     "band {} to {}: {}".format(
                         feet_text(lo), feet_text(hi), ex))
                continue
            job.bands.extend(plan["bands"])

        if not job.bands:
            note(notes, job.label, "no band could be constrained")
```

- [ ] **Step 2: Call it from `main`**

In `main()`, after `skin_plans = collect_skin_plans(wall_jobs)`, insert:

```python
    levels = host_levels()
    if not levels:
        report(notes + [["-", "this model has no levels"]])
        return

    band_walls(wall_jobs, sweep_jobs, levels, notes)
```

and replace the temporary wall row in the diagnostic with:

```python
    for job in wall_jobs:
        for band in job.bands:
            rows.append([job.label,
                         "band {} to {}".format(
                             feet_text(band["base_z"]),
                             feet_text(band["top_z"]))])
```

- [ ] **Step 3: Check it compiles**

Run: `python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"`
Expected: no output, exit 0.

- [ ] **Step 4: Verify in Revit**

Pick one linked wall spanning two storeys with two sweeps on it, plus both sweeps. The diagnostic must list one band per gap, cut again at the level between them, with band elevations matching the sweeps' measured elevations exactly. Then run again picking the same wall but NO sweeps: exactly one band per storey, spanning the wall's full constraints. Then pick a wall and a sweep hosted on a DIFFERENT wall: the wall must come back uncut.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"
git commit -m "feat: cut wall spans at their sweeps and at every level crossed"
```

---

### Task 7: Building the walls

The diagnostic table goes; the transaction arrives. This is the task that makes the tool do its job.

**Files:**
- Modify: `.../Walls.panel/MultiWallCreationV1.pushbutton/script.py`

**Interfaces:**
- Consumes: everything from Tasks 4-6; `wall_chain.Segment`, `wall_chain.mitre_segments`; `wall_skin.skin_centreline`, `wall_skin.layer_group_widths`, `wall_skin.dist_loc_to_exterior`, `wall_skin.create_oriented_wall`; `wall_bands.elevation_group_key`; `wall_constraints.constraints_for`.
- Produces: nothing consumed elsewhere — this is the last task.

- [ ] **Step 1: Add the build functions**

Insert after `band_walls`, before `# REPORTING`:

```python
# ===========================================================================
# BUILDING
# ===========================================================================

def set_location_line(wall, value):
    """Set the Location Line parameter on *wall*."""
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
        if p and p.HasValue and not p.IsReadOnly:
            p.Set(value)
        doc.Regenerate()
    except Exception:
        pass


def set_bg_profile(wall, value):
    """Write *value* into the wall's BG_PROFILE parameter.

    Returns False when the parameter is absent, read-only, or not a text
    parameter -- the caller reports that rather than failing the wall,
    since the wall itself is correct either way.
    """
    p = find_parameter(wall, BG_PROFILE_PARAM)
    if p is None or p.IsReadOnly:
        return False
    try:
        return bool(p.Set(value))
    except Exception:
        return False


def apply_constraints(wall, band):
    """Bind *wall*'s base and top to the levels *band* names.

    The base level was already set at creation, so only the offset is
    written here; the top is bound outright, which is what turns an
    unconnected wall into one that follows its level.
    """
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
        if p and not p.IsReadOnly:
            p.Set(band["base_offset"])
    except Exception as ex:
        logger.debug("Could not set base offset: {}".format(ex))

    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
        if p and not p.IsReadOnly:
            p.Set(band["top_level_id"])
        p = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
        if p and not p.IsReadOnly:
            p.Set(band["top_offset"])
        doc.Regenerate()
    except Exception as ex:
        logger.debug("Could not bind top constraint: {}".format(ex))


def create_sweep_wall(curve, frame, wall_type, band):
    """Create one wall of a sweep's run and return it.

    *curve* is the new wall's CENTRELINE, worked out beforehand so its
    interior face lands on the host wall's exterior face.  Placing the
    centreline explicitly is what makes this dependable: relying on
    Revit's Location Line to shift the wall put the centreline on the
    host wall's face instead of the interior face.  Location Line is set
    to 'Finish Face: Interior' afterwards, which re-references the wall
    without moving it.
    """
    height   = band["height"]
    base_off = band["base_offset"]
    level_id = band["base_level_id"]

    wall = Wall.Create(doc, curve, wall_type.Id, level_id,
                       height, base_off, False, False)
    doc.Regenerate()

    set_location_line(wall, LOC_LINE_CENTRELINE)

    # Face the same way as the host wall, so 'interior' is the side
    # against it.  Reversing the curve keeps the same endpoints, so a
    # mitred corner survives the swap and the centreline does not move.
    try:
        if frame.normal.DotProduct(wall.Orientation) < 0:
            doc.Delete(wall.Id)
            doc.Regenerate()
            wall = Wall.Create(doc, curve.CreateReversed(), wall_type.Id,
                               level_id, height, base_off, False, False)
            doc.Regenerate()
            set_location_line(wall, LOC_LINE_CENTRELINE)
    except Exception:
        pass

    set_location_line(wall, LOC_LINE_FINISH_FACE_INTERIOR)
    apply_constraints(wall, band)
    return wall


def build_sweep_walls(sweep_jobs, levels, notes):
    """Create the walls for every measured sweep.  Inside a transaction.

    Mitring is per sweep: each sweep is its own run of walls, and its
    corners are closed against its own neighbours only.
    """
    for job in sweep_jobs:
        try:
            band = wall_constraints.constraints_for(
                job.base_z, job.top_z, levels)
        except ValueError as ex:
            note(notes, job.label, "could not constrain sweep: {}".format(ex))
            continue

        half = job.wall_type.Width / 2.0

        # Interior face of the new wall on the exterior face of the host,
        # so its centreline sits half a thickness further out again.
        segments = [wall_chain.Segment(frame, offset + half)
                    for frame, offset in zip(job.frames, job.offsets)]
        curves   = wall_chain.mitre_segments(segments)

        unwritten = 0
        for segment, curve in zip(segments, curves):
            label = get_element_name(segment.frame.wall.WallType)
            if curve is None:
                note(notes, label, "could not build a curve for this wall")
                continue
            try:
                wall = create_sweep_wall(
                    curve, segment.frame, job.wall_type, band)
            except Exception as ex:
                note(notes, label, "wall creation failed: {}".format(ex))
                continue

            if job.type_mark and not set_bg_profile(wall, job.type_mark):
                unwritten += 1

        if unwritten:
            note(notes, job.label,
                 "{} could not be written on {} wall(s) - parameter "
                 "missing, read-only, or not a text parameter".format(
                     BG_PROFILE_PARAM, unwritten))


def prepare_bands(wall_jobs, skin_plans, notes):
    """Work out a centreline and a type for every band, building nothing.

    Creation is deferred so that bands sharing an elevation can have
    their corners mitred against each other first.

    Returns [{"job", "band", "curve", "type"}].
    """
    prepared = []

    for job in wall_jobs:
        if not job.bands:
            continue

        key  = skin_plan_key(job.cs, job.source_doc)
        plan = skin_plans.get(key)
        if plan is None or plan.get("action") == "skip":
            note(notes, job.label,
                 plan.get("reason", "no wall type resolved")
                 if plan else "no wall type resolved")
            continue

        skin_type = wall_materials.execute_skin_wall_type_plan(
            doc, plan, _material_of_layer(job.cs, 0, job.source_doc),
            job.source_doc)
        if skin_type is None:
            note(notes, job.label, "no wall type resolved")
            continue

        first_core = job.cs.GetFirstCoreLayerIndex()
        last_core  = job.cs.GetLastCoreLayerIndex()
        skin_w, gap_w, core_w, _int_w, _ext = wall_skin.layer_group_widths(
            job.cs, first_core, last_core)

        if job.loc_to_ext is not None:
            d = job.loc_to_ext
        else:
            d = wall_skin.dist_loc_to_exterior(
                job.loc_line, job.total_width, skin_w, gap_w, core_w)

        curve = wall_skin.skin_centreline(
            job.loc_curve, job.orientation, d, skin_w)

        for band in job.bands:
            prepared.append({"job": job, "band": band,
                             "curve": curve, "type": skin_type})

    return prepared


def mitre_prepared(prepared):
    """Close the corners between bands that sit at the same elevation.

    Adjacency is judged on the ORIGINAL wall curves, which still share
    their endpoints; the corner point is where the two OFFSET lines
    cross.  Bands at different elevations are mitred separately -- two
    walls that never touch must not have a corner dragged between them.

    Curves are replaced in place inside *prepared*.
    """
    groups = {}
    for item in prepared:
        key = wall_bands.elevation_group_key(
            item["band"]["base_z"], item["band"]["top_z"])
        groups.setdefault(key, []).append(item)

    for items in groups.values():
        if len(items) < 2:
            continue

        originals = []
        offsets   = []
        zs        = []
        for item in items:
            oc = item["job"].loc_curve
            sc = item["curve"]
            o0, o1 = oc.GetEndPoint(0), oc.GetEndPoint(1)
            s0, s1 = sc.GetEndPoint(0), sc.GetEndPoint(1)
            originals.append(((o0.X, o0.Y), (o1.X, o1.Y)))
            offsets.append(((s0.X, s0.Y), (s1.X, s1.Y)))
            zs.append((s0.Z, s1.Z))

        from Tahir import wall_miter
        mitred = wall_miter.miter_chain(originals, offsets)

        for idx, item in enumerate(items):
            (x0, y0), (x1, y1) = mitred[idx]
            z0, z1 = zs[idx]
            item["curve"] = Line.CreateBound(XYZ(x0, y0, z0),
                                             XYZ(x1, y1, z1))


def build_bands(prepared, notes):
    """Create one skin wall per prepared band.  Inside a transaction."""
    for item in prepared:
        job  = item["job"]
        band = item["band"]
        try:
            wall = wall_skin.create_oriented_wall(
                doc, item["curve"], item["type"].Id,
                band["base_level_id"], band["height"],
                band["base_offset"], job.structural, job.orientation)
            apply_constraints(wall, band)
        except Exception as ex:
            note(notes, job.label,
                 "band {} to {} failed: {}".format(
                     feet_text(band["base_z"]), feet_text(band["top_z"]),
                     ex))
```

- [ ] **Step 2: Move the `wall_miter` import to the top**

The `from Tahir import wall_miter` inside `mitre_prepared` above is there only to keep that function readable in isolation. Delete that line and add `wall_miter` to the module-level Tahir import instead:

```python
from Tahir import (
    wall_bands,
    wall_chain,
    wall_constraints,
    wall_materials,
    wall_miter,
    wall_naming,
    wall_skin,
)
```

- [ ] **Step 3: Replace `main`**

Replace the whole of `main()` with:

```python
def main():
    wall_picks, sweep_picks = pick_sources()
    if not wall_picks and not sweep_picks:
        return          # cancelled: create nothing, report nothing

    notes      = []
    sweep_jobs = []
    wall_jobs  = []

    for link_inst, sweep in sweep_picks:
        job, job_notes = plan_sweep(link_inst, sweep)
        notes.extend(job_notes)
        if job is not None:
            sweep_jobs.append(job)

    for link_inst, wall in wall_picks:
        job, job_notes = plan_wall(link_inst, wall)
        notes.extend(job_notes)
        if job is not None:
            wall_jobs.append(job)

    if not sweep_jobs and not wall_jobs:
        report(notes)
        return

    levels = host_levels()
    if not levels:
        report(notes + [["-", "this model has no levels"]])
        return

    # Every dialog happens here, before the transaction opens.
    sweep_jobs = resolve_sweep_types(sweep_jobs, notes)
    skin_plans = collect_skin_plans(wall_jobs)

    band_walls(wall_jobs, sweep_jobs, levels, notes)

    t = Transaction(doc, "Multi Wall Creation")
    t.Start()
    try:
        build_sweep_walls(sweep_jobs, levels, notes)

        prepared = prepare_bands(wall_jobs, skin_plans, notes)
        mitre_prepared(prepared)
        build_bands(prepared, notes)

        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    # Silence on success: only problems open the output window.
    report(notes)
```

- [ ] **Step 4: Check it compiles and the diagnostic is gone**

```bash
python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"
grep -n "TEMPORARY\|- measured" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"
```

Expected: `py_compile` silent and exit 0; `grep` finds nothing and exits 1.

- [ ] **Step 5: Verify in Revit**

Run against a linked model and check each of these:

1. **The main case.** A wall spanning two storeys with a stone sweep part-way up, all three picked. Result: a sweep wall at the sweep's exact elevations in `SKIN_CAST STONE PROFILE_0' 2"`, skin walls below and above it, and a further cut at the level between. Section-cut it and confirm no gaps and no overlaps at any junction.
2. **Constraints.** Select each new wall. Every one has a Base Constraint with an offset and a Top Constraint with an offset — none is left with an unconnected height.
3. **Corners.** Two linked walls meeting at a corner, both picked with the same sweep running round them. The sweep walls mitre; the skin bands mitre with the band at their own elevation and not with any other.
4. **Fallback.** A wall picked with no sweeps: skin walls spanning its own constraints, cut only at levels.
5. **Plan position.** The skin wall's outer face sits on the source wall's exterior face; the sweep wall stands proud of it. Both are what the two source tools already produce.
6. **BG_PROFILE.** Each sweep wall carries its sweep type's Type Mark.
7. **Silence.** A clean run opens no output window at all.
8. **The link is untouched.** Nothing in the linked model changed.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS. Nothing in this task touches the pure modules, so this is a regression check.

- [ ] **Step 7: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"
git commit -m "feat: build sweep walls and banded skin walls in one transaction"
```

---

## Notes for the executor

- **`plan_wall` is a name used twice**, deliberately: `wall_constraints.plan_wall` is the level-banding arithmetic, and the pushbutton's own `plan_wall` measures one linked wall. They are always called module-qualified or bare respectively; do not rename either.
- **Do not add rounding.** If a band end looks like an awkward number, that is correct — it is the face of a sweep.
- **Do not widen sweep matching.** `GetHostIds()` only. Plan-proximity matching was considered and rejected during design.
- **`Tahir.wall_bands` must stay importable in CPython.** If a task tempts you to import `Autodesk.Revit` there, the logic belongs in the pushbutton instead.
