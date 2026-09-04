# Multi Wall Creation V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second pushbutton that does everything Multi Wall Creation V1 does, then puts the openings back — every window in a picked linked wall becomes a curtain wall on the new skin wall, and every rectangular `Opening` is cut out of the skin's elevation.

**Architecture:** V1's script is COPIED to a new pushbutton and V1 is never edited — it is in daily use. The machinery V2 needs from `WindowToCurtainWall` and `CurtainWallTrim` is extracted into two library modules instead of being copied a second time; both extractions are behaviour-preserving moves of the kind `Tahir.wall_skin` already was. Only one genuinely new pure function is written, and it is unit-tested.

**Tech Stack:** IronPython 3 / pyRevit for Revit 2025, Revit API (`Autodesk.Revit.DB`), CPython `unittest` for the pure modules.

**Spec:** `docs/superpowers/specs/2026-09-05-multi-wall-creation-v2-design.md`

## Global Constraints

- Target Revit 2025 via pyRevit. Scripts run under IronPython 3 — **no f-strings**; use `.format()`, matching every existing script.
- Every file starts with `# -*- coding: utf-8 -*-`.
- Modules under `lib/Tahir/` named `wall_bands.py`, `wall_limits.py`, `wall_constraints.py`, `wall_miter.py`, `wall_naming.py` MUST NOT import anything from `Autodesk.Revit` — they are unit-tested outside Revit. `wall_sketch.py`, `window_cw.py`, `wall_skin.py` and `wall_chain.py` ARE Revit-facing and may.
- Units are decimal feet. Tolerance is `wall_bands.TOL` = 1/16 inch. Do not introduce another.
- The linked model is NEVER modified.
- Reporting is silent on success; failures print one table with columns `["Element", "Note"]`.
- All Revit dialogs are raised BEFORE the transaction opens.
- **`MultiWallCreationV1.pushbutton/script.py` MUST NOT be edited by any task in this plan.**
- **Arched heads are not traced.** An arched window gets a rectangle tall enough to cover the arch. Do not reinstate head tracing.
- The runner is `python -m unittest discover -s tests` (pytest is NOT installed). The suite stands at **229 tests, all passing**, before this plan starts.
- Beyond `py_compile`, every task runs the undefined-name AST pass described in Task 1 Step 2. IronPython gives no other way to catch a NameError before the user does.

---

## File Structure

| Path | Responsibility |
|---|---|
| `lib/Tahir/wall_sketch.py` | **Create.** Revit-facing wall elevation profile editing, moved from `CurtainWallTrim` and `WindowToCurtainWall`. |
| `.../CurtainWallTrim.pushbutton/script.py` | **Modify.** Delete its profile machinery; import from `wall_sketch`. |
| `.../WindowToCurtainWall.pushbutton/script.py` | **Modify.** Delete its profile machinery and its whole window path; import from `wall_sketch` and `window_cw`. |
| `lib/Tahir/window_cw.py` | **Create.** Everything needed to turn a linked WINDOW into a curtain wall on a given host wall. |
| `lib/Tahir/wall_bands.py` | **Modify.** Add `cutters_clear_of_windows`. |
| `tests/test_wall_bands.py` | **Modify.** Tests for it. |
| `.../MultiWallCreationV2.pushbutton/script.py` | **Create.** V1 copied, plus the three additions. |
| `.../Walls.panel/bundle.yaml` | **Modify.** Add `MultiWallCreationV2`. |

---

### Task 1: Extract `Tahir.wall_sketch`

A pure move. `CurtainWallTrim` and `WindowToCurtainWall` must behave EXACTLY as before.

**Files:**
- Create: `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_sketch.py`
- Modify: `.../Walls.panel/CurtainWallTrim.pushbutton/script.py`
- Modify: `.../Walls.panel/WindowToCurtainWall.pushbutton/script.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SketchFailureSwallower` — an `IFailuresPreprocessor`.
  - `sketch_curve_ids(sketch)` → list of `ElementId`.
  - `apply_profile(doc, wall, curves, sketch_name, scope_name)` → `None` on success, or a reason string.

- [ ] **Step 1: Confirm the three definitions really are interchangeable**

Run this and read the output before moving anything. It proves the claim the whole task rests on:

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel"
python - <<'PY'
import io, difflib
def grab(path, start):
    lines = io.open(path, encoding="utf-8").read().splitlines()
    out = [lines[start - 1]]
    for i in range(start, len(lines)):
        if lines[i].startswith(("def ", "class ", "# ==")):
            break
        out.append(lines[i])
    return out
CWT = "CurtainWallTrim.pushbutton/script.py"
W2C = "WindowToCurtainWall.pushbutton/script.py"
for name, a_ln, b_ln in (("SketchFailureSwallower", 702, 1002),
                         ("sketch_curve_ids", 736, 1036),
                         ("apply_profile", 764, 1064)):
    a, b = grab(CWT, a_ln), grab(W2C, b_ln)
    d = list(difflib.unified_diff(a, b, "CWT", "W2C", lineterm="", n=0))
    print("== {} ==".format(name))
    print("\n".join(d) if d else "IDENTICAL")
