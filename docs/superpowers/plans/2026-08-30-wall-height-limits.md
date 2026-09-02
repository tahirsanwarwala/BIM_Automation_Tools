# Visual Base/Top Limits for SKIN Walls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users set the base and top of generated SKIN walls by clicking reference elements in an elevation/section view, instead of inheriting heights from the source wall.

**Architecture:** All height arithmetic lives in a new Revit-free module `lib/Tahir/wall_limits.py`, unit-tested under CPython. The pushbutton script keeps only Revit API glue: a view gate, two reference picks (each preceded by a linked-vs-host mode switch), conversion of Revit objects into plain tuples for the math module, and application of the resulting constraints.

**Tech Stack:** IronPython/CPython under pyRevit, Autodesk Revit API, stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-30-wall-height-limits-design.md`

## Global Constraints

- `lib/Tahir/wall_limits.py` MUST NOT import `clr`, `Autodesk.*`, `pyrevit`, or `numpy`. It is imported by both Revit (IronPython) and the test suite (CPython 3.13).
- Write Python 2/3 compatible code in `wall_limits.py`: no f-strings, no type annotations, no walrus. Match the existing `# -*- coding: utf-8 -*-` header style.
- Level-match tolerance is `1/16"` = `0.0052083333` feet, defined once as `TOL_LEVEL_MATCH`.
- All elevations are in decimal feet, host-model world coordinates.
- All interactive picking happens BEFORE `Transaction.Start()`. Revit forbids selection inside an open transaction.
- Run tests from the repo root: `C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools`.

---

### Task 1: Pure limit-math module

**Files:**
- Create: `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_limits.py`
- Test: `tests/test_wall_limits.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TOL_LEVEL_MATCH` → float
  - `transform_bbox_z_range(bbox_min, bbox_max, transform=None)` → `(min_z, max_z)`; points are `(x,y,z)` tuples; `transform` is `None` or `(basis_x, basis_y, basis_z, origin)` of four `(x,y,z)` tuples
  - `pick_extreme_z(min_z, max_z, click_z)` → float
  - `match_level_by_elevation(elevation, levels, tol=TOL_LEVEL_MATCH)` → level id or `None`; `levels` is a list of `(level_id, elevation)`
  - `nearest_level_at_or_below(elevation, levels, tol=TOL_LEVEL_MATCH)` → `(level_id, elevation)` or `None`
  - `compute_wall_limits(base_elev, base_level_id, top_elev, top_level_id, levels)` → dict with keys `base_level_id`, `base_offset`, `top_level_id`, `top_offset`, `height`; raises `ValueError`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wall_limits.py`:

```python
# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from Tahir import wall_limits as wl


class TestTransformBboxZRange(unittest.TestCase):

    def test_no_transform_returns_plain_z_range(self):
        lo, hi = wl.transform_bbox_z_range((0.0, 0.0, 3.0), (2.0, 4.0, 9.0))
        self.assertAlmostEqual(lo, 3.0)
        self.assertAlmostEqual(hi, 9.0)

    def test_pure_translation_shifts_range(self):
        tf = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (5.0, 5.0, 10.0))
        lo, hi = wl.transform_bbox_z_range((0.0, 0.0, 3.0), (2.0, 4.0, 9.0), tf)
        self.assertAlmostEqual(lo, 13.0)
        self.assertAlmostEqual(hi, 19.0)

    def test_rotation_about_z_leaves_z_untouched(self):
        # 90 deg about Z: x -> y, y -> -x
        tf = ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
        lo, hi = wl.transform_bbox_z_range((0.0, 0.0, 3.0), (2.0, 4.0, 9.0), tf)
        self.assertAlmostEqual(lo, 3.0)
        self.assertAlmostEqual(hi, 9.0)

    def test_rotation_about_x_uses_all_eight_corners(self):
        # 90 deg about X: world_z becomes local y, so z-range comes from y-range.
        # A naive min/max-only implementation would wrongly return (3.0, 9.0).
        tf = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0), (0.0, 0.0, 0.0))
        lo, hi = wl.transform_bbox_z_range((0.0, 0.0, 3.0), (2.0, 4.0, 9.0), tf)
        self.assertAlmostEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 4.0)


