# -*- coding: utf-8 -*-
"""Pure constraint arithmetic for the WallConstraints tool.

Like BG.wall_limits this module deliberately imports nothing from
Revit, so every rule below can be unit-tested outside Revit.  The
pushbutton script turns Revit objects into the plain tuples these
functions expect and turns the returned dicts back into parameters.

Coordinates are decimal feet in host-model project space.  A *levels*
argument is always a sequence of ``(level_id, elevation)`` pairs; the
ids are opaque and are handed straight back to the caller.

The house rule this module encodes:

  * A wall's base sits on the level at or immediately below it, with a
    positive base offset.
  * A wall's top hangs from the level at or immediately above it, with
    a negative top offset.  Never an unconnected height.
  * No wall crosses a level.  One that does is cut into bands, one per
    storey it passes through.
  * Ends that do not coincide with a level are rounded to the nearest
    whole inch.  Ends that DO coincide with a level are left exactly
    where they are, because the level elevation is authoritative.
"""

from BG.wall_limits import (
    TOL_LEVEL_MATCH,
    nearest_level_at_or_above,
    nearest_level_at_or_below,
)

# One inch in feet.
INCH = 1.0 / 12.0

# Reuse the SplitWalls tolerance so both tools agree on what "on a
# level" means: 1/16 inch.
TOL = TOL_LEVEL_MATCH


def round_to_inch(z):
    """Round an elevation to the nearest whole inch.

    Rounds half away from zero so negative elevations behave the same
    way as positive ones -- Python's built-in round() would break the
    tie towards even and give -8" for -8.5" but 9" for 8.5".
    """
    inches = z / INCH
    if inches >= 0:
        snapped = int(inches + 0.5)
    else:
        snapped = -int(-inches + 0.5)
    return snapped * INCH


def level_at(z, levels, tol=TOL):
    """Return (level_id, elevation) of the level *z* sits on, else None."""
    best = None
    best_d = None
    for lvl_id, lvl_elev in levels:
        d = abs(lvl_elev - z)
        if d <= tol and (best_d is None or d < best_d):
            best_d = d
            best = (lvl_id, lvl_elev)
    return best


def snap_end(z, levels, tol=TOL):
    """Round one end of a wall to the nearest inch.

    Returns ``(elevation, was_rounded)``.  An end that already sits on a
    level is returned untouched: the level defines that elevation, and
    nudging it would only manufacture a fractional offset.
    """
    if level_at(z, levels, tol) is not None:
        return z, False

    snapped = round_to_inch(z)
    return snapped, abs(snapped - z) > tol


def interior_levels(base_z, top_z, levels, tol=TOL):
    """Return the levels strictly inside the span, low to high.

    A level within *tol* of either end is flush with it, not crossed by
    it, so it is excluded.
    """
    inside = [(i, e) for i, e in levels
              if e > base_z + tol and e < top_z - tol]
    inside.sort(key=lambda pair: pair[1])
    return inside


def constraints_for(base_z, top_z, levels, tol=TOL):
    """Bind one vertical span to the levels around it.

    Returns a dict with ``base_level_id``, ``base_offset``,
    ``top_level_id``, ``top_offset``, ``height``, ``base_z`` and
    ``top_z``.  The top is always level-bound -- when the span rises
    above every level it binds to the highest one with a positive
    offset rather than falling back to an unconnected height.

    Raises ValueError when there are no levels or the span is not
    positive.
    """
    if not levels:
        raise ValueError("The model has no levels to bind the wall to.")
    if top_z - base_z <= tol:
        raise ValueError(
            "Top ({0:.4f}) is not above base ({1:.4f}).".format(top_z, base_z))

    below = nearest_level_at_or_below(base_z, levels, tol)
    if below is None:
        # Nothing underneath: hang off the lowest level instead.
        below = min(levels, key=lambda pair: pair[1])

    above = nearest_level_at_or_above(top_z, levels, tol)
    if above is None:
        # Nothing overhead: push up from the highest level instead.
        above = max(levels, key=lambda pair: pair[1])

    base_lvl, base_elev = below
    top_lvl, top_elev = above

    base_off = base_z - base_elev
    top_off = top_z - top_elev
    if abs(base_off) <= tol:
        base_off = 0.0
    if abs(top_off) <= tol:
        top_off = 0.0

    return {
        "base_level_id": base_lvl,
        "base_offset": base_off,
        "top_level_id": top_lvl,
        "top_offset": top_off,
        "height": top_z - base_z,
        "base_z": base_z,
        "top_z": top_z,
    }