PY
```

Expected: the first two IDENTICAL; `apply_profile` differing in exactly two lines — `"Create trim profile sketch"` vs `"Create wall profile sketch"`, and `"Cut the source wall out of the trim"` vs `"Reshape curtain wall to the window"`.

If the line numbers have drifted, find the definitions with `grep -n "def apply_profile\|def sketch_curve_ids\|class SketchFailureSwallower"` and use the real ones. **If the bodies differ by anything more than those two strings, STOP and report** — the extraction as designed is no longer safe.

- [ ] **Step 2: Write the undefined-name checker**

`py_compile` cannot see a NameError, and these scripts cannot be executed outside Revit. Save this to the scratchpad (NOT the repo) and use it in every task from here on:

```python
# -*- coding: utf-8 -*-
"""Report names a module uses but never defines, imports, or binds."""
import ast, builtins, io, sys

FUNC = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def arg_names(args):
    names = set()
    for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        names.add(a.arg)
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def bindings_in(node):
    names = set()
    if isinstance(node, FUNC):
        names |= arg_names(node.args)
    stack = [node]
    while stack:
        cur = stack.pop()
        for child in ast.iter_child_nodes(cur):
            if isinstance(child, FUNC):
                if not isinstance(child, ast.Lambda):
                    names.add(child.name)
                continue
            if isinstance(child, ast.ClassDef):
                names.add(child.name)
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(child, ast.ExceptHandler) and child.name:
                names.add(child.name)
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                names.update(child.names)
            stack.append(child)
    return names


def walk_scope(node, enclosing, problems):
    scope = enclosing | bindings_in(node)
    stack = [node]
    while stack:
        cur = stack.pop()
        for child in ast.iter_child_nodes(cur):
            if isinstance(child, FUNC):
                walk_scope(child, scope, problems)
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                if child.id not in scope:
                    problems.append((child.lineno,
                                     getattr(node, "name", "<lambda>"),
                                     child.id))
            stack.append(child)


def main(path):
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    known = (bindings_in(tree) | set(dir(builtins))
             | {"__file__", "__name__", "__doc__"})
    problems = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, FUNC):
            walk_scope(node, known, problems)
    seen = set()
    for lineno, fn, name in sorted(problems):
        if (fn, name) in seen:
            continue
        seen.add((fn, name))
        print("line {}: {}() uses undefined name '{}'".format(lineno, fn, name))
    if not problems:
        print("OK - {}".format(path.rsplit("/", 1)[-1]))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
```

Prove it works before trusting it: copy any script, delete one function whose call sites remain, run the checker on the copy, and confirm it names that function and exits 1.

- [ ] **Step 3: Create the module**

Create `lib/Tahir/wall_sketch.py` with the standard header, a module docstring explaining WHY the two names are parameters, the `Autodesk.Revit.DB` imports the moved code needs (`ElementId`, `Sketch`, `SketchEditScope`, `Transaction`, plus `IFailuresPreprocessor` and `FailureResolutionType`/`FailureSeverity` as the originals import them), the pyrevit logger, and the three definitions moved VERBATIM from `CurtainWallTrim` — with exactly three changes to `apply_profile`:

1. signature becomes `def apply_profile(doc, wall, curves, sketch_name, scope_name):`
2. `Transaction(doc, "Create trim profile sketch")` becomes `Transaction(doc, sketch_name)`
3. `SketchEditScope(doc, "Cut the source wall out of the trim")` becomes `SketchEditScope(doc, scope_name)`

`doc` was a module global in both scripts and is now a parameter. Change nothing else — not the inner transaction name `"Replace profile curves"`, not the messages, not the exception handling.

- [ ] **Step 4: Re-point `CurtainWallTrim`**

Delete `SketchFailureSwallower`, `sketch_curve_ids` and `apply_profile`. Add `wall_sketch` to the `from Tahir import ...` line. Replace the single call site with:

```python
    failure = wall_sketch.apply_profile(
        doc, wall, curves,
        "Create trim profile sketch",
        "Cut the source wall out of the trim")
```

Find the real call site with `grep -n "apply_profile(" CurtainWallTrim.pushbutton/script.py` and keep whatever it does with the return value. Remove any `Autodesk.Revit.DB` import left unused — check each with grep before removing it.

- [ ] **Step 5: Re-point `WindowToCurtainWall`**

The same three deletions, and its call site becomes:

```python
        failure = wall_sketch.apply_profile(
            doc, wall, moved,
            "Create wall profile sketch",
            "Reshape curtain wall to the window")
```

- [ ] **Step 6: Verify**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools"
python -m py_compile "Revit API/pyRevit-Tools.extension/lib/Tahir/wall_sketch.py"
python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/CurtainWallTrim.pushbutton/script.py"
python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/WindowToCurtainWall.pushbutton/script.py"
grep -n "def apply_profile\|def sketch_curve_ids\|class SketchFailureSwallower" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/CurtainWallTrim.pushbutton/script.py" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/WindowToCurtainWall.pushbutton/script.py"
python -m unittest discover -s tests
```

Expected: three compiles clean; the grep finds NOTHING and exits 1; 229 tests pass. Run the Step 2 checker on all three files — all OK.

- [ ] **Step 7: HUMAN — verify in Revit**

You cannot do this: there is no Revit session and driving the user's is forbidden. Report it as outstanding. The human runs **Curtain Wall Trim** on a curtain wall and **Window To Curtain Wall** on a linked curtain wall with a sketched profile, and confirms both reshape exactly as before.

