# Element To Mass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pyRevit pushbutton that turns one picked element (host or linked) into a conceptual mass in place -- its finished solid, plus each family void trimmed to the volume it cut, on a `Converted Void` subcategory.

**Architecture:** The finished solid is read from the instance's own geometry. The voids are read from a copy of the family opened with `EditFamily`, set to the instance's type and instance values, inside a transaction that is always rolled back: void forms are copied out, then deleted so the uncut solid can be copied out too, and each void is intersected with that uncut solid. All pieces are moved into host coordinates, built into a new mass family around a local origin, loaded and placed. Names, template choice, the volume check, the instance-value rule and the report text live in a Revit-free module that is unit-tested in CPython; the Revit half is checked by compiling, by an undefined-name pass and by the user in Revit.

**Tech Stack:** IronPython 3 / pyRevit for Revit 2025, Revit API (`Autodesk.Revit.DB`), CPython `unittest` for the pure module.

**Spec:** `docs/superpowers/specs/2026-10-15-element-to-mass-design.md`

## Global Constraints

- Target Revit 2025 via pyRevit. Scripts run under IronPython 3 -- **no f-strings**; use `.format()`, matching every existing script.
- Every file starts with `# -*- coding: utf-8 -*-`.
- `lib/BG/mass_plan.py` MUST NOT import anything from `Autodesk.Revit`, and MUST NOT `import clr`. `lib/BG/mass_build.py` IS Revit-facing and may.
- Units are decimal feet and cubic feet. Constants live in `mass_plan` only: `VOLUME_EPS = 1e-6`, `VOLUME_REL_TOL = 0.01`, `PLACE_TOL = 1e-4`. Do not introduce others.
- The source family and any linked model are NEVER modified. `EditFamily` copies are always closed with `Close(False)`.
- The original element is never hidden, moved or deleted.
- An element's name is read with `Element.Name.GetValue(elem)`, as `lib/BG/wall_bind.py` does -- `.Name` on an element type can fail under IronPython.
- All dialogs are raised BEFORE any host transaction opens.
- The runner is `python -m unittest discover -s tests` from the repo root (pytest is NOT installed). The suite stands at **652 tests, all passing**, before this plan starts.
- Every task that writes Revit-facing code runs `py_compile` and the undefined-name pass set up in Task 2 Step 1.
- **Do not open, drive or probe a running Revit session.** The checklist in Task 5 is for the user to run.

Repo root is `C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools`. `EXT` below means `Revit API/pyRevit-Tools.extension`.

Two small departures from the spec, both deliberate:

- The placement check compares the placed instance's transform origin with `origin`, not bounding-box minimums. A solid's bounding box is loose for anything not axis-aligned, so comparing boxes would "correct" a mass that was already right; the transform origin is exact.
- Load, place and move happen in ONE host `Transaction`. A `TransactionGroup` around a single transaction adds nothing: rolling back that transaction already leaves the host as it was.

## Review Focus

- **The same element converted twice.** Expected: a second family, `X_Mass_2`, never an overwrite of `X_Mass`. Pinned in Task 1 (`test_skips_every_taken_suffix`).
- **A family name carrying characters Revit refuses**, such as `Door [Type] : A`. Expected: cleaned, not a crash at `SaveAs`. Pinned in Task 1 (`test_brackets_and_colons`).
- **A family with no voids, or with voids that could not be read.** Expected: no volume warning and no division by zero. Pinned in Task 1 (`test_zero_volumes_agree`) and in Task 4's flow (the check runs only when voids were read).
- **An instance parameter that is reporting, formula-driven or an ElementId.** Expected: left alone rather than `FamilyManager.Set` throwing. Pinned in Task 1 (`TestInstanceValuePlan`).
- **A void that cuts host elements instead of its own family.** Expected: reported as skipped, and the rest of the mass still built. Owned by Task 3 (`family_voids`). It cannot run outside Revit, so the user checks it in Task 5 (the in-place and loadable cases both exercise it whenever a void cuts outside its family).

---

## File Structure

| Path | Responsibility |
|---|---|
| `EXT/lib/BG/mass_plan.py` | **Create.** Names, template choice, volume check, instance-value rule, report text. No Revit. |
| `EXT/lib/BG/mass_build.py` | **Create.** Revit-facing: pick, read solids, read voids, build the family, load and place. |
| `EXT/lib/BG/__init__.py` | **Modify.** Its docstring names which modules are Revit-free; add both new ones. |
| `EXT/Tahir_Tools.tab/Usage.panel/ElementToMass.pushbutton/script.py` | **Create.** The flow and the report. |
| `tests/test_mass_plan.py` | **Create.** Unit tests for `mass_plan`. |

---

### Task 1: `BG.mass_plan` -- the plain-Python half, with tests

