# Copy Roof Sweeps From Link — Design

Date: 2026-09-10
Status: approved for planning

A new pushbutton in BG Tools that brings fascias and gutters out of a
linked model into the host, standing on the host's own roofs.

## Purpose

The roofs have already been copied into the host model. The fascias and
gutters on them have not, because they cannot be: `Copy/Paste Aligned`
and `ElementTransformUtils.CopyElements` both answer **"Can't copy part
of element"**.

That message is exact, and it is the whole problem. A `Fascia` or a
`Gutter` is not geometry that happens to sit next to a roof. It is a
profile swept along a list of REFERENCES to edges of its host roof, and
it is stored as those references. Copying one across documents would
mean copying a pointer into the linked file. There is no host element
for the pointer to name, so Revit refuses, and no copy method will ever
do otherwise.

So the sweeps are not copied. They are REBUILT: read the linked sweep's
segment references, work out which edges of which host roof they
correspond to, and create a new sweep on those host edges with the same
type and the same offsets.

## Scope

In scope: `Fascia` and `Gutter` hosted on roof edges, picked in a linked
model, rebuilt in the host on already-copied roofs.

Out of scope, and each for a reason:

  * **Roof Soffit and Slab Edge.** The same `HostedSweep` machinery, and
    the same code would very nearly do them. They are left out because
    they were not asked for, and because a slab edge needs its host
    floors copied first, which is a separate promise to keep.
  * **Sweeps hosted on anything but a roof.** A fascia may also be hosted
    on a soffit, on another fascia, or on model lines. Those segments are
    reported, not rebuilt.
  * **Copying the roofs.** The roofs are assumed already in the host.
    Where one is not, the tool says so; it does not bring it over.
  * **Per-segment overrides.** See Decisions.
  * **Editing the link.** The linked model is never modified.

## Code structure

### New: `lib/BG/roof_sweep.py`

The whole of the logic, split so that the geometry half can be tested
without Revit. Functions take plain tuples of floats, not `XYZ`, and the
button converts at the boundary — this is what lets `tests/` run.

Pure, testable:

  * `edge_key(p, q, tol)` — one hashable key for an edge, built from its
    two endpoints. The endpoints are SORTED before rounding, so an edge
    read one way round matches the same edge read the other way round.
  * `round_point(p, tol)` — a point snapped to the tolerance grid.
  * `edge_key_candidates(p, q, tol)` — every key an edge could have been
    filed under. Rounding to a grid has one flaw: two points a hair
    apart still land in different cells when they straddle a cell
    boundary, so a lookup by the single key would miss. The index is
    built with `edge_key`; a LOOKUP tries the keys built from each
    coordinate rounded both down and up — eight variants per endpoint,
    and the first hit wins. Cheap, and it removes the only way this
    scheme could silently fail to find an edge that is there.
  * `points_match(p, q, tol)` / `boxes_match(a, b, tol)` — the roof
    identity test's arithmetic.
  * `centroid(points)` — footprint centre, for roof identity.

Revit-facing:

  * `sweeps_in_selection(refs, doc)` — the picked linked sweeps, grouped
    by link instance.
  * `segment_edges(sweep, transform)` — for one linked sweep, a list of
    `(linked roof, edge curve endpoints in host coordinates)`, one per
    segment, plus the segments that could not be read.
  * `host_roofs(doc)` — the host's roofs, indexed for identity matching.
  * `match_roof(linked_roof, transform, index)` — the host roof
    corresponding to a linked one, or `None`.
  * `edge_index(roof)` — `{edge_key: Reference}` for a host roof, from
    `get_Geometry(Options(ComputeReferences=True))`.
  * `ensure_type(link_doc, doc, linked_sweep)` — the host's matching
    `FasciaType`/`GutterType`, copying it out of the link when the host
    has none.
  * `existing_index(doc)` — `{(family, type, edge_key): element id}` for
    the sweeps the host already holds, for the re-run rule.
  * `create_sweep(doc, kind, sweep_type, references)` — the
    `NewFascia`/`NewGutter` call and its failure message.

### New: `BG_Tools.tab/SKIN_Tools.panel/CopyRoofSweeps.pushbutton/script.py`