- [ ] **Step 8: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/Tahir/wall_sketch.py" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/CurtainWallTrim.pushbutton/script.py" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/WindowToCurtainWall.pushbutton/script.py"
git commit -m "refactor: extract wall profile editing into Tahir.wall_sketch"
```

---

### Task 2: Extract `Tahir.window_cw`

Also a pure move. `WindowToCurtainWall` must behave EXACTLY as before.

**Files:**
- Create: `Revit API/pyRevit-Tools.extension/lib/Tahir/window_cw.py`
- Modify: `.../Walls.panel/WindowToCurtainWall.pushbutton/script.py`

**Interfaces:**
- Consumes: `Tahir.wall_sketch` (Task 1).
- Produces, all moved verbatim unless noted:
  - `class WindowPlan` — slots exactly as they are today.
  - `measure_window(link_inst, window, host_wall, direction=None)` →
    `(WindowPlan or None, reason)` — see Step 2 for the added argument.
  - `create_curtain_wall(doc, plan, host_wall, wall_type)` → `(Wall or None, reason)` — `doc` becomes a parameter.
  - `curtain_wall_types(doc)`, `match_curtain_type(plan, types)`, `prompt_curtain_type(types, mark, prefix)`, `type_named(name, types)`
  - `type_mark(window, link_doc)`, `mark_letters`, `mark_prefix`, `candidate_prefixes`
  - `wall_axis(host_wall)`, `segment_on_wall(host_wall, centre, width)`, `strip_curtain_grid(doc, wall)`
  - `apply_bg_parameters(plan, wall, host_wall)`
  - `window_centre`, `sill_from_parameters`, `sill_height_candidates`, `length_param`, `is_category`, `iter_solid_points`, `_iter_geo_points`, `find_level_below(doc, elevation)`, `project_base_elevation(target_doc)`, `params_by_name`, `pick_param`, `set_param_text`, `copy_param`, `as_element_id`, `eid_value`, `get_element_name`
  - the constant `CURTAIN_SUFFIX`

- [ ] **Step 1: List what actually moves, from the file as it stands**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel"
grep -n "^def \|^class \|^CURTAIN_SUFFIX\|^BG_" WindowToCurtainWall.pushbutton/script.py
```

The WINDOW path moves. These STAY in the pushbutton because they serve the linked-curtain-wall source, which V2 does not use: `measure_curtain_wall`, `linked_wall_profile`, `wall_vertical_extent`, `profile_extent`, `move_profile`, `resolve_profile`, `frame_at`, `measure_source`, `is_curtain_wall`, `LinkedSourceFilter`, `WallFilter`, `pick_pairs`, `report`, `report_measurements`, `feet_text`, `main`.

- [ ] **Step 2: Create the module**

Create `lib/Tahir/window_cw.py`: standard header; a module docstring saying it owns the window-to-curtain-wall path and that the linked-curtain-wall path deliberately stays in the pushbutton; the `Autodesk.Revit.DB` and `pyrevit` imports the moved code needs; then the definitions moved verbatim.

Three signature changes only, all because `doc` was a module global:

```python
def create_curtain_wall(doc, plan, host_wall, wall_type):
def strip_curtain_grid(doc, wall):
def find_level_below(doc, elevation):
```

Update their internal call sites to pass `doc` through. `curtain_wall_types(doc)` already takes none today — give it `doc` as well.

And ONE more, which V2 needs and `WindowToCurtainWall` will not notice:

```python
def measure_window(link_inst, window, host_wall, direction=None):
```

`measure_window` uses `host_wall` for exactly one thing — `wall_axis(host_wall)`, whose *direction* it projects the window's solid along and stores as `plan.wall_dir`. The curve that comes back with it is never used. V2 has that direction already, on the wall job's merged frame, and cannot pass a host wall at all: the skin wall it would name does not exist until the transaction, and measurement must happen before it because choosing a curtain wall type raises a dialog.

So when *direction* is given, use it and skip `wall_axis`; when it is None, behave exactly as now. Replace the opening of the function with:

```python
    if direction is None:
        curve, direction = wall_axis(host_wall)
        if curve is None or direction is None:
            return None, "picked wall has no usable location curve"
```

Change nothing else. `WindowToCurtainWall`'s own call sites pass no direction and are unaffected.

- [ ] **Step 3: Re-point `WindowToCurtainWall`**

Delete the moved definitions. Add `window_cw` to the `from Tahir import ...` line. At every remaining call site, qualify with `window_cw.` and pass `doc` to the four functions that now take it. Then, so the rest of the file needs no edit, add module-level aliases immediately after the `doc/uidoc/logger/output` block for the names it still uses bare:

```python
get_element_name = window_cw.get_element_name
as_element_id    = window_cw.as_element_id
eid_value        = window_cw.eid_value
length_param     = window_cw.length_param
iter_solid_points = window_cw.iter_solid_points
```

Add an alias for any other moved name the file still uses bare — find them by running the Step 2 checker from Task 1 and adding an alias for each name it reports.