**Files:**
- Create: `EXT/lib/BG/mass_plan.py`
- Create: `tests/test_mass_plan.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `VOID_SUBCATEGORY = "Converted Void"`, `VOLUME_EPS = 1e-6`, `VOLUME_REL_TOL = 0.01`, `PLACE_TOL = 1e-4`, `SHOW_MASS_NOTE` (str)
  - `family_base_name(source_name)` -> `str`
  - `unique_name(base, taken)` -> `str` (does not modify `taken`)
  - `pick_template(candidates, exists)` -> `str` or `None`
  - `volume_check(uncut, cut, voids, rel_tol=VOLUME_REL_TOL)` -> `None` or warning `str`; `voids` is a list of floats
  - `instance_value_plan(params)` -> `(copy_names, skipped)`; `params` is a list of `(name, storage, is_instance, has_formula, is_reporting)` with `storage` one of `"Double"`, `"Integer"`, `"String"`, `"ElementId"`, `"None"`; `skipped` is a list of `(name, reason)`
  - `report_lines(result)` -> list of `str`; `result` is a dict with keys `family` (str), `solids` (int), `voids` (int), `warnings` (list of str), `skips` (list of str)

The fifth tuple field, `is_reporting`, is not in the spec's tuple. It is there because `FamilyManager.Set` throws on a reporting parameter.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mass_plan.py`:

```python
# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "Revit API", "pyRevit-Tools.extension", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from BG import mass_plan as mp


class TestFamilyBaseName(unittest.TestCase):

    def test_plain_name(self):
        self.assertEqual(mp.family_base_name("Planter Box"), "Planter Box_Mass")

    def test_brackets_and_colons(self):
        self.assertEqual(mp.family_base_name("Door [Type] : A"),
                         "Door _Type_ _ A_Mass")

    def test_every_refused_character(self):
        self.assertEqual(mp.family_base_name("a\\b:c{d}e[f]g|h;i<j>k?l`m~n"),
                         "a_b_c_d_e_f_g_h_i_j_k_l_m_n_Mass")

    def test_empty_name(self):
        self.assertEqual(mp.family_base_name(""), "Element_Mass")

    def test_none_name(self):
        self.assertEqual(mp.family_base_name(None), "Element_Mass")

    def test_whitespace_only(self):
        self.assertEqual(mp.family_base_name("   "), "Element_Mass")


class TestUniqueName(unittest.TestCase):

    def test_free_name_kept(self):
        self.assertEqual(mp.unique_name("Box_Mass", {"Other"}), "Box_Mass")

    def test_taken_name_gets_2(self):
        self.assertEqual(mp.unique_name("Box_Mass", {"Box_Mass"}), "Box_Mass_2")

    def test_skips_every_taken_suffix(self):
        taken = {"Box_Mass", "Box_Mass_2", "Box_Mass_3"}
        self.assertEqual(mp.unique_name("Box_Mass", taken), "Box_Mass_4")

    def test_does_not_modify_taken(self):
        taken = {"Box_Mass"}
        mp.unique_name("Box_Mass", taken)
        self.assertEqual(taken, {"Box_Mass"})


class TestPickTemplate(unittest.TestCase):

    def test_first_existing_wins(self):
        exists = {"b.rft", "c.rft"}.__contains__
        self.assertEqual(mp.pick_template(["a.rft", "b.rft", "c.rft"], exists),
                         "b.rft")

    def test_none_exist(self):
        self.assertIsNone(mp.pick_template(["a.rft"], lambda p: False))

    def test_empty_entries_skipped(self):
        self.assertEqual(mp.pick_template(["", None, "x.rft"], lambda p: True),
                         "x.rft")


class TestVolumeCheck(unittest.TestCase):

    def test_exact_agreement(self):
        self.assertIsNone(mp.volume_check(10.0, 8.0, [2.0]))

    def test_within_tolerance(self):
        # 1% of 10 is 0.1; off by 0.05
        self.assertIsNone(mp.volume_check(10.0, 8.0, [1.95]))

    def test_outside_tolerance(self):
        msg = mp.volume_check(10.0, 8.0, [1.0])
        self.assertEqual(
            msg,
            "converted voids hold 1.000 cu ft but 2.000 cu ft was cut away "
            "(uncut 10.000, finished 8.000) - check the family's type and "
            "instance parameters")

    def test_several_voids_summed(self):
        self.assertIsNone(mp.volume_check(10.0, 7.0, [1.0, 2.0]))

    def test_zero_volumes_agree(self):
        self.assertIsNone(mp.volume_check(0.0, 0.0, []))

    def test_no_voids_but_volume_missing(self):
        self.assertIsNotNone(mp.volume_check(10.0, 8.0, []))


class TestInstanceValuePlan(unittest.TestCase):

    def test_type_parameters_ignored(self):
        copy, skipped = mp.instance_value_plan(
            [("Width", "Double", False, False, False)])
        self.assertEqual((copy, skipped), ([], []))

    def test_copyable_storage(self):
        copy, skipped = mp.instance_value_plan([
            ("Depth", "Double", True, False, False),
            ("Count", "Integer", True, False, False),
            ("Label", "String", True, False, False),
        ])
        self.assertEqual(copy, ["Depth", "Count", "Label"])
        self.assertEqual(skipped, [])

    def test_formula_skipped(self):
        copy, skipped = mp.instance_value_plan(
            [("Half", "Double", True, True, False)])
        self.assertEqual(copy, [])
        self.assertEqual(skipped, [("Half", "set by a formula")])

    def test_reporting_skipped(self):
        copy, skipped = mp.instance_value_plan(
            [("Measured", "Double", True, False, True)])
        self.assertEqual(skipped, [("Measured", "reporting parameter")])

    def test_element_id_skipped(self):
        copy, skipped = mp.instance_value_plan(
            [("Finish", "ElementId", True, False, False)])
        self.assertEqual(
            skipped,
            [("Finish", "ElementId values do not carry across documents")])

    def test_no_storage_skipped(self):
        copy, skipped = mp.instance_value_plan(
            [("Odd", "None", True, False, False)])
        self.assertEqual(skipped, [("Odd", "no value to copy")])