class TestPickExtremeZ(unittest.TestCase):

    def test_click_high_returns_top(self):
        self.assertAlmostEqual(wl.pick_extreme_z(10.0, 20.0, 18.0), 20.0)

    def test_click_low_returns_bottom(self):
        self.assertAlmostEqual(wl.pick_extreme_z(10.0, 20.0, 12.0), 10.0)

    def test_click_exactly_mid_returns_top(self):
        self.assertAlmostEqual(wl.pick_extreme_z(10.0, 20.0, 15.0), 20.0)


class TestMatchLevelByElevation(unittest.TestCase):

    LEVELS = [("L4", 995.0), ("L5", 1013.0), ("L6", 1031.0)]

    def test_exact_match(self):
        self.assertEqual(wl.match_level_by_elevation(1013.0, self.LEVELS), "L5")

    def test_within_tolerance_matches(self):
        self.assertEqual(
            wl.match_level_by_elevation(1013.0 + 0.004, self.LEVELS), "L5")

    def test_outside_tolerance_returns_none(self):
        self.assertIsNone(wl.match_level_by_elevation(1013.5, self.LEVELS))

    def test_picks_closest_when_two_are_in_range(self):
        levels = [("A", 100.0), ("B", 100.004)]
        self.assertEqual(wl.match_level_by_elevation(100.0039, levels), "B")


class TestNearestLevelAtOrBelow(unittest.TestCase):

    LEVELS = [("L4", 995.0), ("L5", 1013.0), ("L6", 1031.0)]

    def test_returns_highest_level_below(self):
        self.assertEqual(
            wl.nearest_level_at_or_below(1020.0, self.LEVELS), ("L5", 1013.0))

    def test_exactly_on_a_level_returns_that_level(self):
        self.assertEqual(
            wl.nearest_level_at_or_below(1013.0, self.LEVELS), ("L5", 1013.0))

    def test_below_all_levels_returns_none(self):
        self.assertIsNone(wl.nearest_level_at_or_below(900.0, self.LEVELS))


class TestComputeWallLimits(unittest.TestCase):

    LEVELS = [("L4", 995.0), ("L5", 1013.0), ("L6", 1031.0)]

    def test_both_levels_bind_with_zero_offsets(self):
        r = wl.compute_wall_limits(995.0, "L4", 1013.0, "L5", self.LEVELS)
        self.assertEqual(r["base_level_id"], "L4")
        self.assertAlmostEqual(r["base_offset"], 0.0)
        self.assertEqual(r["top_level_id"], "L5")
        self.assertAlmostEqual(r["top_offset"], 0.0)
        self.assertAlmostEqual(r["height"], 18.0)

    def test_non_level_base_and_top_bakes_offset_and_height(self):
        r = wl.compute_wall_limits(1000.0, None, 1020.0, None, self.LEVELS)
        self.assertEqual(r["base_level_id"], "L4")
        self.assertAlmostEqual(r["base_offset"], 5.0)
        self.assertIsNone(r["top_level_id"])
        self.assertAlmostEqual(r["height"], 20.0)

    def test_level_base_with_non_level_top_measures_from_level(self):
        r = wl.compute_wall_limits(995.0, "L4", 1020.0, None, self.LEVELS)
        self.assertEqual(r["base_level_id"], "L4")
        self.assertAlmostEqual(r["base_offset"], 0.0)
        self.assertAlmostEqual(r["height"], 25.0)

    def test_height_is_always_positive_for_level_bound_top(self):
        r = wl.compute_wall_limits(1000.0, None, 1013.0, "L5", self.LEVELS)
        self.assertGreater(r["height"], 0.0)

    def test_top_below_base_raises(self):
        with self.assertRaises(ValueError):
            wl.compute_wall_limits(1020.0, None, 1000.0, None, self.LEVELS)

    def test_top_equal_to_base_raises(self):
        with self.assertRaises(ValueError):
            wl.compute_wall_limits(1000.0, None, 1000.0, None, self.LEVELS)

    def test_no_level_below_base_raises(self):
        with self.assertRaises(ValueError):
            wl.compute_wall_limits(900.0, None, 950.0, None, self.LEVELS)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Tahir.wall_limits'`