- [ ] **Step 4: Verify**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools"
python -m py_compile "Revit API/pyRevit-Tools.extension/lib/Tahir/window_cw.py"
python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/WindowToCurtainWall.pushbutton/script.py"
python -m unittest discover -s tests
```

Expected: both compile; 229 tests pass; the Task 1 Step 2 checker reports OK on both files. Also confirm no moved definition survives in the pushbutton:

```bash
grep -nE "^def (measure_window|window_centre|sill_from_parameters|segment_on_wall|strip_curtain_grid|create_curtain_wall|apply_bg_parameters|type_mark|mark_letters|mark_prefix|candidate_prefixes|curtain_wall_types|match_curtain_type|prompt_curtain_type|wall_axis)\b" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/WindowToCurtainWall.pushbutton/script.py"
```

Expected: nothing, exit 1.

- [ ] **Step 5: HUMAN — verify in Revit**

Cannot be done here. The human runs **Window To Curtain Wall** on a linked WINDOW and on a linked CURTAIN WALL and confirms both behave exactly as before — the window path is what moved, the curtain wall path is what must not have.

- [ ] **Step 6: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/Tahir/window_cw.py" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/WindowToCurtainWall.pushbutton/script.py"
git commit -m "refactor: extract the window to curtain wall path into Tahir.window_cw"
```

---

### Task 3: `wall_bands.cutters_clear_of_windows`

**Files:**
- Modify: `Revit API/pyRevit-Tools.extension/lib/Tahir/wall_bands.py`
- Test: `tests/test_wall_bands.py`

**Interfaces:**
- Consumes: `wall_bands.TOL`.
- Produces: `cutters_clear_of_windows(cutters, windows, tol=TOL)` → list of the `(lo, hi)` cutters that no window overlaps.

- [ ] **Step 1: Write the failing tests**

Add above the `if __name__ == "__main__":` block in `tests/test_wall_bands.py`:

```python
class TestCuttersClearOfWindows(unittest.TestCase):
    """A stone course crossing a window stops governing that wall.

    Otherwise the skin is split behind the window, and the elevation
    gains a joint the building does not have.
    """

    WINDOW = (10.0, 20.0)          # sill 10, head 20

    def test_no_windows_keeps_every_cutter(self):
        cutters = [(4.0, 5.0), (25.0, 26.0)]
        self.assertEqual(
            wb.cutters_clear_of_windows(cutters, []), cutters)

    def test_no_cutters_gives_nothing(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([], [self.WINDOW]), [])

    def test_a_cutter_below_the_sill_survives(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(4.0, 5.0)], [self.WINDOW]),
            [(4.0, 5.0)])

    def test_a_cutter_above_the_head_survives(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(25.0, 26.0)], [self.WINDOW]),
            [(25.0, 26.0)])

    def test_a_cutter_inside_the_window_is_dropped(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(14.0, 15.0)], [self.WINDOW]), [])

    def test_a_cutter_straddling_the_head_is_dropped(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(19.0, 21.0)], [self.WINDOW]), [])

    def test_a_cutter_straddling_the_sill_is_dropped(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(9.0, 11.0)], [self.WINDOW]), [])

    def test_a_cutter_swallowing_the_window_is_dropped(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(5.0, 25.0)], [self.WINDOW]), [])

    def test_a_cutter_sitting_exactly_on_the_head_survives(self):
        # A course whose base is the window head does not cross it: it
        # sits on it, which is what a lintel band does.
        self.assertEqual(
            wb.cutters_clear_of_windows([(20.0, 21.0)], [self.WINDOW]),
            [(20.0, 21.0)])

    def test_a_cutter_sitting_exactly_on_the_sill_survives(self):
        self.assertEqual(
            wb.cutters_clear_of_windows([(9.0, 10.0)], [self.WINDOW]),
            [(9.0, 10.0)])

    def test_an_overlap_under_tolerance_is_not_an_overlap(self):
        cutters = [(20.0 - 0.5 * wb.TOL, 21.0)]
        self.assertEqual(
            wb.cutters_clear_of_windows(cutters, [self.WINDOW]), cutters)

    def test_only_the_crossing_cutter_is_dropped(self):
        cutters = [(4.0, 5.0), (14.0, 15.0), (25.0, 26.0)]
        self.assertEqual(
            wb.cutters_clear_of_windows(cutters, [self.WINDOW]),
            [(4.0, 5.0), (25.0, 26.0)])

    def test_a_cutter_crossing_any_of_several_windows_is_dropped(self):
        windows = [(10.0, 20.0), (30.0, 40.0)]
        cutters = [(35.0, 36.0), (25.0, 26.0)]
        self.assertEqual(
            wb.cutters_clear_of_windows(cutters, windows), [(25.0, 26.0)])

    def test_order_is_preserved(self):
        cutters = [(25.0, 26.0), (4.0, 5.0)]
        self.assertEqual(
            wb.cutters_clear_of_windows(cutters, [self.WINDOW]), cutters)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests`
Expected: FAIL — `AttributeError: module 'Tahir.wall_bands' has no attribute 'cutters_clear_of_windows'`, 14 errors.

- [ ] **Step 3: Write the implementation**

Append to `lib/Tahir/wall_bands.py`:

```python
def cutters_clear_of_windows(cutters, windows, tol=TOL):
    """Drop the cutters that cross a window, keep the rest in order.

    A cast stone course running across a window would otherwise cut the
    wall behind it into two bands, putting a joint in the elevation that
    the building does not have.  Where a course crosses a window, it
    stops governing heights on that wall at all.

    Dropping it for the whole wall rather than just over the window is
    deliberate.  Suppressing it over the window alone would mean a band
    boundary that stops and restarts along the elevation -- splitting
    the skin in plan, which was tried and taken back out.

    Touching is not crossing: a course whose base is exactly a window's
    head SITS on it, which is what a lintel band does, and it survives.
    *windows* are (sill, head) pairs; *cutters* are (lo, hi) pairs.
    """
    kept = []
    for lo, hi in cutters:
        crosses = False
        for sill, head in windows:
            if hi > sill + tol and lo < head - tol:
                crosses = True
                break
        if not crosses:
            kept.append((lo, hi))
    return kept
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests`
Expected: PASS, 243 tests.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/Tahir/wall_bands.py" tests/test_wall_bands.py
git commit -m "feat: add cutters_clear_of_windows so a course crossing a window stops cutting"
```

---

### Task 4: The V2 pushbutton, behaving exactly like V1

No new behaviour. The deliverable is a second button that does what V1 does, so everything after this is a diff against a working baseline.

**Files:**
- Create: `.../Walls.panel/MultiWallCreationV2.pushbutton/script.py`
- Modify: `.../Walls.panel/bundle.yaml`

**Interfaces:**
- Consumes: nothing new.
- Produces: the whole of V1's script under a new name — every function later tasks touch (`plan_wall`, `band_walls`, `prepare_bands`, `build_bands`, `build_sweep_walls`, `main`, `WallJob`, `wall_openings`, `_insert_extent`) exists here with V1's signatures.

- [ ] **Step 1: Copy V1**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools/Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel"
mkdir -p MultiWallCreationV2.pushbutton
cp MultiWallCreationV1.pushbutton/script.py MultiWallCreationV2.pushbutton/script.py
```

`MultiWallCreationV1.pushbutton/script.py` is now READ-ONLY for the rest of this plan.

- [ ] **Step 2: Rename the button**

In the V2 copy only, change:

```python
__title__  = "Multi Wall\nCreation V2"
```

and `TOOL_TITLE = "Multi Wall Creation V2"`. Add one paragraph to the module docstring, after the first:

```
V2 also puts the openings back: every window in a picked wall becomes a
curtain wall on the new skin wall, and every rectangular opening is cut
out of the skin's elevation.  V1 is left alone -- it is a separate
button, and this one is where the openings work is being proved.
```

- [ ] **Step 3: Register the button**

Replace `bundle.yaml` with:

```yaml
layout:
  - WallConstraints
  - SplitWalls
  - SweepToWall
  - MultiWallCreationV1
  - MultiWallCreationV2
  - WindowToCurtainWall
  - CurtainWallTrim
```

- [ ] **Step 4: Verify**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools"
python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV2.pushbutton/script.py"
git diff --stat -- "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"
diff <(git show HEAD:"Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py") "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV2.pushbutton/script.py" | head -30
```

Expected: compiles; the V1 diff is EMPTY (it must not have changed); the last diff shows only the title, `TOOL_TITLE` and docstring lines. Run the Task 1 Step 2 checker — OK.

- [ ] **Step 5: HUMAN — verify in Revit**

Reload pyRevit. **Multi Wall Creation V2** appears after V1. Run it on the same selection you would give V1 and confirm the result is identical.

- [ ] **Step 6: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV2.pushbutton/script.py" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/bundle.yaml"
git commit -m "feat: add Multi Wall Creation V2, a copy of V1 to build the openings work on"
```

---

### Task 5: Measure the windows and openings, and let windows suppress a course

**Files:**
- Modify: `.../Walls.panel/MultiWallCreationV2.pushbutton/script.py`

**Interfaces:**
- Consumes: `wall_bands.cutters_clear_of_windows` (Task 3); `window_cw.is_category` (Task 2); V2's own `_insert_extent`, `WallJob`, `band_walls`, `merge_wall_jobs`.
- Produces:
  - `WallJob.windows` — list of `(along_lo, along_hi, z_lo, z_hi, Element)`, the linked window element last.
  - `WallJob.rect_openings` — list of `(along_lo, along_hi, z_lo, z_hi, Element)`.
  - `wall_inserts(wall, link_tf, origin, direction)` → `(windows, rect_openings)`.

- [ ] **Step 1: Add the measurement**

`WallJob.__slots__` gains `"windows"` and `"rect_openings"`. Add this beside `wall_openings`:

```python
def wall_inserts(wall, link_tf, origin, direction):
    """Return (windows, rectangular openings) in *wall*, in its frame.

    Measured the same way wall_openings measures a door: along the wall
    from *origin*, and vertically from the insert's own extent.  Each
    entry keeps the linked element itself as its last item, because the
    window still has to be measured properly by window_cw later and the
    opening has to be found again to cut.

    Doors are not here.  They break the sweeps, as in V1, and the skin
    is left solid across them.
    """
    try:
        ids = list(wall.FindInserts(True, False, True, True))
    except Exception as ex:
        logger.debug("Could not read inserts: {}".format(ex))
        return [], []

    link_doc = wall.Document
    windows  = []
    openings = []

    for iid in ids:
        insert = link_doc.GetElement(iid)
        if insert is None:
            continue

        extent = _insert_extent(insert, link_tf, origin, direction)
        if extent is None:
            continue
        lo, hi, z_lo, z_hi = extent

        if window_cw.is_category(insert, BuiltInCategory.OST_Windows):
            windows.append((lo, hi, z_lo, z_hi, insert))
        elif isinstance(insert, Opening):
            openings.append((lo, hi, z_lo, z_hi, insert))

    return windows, openings
```