class TestReportLines(unittest.TestCase):

    def test_clean_run(self):
        lines = mp.report_lines({"family": "Box_Mass", "solids": 2,
                                 "voids": 1, "warnings": [], "skips": []})
        self.assertEqual(lines, [
            "Made **Box_Mass**: 2 solid piece(s), 1 converted void(s).",
            mp.SHOW_MASS_NOTE,
        ])

    def test_warnings_then_skips(self):
        lines = mp.report_lines({"family": "Box_Mass", "solids": 1,
                                 "voids": 0, "warnings": ["w1"],
                                 "skips": ["s1", "s2"]})
        self.assertEqual(lines, [
            "Made **Box_Mass**: 1 solid piece(s), 0 converted void(s).",
            "- Warning: w1",
            "- Skipped: s1",
            "- Skipped: s2",
            mp.SHOW_MASS_NOTE,
        ])

    def test_missing_lists_tolerated(self):
        lines = mp.report_lines({"family": "Box_Mass", "solids": 1,
                                 "voids": 0})
        self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_mass_plan -v` (from the repo root)
Expected: ERROR -- `ImportError: cannot import name 'mass_plan' from 'BG'`.

- [ ] **Step 3: Write the module**

Create `EXT/lib/BG/mass_plan.py`:

```python
# -*- coding: utf-8 -*-
"""The plain-Python half of Element To Mass.

Element To Mass turns one element into a conceptual mass standing where
the element stands: its finished solid, and each of its family's voids
trimmed to the volume it actually cut.  Reading that geometry is Revit
work and lives in mass_build.  What is left over -- what the family is
called, which template it starts from, whether the voids account for
what was cut away, which instance values can be copied into a family,
and what the report says -- is here.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.
"""

import re

# The subcategory the converted voids are put on, inside the mass
# family, so they can be coloured, filtered or hidden apart from the
# solid.
VOID_SUBCATEGORY = "Converted Void"

MASS_SUFFIX = "_Mass"
FALLBACK_NAME = "Element"

# Cubic feet.  A solid smaller than this is a sliver from a boolean,
# not a piece of the element.
VOLUME_EPS = 1e-6

# The converted voids must account for the volume cut away to within
# this fraction of the uncut volume, or the report warns.
VOLUME_REL_TOL = 0.01

# Feet.  A placed mass further than this from where it was meant to go
# is moved there.
PLACE_TOL = 1e-4

SHOW_MASS_NOTE = ("Masses show only where the Mass category is visible -- "
                  "turn on Show Mass if you cannot see it.")

# The characters Revit refuses in a family name.
_REFUSED = re.compile(r'[\\:{}\[\]|;<>?`~]')

_COPYABLE_STORAGE = ("Double", "Integer", "String")


def family_base_name(source_name):
    """'<source>_Mass', with the characters Revit refuses replaced by '_'."""
    cleaned = _REFUSED.sub("_", source_name or "").strip()
    return (cleaned or FALLBACK_NAME) + MASS_SUFFIX


def unique_name(base, taken):
    """base, or base_2, base_3 ... -- the first one not in taken."""
    name, n = base, 1
    while name in taken:
        n += 1
        name = "{}_{}".format(base, n)
    return name


def pick_template(candidates, exists):
    """The first candidate path for which exists(path) is true, or None."""
    for path in candidates:
        if path and exists(path):
            return path
    return None


def volume_check(uncut, cut, voids, rel_tol=VOLUME_REL_TOL):
    """None when the converted voids account for what was cut away.

    uncut -- volume of the family's solids with every void deleted
    cut   -- volume of the finished element
    voids -- volumes of the converted void pieces

    A disagreement is how a type or instance value that did not carry
    into the family copy shows up, so it is worth a line in the report.
    """
    removed = uncut - cut
    converted = sum(voids)
    if abs(removed - converted) <= rel_tol * abs(uncut) + VOLUME_EPS:
        return None
    return ("converted voids hold {:.3f} cu ft but {:.3f} cu ft was cut away "
            "(uncut {:.3f}, finished {:.3f}) - check the family's type and "
            "instance parameters".format(converted, removed, uncut, cut))


def instance_value_plan(params):
    """Which instance values to copy from the element into the family.

    params -- (name, storage, is_instance, has_formula, is_reporting)
              tuples, storage being the StorageType's name.

    Returns (names to copy, [(name, reason) skipped]).  Type parameters
    are neither: the family type is matched as a whole instead.
    """
    copy, skipped = [], []
    for name, storage, is_instance, has_formula, is_reporting in params:
        if not is_instance:
            continue
        if has_formula:
            skipped.append((name, "set by a formula"))
        elif is_reporting:
            skipped.append((name, "reporting parameter"))
        elif storage == "ElementId":
            skipped.append(
                (name, "ElementId values do not carry across documents"))
        elif storage not in _COPYABLE_STORAGE:
            skipped.append((name, "no value to copy"))
        else:
            copy.append(name)
    return copy, skipped


