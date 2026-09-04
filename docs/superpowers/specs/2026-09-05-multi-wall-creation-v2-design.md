# Multi Wall Creation V2 — Design

Date: 2026-09-05
Status: approved for planning

Builds on `2026-09-04-multi-wall-creation-v1-design.md`, which stands
unchanged. Read that first; this describes only what V2 adds.

## Purpose

V1 turns a linked selection of walls and wall sweeps into host-model skin
walls and sweep walls. V2 does all of that and then puts the openings back:

  * every window hosted on a picked wall becomes a curtain wall on the new
    skin wall, exactly as `WindowToCurtainWall` makes one;
  * every rectangular `Opening` in a picked wall is cut out of the new skin
    wall's elevation profile.

V2 is a SEPARATE pushbutton. V1 is copied, not shared, and is not edited —
it is in daily use while V2 is built.

## What V2 changes about V1's own behaviour

One rule changes, and only one:

**A cast stone sweep that crosses a window stops governing heights on that
wall.** V1 cuts a wall's span at every stone run on it. Where a run's
z-range overlaps a window in that wall, the run is dropped as a cutter for
that WHOLE wall, so the skin stays one band top to bottom rather than being
split behind the window.

Dropping it for the whole wall rather than only over the window's width is
deliberate. Suppressing it over the window alone would mean a band boundary
that stops and restarts along the elevation — splitting the skin in plan,
which was tried in V1 and taken back out. A wall with three windows crossed
by a course would become seven walls instead of two.

Levels are NOT suppressed. They remain the strict constraint: a wall never
crosses one, whatever is in front of it. A tall window crossing a storey
line is split at it — and so is its curtain wall, into one per storey,
mirroring how the skin splits.

Everything else in V1 is untouched: banding, mitring, joining, colinear
merging, level snapping, BG parameters, the STONE/EIFS type rule.

## Scope

In scope: windows in picked linked walls; rectangular `Opening` elements in
picked linked walls; curtain wall type matching by Type Mark; splitting a
curtain wall at a level.

Out of scope: doors (they break the sweeps as in V1, and the skin is left
solid across them); loadable families used as openings; reveal returns;
linked curtain walls as a source; anything already out of scope in V1.

**Arched heads are NOT traced.** An arched window gets a rectangle tall
enough to cover the arch, exactly as `WindowToCurtainWall` does now. Its
`resolve_profile` records why: the head shape can only be recovered by
tracing tessellated solids, and that trace was found unreliable enough to
be taken back out of the tool. V2 does not reinstate it. This reverses an
earlier decision in this document, taken when the tracing was still in the
tool and before it was read closely enough.

## Code structure

### Extractions — the two tools that ARE edited

`WindowToCurtainWall` and `CurtainWallTrim` are edited so V2 can use their
machinery rather than carry a second copy. Both are behaviour-preserving
moves of the kind `wall_skin` already was: the code moves, the callers are
re-pointed, nothing else changes.

**`lib/Tahir/wall_sketch.py`** — Revit-facing profile editing, from both
tools at once. `SketchFailureSwallower` and `sketch_curve_ids` are
byte-identical in the two files today; their two `apply_profile` functions
differ in exactly two string literals, the transaction name and the sketch
scope name. Those two become parameters, so each caller keeps the wording it
has now.

    apply_profile(doc, wall, curves, sketch_name, scope_name) -> None or reason
    sketch_curve_ids(sketch)
    SketchFailureSwallower

**`lib/Tahir/window_cw.py`** — everything needed to turn a linked WINDOW
into a curtain wall on a given host wall, moved from
`WindowToCurtainWall`. That boundary is deliberate: the tool's other source,
a linked curtain wall, keeps its own path (`measure_curtain_wall`,
`linked_wall_profile`, `wall_vertical_extent`, `profile_extent`,
`move_profile`, `resolve_profile`, `frame_at`) and stays in the pushbutton,
because V2 has no use for it.

    class WindowPlan
    measure_window(link_inst, window, host_wall)
    window_centre, sill_from_parameters, sill_height_candidates
    length_param, is_category, iter_solid_points, _iter_geo_points
    type_mark, mark_letters, mark_prefix, candidate_prefixes
    curtain_wall_types, type_named, match_curtain_type, prompt_curtain_type
    wall_axis, segment_on_wall, strip_curtain_grid
    create_curtain_wall, apply_bg_parameters
    params_by_name, pick_param, set_param_text, copy_param
    find_level_below, project_base_elevation
    as_element_id, eid_value, get_element_name

`WindowToCurtainWall` keeps its selection, orchestration and reporting and
imports the rest. `CurtainWallTrim` changes only its `apply_profile` call.

### New

**`MultiWallCreationV2.pushbutton/script.py`** — V1's script copied at its
current commit, plus the three additions below. Added to `bundle.yaml` after
`MultiWallCreationV1`.

**`lib/Tahir/wall_bands.py`** gains one pure function:

    cutters_clear_of_windows(cutters, windows, tol) -> list of cutters

Drops any cutter whose z-range overlaps any window's z-range. Unit-tested.

## Data flow — what V2 adds to V1's phases

### Phase 1b — measure the windows and openings (with the walls)

