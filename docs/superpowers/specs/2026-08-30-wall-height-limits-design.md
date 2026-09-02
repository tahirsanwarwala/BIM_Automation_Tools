# Visual Base/Top Limits for SKIN Walls

**Date:** 2026-08-30
**Tool:** `Revit API/pyRevit-Tools.extension/Tahir_Tools.tab/Walls.panel/SplitWalls.pushbutton/script.py`
**Status:** Design — awaiting review

## Problem

The tool creates a SKIN wall in the host model for each selected compound wall
(host or linked). The new wall inherits its base level, base offset and
unconnected height from the source wall.

That inheritance is frequently wrong. A skin often needs to start and stop at
places the source wall does not — the top of the wall below, a level datum, a
window head. Users cannot correct this by typing numbers, because when looking
at an elevation the required height is not known as a number. The reference is
visual: *"from the top of that wall up to that level."*

## Goals

- Let the user set the base and top of the new walls by clicking reference
  elements in an elevation or section view.
- Never require the user to type or know a numeric height.
- Where the reference is a Level, keep the new wall parametrically bound to it.
- Fail before creating geometry, not after.

## Non-goals

- Sub-element references (window heads, sills, roof edges). Whole-element
  top/bottom only. See Decision 1.
- Per-wall limits. One base and one top apply to the whole selection.
- Changing how walls are selected, or how the SKIN type and its position across
  the wall thickness are computed. Those are settled and out of scope.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Snap to the picked element's **overall top or bottom**, chosen by where the user clicked | Predictable. Sub-element snapping (heads, sills) was considered and rejected as unnecessary for now. |
| 2 | **Bind to a Level when a Level is picked**, otherwise bake an offset | Keeps the parametric relationship where one genuinely exists, without forcing odd offsets elsewhere. |
| 3 | **One base and one top for the entire selection** | Matches the facade-run case the tool is used for. |
| 4 | **Always pick limits** — no fallback to source heights | The source height is the behaviour being replaced. |
| 5 | **Mode switch before each pick**: linked element vs. host element/level | `ObjectType.Element` and `ObjectType.LinkedElement` are separate pick modes in the Revit API and cannot be combined in one call. An explicit switch is predictable; auto-detection would produce occasional surprise double-picks. |
| 6 | **Handle host and linked levels both** | Both are visible in the user's views. |

## Flow

```
Run from an elevation or section view
  ├─ view type is not Elevation/Section  → alert, exit
  ├─ select walls                          (existing logic, unchanged)
  ├─ pick BASE reference
  │    ├─ mode switch: Linked element / Host element or Level
  │    └─ pick → resolve to elevation
  ├─ pick TOP reference
  │    └─ (same as base)
  ├─ confirmation dialog: both resolved elevations + how each will be applied
  └─ single transaction → create SKIN walls
```

All picking happens **before** the transaction opens; Revit forbids interactive
selection inside an open transaction.

## Resolving a pick to an elevation

`PickObject` returns a `Reference` carrying the element and `GlobalPoint` — the
point the user clicked, in host coordinates. Resolution by element kind:

**Level (host doc)**
Use `level.Elevation`. Record the level's `ElementId` for binding.

**Level (linked doc)**
Use its elevation transformed into host coordinates. Attempt to match a host
level whose elevation is within tolerance (`1/16"`, i.e. `0.0052 ft`); if found,
record that host level's id for binding. Otherwise treat as a non-level
reference and bake.

**Any other element (host or linked)**
1. `elem.get_BoundingBox(None)` — bounding box in the element's own document
   coordinates.
2. Transform all **8 corners** into host coordinates (identity transform for
   host elements, `link_inst.GetTotalTransform()` for linked ones), then take
   min/max Z. Transforming all 8 corners rather than just min/max keeps this
   correct under rotated link transforms.
3. `mid = (minZ + maxZ) / 2`. If `GlobalPoint.Z >= mid` use `maxZ` (top),
   else `minZ` (bottom).

The result of a pick is a small record:

```
PickedLimit:
    elevation    # float, feet, host coordinates
    level_id     # ElementId of a HOST level, or None
    label        # human-readable, for the confirmation dialog
```

`level_id` is set only when the pick resolved to a level that can be bound to.

## Applying the limits