def report_lines(result):
    """The closing report, one markdown line per entry."""
    lines = ["Made **{}**: {} solid piece(s), {} converted void(s).".format(
        result["family"], result["solids"], result["voids"])]
    for text in result.get("warnings", []):
        lines.append("- Warning: {}".format(text))
    for text in result.get("skips", []):
        lines.append("- Skipped: {}".format(text))
    lines.append(SHOW_MASS_NOTE)
    return lines
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_mass_plan -v`
Expected: 28 tests, all PASS.

Run: `python -m unittest discover -s tests`
Expected: `Ran 680 tests` ... `OK`.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/BG/mass_plan.py" tests/test_mass_plan.py
git commit -m "feat: mass_plan, the Revit-free half of Element To Mass"
```

---

### Task 2: `BG.mass_build` -- picking and reading the finished solid

**Files:**
- Create: `EXT/lib/BG/mass_build.py`

**Interfaces:**
- Consumes: `BG.mass_plan` -- `VOLUME_EPS`.
- Produces:
  - `HOST = "In this model"`, `LINK = "In a link"`
  - `selected_source(uidoc)` -> `(element, source_doc, link_tf)` or `None`
  - `pick_source(uidoc, where)` -> `(element, source_doc, link_tf)` or `None`; `where` is `HOST` or `LINK`
  - `element_solids(element, transform)` -> list of new `Solid`s, copied through `transform`
  - `source_name(element)` -> `str`, the family name for a family instance, else the element's own name

- [ ] **Step 1: Set up the undefined-name checker**

`py_compile` cannot see a NameError, and none of this runs outside Revit. The checker already exists in an earlier plan. Copy it into `%TEMP%` -- **not into the repo**:

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

Create `EXT/lib/BG/mass_build.py`:

```python
# -*- coding: utf-8 -*-
"""The Revit half of Element To Mass.

One element -- in this model or in a link -- becomes a conceptual mass
standing where it stands.  Two kinds of geometry go into it:

  * the FINISHED solid, read from the element itself, voids already
    cut;
  * each of the family's VOIDS, read from a copy of the family and
    trimmed to the volume it actually removed.

A void leaves nothing in the finished geometry but a hole, so it can
only be read from the family definition.  EditFamily hands back a COPY,
and everything done to it happens in a transaction that is rolled back;
the source family and the link are never modified.

The names, the checks and the report text are in mass_plan, which
imports no Revit and is unit-tested.  This module is verified by
running the tool.
"""

import os
import tempfile

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    BooleanOperationsType,
    BooleanOperationsUtils,
    Element,
    ElementId,
    ElementTransformUtils,
    Family,
    FamilyInstance,
    FilteredElementCollector,
    FreeFormElement,
    GenericForm,
    GeometryInstance,
    Options,
    RevitLinkInstance,
    SaveAsOptions,
    Solid,
    SolidUtils,
    StorageType,
    SubTransaction,
    Transaction,
    Transform,
    ViewDetailLevel,
    XYZ,
)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ObjectType

from BG import mass_plan

HOST = "In this model"
LINK = "In a link"


# ===========================================================================
# PICKING
# ===========================================================================

def selected_source(uidoc):
    """The pre-selected element, when exactly one host element is selected.

    A selected link instance does not count: it is the whole link, not
    an element in it, and the user is asked instead.
    """
    doc = uidoc.Document
    ids = list(uidoc.Selection.GetElementIds())
    if len(ids) != 1:
        return None
    elem = doc.GetElement(ids[0])
    if elem is None or isinstance(elem, RevitLinkInstance):
        return None
    return elem, doc, Transform.Identity


def pick_source(uidoc, where):
    """(element, the document it lives in, link transform), or None.

    The link transform is identity for an element in this model.
    """
    doc = uidoc.Document
    try:
        if where == HOST:
            ref = uidoc.Selection.PickObject(
                ObjectType.Element, "Pick the element to turn into a mass")
            return doc.GetElement(ref.ElementId), doc, Transform.Identity
        ref = uidoc.Selection.PickObject(
            ObjectType.LinkedElement,
            "Pick the linked element to turn into a mass")
    except OperationCanceledException:
        return None

    link = doc.GetElement(ref.ElementId)
    link_doc = link.GetLinkDocument()
    if link_doc is None:
        return None
    return (link_doc.GetElement(ref.LinkedElementId), link_doc,
            link.GetTotalTransform())


def source_name(element):
    """What the mass family is named after."""
    if isinstance(element, FamilyInstance):
        return element.Symbol.Family.Name
    try:
        return Element.Name.GetValue(element)
    except Exception:
        return ""


# ===========================================================================
# THE FINISHED SOLID
# ===========================================================================

def _options():
    opt = Options()
    opt.DetailLevel = ViewDetailLevel.Fine
    return opt


def _walk_solids(geom):
    """Every solid with volume in a geometry element, nested ones too.

    GetInstanceGeometry is already in the owning document's
    coordinates, so a nested family or a family instance's symbol
    geometry needs no transform of its own here.
    """
    for obj in geom or []:
        if isinstance(obj, Solid):
            if obj.Volume > mass_plan.VOLUME_EPS:
                yield obj
        elif isinstance(obj, GeometryInstance):
            for solid in _walk_solids(obj.GetInstanceGeometry()):
                yield solid


def element_solids(element, transform):
    """The element's solids, COPIED through transform.

    CreateTransformed always makes a new solid, so nothing returned
    belongs to the element's document -- which matters for the family
    copy, whose elements are gone once its transaction is rolled back.
    """
    geom = element.get_Geometry(_options())
    return [SolidUtils.CreateTransformed(s, transform)
            for s in _walk_solids(geom)]
```