- [ ] **Step 3: Write minimal implementation**

Create `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_limits.py`:

```python
# -*- coding: utf-8 -*-
"""Pure height/limit arithmetic for the SplitWalls tool.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.  The pushbutton script converts Revit objects into the plain
tuples these functions expect.

Coordinates are decimal feet in host-model world space.
"""

# 1/16 inch, expressed in feet
TOL_LEVEL_MATCH = 0.0052083333


def _apply(transform, pt):
    """Apply a (basis_x, basis_y, basis_z, origin) transform to an (x,y,z)."""
    if transform is None:
        return pt

    bx, by, bz, origin = transform
    x, y, z = pt
    return (
        origin[0] + bx[0] * x + by[0] * y + bz[0] * z,
        origin[1] + bx[1] * x + by[1] * y + bz[1] * z,
        origin[2] + bx[2] * x + by[2] * y + bz[2] * z,
    )


def transform_bbox_z_range(bbox_min, bbox_max, transform=None):
    """Return (min_z, max_z) of a bounding box after *transform*.

    All eight corners are transformed rather than just the min/max point,
    so rotated link transforms give the correct vertical extent.
    """
    world_zs = []
    for x in (bbox_min[0], bbox_max[0]):
        for y in (bbox_min[1], bbox_max[1]):
            for z in (bbox_min[2], bbox_max[2]):
                world_zs.append(_apply(transform, (x, y, z))[2])
    return min(world_zs), max(world_zs)


def pick_extreme_z(min_z, max_z, click_z):
    """Choose the top or bottom of a vertical range based on where the
    user clicked.  A click at or above mid-height selects the top.
    """
    mid = (min_z + max_z) / 2.0
    if click_z >= mid:
        return max_z
    return min_z


def match_level_by_elevation(elevation, levels, tol=TOL_LEVEL_MATCH):
    """Return the id of the level closest to *elevation* within *tol*.

    *levels* is a sequence of (level_id, elevation).  Returns None when
    nothing is close enough.
    """
    best_id = None
    best_d = None
    for lvl_id, lvl_elev in levels:
        d = abs(lvl_elev - elevation)
        if d <= tol and (best_d is None or d < best_d):
            best_d = d
            best_id = lvl_id
    return best_id


def nearest_level_at_or_below(elevation, levels, tol=TOL_LEVEL_MATCH):
    """Return (level_id, elevation) of the highest level at or below
    *elevation*, or None when every level sits above it.
    """
    best = None
    for lvl_id, lvl_elev in levels:
        if lvl_elev <= elevation + tol:
            if best is None or lvl_elev > best[1]:
                best = (lvl_id, lvl_elev)
    return best


def compute_wall_limits(base_elev, base_level_id, top_elev, top_level_id,
                        levels):
    """Turn two picked elevations into Revit wall constraints.

    *base_level_id* / *top_level_id* are host Level ids when the pick
    resolved to a bindable level, otherwise None.

    Returns a dict:
        base_level_id  host Level to host the wall (always set)
        base_offset    offset from that level, feet
        top_level_id   host Level for "Up to level", or None
        top_offset     offset from the top level, feet
        height         unconnected height, feet -- also used as the
                       creation seed when the top is level-bound

    Raises ValueError when the limits cannot produce a valid wall.
    """
    if top_elev <= base_elev:
        raise ValueError(
            "Top limit must be above the base limit "
            "(base {0:.4f}, top {1:.4f})".format(base_elev, top_elev))

    elev_by_id = dict(levels)

    if base_level_id is not None:
        base_lvl = base_level_id
        base_off = 0.0
        # Binding wins over the picked elevation; see the spec note on
        # absorbing the match tolerance.
        eff_base = elev_by_id[base_level_id]
    else:
        found = nearest_level_at_or_below(base_elev, levels)
        if found is None:
            raise ValueError(
                "No level at or below the base limit "
                "({0:.4f})".format(base_elev))
        base_lvl, lvl_elev = found
        base_off = base_elev - lvl_elev
        eff_base = base_elev

    return {
        "base_level_id": base_lvl,
        "base_offset": base_off,
        "top_level_id": top_level_id,
        "top_offset": 0.0,
        "height": top_elev - eff_base,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: PASS — 21 tests, `OK`

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/Tahir/wall_limits.py" tests/test_wall_limits.py
git commit -m "feat: add pure wall limit arithmetic module with tests"
```

