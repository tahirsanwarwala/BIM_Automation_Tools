# -*- coding: utf-8 -*-
"""Pure height/limit arithmetic for the SplitWalls tool.

Deliberately free of any Revit import so it can be unit-tested outside
Revit.  The pushbutton script converts Revit objects into the plain
tuples these functions expect.

Coordinates are decimal feet in host-model world space.
"""

# 1/16 inch, expressed in feet
TOL_LEVEL_MATCH = 0.0052083333


def _apply(transform, pt):
    """Apply a (basis_x, basis_y, basis_z, origin) transform to an (x,y,z)."""
    if transform is None:
        return pt

    bx, by, bz, origin = transform
    x, y, z = pt
    return (
        origin[0] + bx[0] * x + by[0] * y + bz[0] * z,
        origin[1] + bx[1] * x + by[1] * y + bz[1] * z,
        origin[2] + bx[2] * x + by[2] * y + bz[2] * z,
    )


def transform_bbox_z_range(bbox_min, bbox_max, transform=None):
    """Return (min_z, max_z) of a bounding box after *transform*.

    All eight corners are transformed rather than just the min/max point,
    so rotated link transforms give the correct vertical extent.
    """
    world_zs = []
    for x in (bbox_min[0], bbox_max[0]):
        for y in (bbox_min[1], bbox_max[1]):
            for z in (bbox_min[2], bbox_max[2]):
                world_zs.append(_apply(transform, (x, y, z))[2])
    return min(world_zs), max(world_zs)


def pick_extreme_z(min_z, max_z, click_z):
    """Choose the top or bottom of a vertical range based on where the
    user clicked.  A click at or above mid-height selects the top.
    """
    mid = (min_z + max_z) / 2.0
    if click_z >= mid:
        return max_z
    return min_z


def match_level_by_elevation(elevation, levels, tol=TOL_LEVEL_MATCH):
    """Return the id of the level closest to *elevation* within *tol*.

    *levels* is a sequence of (level_id, elevation).  Returns None when
    nothing is close enough.
    """
    best_id = None
    best_d = None
    for lvl_id, lvl_elev in levels:
        d = abs(lvl_elev - elevation)
        if d <= tol and (best_d is None or d < best_d):
            best_d = d
            best_id = lvl_id
    return best_id


def nearest_level_at_or_below(elevation, levels, tol=TOL_LEVEL_MATCH):
    """Return (level_id, elevation) of the highest level at or below
    *elevation*, or None when every level sits above it.
    """
    best = None
    for lvl_id, lvl_elev in levels:
        if lvl_elev <= elevation + tol:
            if best is None or lvl_elev > best[1]:
                best = (lvl_id, lvl_elev)
    return best


def nearest_level_at_or_above(elevation, levels, tol=TOL_LEVEL_MATCH):
    """Return (level_id, elevation) of the lowest level at or above
    *elevation*, or None when every level sits below it.
    """
    best = None
    for lvl_id, lvl_elev in levels:
        if lvl_elev >= elevation - tol:
            if best is None or lvl_elev < best[1]:
                best = (lvl_id, lvl_elev)
    return best


def compute_wall_limits(base_elev, base_level_id, top_elev, top_level_id,
                        levels):
    """Turn two picked elevations into Revit wall constraints.

    *base_level_id* / *top_level_id* are host Level ids when the pick
    resolved to a bindable level, otherwise None.

    Returns a dict:
        base_level_id  host Level to host the wall (always set)
        base_offset    offset from that level, feet
        top_level_id   host Level for "Up to level", or None
        top_offset     offset from the top level, feet
        height         unconnected height, feet -- also used as the
                       creation seed when the top is level-bound

    Raises ValueError when the limits cannot produce a valid wall.
    """
    if top_elev <= base_elev:
        raise ValueError(
            "Top limit must be above the base limit "
            "(base {0:.4f}, top {1:.4f})".format(base_elev, top_elev))

    elev_by_id = dict(levels)

    if base_level_id is not None:
        base_lvl = base_level_id
        base_off = 0.0
        # Binding wins over the picked elevation; see the spec note on
        # absorbing the match tolerance.
        eff_base = elev_by_id[base_level_id]
    else:
        found = nearest_level_at_or_below(base_elev, levels)
        if found is None:
            if not levels:
                raise ValueError(
                    "No levels found to host the wall "
                    "(base limit {0:.4f})".format(base_elev))
            elevs = [e for _i, e in levels]
            raise ValueError(
                "No level at or below the base limit ({0:.4f}).\n"
                "Levels available span {1:.4f} to {2:.4f}.\n"
                "A large gap here usually means the picked elevation and the "
                "level elevations are in different coordinate spaces.".format(
                    base_elev, min(elevs), max(elevs)))
        base_lvl, lvl_elev = found
        base_off = base_elev - lvl_elev
        eff_base = base_elev

    if top_level_id is not None:
        # The user picked a level outright.
        top_lvl = top_level_id
        top_off = 0.0
    else:
        # A non-level reference still binds parametrically: attach to the
        # immediate level ABOVE the picked point and hang down from it with
        # a negative offset.  Only when nothing sits above does the wall
        # fall back to an unconnected height.
        above = nearest_level_at_or_above(top_elev, levels)
        if above is None:
            top_lvl = None
            top_off = 0.0
        else:
            top_lvl, above_elev = above
            top_off = top_elev - above_elev

    return {
        "base_level_id": base_lvl,
        "base_offset": base_off,
        "top_level_id": top_lvl,
        "top_offset": top_off,
        "height": top_elev - eff_base,
    }