- [ ] **Step 3: Compile and check names**

Run:

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && python -m py_compile "Revit API/pyRevit-Tools.extension/lib/BG/mass_build.py" && python "$TEMP/undefined_names.py" "Revit API/pyRevit-Tools.extension/lib/BG/mass_build.py"
```

Expected: `OK - mass_build.py`. Imports not used yet (for example `Family`, `SubTransaction`) are fine at this stage; they are used in Tasks 3 and 4.

- [ ] **Step 4: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/BG/mass_build.py"
git commit -m "feat: mass_build reads the picked element's finished solid"
```

---

### Task 3: `BG.mass_build` -- reading the voids

**Files:**
- Modify: `EXT/lib/BG/mass_build.py` (append after `element_solids`)

**Interfaces:**
- Consumes: `element_solids` (Task 2); `mass_plan.instance_value_plan`, `mass_plan.VOLUME_EPS` (Task 1).
- Produces:
  - `VoidResult` -- plain class with `.voids` (list of `Solid` in host coordinates), `.uncut` (float, cu ft), `.warnings` (list of str), `.skips` (list of str), `.read` (bool: the family was opened and read)
  - `family_voids(source_doc, element, link_tf)` -> `VoidResult`

- [ ] **Step 1: Append the void reading**

Append to `EXT/lib/BG/mass_build.py`:

```python
# ===========================================================================
# THE VOIDS
# ===========================================================================

class VoidResult(object):
    """What family_voids found.

    voids    -- converted void pieces, in host coordinates
    uncut    -- volume of the family's solids with every void deleted
    warnings -- things that may have made the voids wrong
    skips    -- things deliberately left out
    read     -- whether the family was opened and read at all
    """

    def __init__(self):
        self.voids = []
        self.uncut = 0.0
        self.warnings = []
        self.skips = []
        self.read = False


def family_voids(source_doc, element, link_tf):
    """The family's voids, each trimmed to the volume it cut."""
    result = VoidResult()
    if not isinstance(element, FamilyInstance):
        result.skips.append("not a family instance, so it has no family "
                            "voids to read")
        return result

    family = element.Symbol.Family
    try:
        fam_doc = source_doc.EditFamily(family)
    except Exception as ex:
        result.warnings.append(
            "voids not read: Revit would not open family '{}' ({})".format(
                family.Name, ex))
        return result

    try:
        cutters, uncut = _read_family(fam_doc, element, result)
    finally:
        fam_doc.Close(False)

    to_host = link_tf.Multiply(element.GetTotalTransform())
    union = _union(uncut)
    for cutter in cutters:
        pieces = _intersect(cutter, union, uncut)
        if not pieces:
            result.skips.append("a void that cuts nothing in its own family "
                                "(it may cut host elements)")
            continue
        result.voids.extend(SolidUtils.CreateTransformed(p, to_host)
                            for p in pieces)

    result.uncut = sum(s.Volume for s in uncut)
    result.read = True
    return result


def _read_family(fam_doc, element, result):
    """(void solids, uncut solids) from the family copy, both copied out.

    Everything happens in one transaction that is ALWAYS rolled back,
    and every solid is copied before it is, because the elements it
    came from do not survive the rollback.
    """
    t = Transaction(fam_doc, "Element To Mass - read voids")
    t.Start()
    try:
        _match_type(fam_doc, element, result)
        _copy_instance_values(fam_doc, element, result)
        fam_doc.Regenerate()

        void_forms = [f for f in _forms(fam_doc) if not f.IsSolid]
        cutters = []
        for form in void_forms:
            solids = element_solids(form, Transform.Identity)
            if not solids:
                result.warnings.append(
                    "void form {} gave no geometry".format(_id_text(form.Id)))
            cutters.extend(solids)

        if void_forms:
            fam_doc.Delete(List[ElementId]([f.Id for f in void_forms]))
            fam_doc.Regenerate()

        uncut = []
        for elem in _solid_elements(fam_doc):
            uncut.extend(element_solids(elem, Transform.Identity))
    finally:
        t.RollBack()
    return cutters, uncut


def _forms(fam_doc):
    """Every form in the family: extrusions, blends, sweeps, free forms."""
    return [e for e in FilteredElementCollector(fam_doc)
            .WhereElementIsNotElementType()
            if isinstance(e, GenericForm)]


def _solid_elements(fam_doc):
    """What holds the family's solid geometry: solid forms and nested
    family instances."""
    solid_forms = [f for f in _forms(fam_doc) if f.IsSolid]
    nested = list(FilteredElementCollector(fam_doc).OfClass(FamilyInstance))
    return solid_forms + nested


def _match_type(fam_doc, element, result):
    """Set the family copy to the element's own type."""
    fm = fam_doc.FamilyManager
    wanted = Element.Name.GetValue(element.Symbol)
    for ftype in fm.Types:
        if ftype.Name == wanted:
            fm.CurrentType = ftype
            return
    result.warnings.append(
        "the family has no type named '{}', so its voids were read at its "
        "current type".format(wanted))


def _copy_instance_values(fam_doc, element, result):
    """Give the family copy the element's own instance values.

    Without this a void sized by an instance parameter would be read at
    the family's default size.
    """
    fm = fam_doc.FamilyManager
    by_name = {}
    specs = []
    for fp in fm.Parameters:
        name = fp.Definition.Name
        by_name[name] = fp
        specs.append((name, str(fp.StorageType), fp.IsInstance,
                      bool(fp.Formula), fp.IsReporting))

    names, _skipped = mass_plan.instance_value_plan(specs)
    for name in names:
        src = element.LookupParameter(name)
        if src is None or not src.HasValue:
            continue
        fp = by_name[name]
        try:
            if fp.StorageType == StorageType.Double:
                fm.Set(fp, src.AsDouble())
            elif fp.StorageType == StorageType.Integer:
                fm.Set(fp, src.AsInteger())
            else:
                fm.Set(fp, src.AsString() or "")
        except Exception as ex:
            result.warnings.append(
                "instance parameter '{}' could not be copied ({}); a void it "
                "sizes may be off".format(name, ex))


def _union(solids):
    """One solid for all of them, or None if a boolean fails."""
    if not solids:
        return None
    try:
        whole = solids[0]
        for solid in solids[1:]:
            whole = BooleanOperationsUtils.ExecuteBooleanOperation(
                whole, solid, BooleanOperationsType.Union)
        return whole
    except Exception:
        return None


def _intersect(cutter, union, uncut):
    """The part of cutter inside the uncut solid, as a list of solids.

    Against the union when there is one; against each uncut solid in
    turn when the union failed.
    """
    targets = [union] if union is not None else uncut
    pieces = []
    for target in targets:
        try:
            piece = BooleanOperationsUtils.ExecuteBooleanOperation(
                cutter, target, BooleanOperationsType.Intersect)
        except Exception:
            continue
        if piece is not None and piece.Volume > mass_plan.VOLUME_EPS:
            pieces.append(piece)
    return pieces


def _id_text(element_id):
    """An ElementId as text, whichever Revit version this is."""
    for attr in ("Value", "IntegerValue"):
        try:
            return str(getattr(element_id, attr))
        except Exception:
            continue
    return str(element_id)
```