Selection, the transaction, the fallback prompt, and the report. Written
in the shape of `CopyFromLink.pushbutton/script.py`, which it sits beside:
a `note`/`report` pair, one `main()`, and a `try` that turns any
unhandled failure into a `forms.alert`.

`bundle.yaml` gains `CopyRoofSweeps` in the layout, after `CopyFromLink`.

### New: `tests/test_roof_sweep.py`

Unit tests over the pure functions, in the style of
`tests/test_wall_miter.py` — plain `unittest`, `lib` put on `sys.path`,
no Revit import reached.

## Data flow

### 1. Pick

`uidoc.Selection.PickObjects(ObjectType.LinkedElement, filter, …)` with a
filter that allows only linked elements of `OST_Fascia` and `OST_Gutter`.
As in `CopyFromLink`, the real test lives in `AllowReference`, because
that is where Revit offers the linked element rather than the link
instance.

No category prompt: the category IS the tool. Cancelling, or finishing
with nothing picked, does nothing and reports nothing.

### 2. Read the linked sweeps

For each picked sweep, `GetSegmentIds()` and then
`GetSegmentReference(id)` per segment. Each reference names a host
element in the link and one edge of it.
`linked_roof.GetGeometryObjectFromReference(ref)` gives the `Edge`;
`AsCurve()` gives its geometry; the link instance's `GetTotalTransform()`
puts the endpoints into host coordinates.

A segment whose host is not a roof, or whose geometry will not resolve,
is counted as unread and carried into the report. It does not stop the
others.

### 3. Match the roof

The sweep's segments are grouped by the linked roof they stand on —
normally one, but a sweep may run across two.

A host roof matches a linked one when it has the same type name AND its
footprint centroid and bounding box both agree within 1 inch, the linked
roof's geometry having first been pushed through the link transform.

Where no host roof matches, the user is asked to pick one, once, with a
message naming the linked roof. The answer is REMEMBERED for the rest of
the run, keyed by the linked roof's id, so a dozen sweeps on one
unmatched roof cost one prompt, not a dozen. Declining the prompt skips
every sweep on that roof.

### 4. Match the edges

For the matched host roof, `edge_index(roof)` walks the solids of
`get_Geometry(Options(ComputeReferences=True, DetailLevel=Fine))` and
records every edge under its `edge_key`, against the `Reference` that
`Edge.Reference` gives. References are only populated when
`ComputeReferences` is on, which is the whole reason for the option.

Each transformed linked edge is then a dictionary lookup.

The index is built ONCE PER HOST ROOF for the run and reused, because the
alternative is regenerating a roof's geometry for every sweep on it.

### 5. The type

The linked sweep's type is looked for in the host by family name and type
name together, over `FasciaType`/`GutterType`. Where the host has none,
the type element ALONE is copied out of the link with
`ElementTransformUtils.CopyElements`. A type copies without complaint —
it holds a profile and numbers, not references into the link. It is the
instance, and only the instance, that cannot come over.

Types copied this way are counted and named in the report, because a type
appearing in the host model is worth knowing about.

### 6. Create

`doc.Create.NewFascia(sweep_type, references)` or `NewGutter`, with a
`ReferenceArray` of the matched host edges in the order the linked
segments were read. Then `HorizontalOffset`, `VerticalOffset` and `Angle`
are set from the linked original.

One `Transaction` for the whole run. Any unhandled exception rolls it
back, so a run either lands or leaves nothing behind.

## Tolerances

**Edge endpoints: 1/32 inch.** The roofs came over by Revit's own copy,
so their edges should be bit-for-bit what the link holds; this tolerance
is absorbing the floating-point error of pushing a point through the link
transform, and nothing else. It is deliberately far tighter than the inch
used elsewhere in this extension: loosening it until it could bridge a
roof that is genuinely different would mean silently hosting a fascia on
the wrong edge, which is worse than not hosting it at all.

**Roof identity: 1 inch.** The same inch `lib/BG/link_copy.py` uses, for
the same reason — a roof may have been nudged by hand after copying, and
a roof an inch out is still that roof. Getting this wrong is cheap:
either it prompts when it need not have, or it picks a roof whose edges
then fail to match and says so.