Both limits are resolved to a single `WallLimits` record, computed once and
shared by every wall in the selection:

```
WallLimits:
    base_level_id   # ElementId, always valid
    base_offset     # float, feet
    top_level_id    # ElementId or None
    top_offset      # float, feet
    height          # float, feet — always computed; it is the unconnected
                    # height when top_level_id is None, and the seed height
                    # Wall.Create needs before the top constraint is applied
```

**Base**
- Picked a bindable level → `base_level_id` = that level, `base_offset` = 0.
  Note: when the bindable level came from *elevation matching* a linked level,
  binding snaps the wall to the host level's exact elevation, absorbing up to
  the matching tolerance. This is intended — binding to the level is worth more
  than preserving a sub-1/16" discrepancy.
- Otherwise → `base_level_id` = nearest host level at or below the base
  elevation; `base_offset` = `base_elevation − level.Elevation`.

**Top**
- Picked a bindable level → `top_level_id` = that level, `top_offset` = 0.
  Applied via `WALL_HEIGHT_TYPE` ("Up to level"), so the wall follows the level.
- Otherwise → `top_level_id` = None, `height` = `top_elevation − base_elevation`,
  applied as unconnected height.

`Wall.Create` is called with the base level and computed height; the top
constraint is applied afterward when `top_level_id` is set.

## Changes to existing code

| Location | Change |
|---|---|
| `split_wall()` | Takes a `WallLimits` argument; uses it instead of `wd.height` / `wd.base_off` / `wd.level_id`. |
| `copy_instance_params()` | **Remove** `WALL_BASE_OFFSET`, `WALL_USER_HEIGHT_PARAM`, `WALL_HEIGHT_TYPE` from the copy list. Currently these would overwrite the limits just picked — a real bug this feature exposes. |
| `main()` | View gate, the two picks, confirmation dialog, then the existing transaction loop. |
| New section | `pick_limits()` and its resolution helpers, placed alongside `measure_face_offsets()`. |

`WallData.height` / `.base_off` / `.level_id` remain populated (harmless, and
useful if a source-height fallback is ever wanted), but are no longer read
during creation.

## Validation and errors

Checked before the transaction opens, each with a specific message:

- Active view is not an elevation or section.
- Top elevation is at or below base elevation.
- No host level exists at or below the base elevation (cannot anchor the base).
- Picked element has no bounding box.
- User pressed Esc — abort cleanly, create nothing, no error dialog.

Per-wall failures inside the transaction keep the existing behaviour: collected
and reported at the end without aborting the other walls.

## Edge cases

- **Rotated or mirrored link transforms** — handled by transforming all 8 bbox
  corners rather than assuming Z is preserved.
- **Picking the same element for base and top** — legal; the top/bottom
  disambiguation makes it meaningful (bottom of an element as base, top of the
  same element as top).
- **Linked level with no matching host level** — falls back to a baked offset
  rather than failing.
- **Wall shorter than its own skin thickness** — allowed; Revit permits it.

## Testing

The Revit API cannot be exercised from the development environment, so
verification is split:

*Statically checkable here*
- Script parses; no unresolved references.
- Bbox-corner transform and top/bottom selection logic verified numerically
  against hand-computed cases, including a rotated transform.
- Level-matching tolerance behaviour at and just outside the threshold.

*Requires Revit — for the user to confirm*
1. Base = top of a linked wall, top = host Level datum → wall spans exactly
   between them; Top Constraint reads "Up to level".
2. Base = host Level, top = host Level → both constraints bound, offsets zero.
3. Base and top both non-level references → correct unconnected height, base
   offset from the nearest level below.
4. Esc at each pick stage → nothing created.
5. Run from a plan view → blocked with a clear message.
6. Multi-wall selection → all walls share identical base and top.

## Risks

- **Unverified API behaviour.** Whether `Reference.GlobalPoint` is reliably
  populated for linked-element picks in elevation views cannot be confirmed
  without Revit. If it is not, the top/bottom disambiguation needs a fallback —
  most likely the explicit "top or bottom?" prompt considered and set aside
  earlier. This is the main thing to watch in the first test run.
- **Level-matching tolerance.** `1/16"` is a guess. If a project has host and
  linked levels intentionally offset by less than that, matching could bind the
  wrong one.