- [ ] **Step 2: Compile and check names**

Run:

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && python -m py_compile "Revit API/pyRevit-Tools.extension/lib/BG/mass_build.py" && python "$TEMP/undefined_names.py" "Revit API/pyRevit-Tools.extension/lib/BG/mass_build.py"
```

Expected: `OK - mass_build.py`.

- [ ] **Step 3: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/BG/mass_build.py"
git commit -m "feat: mass_build reads family voids trimmed to what they cut"
```

---

### Task 4: Building, placing, and the button

**Files:**
- Modify: `EXT/lib/BG/mass_build.py` (append after `_id_text`)
- Modify: `EXT/lib/BG/__init__.py` (docstring)
- Create: `EXT/Tahir_Tools.tab/Usage.panel/ElementToMass.pushbutton/script.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces:
  - `origin_of(solids)` -> `XYZ`, the XY minimum of all pieces at Z = 0
  - `template_candidates(app)` -> list of `str`
  - `build_mass_family(app, template, solids, voids, name, origin)` -> `(rfa_path, made_solids, made_voids, failed)`; `failed` is a list of str; raises if nothing could be built
  - `load_and_place(doc, rfa_path, name, origin)` -> the placed `FamilyInstance`; raises after rolling back on any failure

- [ ] **Step 1: Append building and placing**

Append to `EXT/lib/BG/mass_build.py`:

```python
# ===========================================================================
# THE MASS FAMILY
# ===========================================================================

def origin_of(solids):
    """Where the family's own origin goes: the XY minimum of every piece,
    at Z = 0.

    Built around this point instead of the project origin, so a mass for
    an element miles from the origin does not sit miles from its own.
    It need not be exact -- the pieces are shifted by it and the
    instance placed at it -- so edge points are enough.
    """
    xs, ys = [], []
    for solid in solids:
        for edge in solid.Edges:
            for p in edge.Tessellate():
                xs.append(p.X)
                ys.append(p.Y)
    if not xs:
        return XYZ.Zero
    return XYZ(min(xs), min(ys), 0.0)


def template_candidates(app):
    """The mass templates to try, in order."""
    root = os.path.join(app.FamilyTemplatePath, "Conceptual Mass")
    return [os.path.join(root, "Metric Mass.rft"),
            os.path.join(root, "Mass.rft")]


