# -*- coding: utf-8 -*-
"""Re-pointing a level-based element at the level below it.

A wall carries a base AND a top, and can be cut in half when it crosses
a storey; that is what BG.wall_constraints is for.  Everything else in
a model -- a floor, a ceiling, a roof, a light fitting, a run of duct --
carries ONE level reference and an offset from it, and the only
question worth asking of it is whether that level is the one under it.

This is the arithmetic for that question.  Like wall_constraints it
imports nothing from Revit, so the rule can be tested outside it; the
caller turns Revit parameters into two numbers and turns the answer
back into parameters.

THE RULE, as asked for: an element belongs to the level at or
immediately below its reference point, with a positive offset.  Taken
literally, including the case it reads oddly in -- a slab dropped two
inches below a storey belongs to the storey underneath, with an offset
of very nearly a full storey height.  That is the rule the model is to
be held to, and softening it here would mean two rules.

THE ELEMENT NEVER MOVES.  The new offset is DEFINED as the difference
between the element's reference elevation and its new level, so
conserving that elevation is not something this code remembers to do --
it is the only thing it can do.  The caller still reads the written
values back and checks, because the parameters it writes through are
Revit's and this module's guarantee stops at the arithmetic.
"""

from BG.wall_limits import TOL_LEVEL_MATCH, nearest_level_at_or_below

# The same 1/16" every other module here calls "on a level".
TOL = TOL_LEVEL_MATCH


def reference_z(level_elevation, offset):
    """The absolute elevation an element sits at.

    The point Revit itself places the element from, which is why it is
    the one thing worth conserving: whatever that point means for a
    given category -- a slab's top, a fitting's insertion point -- the
    element is where it is because of it.
    """
    return level_elevation + offset


# How far outside its own solid an element's reference point may sit
# and still be believed, in feet.  A reference point is not obliged to
# be inside the element -- a fitting can hang below its insertion point
# -- but it is obliged to be somewhere near it.  Two feet is wider than
# any such overhang and far narrower than a storey, which is the size
# of the error this exists to catch.
EXTENT_SLACK = 2.0


def describes(z, extent_lo, extent_hi, slack=EXTENT_SLACK):
    """True when *z* could plausibly be where this element sits.

    Level plus offset is the point Revit places most things from, and
    the whole re-referencing rule is built on that.  It is not true of
    everything: a CURTAIN PANEL is placed by the curtain grid, and its
    level and elevation parameters are left saying something unrelated.
    A door panel standing at 13'-0" reported Level 01 with an offset of
    -13'-0" -- a reference point of 0'-0", below every level in the
    building, so it was dutifully rebased onto the lowest one and its
    level name came out as the basement.

    The arithmetic was right and the input was never a position.  So
    the point is checked against the element's own vertical extent
    before anything is done with it, which catches that for every
    category rather than only for the one that was noticed.

    An element whose extent cannot be measured is believed: not being
    able to check is not evidence against it.
    """
    if extent_lo is None or extent_hi is None:
        return True
    return extent_lo - slack <= z <= extent_hi + slack


def rebase(z, levels, tol=TOL):
    """The level and offset an element at *z* should carry.

    Returns ``(level_id, offset)``.  *levels* is the usual sequence of
    ``(level_id, elevation)`` pairs.

    An element below every level hangs off the lowest one with a
    NEGATIVE offset -- the only case that produces one, and the same
    answer wall_constraints.constraints_for gives a wall with nothing
    underneath it.

    Raises ValueError when there are no levels to choose from.
    """
    if not levels:
        raise ValueError("The model has no levels to reference.")

    below = nearest_level_at_or_below(z, levels, tol)
    if below is None:
        below = min(levels, key=lambda pair: pair[1])

    level_id, elevation = below
    offset = z - elevation
    if abs(offset) <= tol:
        offset = 0.0
    return level_id, offset


def needs_rebase(level_id, offset, levels, tol=TOL):
    """True when this element's level reference is not the one below it.

    *level_id* and *offset* are what the element carries now.  A level
    this model does not have counts as needing rebasing: its elevation
    cannot be read, so the reference cannot be shown to be right.
    """
    elevations = dict(levels)
    if level_id not in elevations:
        return True

    z = reference_z(elevations[level_id], offset)
    wanted_id, wanted_offset = rebase(z, levels, tol)

    if wanted_id != level_id:
        return True
    return abs(wanted_offset - offset) > tol
