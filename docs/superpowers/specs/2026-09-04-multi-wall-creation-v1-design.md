# Multi Wall Creation V1 — Design

Date: 2026-09-04
Status: approved for planning

## Purpose

One pyRevit tool (Revit 2025) that takes a single mixed selection of walls
AND wall sweeps from a LINKED model and creates, in the host model:

  * a SKIN wall for each picked wall, as `SplitWalls` does, and
  * a wall for each picked wall sweep, as `SweepToWall` does,

with one change that is the whole reason the tool exists: the user never
picks base and top limits. A wall's vertical extent is derived from the
sweeps that run on it.

## The height rule

  1. Sweep-derived walls keep the vertical extent of their source sweep,
     exactly as measured from the linked model. Every picked sweep gets
     one, cast stone and EIFS alike.
  2. A wall stops where a CAST STONE sweep starts. Its top is the bottom of
     the stone course above it; its base is the top of the stone course
     below it.
  3. No wall crosses a cast stone course. A wall with stone courses
     part-way up is cut into one wall per gap between them.
  4. An EIFS sweep does not cut anything. It is measured, built and mitred
     like any other sweep, but the walls it runs across pass it unbroken.
  5. No wall crosses a level. Each gap is cut again at every level it
     crosses. Sweep-derived walls are NOT split at levels.
  6. With no stone course above or below, that end falls back to the source
     wall's own constraint parameters.

Levels are the strict constraint; cast stone courses are the second. Both
cuts are exact — nothing is rounded (see Decisions).

Which sweeps cut is decided on the wall type a sweep RESOLVED to, not on
its name or its material: those are what the STONE/EIFS rule reads to
reach a type in the first place, and a sweep the rule could not read has
had its type chosen by hand. What a sweep is being built as is the honest
answer to what it is.

## Scope

In scope: linked walls and linked horizontal wall sweeps; host-model output;
per-band level-bound constraints; automatic wall-type resolution for sweeps;
mitred corners.

