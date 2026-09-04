# -*- coding: utf-8 -*-
"""Pure arithmetic and naming rules for the Multi Wall Creation tool.

Like Tahir.wall_limits and Tahir.wall_constraints this module imports
nothing from Revit, so every rule below can be unit-tested outside it.

What lives here is the part of the tool that decides things:

  * where a wall stops, given the sweeps running on it;
  * how tall a linked wall is, read off its constraint parameters;
  * which wall type a sweep's profile calls for;
  * which new walls sit at the same elevation and may be mitred together.

A *span* is an ``(low_z, high_z)`` pair of elevations in decimal feet,
in host-model geometry space.
"""

from Tahir.wall_limits import TOL_LEVEL_MATCH

# 1/16 inch in feet.  Shared with wall_limits and wall_constraints so all
# three tools agree on what "the same elevation" means.
TOL = TOL_LEVEL_MATCH

# The two wall types the sweep naming rule can resolve to.  Written out
# in full because they are matched against wall type names by equality,
# not by pattern.
CAST_STONE_TYPE_NAME = "SKIN_CAST STONE PROFILE_0' 2\""
EIFS_TYPE_NAME = "SKIN_EIFS PROFILE_0' 2\""


def clip(span, lo, hi):
    """Return *span* trimmed to the range [lo, hi], or None.

    A span given the wrong way round is normalised first, so a caller
    need not care which end of a sweep envelope came out larger.  None
    means nothing of the span survives inside the range.
    """
    a, b = span
    if b < a:
        a, b = b, a
    a = max(a, lo)
    b = min(b, hi)
    if b <= a:
        return None
    return (a, b)


def merge_spans(spans):
    """Return *spans* sorted low to high, overlaps and touches merged.

    Two sweeps that overlap must not each cut the wall separately -- the
    stretch between them does not exist, and reporting it as a dropped
    band would be noise.
    """
    merged = []
    for lo, hi in sorted(spans):
        if merged and lo <= merged[-1][1]:
            prev_lo, prev_hi = merged[-1]
            merged[-1] = (prev_lo, max(prev_hi, hi))
        else:
            merged.append((lo, hi))
    return merged


def subtract_spans(span, cutters, tol=TOL):
    """Cut *span* with every span in *cutters*.

    Returns ``(gaps, dropped)``, both low to high:

        gaps     the stretches of *span* left over, each at least *tol*
                 tall -- one new wall will be built per gap
        dropped  stretches thinner than *tol* that were left over but
                 are too thin to build.  The caller reports these, so a
                 sliver is never lost silently.

    Cutters outside *span* are ignored and cutters straddling its ends
    are clipped, so a sweep that runs past the top of its host wall does
    not extend the wall.  An exactly zero-height leftover is neither a
    gap nor a drop -- two sweeps meeting face to face leave nothing, and
    there is nothing to report about it.
    """
    base_z, top_z = span
    if top_z - base_z <= tol:
        return [], []

    clipped = []
    for cutter in cutters:
        piece = clip(cutter, base_z, top_z)
        if piece is not None:
            clipped.append(piece)

    gaps = []
    dropped = []
    cursor = base_z

    for lo, hi in merge_spans(clipped):
        _record(gaps, dropped, cursor, lo, tol)
        cursor = max(cursor, hi)

    _record(gaps, dropped, cursor, top_z, tol)
    return gaps, dropped


def _record(gaps, dropped, lo, hi, tol):
    """File one leftover stretch as a gap, a drop, or nothing at all."""
    height = hi - lo
    if height > tol:
        gaps.append((lo, hi))
    elif height > 0.0:
        dropped.append((lo, hi))


def wall_span(base_elev, base_offset, top_elev, top_offset,
              unconnected_height):
    """Return ``(base_z, top_z)`` for a wall, from its constraints.

    *base_elev* and *top_elev* are the elevations of the wall's Base and
    Top Constraint levels; *top_elev* is None when the wall has no top
    constraint, and the top then comes from *unconnected_height* above
    the base.

    Constraint parameters are used rather than the wall's solid because
    a wall attached to a sloping roof would otherwise report the highest
    point of that slope as its top, and every wall under it would be
    built to the wrong height.
    """
    base_z = base_elev + base_offset
    if top_elev is None:
        return base_z, base_z + unconnected_height
    return base_z, top_elev + top_offset


def sweep_wall_type_name(*names):
    """Return the wall type name a sweep's profile calls for, or None.

    *names* are searched in the order given -- the sweep's type name
    first, then its dominant material name -- so a type name that says
    what the profile is beats a material that says something else.
    Within one name STONE is tested before EIFS, so 'Cast Stone over
    EIFS' is stone.  Matching is a case-insensitive substring.

    None means the rule cannot tell, and the caller must ask.
    """
    for name in names:
        text = (name or "").upper()
        if "STONE" in text:
            return CAST_STONE_TYPE_NAME
        if "EIFS" in text:
            return EIFS_TYPE_NAME
    return None


def elevation_group_key(base_z, top_z, tol=TOL):
    """Return a key shared by bands at the same vertical extent.

    Only walls that actually sit at the same height may have their
    corners mitred together: mitring a band at 11-20 ft against its
    neighbour at 0-10 ft would drag a corner between two walls that
    never touch.  Elevations are quantised to *tol* so two bands cut by
    the same sweep group together despite floating-point drift.
    """
    return (int(round(base_z / tol)), int(round(top_z / tol)))