def plan_wall(base_z, top_z, levels, tol=TOL, allow_split=True,
              allow_round=True):
    """Work out everything that should happen to one wall.

    *base_z* / *top_z* are the wall's current absolute extent.  Both
    ends are rounded first, then the span is cut at every level it
    crosses and each band is bound to its own levels.

    When *allow_split* is False the wall is left whole -- the caller has
    decided a split is unsafe -- but ``needs_split`` still reports that
    it crosses a level so the run can say so.

    When *allow_round* is False the ends are used exactly as given.  The
    caller sets this for walls whose geometry is drawn against the
    constraints, such as a sketched profile, where moving an end would
    drag the sketch with it.

    Returns a dict:
        base_z, top_z   the rounded span
        rounded         True when either end moved
        needs_split     True when the span crosses a level
        interior        the crossed levels, low to high
        bands           one constraints_for() dict per band, low to high

    Raises ValueError when rounding leaves nothing to build.
    """
    if allow_round:
        base_z, base_rounded = snap_end(base_z, levels, tol)
        top_z, top_rounded = snap_end(top_z, levels, tol)
    else:
        base_rounded = top_rounded = False

    if top_z - base_z <= tol:
        raise ValueError(
            "Rounding to the nearest inch leaves no height "
            "(base {0:.4f}, top {1:.4f}).".format(base_z, top_z))

    inside = interior_levels(base_z, top_z, levels, tol)

    if inside and allow_split:
        cuts = [base_z] + [e for _i, e in inside] + [top_z]
        bands = [constraints_for(lo, hi, levels, tol)
                 for lo, hi in zip(cuts, cuts[1:])]
    else:
        bands = [constraints_for(base_z, top_z, levels, tol)]

    return {
        "base_z": base_z,
        "top_z": top_z,
        "rounded": base_rounded or top_rounded,
        "needs_split": bool(inside),
        "interior": inside,
        "bands": bands,
    }


def constraints_changed(current, target, tol=TOL):
    """Compare a wall's current constraints against a planned band.

    *current* is ``(base_level_id, base_offset, top_level_id,
    top_offset)`` as read off the wall, with ``top_level_id`` None for
    an unconnected wall.  Offsets closer than *tol* count as equal, so a
    wall already in good shape is not rewritten.
    """
    cur_base_lvl, cur_base_off, cur_top_lvl, cur_top_off = current

    if cur_base_lvl != target["base_level_id"]:
        return True
    if cur_top_lvl != target["top_level_id"]:
        return True
    if abs(cur_base_off - target["base_offset"]) > tol:
        return True
    if abs(cur_top_off - target["top_offset"]) > tol:
        return True
    return False


# How near a level an end has to be before it is taken to be ON it.
# One inch: further than any modelling slop, closer than any real
# dimension a designer would have meant.
LEVEL_SNAP_TOL = INCH


def snap_span_to_levels(base_z, top_z, levels, tol=LEVEL_SNAP_TOL,
                        min_height=0.0):
    """Pull ends that all but reach a level onto it.

    Returns ``(base_z, top_z, moved)``.

    A coping whose base drops an inch below a level binds its base to
    the level BELOW that one and its top to the level above -- the house
    rule working exactly as written, and reading as nonsense: a parapet
    spanning 03 to 05 when it plainly sits on 04.  An end within *tol*
    of a level was meant to be on it.

    Each end is snapped on its own, so a span is stretched onto the
    levels rather than slid between them, and neither end drags the
    other.  Where this belongs is at the source: a sweep and the wall
    beneath it are cut from ONE number, so moving it moves both and no
    gap can open between them.  Snapping them separately afterwards is
    what would open one.

    A span that snapping would collapse -- a short sweep sitting astride
    a level, both ends reaching for it -- is returned untouched, since
    an unhelpful constraint beats a wall that cannot be built.
    *min_height* sets how much must survive.
    """
    if not levels:
        return base_z, top_z, False

    # An end exactly *tol* from a level must snap: the reach is stated
    # as a maximum, not an exclusive bound.  A hair of slack keeps that
    # promise, because an inch below a level does not come out exactly
    # an inch away in binary -- 10.0 - 1/12 lands 6e-16 too far.
    reach = tol + 1e-9

    new_base = base_z
    new_top = top_z

    found = level_at(base_z, levels, reach)
    if found is not None:
        new_base = found[1]

    found = level_at(top_z, levels, reach)
    if found is not None:
        new_top = found[1]

    if new_top - new_base <= max(min_height, 0.0):
        return base_z, top_z, False

    moved = (abs(new_base - base_z) > TOL or abs(new_top - top_z) > TOL)
    return new_base, new_top, moved