Add `Opening` to the `Autodesk.Revit.DB` import list, and `window_cw` to the `from Tahir import ...` list.

In `plan_wall`, beside the existing assignments:

```python
    job.windows, job.rect_openings = wall_inserts(
        wall, link_tf, pt0, (pt1 - pt0).Normalize())
```

- [ ] **Step 2: Carry them through the colinear merge**

`merge_wall_jobs` folds several source walls into one job. Its merged job must carry every member's inserts, or the windows on the second and third pieces are lost. In the branch that builds the merged `WallJob`, add:

```python
        job.windows       = []
        job.rect_openings = []
        for i in members:
            job.windows.extend(wall_jobs[i].windows)
            job.rect_openings.extend(wall_jobs[i].rect_openings)
```

**These are measured along each MEMBER's frame, not the merged one.** Task 6 needs them in host coordinates anyway and re-derives position from the window element itself, so the along values are used only for reporting. Note that in a comment where they are extended.

- [ ] **Step 3: Suppress the courses that cross a window**

In `band_walls`, replace the line that builds `cutters` for a wall with:

```python
        cutters = [(run.base_z, run.top_z)
                   for sweep_job in cutting
                   for run in sweep_job.runs
                   if run.wall_keys & job.wall_keys]

        # A course running across a window would split the wall behind
        # it, putting a joint in the elevation the building does not
        # have.  Where one crosses a window, it stops governing this
        # wall's heights entirely.
        cutters = wall_bands.cutters_clear_of_windows(
            cutters, [(w[2], w[3]) for w in job.windows])
```

- [ ] **Step 4: Verify**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools"
python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV2.pushbutton/script.py"
python -m unittest discover -s tests
git diff --stat -- "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"
```

Expected: compiles; 243 tests pass; the V1 diff is EMPTY. Run the Task 1 Step 2 checker — OK.

- [ ] **Step 5: HUMAN — verify in Revit**

Run V2 on a wall with a cast stone course crossing a window: the skin must come out as ONE band there, not two. Run it on a wall whose course is clear of every window: the skin must still split at the course exactly as V1 does.

- [ ] **Step 6: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV2.pushbutton/script.py"
git commit -m "feat: measure windows and openings, and let a window suppress a course"
```

---

### Task 6: Build the curtain walls

**Files:**
- Modify: `.../Walls.panel/MultiWallCreationV2.pushbutton/script.py`

**Interfaces:**
- Consumes: `window_cw.measure_window`, `window_cw.curtain_wall_types`, `window_cw.match_curtain_type`, `window_cw.prompt_curtain_type`, `window_cw.mark_prefix`, `window_cw.create_curtain_wall`, `window_cw.WindowPlan` (Task 2); `wall_constraints.plan_wall`; V2's `prepare_bands` output.
- Produces: `plan_windows(wall_jobs, notes)` → `list` of `(WallJob, WindowPlan, Wall_type)`; `build_curtain_walls(planned, levels, notes)`.

- [ ] **Step 1: Resolve the curtain wall types BEFORE the transaction**

`prompt_curtain_type` raises a dialog, so it must run outside the transaction, like every other dialog in this tool. Add:

```python
def plan_windows(wall_jobs, notes):
    """Measure every window and settle its curtain wall type.

    Runs BEFORE the transaction: prompt_curtain_type raises a dialog,
    and this tool never opens one inside a transaction.  The type is
    asked once per Type Mark prefix and cached, as Window To Curtain
    Wall does, so a facade of twenty identical windows asks once.
    """
    types = window_cw.curtain_wall_types(doc)
    if not types:
        note(notes, "-", "no curtain wall types in this model")
        return []

    asked   = {}
    planned = []

    for job in wall_jobs:
        for _lo, _hi, _z_lo, _z_hi, window in job.windows:
            # No host wall: the skin wall this window will sit on is not
            # built yet, and cannot be -- choosing its type raises a
            # dialog, so all of this runs before the transaction.  The
            # merged frame's direction is the only thing measure_window
            # wanted a wall for, and it is the direction the skin wall
            # will have.
            plan, reason = window_cw.measure_window(
                job.link_inst, window, None, direction=job.direction)
            if plan is None:
                note(notes, job.label,
                     "window {}: {}".format(window.Id.IntegerValue, reason))
                continue

            wall_type = window_cw.match_curtain_type(plan, types)
            if wall_type is None:
                prefix = window_cw.mark_prefix(plan.mark)
                if prefix not in asked:
                    asked[prefix] = window_cw.prompt_curtain_type(
                        types, plan.mark, prefix)
                wall_type = asked[prefix]

            if wall_type is None:
                note(notes, job.label,
                     "window {}: no curtain wall type chosen".format(
                         window.Id.IntegerValue))
                continue

            planned.append((job, plan, wall_type))

    return planned
```

`measure_window` needs the link instance and a direction. `WallJob` carries neither today, so add `"link_inst"` and `"direction"` to its `__slots__` and set them in `plan_wall`, beside where `loc_curve` is set:

```python
    job.link_inst = link_inst
    job.direction = (pt1 - pt0).Normalize()
```

In `merge_wall_jobs`, take `link_inst` from `first`, but derive `direction` from the MERGED curve rather than copying it — a merged run is one wall and the direction is its own:

```python
        job.link_inst = first.link_inst
        job.direction = (job.loc_curve.GetEndPoint(1)
                         - job.loc_curve.GetEndPoint(0)).Normalize()
```

Call it in `main()` immediately after `collect_skin_plans`, which is the last thing before the transaction:

```python
    window_plans = plan_windows(wall_jobs, notes)
```

- [ ] **Step 2: Build them inside the transaction**

`prepare_bands` already knows which skin wall covers which elevation. Record the built wall against its job so a window can find its host. In `build_bands`, after `item["wall"] = wall`, add:

```python
            item["job"].built_bands.append(
                (band["base_z"], band["top_z"], wall))
```

Add `"built_bands"` to `WallJob.__slots__`, set `job.built_bands = []` wherever `job.bands = []` is set, and copy nothing in `merge_wall_jobs` beyond initialising it to `[]`.

Then add:

```python
def build_curtain_walls(planned, levels, notes):
    """Create one curtain wall per window, per storey.  In a transaction.

    A window crossing a level becomes one curtain wall per storey,
    split at exactly the elevations the skin bands split at -- the same
    wall_constraints.plan_wall, called with allow_round=False, so the
    two can never disagree about where a storey ends.

    Each piece is hosted on whichever skin band covers its own middle.
    That is what makes a split window work: the lower piece embeds in
    the lower band and the upper piece in the upper one.
    """
    for job, plan, wall_type in planned:
        try:
            cut = wall_constraints.plan_wall(
                plan.sill, plan.sill + plan.height, levels,
                allow_round=False)
        except ValueError as ex:
            note(notes, job.label,
                 "window {}: {}".format(plan.window_id, ex))
            continue

        for band in cut["bands"]:
            mid  = (band["base_z"] + band["top_z"]) / 2.0
            host = None
            for base_z, top_z, wall in job.built_bands:
                if base_z - wall_bands.TOL <= mid <= top_z + wall_bands.TOL:
                    host = wall
                    break

            if host is None:
                note(notes, job.label,
                     "window {}: no skin wall at {} to host it".format(
                         plan.window_id, feet_text(mid)))
                continue

            piece = copy_window_plan(plan)
            piece.sill   = band["base_z"]
            piece.height = band["top_z"] - band["base_z"]

            try:
                wall, reason = window_cw.create_curtain_wall(
                    doc, piece, host, wall_type)
            except Exception as ex:
                note(notes, job.label,
                     "window {}: curtain wall failed: {}".format(
                         plan.window_id, ex))
                continue

            if wall is None:
                note(notes, job.label,
                     "window {}: {}".format(plan.window_id, reason))
            elif reason:
                note(notes, job.label,
                     "window {}: {}".format(plan.window_id, reason))


def copy_window_plan(plan):
    """A shallow copy of a WindowPlan, so one window can become several.

    WindowPlan uses __slots__ and has no copy of its own, and a split
    window needs one plan per storey with its own sill and height while
    everything else stays shared.
    """
    other = window_cw.WindowPlan()
    for name in window_cw.WindowPlan.__slots__:
        try:
            setattr(other, name, getattr(plan, name))
        except AttributeError:
            continue
    other.notes = list(plan.notes)
    other.grid_removed = []
    return other
```

Call it in `main()` inside the transaction, after `build_bands(prepared, notes)`:

```python
        build_curtain_walls(window_plans, levels, notes)
```

- [ ] **Step 3: Verify**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools"
python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV2.pushbutton/script.py"
python -m unittest discover -s tests
git diff --stat -- "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"
```

Expected: compiles; 243 tests pass; V1 diff EMPTY. Run the Task 1 Step 2 checker — OK. Then read `main()` back and confirm `plan_windows` is called BEFORE `t.Start()` and `build_curtain_walls` after `build_bands` and before `t.Commit()`.

- [ ] **Step 4: HUMAN — verify in Revit**

Check each: a plain window becomes one curtain wall of the type its Type Mark prefix names, embedded in the skin; twenty identical windows ask for a type at most once; a window whose prefix matches nothing asks once and cancelling skips just those; a tall window crossing a level becomes TWO curtain walls split at that level; an arched window becomes a rectangle tall enough to cover the arch; the curtain walls have no grid or mullions; BG parameters are filled.

**Watch for:** whether Revit embeds a curtain wall into a 2–3 inch skin wall the way it does into a full compound wall. This is the untested assumption in the whole design.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV2.pushbutton/script.py"
git commit -m "feat: turn windows in the picked walls into curtain walls on the new skins"
```

---

### Task 7: Cut the rectangular openings

**Files:**
- Modify: `.../Walls.panel/MultiWallCreationV2.pushbutton/script.py`

**Interfaces:**
- Consumes: `wall_sketch.apply_profile` (Task 1); `WallJob.rect_openings` and `WallJob.built_bands` (Tasks 5, 6).
- Produces: `cut_openings(wall_jobs, notes)`, called after the transaction commits.

- [ ] **Step 1: Add the cutting**