---

### Task 2: View gate and reference picking

**Files:**
- Modify: `Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py`

**Interfaces:**
- Consumes: `Tahir.wall_limits` (`transform_bbox_z_range`, `pick_extreme_z`, `match_level_by_elevation`)
- Produces:
  - `PickedLimit` class with attributes `elevation` (float), `level_id` (ElementId or None), `label` (str)
  - `ensure_elevation_view()` → bool
  - `host_levels_as_tuples()` → list of `(ElementId, float)`
  - `pick_limit(what)` → `PickedLimit` or `None` (None = user cancelled); `what` is `"BASE"` or `"TOP"`

This task is Revit-dependent and cannot be unit-tested; it is verified by the manual runs in Task 4. Keep it free of arithmetic — all math belongs in `wall_limits`.

- [ ] **Step 1: Extend the imports**

In the `from Autodesk.Revit.DB import (...)` block, add `ViewType` in alphabetical position (after `Transform`, before `Wall`):

```python
    Transform,
    ViewDetailLevel,
    ViewType,
    Wall,
```

Add below the existing `from System.Collections.Generic import ...` line:

```python
from Tahir import wall_limits
```

- [ ] **Step 2: Add the view gate and level helper**

Insert immediately after the `get_element_name()` function:

```python
ALLOWED_LIMIT_VIEWS = (ViewType.Elevation, ViewType.Section)


def ensure_elevation_view():
    """Return True when the active view allows picking vertical limits."""
    view = doc.ActiveView
    if view is None or view.ViewType not in ALLOWED_LIMIT_VIEWS:
        forms.alert(
            "Base and top limits are picked visually, so this tool must be "
            "run from an elevation or section view.\n\n"
            "Open an elevation or section, then run it again.",
            title="Split Walls – Wrong View",
        )
        return False
    return True


def host_levels_as_tuples():
    """Return [(ElementId, elevation)] for every Level in the host doc."""
    return [(lvl.Id, lvl.Elevation)
            for lvl in FilteredElementCollector(doc).OfClass(Level)]


def _tf_tuple(tf):
    """Convert a Revit Transform into the plain tuple form wall_limits wants."""
    if tf is None:
        return None
    return (
        (tf.BasisX.X, tf.BasisX.Y, tf.BasisX.Z),
        (tf.BasisY.X, tf.BasisY.Y, tf.BasisY.Z),
        (tf.BasisZ.X, tf.BasisZ.Y, tf.BasisZ.Z),
        (tf.Origin.X, tf.Origin.Y, tf.Origin.Z),
    )
```

- [ ] **Step 3: Add the pick filters and PickedLimit**

Insert after the `LinkedWallFilter` class:

```python
class AnyHostElementFilter(ISelectionFilter):
    """Allow any element in the host model (levels included)."""

    def AllowElement(self, elem):
        return True

    def AllowReference(self, ref, point):
        return False


class AnyLinkedElementFilter(ISelectionFilter):
    """Allow any element inside a RevitLinkInstance."""

    def AllowElement(self, elem):
        return isinstance(elem, RevitLinkInstance)

    def AllowReference(self, ref, point):
        return True


class PickedLimit(object):
    """One resolved vertical limit."""

    __slots__ = ("elevation", "level_id", "label")

    def __init__(self, elevation, level_id, label):
        self.elevation = elevation
        self.level_id  = level_id
        self.label     = label
```

- [ ] **Step 4: Add the pick + resolve routine**

Insert after `PickedLimit`:

```python
def _resolve_level(level_elem, link_tf_tuple, host_levels):
    """Return (elevation, host_level_id) for a picked Level."""
    raw_elev = level_elem.Elevation

    if link_tf_tuple is None:
        return raw_elev, level_elem.Id

    # Linked level: move its elevation into host coordinates, then try to
    # bind it to a host level of the same height.
    lo, _hi = wall_limits.transform_bbox_z_range(
        (0.0, 0.0, raw_elev), (0.0, 0.0, raw_elev), link_tf_tuple)
    matched = wall_limits.match_level_by_elevation(lo, host_levels)
    return lo, matched


def _resolve_solid_element(elem, link_tf_tuple, click_z):
    """Return (elevation, is_top) for *elem*, picking whichever of its top
    or bottom the user clicked nearer to.  Returns None when the element
    has no bounding box.
    """
    bbox = elem.get_BoundingBox(None)
    if bbox is None:
        return None

    lo, hi = wall_limits.transform_bbox_z_range(
        (bbox.Min.X, bbox.Min.Y, bbox.Min.Z),
        (bbox.Max.X, bbox.Max.Y, bbox.Max.Z),
        link_tf_tuple,
    )
    elev = wall_limits.pick_extreme_z(lo, hi, click_z)
    return elev, (elev == hi)


def pick_limit(what):
    """Ask the user to pick one vertical reference.

    *what* is "BASE" or "TOP", used only in prompts.
    Returns a PickedLimit, or None when the user cancels.
    """
    mode = forms.CommandSwitchWindow.show(
        ["Linked element", "Host element or Level"],
        message="Pick the {} limit from:".format(what),
    )
    if not mode:
        return None

    host_levels = host_levels_as_tuples()

    try:
        if mode == "Linked element":
            ref = uidoc.Selection.PickObject(
                ObjectType.LinkedElement,
                AnyLinkedElementFilter(),
                "Click the element marking the {} limit".format(what),
            )
            link_inst  = doc.GetElement(ref.ElementId)
            linked_doc = link_inst.GetLinkDocument()
            if linked_doc is None:
                forms.alert("That link is not loaded.",
                            title="Split Walls – Pick Failed")
                return None
            elem     = linked_doc.GetElement(ref.LinkedElementId)
            tf_tuple = _tf_tuple(link_inst.GetTotalTransform())
        else:
            ref = uidoc.Selection.PickObject(
                ObjectType.Element,
                AnyHostElementFilter(),
                "Click the element marking the {} limit".format(what),
            )
            elem     = doc.GetElement(ref.ElementId)
            tf_tuple = None
    except Exception:
        return None  # Esc

    if elem is None:
        return None

    if isinstance(elem, Level):
        elev, level_id = _resolve_level(elem, tf_tuple, host_levels)
        return PickedLimit(
            elev, level_id, "Level '{}'".format(get_element_name(elem)))

    click_z  = ref.GlobalPoint.Z
    resolved = _resolve_solid_element(elem, tf_tuple, click_z)
    if resolved is None:
        forms.alert(
            "That element has no geometry to measure. Pick another.",
            title="Split Walls – Pick Failed",
        )
        return None

    elev, is_top = resolved
    which = "top" if is_top else "bottom"
    return PickedLimit(
        elev, None,
        "{} of {}".format(which, get_element_name(elem)))
```

- [ ] **Step 5: Verify the script still parses**

Run:
```bash
python -c "import ast; ast.parse(open(r'Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py', encoding='utf-8').read()); print('SYNTAX OK')"
```
Expected: `SYNTAX OK`

- [ ] **Step 6: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py"
git commit -m "feat: add elevation view gate and limit reference picking"
```

---

### Task 3: Apply limits during wall creation

**Files:**
- Modify: `Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py`

**Interfaces:**
- Consumes: the `limits` dict from `wall_limits.compute_wall_limits()` (keys `base_level_id`, `base_offset`, `top_level_id`, `top_offset`, `height`)
- Produces: `split_wall(wd, limits)` — note the added second parameter

- [ ] **Step 1: Strip height parameters from the instance-parameter copy**

In `copy_instance_params()`, replace the `bip_list` assignment. These three would overwrite the limits the user just picked:

```python
    # NOTE: WALL_BASE_OFFSET, WALL_USER_HEIGHT_PARAM and WALL_HEIGHT_TYPE are
    # deliberately NOT copied -- the new wall's vertical extent comes from the
    # limits the user picked, and copying them would silently overwrite it.
    bip_list = [
        BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT,
    ]