def build_mass_family(app, template, solids, voids, name, origin):
    """Make, save and close the mass family.

    Returns (rfa path, solids made, voids made, failure notes).  A piece
    FreeFormElement refuses is noted and the rest go on; if no piece at
    all could be made, it raises.
    """
    shift = Transform.CreateTranslation(origin.Negate())
    failed = []
    fam_doc = app.NewFamilyDocument(template)
    try:
        t = Transaction(fam_doc, "Element To Mass - build")
        t.Start()
        try:
            sub = fam_doc.Settings.Categories.NewSubcategory(
                fam_doc.OwnerFamily.FamilyCategory,
                mass_plan.VOID_SUBCATEGORY)
            made_solids = _create_forms(fam_doc, solids, shift, None,
                                        "solid", failed)
            made_voids = _create_forms(fam_doc, voids, shift, sub,
                                       "converted void", failed)
            t.Commit()
        except Exception:
            t.RollBack()
            raise
        if made_solids + made_voids == 0:
            raise Exception("Revit refused every piece: {}".format(
                "; ".join(failed)))

        path = os.path.join(tempfile.gettempdir(), name + ".rfa")
        opts = SaveAsOptions()
        opts.OverwriteExistingFile = True
        fam_doc.SaveAs(path, opts)
    finally:
        fam_doc.Close(False)
    return path, made_solids, made_voids, failed


def _create_forms(fam_doc, solids, shift, subcategory, label, failed):
    """One FreeFormElement per solid; returns how many were made.

    Each in its own SubTransaction, so a refused piece is undone cleanly
    and does not spoil the ones around it.
    """
    made = 0
    for i, solid in enumerate(solids):
        st = SubTransaction(fam_doc)
        st.Start()
        try:
            form = FreeFormElement.Create(
                fam_doc, SolidUtils.CreateTransformed(solid, shift))
            if subcategory is not None:
                form.Subcategory = subcategory
            st.Commit()
            made += 1
        except Exception as ex:
            st.RollBack()
            failed.append("{} piece {} refused by Revit ({})".format(
                label, i + 1, ex))
    return made


# ===========================================================================
# LOAD AND PLACE
# ===========================================================================

def load_and_place(doc, rfa_path, name, origin):
    """Load the family, place it at origin, and make sure it is there.

    Revit may place a mass relative to a level or work plane; comparing
    the placed instance's transform origin with where it was meant to
    go, and moving it by the difference, makes the result right however
    it was placed.  One transaction: a failure leaves the host as it was.
    """
    t = Transaction(doc, "Element To Mass")
    t.Start()
    try:
        doc.LoadFamily(rfa_path)
        family = None
        for fam in FilteredElementCollector(doc).OfClass(Family):
            if fam.Name == name:
                family = fam
                break
        if family is None:
            raise Exception("family '{}' did not load".format(name))

        symbol = doc.GetElement(list(family.GetFamilySymbolIds())[0])
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()

        inst = doc.Create.NewFamilyInstance(origin, symbol,
                                            StructuralType.NonStructural)
        doc.Regenerate()
        delta = origin.Subtract(inst.GetTotalTransform().Origin)
        if delta.GetLength() > mass_plan.PLACE_TOL:
            ElementTransformUtils.MoveElement(doc, inst.Id, delta)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    finally:
        try:
            os.remove(rfa_path)
        except Exception:
            pass
    return inst
```

- [ ] **Step 2: Name the new modules in the library's docstring**

In `EXT/lib/BG/__init__.py`, the docstring's second paragraph currently reads:

```
Two halves, and the split is deliberate.  wall_bands, wall_constraints,
wall_limits, wall_miter, wall_naming, plan_shapes, sweep_geom,
dup_check, wall_overlap and param_push import nothing from Revit at
all, so they are unit-tested in ordinary CPython outside it.  soffit,
wall_chain, wall_materials, wall_sketch, wall_skin, window_cw,
link_copy and roof_sweep do talk to the Revit API, and are verified by
running the tools.
```

Replace it with:

```
Two halves, and the split is deliberate.  wall_bands, wall_constraints,
wall_limits, wall_miter, wall_naming, plan_shapes, sweep_geom,
dup_check, wall_overlap, param_push and mass_plan import nothing from
Revit at all, so they are unit-tested in ordinary CPython outside it.
soffit, wall_chain, wall_materials, wall_sketch, wall_skin, window_cw,
link_copy, roof_sweep and mass_build do talk to the Revit API, and are
verified by running the tools.
```

If the paragraph on disk differs from the quoted text (the module lists have grown before), add `mass_plan` to the Revit-free list and `mass_build` to the Revit-facing list and leave the rest as it is.

- [ ] **Step 3: Write the button**

Create `EXT/Tahir_Tools.tab/Usage.panel/ElementToMass.pushbutton/script.py`:

```python
# -*- coding: utf-8 -*-
"""Turn one element into a conceptual mass, in place.

Pick an element -- in this model or in a link -- or pre-select one in
this model.  A new mass family is made, loaded and placed exactly where
the element stands, holding:

  * the element's finished solid geometry, and
  * every void of its family, trimmed to the volume it actually cut and
    made solid, on its own "Converted Void" subcategory.

The original element is left exactly as it is, and a linked model is
never modified.  Each run makes a new family.

Masses show only where the Mass category is visible: turn on Show Mass
if the result cannot be seen.
"""

import os
import traceback

from Autodesk.Revit.DB import Family, FilteredElementCollector
from pyrevit import revit, forms, script