## Error handling

Three failures, three distinct report rows, because the user's next
action differs for each:

  * **Roof not found, prompt declined** — the sweep is skipped whole,
    nothing created. Row names the linked roof.
  * **Roof found, some edges not** — the sweep IS created, from the edges
    that matched, and the row reads `partial: 5 of 7 segments`. This is
    the expected real-world failure: a host roof that is nearly, but not
    exactly, the linked one. A partial sweep with two edges to add by
    hand is a far better outcome than nothing, and the count tells the
    user how much is left.
  * **No edges matched, or `NewFascia` throws** — nothing created, one row
    carrying Revit's own message.

Nothing aborts the run. Every picked element gets its own outcome.

## Re-runs

A picked sweep is ALREADY HERE when the host holds a sweep of the same
family and type standing on any one of the target edges.

A single shared edge is proof enough. Two fascias of one type on one roof
edge is never something anybody meant, so the shared edge cannot be a
coincidence — and requiring the whole segment list to match would let a
re-run double up a sweep that had since been extended by hand. Skipped
elements are counted, and the count is reported the way `CopyFromLink`
reports its own.

## Decisions

**Rebuild, not copy.** Forced, not chosen. See Purpose.

**Match the roof first, then its edges.** Rather than searching every
edge of every roof in the host for the linked curve. Two reasons. It
cannot pick up a coincidentally identical edge on an unrelated roof
below. And it splits one useless failure — "no edge found" — into two
useful ones: the roof is missing, or the roof is here but has changed.

**Not by stable representation.** The short route is to take the linked
reference's stable representation string, swap the element id for the
host roof's, and `ParseFromStableRepresentation`. Rejected: the face and
edge indices in that string are only valid while the host roof generates
its geometry identically, which does not survive a re-copy or an attached
wall — and when it breaks it does not raise, it silently returns a
reference to a DIFFERENT edge. A fascia quietly on the wrong side of a
roof is the one outcome this tool must not have.

**Whole-element offsets only, not per-segment.** `HorizontalOffset`,
`VerticalOffset` and `Angle` are carried; per-segment overrides and
segment-end cutbacks are not. The normal sweep has one setting
throughout, the API surface for the per-segment case is wide, and a
wrongly applied override is harder to spot than a missing one. If
hand-tweaked sweeps turn up in practice this is an addition, not a
rewrite.

**Partial creation over refusal.** See Error handling.

## Risks

**The host roof is not geometrically the linked roof.** The likeliest
failure by far, and the reason partial creation and per-segment counts
are in the design rather than a plain success/fail. Not preventable in
code — the tool's job is to be clear about it.

**A roof's edges are split differently in the host.** One linked edge may
correspond to two host edges end to end, or the reverse, if the roofs
join their neighbours differently. Those segments will not match and will
be reported as missing. Detecting and stitching split edges is
deliberately not attempted in this version: it is real work, and it may
never come up.

**`Edge.Reference` may be null.** For some geometry Revit does not
produce a reference even with `ComputeReferences` on. Such edges are
simply absent from the index, and the segment reports as unmatched.

## Testing

Pure unit tests, `tests/test_roof_sweep.py`, no Revit:

  * `edge_key` gives the same key for an edge read in either direction.
  * `edge_key` gives different keys for two edges a foot apart.
  * an edge whose endpoints differ by less than the tolerance is found
    through `edge_key_candidates` in an index built with `edge_key`,
    INCLUDING when the two points straddle a grid cell boundary — the
    case the candidates exist for.
  * an edge whose endpoints differ by more than the tolerance is NOT
    found by any of its candidates.
  * `centroid` of a known footprint.
  * `boxes_match` accepts an inch of drift and refuses a foot.
  * `points_match` at, just inside, and just outside the tolerance.

Manual verification in Revit, on a model with a link and copied roofs:

  * one fascia on a simple roof rebuilds in place, right type, right
    offsets;
  * a gutter picked in the same run rebuilds too;
  * running the tool twice creates nothing the second time;
  * a fascia whose host roof is not in the host model prompts once and
    skips cleanly when declined;
  * a fascia whose type is not in the host brings the type over;
  * cancelling the pick does nothing at all.