```

- [ ] **Step 2: Apply the limits in split_wall**

Change the `split_wall` signature and its level check. Replace:

```python
def split_wall(wd):
```

with:

```python
def split_wall(wd, limits):
```

Then replace this block:

```python
    if wd.level_id is None or wd.level_id == ElementId.InvalidElementId:
        return False, "Could not find a matching level in the host model"
```

with:

```python
    if limits["base_level_id"] == ElementId.InvalidElementId:
        return False, "No valid host level to host the new wall"
```

- [ ] **Step 3: Create the wall from the limits**

Replace the wall-creation block:

```python
    skin_wall = create_oriented_wall(
        skin_curve, skin_type.Id, wd.level_id,
        wd.height, wd.base_off, wd.structural, wd.orientation,
    )
```

with:

```python
    skin_wall = create_oriented_wall(
        skin_curve, skin_type.Id, limits["base_level_id"],
        limits["height"], limits["base_offset"],
        wd.structural, wd.orientation,
    )

    # Bind the top to a level when the user picked one, so the wall follows it.
    if limits["top_level_id"] is not None:
        try:
            tp = skin_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
            if tp and not tp.IsReadOnly:
                tp.Set(limits["top_level_id"])
            op = skin_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
            if op and not op.IsReadOnly:
                op.Set(limits["top_offset"])
            doc.Regenerate()
        except Exception as ex:
            logger.debug("Could not bind top constraint: {}".format(ex))
```

- [ ] **Step 4: Verify the script still parses**

Run:
```bash
python -c "import ast; ast.parse(open(r'Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py', encoding='utf-8').read()); print('SYNTAX OK')"
```
Expected: `SYNTAX OK`

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py"
git commit -m "feat: apply picked base/top limits to created SKIN walls"
```

---

### Task 4: Wire up main(), confirmation, and end-to-end verification

**Files:**
- Modify: `Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py`

**Interfaces:**
- Consumes: `ensure_elevation_view()`, `pick_limit()`, `host_levels_as_tuples()`, `wall_limits.compute_wall_limits()`, `split_wall(wd, limits)`

- [ ] **Step 1: Rewrite main()**

Replace the whole `main()` function with:

```python
def main():
    if not ensure_elevation_view():
        script.exit()

    wall_data_list = get_walls()
    if not wall_data_list:
        script.exit()

    # ── Pick the vertical limits (must happen outside the transaction) ──
    base_pick = pick_limit("BASE")
    if base_pick is None:
        script.exit()

    top_pick = pick_limit("TOP")
    if top_pick is None:
        script.exit()

    try:
        limits = wall_limits.compute_wall_limits(
            base_pick.elevation, base_pick.level_id,
            top_pick.elevation,  top_pick.level_id,
            host_levels_as_tuples(),
        )
    except ValueError as ex:
        forms.alert(str(ex), title="Split Walls – Invalid Limits")
        return

    # ── Confirm before creating anything ───────────────────────────────
    if limits["top_level_id"] is not None:
        top_desc = "bound to {}".format(top_pick.label)
    else:
        top_desc = "unconnected height {}".format(
            feet_to_imperial(limits["height"]))

    confirmed = forms.alert(
        "Base:  {}   ({})\n"
        "Top:   {}   ({})\n\n"
        "Height: {}\n"
        "Walls to create: {}".format(
            base_pick.label, feet_to_imperial(base_pick.elevation),
            top_pick.label,  feet_to_imperial(top_pick.elevation),
            feet_to_imperial(limits["height"]),
            len(wall_data_list),
        ),
        title="Split Walls – Confirm Limits",
        ok=False, yes=True, no=True,
    )
    if not confirmed:
        return

    ok_list   = []
    fail_list = []

    with Transaction(doc, "Create SKIN Walls") as t:
        t.Start()
        try:
            for wd in wall_data_list:
                try:
                    success, msg = split_wall(wd, limits)
                    if success:
                        ok_list.append(msg)
                    else:
                        fail_list.append("{}: {}".format(wd.source_label, msg))
                except Exception as ex:
                    fail_list.append("{}: {}".format(wd.source_label, str(ex)))
            t.Commit()
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            forms.alert(
                "Transaction failed:\n{}".format(str(ex)),
                title="Split Walls – Error",
            )
            return

    # ── Report results ─────────────────────────────────────────────────
    lines = []
    if ok_list:
        lines.append("Created {} SKIN wall(s):".format(len(ok_list)))
        lines.append("  Base: {}".format(base_pick.label))
        lines.append("  Top:  {}".format(top_desc))
        for m in ok_list:
            lines.append("  - {}".format(m))

    if fail_list:
        if lines:
            lines.append("")
        lines.append("Failed on {} wall(s):".format(len(fail_list)))
        for m in fail_list:
            lines.append("  - {}".format(m))

    if lines:
        forms.alert("\n".join(lines), title="Create SKIN Walls – Results")
```