```python
def opening_profile(wall, hole):
    """Curves for *wall*'s elevation with *hole* cut out of it.

    Returns the wall's own rectangle followed by the hole's, both as
    closed loops in the wall's elevation plane.  Revit takes the first
    loop as the outline and the rest as holes in it.

    *hole* is (along_lo, along_hi, z_lo, z_hi) measured along the SOURCE
    wall; it is re-projected onto this wall here, because the skin wall
    is offset from the source and may be a merged run of several.
    """
    curve = wall.Location.Curve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    direction = (p1 - p0).Normalize()
    normal = XYZ(-direction.Y, direction.X, 0.0)

    base_z = wall.get_Parameter(
        BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
    level = doc.GetElement(wall.LevelId)
    base = level.Elevation + base_z
    top = base + wall.get_Parameter(
        BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()

    length = p0.DistanceTo(p1)

    def at(along, z):
        return XYZ(p0.X + direction.X * along,
                   p0.Y + direction.Y * along,
                   z)

    outline = [(0.0, base), (length, base), (length, top), (0.0, top)]
    lo, hi, z_lo, z_hi = hole
    lo = max(lo, wall_bands.TOL)
    hi = min(hi, length - wall_bands.TOL)
    z_lo = max(z_lo, base + wall_bands.TOL)
    z_hi = min(z_hi, top - wall_bands.TOL)
    if hi - lo < MIN_RUN_LENGTH or z_hi - z_lo < MIN_RUN_LENGTH:
        return None, normal

    inner = [(lo, z_lo), (hi, z_lo), (hi, z_hi), (lo, z_hi)]

    curves = []
    for loop in (outline, inner):
        for idx in range(len(loop)):
            a = loop[idx]
            b = loop[(idx + 1) % len(loop)]
            curves.append(Line.CreateBound(at(a[0], a[1]), at(b[0], b[1])))
    return curves, normal


def cut_openings(wall_jobs, notes):
    """Cut every rectangular opening out of the skin wall covering it.

    Runs AFTER the transaction has committed, and it has no choice:
    SketchEditScope refuses to start inside an open transaction, and a
    sketched profile is drawn against the wall's constraints, so those
    have to be final first.  Window To Curtain Wall sequences it the
    same way, for the same reasons.

    A failure here therefore cannot roll the walls back -- they are
    already committed.  That is the right trade: a wall standing uncut
    is worth more than a run that throws away everything it built.
    """
    for job in wall_jobs:
        for lo, hi, z_lo, z_hi, opening in job.rect_openings:
            mid = (z_lo + z_hi) / 2.0

            host = None
            for base_z, top_z, wall in job.built_bands:
                if (base_z - wall_bands.TOL <= z_lo
                        and z_hi <= top_z + wall_bands.TOL):
                    host = wall
                    break

            if host is None:
                note(notes, job.label,
                     "opening {} spans more than one band, or no band "
                     "covers it - left uncut".format(
                         opening.Id.IntegerValue))
                continue

            curves, _normal = opening_profile(host, (lo, hi, z_lo, z_hi))
            if curves is None:
                note(notes, job.label,
                     "opening {} is too small or falls outside the wall "
                     "- left uncut".format(opening.Id.IntegerValue))
                continue

            failure = wall_sketch.apply_profile(
                doc, host, curves,
                "Create skin profile sketch",
                "Cut the opening out of the skin wall")
            if failure:
                note(notes, job.label,
                     "opening {}: {}".format(
                         opening.Id.IntegerValue, failure))
```

Add `wall_sketch` to the `from Tahir import ...` list.

- [ ] **Step 2: Call it after the transaction**

In `main()`, after the `t.Commit()` block and before `report(notes)`:

```python
    # After the transaction, and it cannot be otherwise: SketchEditScope
    # will not start inside one, and a sketched profile is drawn against
    # constraints that have to be final first.
    cut_openings(wall_jobs, notes)
```

- [ ] **Step 3: Verify**

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools"
python -m py_compile "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV2.pushbutton/script.py"
python -m unittest discover -s tests
git diff --stat -- "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py"
grep -n "cut_openings(wall_jobs, notes)" -B4 "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV2.pushbutton/script.py"
```

Expected: compiles; 243 tests pass; V1 diff EMPTY; the grep shows `cut_openings` AFTER `t.Commit()`. Run the Task 1 Step 2 checker — OK.

- [ ] **Step 4: HUMAN — verify in Revit**

A wall with a rectangular Opening in it: the skin wall comes out with a matching hole. An opening spanning two bands: reported, both walls left whole. A wall with no openings: unchanged from Task 6.

**Watch for:** whether profile editing survives repeated runs. It is the most fragile thing in this repo. If it proves unreliable, the fallback recorded in the spec is `NewOpening`, which needs no sketch at all.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV2.pushbutton/script.py"
git commit -m "feat: cut rectangular openings out of the skin walls"
```

---

## Notes for the executor

- **Never edit `MultiWallCreationV1.pushbutton/script.py`.** Every task verifies its diff is empty. If a fix belongs in both, make it in V2 and report that V1 needs the same.
- **Nothing here can be run in Revit.** There is no Revit session, and driving the user's is forbidden — it has crashed Revit and lost work before. Every task's Revit verification is the human's; say so plainly rather than claiming it passed.
- **`plan_wall` names two different functions.** `wall_constraints.plan_wall` bands a span; the script's own `plan_wall` measures one linked wall. Always module-qualify the first.
- **Dialogs never open inside a transaction.** `plan_windows` and `collect_skin_plans` run before `t.Start()`; if a task needs a new dialog, it goes there too.
- **Profile editing never runs inside a transaction either**, for the opposite reason: it starts its own.
