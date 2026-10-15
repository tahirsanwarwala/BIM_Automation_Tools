# Element To Mass — Design

Date: 2026-10-15
Status: approved for planning

A new pushbutton that turns one picked element into a conceptual mass
standing exactly where the element stands -- its solid geometry, and
the volume its family's voids cut away, rebuilt as solid too.

## Purpose

The Dynamo graph this replaces (`Mass python.py`) already makes real
mass families from Dynamo solids. Two things are wrong with it for daily
use: it needs Dynamo and a graph wired up for every run, and it only
ever sees the FINISHED geometry. A void in a family leaves nothing
behind in the finished geometry except a hole, so the graph has no way
to give the recess, the opening or the reveal a mass of its own.

This tool reads the element directly in Revit 2025 through pyRevit, and
it reads the voids from the family definition itself.

## Scope

In scope:

  * one element per run, picked in the host model or in a linked model;
  * loadable family instances and in-place families -- every family
    instance -- and, as a free consequence of how the solid is read,
    any other element with solid geometry (a wall, a floor), which
    simply has no voids to convert;
  * ONE mass family per run holding both the solid geometry and the
    converted voids, loaded into the host model and placed in the
    element's own position.

Out of scope, and each for a reason:

  * **Walls by face.** Asked for, then withdrawn on 2026-10-15. Nothing
    here creates walls; the mass is the whole output.
  * **Nested void families.** A void that lives inside a nested family
    instance is not a form of the picked family. Reported, not converted.
  * **Voids that cut the host.** A family void set to cut host
    geometry when loaded, and cutting nothing in its own family, has no
    "volume it removed" in the family. Reported, not converted.
  * **The original element.** Left exactly as it is. It is never
    hidden, moved or deleted, and a linked model is never modified.

## Code structure

### New: `lib/BG/mass_plan.py` -- no Revit import