from BG import mass_build, mass_plan

__title__ = "Element\nTo Mass"

doc    = revit.doc
uidoc  = revit.uidoc
app    = doc.Application
logger = script.get_logger()
output = script.get_output()

TOOL_TITLE = "Element To Mass"


def choose_source():
    """The element to convert, from the selection or a pick, or None."""
    picked = mass_build.selected_source(uidoc)
    if picked is not None:
        return picked
    where = forms.CommandSwitchWindow.show(
        [mass_build.HOST, mass_build.LINK],
        message="Where is the element to turn into a mass?")
    if not where:
        return None
    return mass_build.pick_source(uidoc, where)


def choose_template():
    """The mass template, found or browsed for; None if cancelled."""
    found = mass_plan.pick_template(
        mass_build.template_candidates(app), os.path.exists)
    if found:
        return found
    forms.alert("No conceptual mass template was found in the default "
                "template folder. Browse for a mass .rft.",
                title=TOOL_TITLE)
    return forms.pick_file(file_ext="rft")


def existing_family_names():
    return set(f.Name for f in FilteredElementCollector(doc).OfClass(Family))


def main():
    picked = choose_source()
    if picked is None:
        return          # cancelled: make nothing, report nothing
    element, source_doc, link_tf = picked
    if element is None:
        return

    solids = mass_build.element_solids(element, link_tf)
    if not solids:
        forms.alert("The picked element has no solid geometry to turn "
                    "into a mass.", title=TOOL_TITLE)
        return

    template = choose_template()
    if not template:
        return

    voids = mass_build.family_voids(source_doc, element, link_tf)
    warnings = list(voids.warnings)
    if voids.read and voids.voids:
        mismatch = mass_plan.volume_check(
            voids.uncut,
            sum(s.Volume for s in solids),
            [s.Volume for s in voids.voids])
        if mismatch:
            warnings.append(mismatch)

    name = mass_plan.unique_name(
        mass_plan.family_base_name(mass_build.source_name(element)),
        existing_family_names())
    origin = mass_build.origin_of(solids + voids.voids)

    try:
        path, made_solids, made_voids, failed = mass_build.build_mass_family(
            app, template, solids, voids.voids, name, origin)
        mass_build.load_and_place(doc, path, name, origin)
    except Exception as ex:
        logger.debug(traceback.format_exc())
        forms.alert("The mass could not be made; the model is unchanged.\n\n"
                    "{}".format(ex), title=TOOL_TITLE)
        return

    for line in mass_plan.report_lines({
            "family": name,
            "solids": made_solids,
            "voids": made_voids,
            "warnings": warnings + failed,
            "skips": voids.skips}):
        output.print_md(line)


main()
```

- [ ] **Step 4: Compile and check names**

Run:

```bash
cd "C:/Users/TahirSanwarwala/AppData/Roaming/Github_Tahir/BIM_Automation_Tools" && for f in "Revit API/pyRevit-Tools.extension/lib/BG/mass_build.py" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Usage.panel/ElementToMass.pushbutton/script.py" "Revit API/pyRevit-Tools.extension/lib/BG/__init__.py"; do python -m py_compile "$f" && python "$TEMP/undefined_names.py" "$f"; done
```

Expected: three `OK - ...` lines.

Run: `python -m unittest discover -s tests`
Expected: `Ran 680 tests` ... `OK`.

- [ ] **Step 5: Commit**

```bash
git add "Revit API/pyRevit-Tools.extension/lib/BG/mass_build.py" "Revit API/pyRevit-Tools.extension/lib/BG/__init__.py" "Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Usage.panel/ElementToMass.pushbutton/script.py"
git commit -m "feat: Element To Mass button builds and places the mass"
```

---

### Task 5: Manual checks in Revit (the user runs these)

Nothing here is automated. Reload pyRevit, then run **Element To Mass** from Usage.panel against each case below, with Show Mass on. The risks are listed in the spec's order, so the first runs answer the open questions first.

- [ ] **Loadable family with an oversized void cutting a recess.** Expected: one mass in place; the recess is filled by a `Converted Void` piece that does not stick out of the element; no volume warning.
- [ ] **In-place family with a void (spec risk 1).** Expected: either the same result, or a solid-only mass and a warning that Revit would not open the family. Either is acceptable; report which.
- [ ] **The same loadable family picked through a link (spec risk 2).** Expected: the mass lands on the linked element; the link is unchanged.
- [ ] **A void form whose geometry Revit does not return (spec risk 3).** Shows up as a `void form <id> gave no geometry` warning in any of the runs above. Report it if seen.
- [ ] **The loadable family mirrored (spec risk 4).** Expected: the mass is mirrored the same way and is a valid solid.
- [ ] **A family whose void is sized by an instance parameter, set away from its default.** Expected: the void piece matches the element's recess, not the default size.
- [ ] **An element far from the project origin.** Expected: no far-from-origin warning, and the mass sits on the element.
- [ ] **A wall.** Expected: a solid-only mass, and the report skips "not a family instance".
- [ ] **The same element converted twice.** Expected: `<name>_Mass` then `<name>_Mass_2`.
- [ ] **Undo once after a run.** Expected: the mass and its family load are undone together.

Report anything unexpected back with the report text from the pyRevit output window.