Out of scope: host-model source walls (this tool is linked-source only, as
`SplitWalls`' pick already is); reveals; vertical sweeps; curved walls;
stacked and curtain walls; modifying the link.

## Code structure

New pushbutton: `Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/MultiWallCreationV1.pushbutton/script.py`

  * `__title__ = "Multi Wall\nCreation V1"`
  * added to `Walls.panel/bundle.yaml` after `SweepToWall`.

New library module: `lib/Tahir/wall_bands.py` — pure arithmetic, no Revit
import, unit-tested outside Revit like `wall_limits` and `wall_constraints`.
It owns span subtraction and gap production only; level cutting is delegated
to `wall_constraints.plan_wall`.

Targeted extraction: `lib/Tahir/wall_skin.py` receives, unchanged in
behaviour, three functions currently private to `SplitWalls`:
`measure_face_offsets`, `compute_skin_curve`, `create_oriented_wall` (with
its helper `_center_wall_on_curve`). `SplitWalls` is edited to import them
from there. This is the code the new tool would otherwise copy verbatim;
nothing else in `SplitWalls` or `SweepToWall` changes.

Reused as-is: `Tahir.wall_chain` (level finding, solids, wall frames,
`Segment`, `mitre_segments`), `Tahir.wall_miter`, `Tahir.wall_materials`
(skin type planning and creation), `Tahir.wall_naming`,
`Tahir.wall_constraints` (`constraints_for`, `plan_wall`).

## Data flow

### Phase 0 — selection

A single `PickObject(ObjectType.LinkedElement, filt, ...)` loop until Esc.
The filter accepts, inside a `RevitLinkInstance`:

  * `Wall` whose `WallType.Kind == WallKind.Basic`, and
  * `WallSweep` that is neither a reveal nor vertical
    (`sweep_is_convertible`, copied from `SweepToWall`).

Picks are de-duplicated on `(link id, linked element id)`. Cancelling before
anything is picked ends the run creating and reporting nothing.

One pass only: the tool does not loop back for another selection the way
`SplitWalls` does, because there are no per-pass limits to vary.

### Phase 1 — measure sweeps

**Revised after first testing — see Decisions.** Per picked sweep:

  * host walls from `sweep.GetHostIds()`, resolved in the linked doc;
  * a `WallFrame` and `wall_exterior_offset` per host wall;
  * the sweep's solid split between those walls, each edge assigned to the
    host wall its tessellation's CENTROID is nearest to, by distance to the
    wall's location segment rather than to its infinite line;
  * per wall, the assigned edges' along-axis intervals unioned by
    `wall_bands.merge_intervals`, bridging gaps under `SWEEP_GAP_TOL`
    (one inch — a seam between abutting sweep solids or the notch at a
    mitred corner is not a break; an opening is);
  * one `SweepRun` per surviving interval, carrying its frame, offset,
    `along_min`/`along_max`, its own `(base_z, top_z)` measured from just
    the edges inside it, and the `(link id, wall id)` of its host wall;
  * a run end within one host wall thickness of the wall's end snapped
    onto it, so a sweep that returns into a corner is still seen as
    adjacent to its neighbour and mitres;
  * the dominant material name;
  * the sweep type's Type Mark, for `BG_PROFILE`.

A run's own `(base_z, top_z)` both builds its wall and cuts its host wall,
so the two always meet exactly.

### Phase 2 — resolve wall types (before the transaction)

Sweeps, by name rule, case-insensitive substring, sweep TYPE NAME tested
first and the dominant MATERIAL NAME second:

    "STONE" -> wall type named exactly: SKIN_CAST STONE PROFILE_0' 2"
    "EIFS"  -> wall type named exactly: SKIN_EIFS PROFILE_0' 2"

No match, both match (STONE wins, being tested first), or the named type
absent from the host model: fall back to
`wall_materials.pick_skin_wall_type`, asked ONCE per sweep TYPE and cached.
Cancelling that dialog skips every sweep of that type, with a note.

Wall skins: unchanged from `SplitWalls` —
`wall_materials.plan_skin_wall_type` keyed by
`type_match_key(material Mark, finish layer width)`, resolved once per key
across the whole selection.

All dialogs happen here, before any transaction opens.

### Phase 3 — band the walls

Per picked wall:

    span     = source wall extent, from CONSTRAINT PARAMETERS ONLY:
               base level elevation + WALL_BASE_OFFSET, and
               top level elevation + WALL_TOP_OFFSET when the wall is
               level-bound, else base + WALL_USER_HEIGHT_PARAM;
               all mapped through the link's total transform.
    cutters  = picked sweeps whose GetHostIds() contains this wall,
               each clipped to `span`
    gaps     = wall_bands.subtract_spans(span, cutters)
    bands    = for each gap:
                   wall_constraints.plan_wall(lo, hi, levels,
                                              allow_round=False)["bands"]

A wall with no cutters yields one gap equal to its whole span, still cut at
levels — rule 5 falls out of the same code path rather than being a special
case.

Level elevations come from host levels converted out of level space with
`project_base_elevation`, so every elevation in the run — sweep envelopes,
wall spans and level datums alike — sits in one coordinate space.

### Phase 4 — plan sweep-wall constraints

Per sweep: `wall_constraints.constraints_for(z_min, z_max, levels)`. Base
binds to the level at or below with a positive offset; top hangs from the
level at or above with a negative offset. No level splitting.

This is a deliberate change from `SweepToWall`, which today uses a base
offset plus an unconnected height. Level-bound tops are what let a banded
wall's constraints relate to the sweep wall above it.

### Phase 5 — build (one transaction)

Sweep walls, per sweep:

  * centreline = host wall exterior face + half the chosen type's width, so
    the new wall's interior finish face lands on that host face;
  * `wall_chain.Segment` + `mitre_segments` per sweep run, so each sweep's
    corners are mitred within its own run;
  * created with `SweepToWall.create_wall` behaviour: Location Line set to
    Centreline, curve reversed if the orientation is flipped, then Location
    Line set to Finish Face Interior;
  * `BG_PROFILE` written from the sweep type's Type Mark;
  * base and top constraints from Phase 4 applied.

Wall skins, per band:

  * centreline from `wall_skin.compute_skin_curve`, so the new wall's outer
    face lands on the source wall's exterior face;
  * mitred WITHIN ELEVATION GROUPS: bands are grouped by
    `(round(base_z, 4), round(top_z, 4))` and mitred only against neighbours
    in the same group. Mitring a band at 11-20 ft against a neighbour at
    0-10 ft would join walls that do not touch;
  * created with `wall_skin.create_oriented_wall`;
  * base and top constraints from Phase 3 applied.

Failure of one wall never aborts the transaction; it is recorded and the run
continues.

## Error handling and edge cases

| Case | Behaviour |
|---|---|
| Sweep hosted on a wall that was not picked | Sweep wall created; that wall is not banded |
| Wall picked, its sweeps not picked | Wall spans its full source extent, cut only at levels |
| Sweep covers the whole wall, or two sweeps touch | Band dropped; EVERY drop reported with wall and elevations |
| Sweep envelope extends past the wall span | Clipped to the span before subtraction |
| Curved wall / zero-length wall / no compound structure / fewer than 2 layers | Reported and skipped, same messages as `SplitWalls` |
| Sweep with no host walls, or no readable geometry | Reported and skipped, same messages as `SweepToWall` |
| Named sweep wall type missing | Falls to the pick dialog for that sweep type |
| Model has no levels | The run reports it and creates nothing; `constraints_for` raises `ValueError` without levels |
| Stepped sweep, running at different heights on different host walls | Each run measures its own height, so every stretch is built and cuts at the height it truly runs at |
| Sweep or wall finish that wraps into an opening reveal | Stops at the jamb; the perpendicular return is NOT modelled and the reveal is left empty |
| Insert with no readable solid | Its extent falls back to its bounding box, which over-cuts a wall running diagonally to the model axes |

Reporting follows both source tools: silence on success, and on failure one
`output.print_table` with columns `["Element", "Note"]`. Printing is what
opens the pyRevit output window, so a clean run shows nothing.

## Decisions

  * **Sweep-to-wall matching is by host ID only.** `GetHostIds()` is exact.
    Plan-proximity matching was considered and rejected as prone to catching
    sweeps on parallel walls nearby.
  * **Only picked sweeps count.** An unpicked sweep never cuts a wall and
    never gets modelled. The selection is the contract.
  * **Nothing is rounded.** `WallConstraints` snaps off-level ends to the
    nearest inch; this tool must not, because a band end has to sit exactly
    on a sweep face or a level or a gap opens in the elevation. `plan_wall`
    is therefore called with `allow_round=False`.
  * **Fallback extent comes from constraint parameters, not geometry.**
    Measured solids were considered; parameters were chosen so a wall
    attached to a sloped roof does not report its highest point as its top.
  * **Every dropped band is reported**, slivers included, so nothing is ever
    invisible.
  * **Sweep wall types are automatic**, by the STONE/EIFS name rule, with a
    dialog only for what the rule cannot resolve. `SweepToWall`'s
    unconditional "pick one type for the whole selection" prompt does not
    appear in this tool.
  * **REVERSED after first testing: plan extents come from geometry, not
    from the host wall's length.** The original decision — "only the
    vertical envelope is taken from the sweep; where each wall goes in plan
    comes from the host wall itself" — was inherited from `SweepToWall` and
    proved to be the cause of three defects seen in a real model: a sweep
    wall ran straight past an opening its sweep stopped at, one that wraps
    into a reveal ran across it, and at a corner two offset runs overshot
    and crossed instead of trimming. Both sweeps and skin bands now take
    their plan extent from geometry. `SweepToWall` still carries all three
    defects and is untouched.
  * **Mitring is across sweeps, not within one**, grouped by
    `(elevation, resolved wall type)`. Two sweeps meeting at a building
    corner are two separate picks, and mitring each alone left them
    crossing.
  * **Skin bands are cut in plan at inserts**, from `wall.FindInserts`,
    filtered to those whose own height range overlaps the band. The extent
    is the insert's whole solid — frame and trim, not the rough opening —
    because that is where a finish genuinely stops.
  * **Every new wall carries its Base Constraint level's name in
    `BG_LEVEL`.**

## Testing

`tests/test_wall_bands.py`, plain `unittest`, matching the style of
`tests/test_wall_constraints.py` (a `sys.path` insert to the extension's
`lib`). Cases:

  * no cutters — the whole span comes back as one gap;
  * one cutter mid-span — two gaps;
  * two cutters — three gaps;
  * touching cutters — the zero-width gap between them is dropped;
  * overlapping cutters — merged, not double-counted;
  * a cutter flush with the span base, and flush with the span top — one
    gap, not a zero-width gap plus one;
  * a cutter covering the whole span — no gaps;
  * a cutter wholly outside the span — ignored;
  * a cutter partly outside the span — clipped;
  * unsorted cutters — order-independent;
  * sliver tolerance — a gap under 1/16 in is dropped and flagged as
    dropped, so the caller can report it.

Integration with `wall_constraints.plan_wall` is covered by asserting that a
gap crossing a level yields one band per storey with exact offsets.

Revit-facing code is not unit-tested, in line with the rest of the
extension. It is verified by running the tool in Revit against a model with
sweeps at, above, below, and part-way up a wall.

## Out of scope for V1

  * host-model source walls;
  * reveal returns — the short perpendicular walls where a sweep or finish
    turns into an opening;
  * re-running over walls the tool has already created;
  * any change to `SweepToWall` or `SplitWalls` beyond the `wall_skin.py`
    extraction.