Per picked wall, alongside V1's measurement:

  * `wall.FindInserts(True, False, True, True)`, filtered to
    `OST_Windows` for curtain walls and to `Opening` elements for profile
    cuts. Doors are ignored.
  * Each window measured by `window_cw.measure_window`: sill from
    parameters cross-checked against the solid, Rough Width/Height falling
    back to Width/Height. No head tracing — see Scope.
  * Each `Opening` measured to an along/z rectangle in the wall's frame,
    the same way V1 measures an insert for its sweep cutting.

Both are recorded on the `WallJob`, in the merged frame's coordinates so a
colinear run of source walls measures as one wall.

### Phase 3b — windows suppress the sweeps that cross them

Before banding, `wall_bands.cutters_clear_of_windows` drops every cast
stone cutter whose z-range overlaps a window on that wall. The surviving
cutters go into V1's banding unchanged.

### Phase 5b — build the curtain walls (in the transaction, after the skins)

Per window, after the skin walls exist:

  * the window's span is cut at the levels it crosses, giving one curtain
    wall per storey — the same `wall_constraints.plan_wall` the skin bands
    use, so the two split at identical elevations;
  * for each piece, `segment_on_wall` gives a curve on the NEW skin wall's
    centreline over the window's width, and a curtain wall is created there
    at that piece's own base and height;
  * the type comes from the Type Mark prefix, asked once per prefix and
    cached, as `WindowToCurtainWall` does;
  * the grid is stripped and BG parameters are filled from the new skin
    wall.

Revit embeds the curtain wall in the skin wall it overlaps. Note the skin
wall is a finish layer, commonly 2-3 inches, not a full compound wall.

### Phase 5c — cut the openings, after the transaction closes

A rectangular `Opening` in a picked wall is cut out of the new skin wall's
elevation through `wall_sketch.apply_profile`. Curtain walls need no profile
edit at all, since their heads are rectangles.

This runs LAST, outside the main transaction, for two reasons that leave no
choice: `SketchEditScope` refuses to start inside an open transaction — it
opens transactions of its own — and a sketched profile is drawn against the
wall's constraints, so those must already be final. `WindowToCurtainWall`
sequences it the same way today, for the same reasons.

A profile edit that fails therefore cannot roll back the walls, which are
already committed. That is the right trade: a wall standing uncut is worth
more than a run that abandons everything it built.

## Error handling and edge cases

| Case | Behaviour |
|---|---|
| Window on a wall that produced no skin wall | Reported and skipped; there is nothing to host it on |
| Window wider than the skin wall it sits on | `segment_on_wall` trims it to the wall and says so, as it does today |
| Window with no readable sill or width | Reported and skipped, same messages as `WindowToCurtainWall` |
| No curtain wall type matches the Type Mark prefix | One dialog per prefix; cancelling skips every window of that prefix |
| Window crossing a level | One curtain wall per storey, split at the level |
| Window crossing a stone course | Course stops cutting that wall; window gets one curtain wall |
| Arched head on a window | A rectangle tall enough to cover the arch, as `WindowToCurtainWall` does today |
| Profile edit rejected by Revit | Reported with Revit's reason; the wall stands uncut rather than the run failing |
| `Opening` in a wall that produced several bands | The band whose z-range contains the opening is cut; an opening spanning two bands is reported and skipped |

Reporting follows V1: silent on success, one `["Element", "Note"]` table.

## Decisions

  * **V1 is copied, not shared.** It is in daily use while V2 is built, and
    a shared engine would put every V2 change into it. The duplication is
    deliberate and temporary; once V2 is signed off the two collapse.
  * **`WindowToCurtainWall` and `CurtainWallTrim` ARE edited**, because the
    alternative is a second copy of 800 lines that has to be fixed twice.
    Both edits are behaviour-preserving moves.
  * **Rectangular `Opening` elements only, cut by profile.** `NewOpening`
    would be more robust and was recommended; the profile route was chosen
    instead. See the risk below.
  * **Curtain walls take the window's own sill and height**, not level-bound
    constraints. A curtain wall's extent IS its window.
  * **A sweep crossing a window is dropped for the whole wall**, not just
    over the window, to avoid reintroducing plan splitting.
  * **Levels are never suppressed.** The one rule that has held without
    exception holds here too.

## Risks

**Profile editing is the most fragile code in this repo.** It needs a
failure-swallowing preprocessor to survive, it cannot run inside a
transaction, and it interacts badly with constraints — `wall_constraints`
already refuses to move the ends of a sketched wall for that reason. V2 puts
it on the critical path for openings. If it proves unreliable in practice
the answer is `NewOpening` for rectangular holes, which needs no sketch at
all.

**Curtain walls embed in a thin skin.** `WindowToCurtainWall` embeds into a
full compound wall; here the host is a finish layer. Whether Revit's
automatic embedding behaves the same at 2 inches is the first thing to check
in the model.

## Testing

Unit tests, run outside Revit with `python -m unittest discover -s tests`:

  * `tests/test_wall_bands.py` gains `cutters_clear_of_windows`: no windows;
    a cutter clear of every window; a cutter inside a window; a cutter
    straddling a window's head; a cutter touching a window's sill exactly;
    several windows where only one overlaps; an empty cutter list.

Everything Revit-facing is verified by the human in Revit. Nothing in this
repo can execute the Revit API outside it.

## Out of scope for V2

  * doors;
  * loadable families used as openings;
  * lintel and sill bands — a separate tool, with its own spec;
  * collapsing V1 and V2 back into one script.