Plain Python, so `tests/` can run it in ordinary CPython, the same split
`lib/BG/__init__.py` already draws. Its docstring gets `mass_plan` added
to the Revit-free list and `mass_build` to the Revit-facing one.

  * `family_base_name(source_name)` -- `<source>_Mass`, with the
    characters Revit refuses in a family name (`\ : { } [ ] | ; < > ? ` ~`)
    replaced by `_`. An empty source name gives `Element_Mass`.
  * `unique_name(base, taken)` -- `base`, or `base_2`, `base_3` ... the
    first not in `taken`.
  * `pick_template(candidates, exists)` -- the first template path that
    exists; `exists` is passed in so the test needs no file system.
  * `volume_check(uncut, cut, voids, rel_tol)` -- whether the converted
    voids account for what was cut away: `uncut - cut` against the sum of
    the void pieces. Returns `None` when they agree within tolerance,
    else a one-line warning with the three volumes in cubic feet.
  * `instance_value_plan(params)` -- given `(name, storage, is_instance,
    has_formula)` tuples, the names whose instance values get copied
    into the family document (see step 3), and the names skipped with
    the reason.
  * `report_lines(result)` -- the text of the closing report from a plain
    dict of counts, warnings and skips.

### New: `lib/BG/mass_build.py` -- Revit-facing

  * `pick_source(uidoc)` -- the picked element, the document it lives
    in, and the link transform (identity in the host).
  * `element_solids(element, link_tf)` -- the finished solids.
  * `family_voids(source_doc, instance, link_tf)` -- the converted voids,
    the uncut volume, and the skip reasons.
  * `build_mass_family(app, template, solids, voids, name, origin)` --
    the saved `.rfa` path, and a reason for every piece that failed.
  * `load_and_place(doc, rfa_path, name, origin, expected_min)` -- the
    placed instance.

### New: `Tahir_Tools.tab/Usage.panel/ElementToMass.pushbutton/script.py`

The flow below, the transaction group, and the report. A standalone
button on Usage.panel: Skin.stack already holds three buttons, which is
all a stack shows, and this tool is not B&G-specific.

### New: `tests/test_mass_plan.py`

## Data flow

### 1. Pick

If exactly one element is pre-selected in the host, it is used.
Otherwise a two-button switch asks **In this model** or **In a link**,
then `PickObject` with `ObjectType.Element` or `ObjectType.LinkedElement`.
For a linked pick the source document is the link's document and
`link_tf` is `RevitLinkInstance.GetTotalTransform()`.

### 2. The solid

`element.get_Geometry` with `Options(DetailLevel=Fine)`, walked
recursively: a `GeometryInstance` contributes `GetInstanceGeometry()`,
already in the source document's coordinates. Every `Solid` with volume
above `1e-6` ft³ is kept, copied through `SolidUtils.CreateTransformed`
with `link_tf`, so nothing held afterwards belongs to the source
document.

This is the finished geometry: voids already cut, joins already made.

### 3. The voids

Only for a `FamilyInstance`. The family is opened with
`source_doc.EditFamily(family)`, which hands back a COPY -- nothing is
ever saved into the source family.

Inside one transaction in the family copy, always rolled back:

  1. `FamilyManager.CurrentType` is set to the type named like the
     instance's own type.
  2. Instance parameter values are copied from the instance onto the
     family's matching instance parameters -- Double, Integer and String
     storage, and only parameters with no formula. ElementId parameters
     (materials, nested types) are skipped: ids do not carry across
     documents, and they do not drive geometry. Without this step a void
     sized by an instance parameter would come out at the family's
     default size.
  3. Regenerate.
  4. Every `GenericForm` with `IsSolid == False` is a void. Its geometry
     is read and copied out with `SolidUtils.Clone` BEFORE anything is
     deleted.
  5. The voids are deleted and the document regenerated. Every solid
     left in the family is now UNCUT, and is copied out the same way.

The family copy is then closed without saving.

Each void is intersected with the union of the uncut solids
(`BooleanOperationsUtils`, `Intersect`). What survives is the volume
that void actually removed, so an oversized cutter becomes exactly the
recess it made. If the union fails, the void is intersected with each
uncut solid in turn instead. A void whose intersection is empty is
reported as cutting nothing in its own family.

Every piece is then moved into project coordinates by
`instance.GetTotalTransform()` followed by `link_tf`.

The check: `volume_check(uncut, cut, voids)`, where `cut` is the volume
of the step-2 solids. A disagreement is a warning in the report, not a
failure -- it is how a type or parameter mismatch in steps 1-2 shows up.

### 4. The mass family

`app.NewFamilyDocument` from the first existing of
`<FamilyTemplatePath>\Conceptual Mass\Metric Mass.rft` and `...\Mass.rft`.
If neither exists, the user browses for a `.rft` once.

The geometry is built around a local origin: `origin` is the XY of the
minimum corner of all pieces, at Z = 0, and every piece is translated
by `-origin` before it goes in. A mass built at project coordinates
could sit miles from the family's own origin, which is where Revit
starts to warn and to lose precision.

Inside one transaction:

  * a `Converted Void` subcategory is created under the family's Mass
    category;
  * every solid becomes one `FreeFormElement.Create`;
  * every void piece becomes one too, and its `Subcategory` is set to
    `Converted Void`, so the voids can be coloured, filtered or hidden
    apart from the solid.

A piece `FreeFormElement` refuses is reported and the rest go on. The
family is saved as `<name>.rfa` in the temp folder and closed.

### 5. Load and place

`doc.LoadFamily`, the family's only symbol activated, and
`NewFamilyInstance(origin, symbol, NonStructural)`. The placed
instance's bounding-box minimum is then compared with the expected
one; if they differ by more than `1e-4` ft the instance is moved by the
difference. This makes the result right whatever level or work plane
offset Revit applies when it places a mass.

Step 4 touches only the new family document. Step 5 -- load, place and
the corrective move -- runs inside one host `TransactionGroup`,
"Element To Mass", so a failure leaves the host model as it was. The
temp `.rfa` is deleted after loading.

## Error handling

  * Nothing picked, or the pick cancelled: the tool exits quietly.
  * No solid geometry: an alert, and no family is made.
  * `EditFamily` refuses (expected for some in-place families and
    possibly for linked documents -- see Risks): the mass is built from
    the solid alone and the report says the voids were not read and why.
  * No void forms in the family: not a warning; the report says
    "0 voids".
  * A failure in step 4 closes the family document unsaved; one in step
    5 rolls back the transaction group. Either way the host is unchanged
    and the exception text is shown.

## Re-runs

Each run makes a new family under a unique name. Nothing is matched
against an earlier mass; deleting an unwanted one is the user's call.

## Decisions

  * **One family, voids on a subcategory.** Chosen over two families.
    The subcategory keeps the voids separable for anyone who wants to
    tell them apart.
  * **Voids trimmed to what they cut.** Chosen over rebuilding the void
    form as drawn, because cutters are routinely drawn oversized.
  * **Solid from the instance, uncut solid from the family.** The
    instance's own geometry is the truth for what is there; only what is
    missing needs the family.
  * **Instance values copied, ElementIds skipped.** See step 3.
  * **Local origin plus a corrective move.** See steps 4 and 5.

## Risks

To be checked in the first manual runs, in this order:

  1. **In-place families.** The API may refuse `EditFamily` on an
     in-place family. If it does, in-place voids cannot be read and the
     fallback above applies.
  2. **Linked documents.** `EditFamily` on a family in a link's document
     is expected to work and is not yet confirmed.
  3. **Void form geometry.** A void `GenericForm`'s `get_Geometry` is
     expected to return its solid in the family document; if it returns
     nothing, the void cannot be read that way.
  4. **Mirrored instances.** `GetTotalTransform` carries the mirror;
     `CreateTransformed` must keep the solid valid under it.

## Testing

  * `tests/test_mass_plan.py` covers every function in `mass_plan`:
    name cleaning and uniqueness, template choice, the volume check on
    both sides of its tolerance, the instance-value plan's skips, and the
    report text.
  * The Revit half is verified by the user running the tool. Nothing
    drives an open Revit session from outside. Cases: a loadable family
    with an oversized void cutting a recess; the same family mirrored;
    one whose void is sized by an instance parameter; an in-place family
    with a void; the same loadable family picked through a link; an
    element far from the project origin; a wall (solid only).