- [ ] **Step 2: Update the module docstring**

Replace the `__doc__` assignment with:

```python
__doc__    = (
    "Run from an ELEVATION or SECTION view.\n"
    "Select one or more compound walls (host OR linked model), then click\n"
    "the elements marking the base and top of the new walls.\n"
    "For each wall a single SKIN wall is created:\n"
    "- SKIN wall: Outermost exterior finish layer only\n"
    "New walls are created in the HOST model, positioned so their outer\n"
    "face matches the original wall's exterior face, spanning between the\n"
    "two limits you picked.\n"
    "The original wall is left untouched (host and linked alike)."
)
```

- [ ] **Step 3: Verify parse and check for dangling references**

Run:
```bash
python -c "
import ast
src = open(r'Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py', encoding='utf-8').read()
tree = ast.parse(src); print('SYNTAX OK')
defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
imported = set()
for n in ast.walk(tree):
    if isinstance(n, (ast.Import, ast.ImportFrom)):
        for a in n.names: imported.add(a.asname or a.name.split('.')[0])
called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
import builtins
print('unresolved:', sorted(called - defined - imported - set(dir(builtins))) or 'NONE')
print('split_wall(wd) leftovers:', src.count('split_wall(wd)'))
"
```
Expected: `SYNTAX OK`, `unresolved: NONE`, `split_wall(wd) leftovers: 0`

- [ ] **Step 4: Re-run the unit tests**

Run: `python -m unittest discover -s tests -v`
Expected: PASS — 21 tests, `OK`

- [ ] **Step 5: Manual verification in Revit**

These cannot be automated. Work through each and record the result:

1. Run from a **plan view** → blocked with the wrong-view message, nothing created.
2. Run from an elevation. Select a linked wall. Base = *top of the wall below* (Linked element mode, click near its top). Top = *Level 05 datum* (Host element or Level mode).
   Expect: confirmation shows both elevations; created wall spans exactly between them; its **Top Constraint reads "Up to level: LEVEL 05"**.
3. Base = host Level 04, top = host Level 05 → both constraints bound, both offsets `0'`.
4. Base and top both non-level references → correct unconnected height, base offset measured from the nearest level below.
5. Press **Esc** at the mode switch, at the base pick, and at the top pick → nothing created, no error dialog.
6. Answer **No** at the confirmation → nothing created.
7. Pick top *below* base → "Top limit must be above the base limit", nothing created.
8. Select **three** walls at once → all three share identical base and top.

**If step 2 shows the wrong end of the element** (top when you clicked the bottom, or vice versa), `Reference.GlobalPoint` is not being populated for linked picks — the risk flagged in the spec. Report it rather than guessing; the fix is an explicit "top or bottom?" prompt, which is a contained change to `pick_limit()`.

- [ ] **Step 6: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py"
git commit -m "feat: pick base and top limits visually in elevation views"
```

---

## Notes for the executor

- `WallData.height`, `.base_off` and `.level_id` stay populated but are no longer read during creation. Leave them; they are harmless and useful if a source-height fallback is ever wanted.
- `_dist_loc_to_exterior()` remains as the fallback path for `compute_skin_curve()` when solid geometry cannot be read. Do not delete it.
- `get_or_create_ext_type()`, `compute_ext_type_name()` and `get_or_create_ext_material()` are already dead code from the earlier SKIN-only change. Out of scope here — leave them alone.
- `forms.alert(..., yes=True, no=True)` returns True only for Yes, which is what the confirmation gate relies on.
