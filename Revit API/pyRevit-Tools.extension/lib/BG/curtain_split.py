# -*- coding: utf-8 -*-
"""Reading a curtain wall's panels, for a tool about to cut one.

Wall Limits never cuts a curtain wall.  BG_LEVEL will, when asked to,
and two things then have to be known about the panels -- one before the
cut and one after.

BEFORE: where the doors are.  A wall is split by shortening the
original to the lowest band and building the storeys above it as new
walls, and a curtain wall's door is a PANEL of the original, standing
in a cell of its grid.  A door reaching above the first band is
therefore destroyed by the cut, and the band built above it comes out
of Wall.Create as plain glass, with no door in it and no way to put one
back that the user did not draw.  So the doors are measured first and
the caller is told how many are in the way; what it does about them is
its own business.

AFTER: what the new bands are made of.  A band is built fresh from the
wall type, so its cells are the type's own system panels and nothing
was carried up from below.  normalise_panels checks that rather than
assuming it, and puts back anything that is neither a door nor the
system panel.  It is deliberately never pointed at the ORIGINAL wall:
that one keeps the lowest band with the panels the user drew in it, and
they are not this tool's to normalise.

Nothing here decides anything.  Whether a count of doors forbids a cut
is wall_constraints.doors_above, which imports no Revit and is tested
without it; reading a panel's extent needs the API, and deciding what
the extent MEANS does not.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FamilyInstance,
)
from pyrevit import script

from BG import wall_bind

logger = script.get_logger()

# Ids are compared through wall_bind's reader, not with ==: ElementId
# equality does not reliably cross the Python boundary, and Revit 2024
# renamed IntegerValue to Value.
_eid = wall_bind.eid
_is_valid = wall_bind.is_valid


def is_door_panel(elem):
    """True when this curtain panel is a door family rather than glass.

    The one test BG.curtain_doors and this module share.  Two copies of
    it would be two answers to "is this a door", and the tools would
    disagree about which panels may be destroyed.
    """
    if not isinstance(elem, FamilyInstance):
        return False
    try:
        cat = elem.Category
        return (cat is not None
                and cat.Id == ElementId(BuiltInCategory.OST_Doors))
    except Exception:
        return False


def grid_of(wall):
    """A wall's CurtainGrid, or None when it has not got one."""
    try:
        return wall.CurtainGrid
    except Exception:
        return None


def panels_of(doc, wall):
    """Every panel element in *wall*'s curtain grid, skipping the unreadable."""
    grid = grid_of(wall)
    if grid is None:
        return []

    try:
        panel_ids = list(grid.GetPanelIds())
    except Exception:
        return []

    panels = []
    for pid in panel_ids:
        try:
            panel = doc.GetElement(pid)
        except Exception:
            continue
        if panel is not None:
            panels.append(panel)
    return panels


def door_tops(doc, wall):
    """The highest elevation of each door panel in *wall*.

    Returns ``(tops, unreadable)``: a list of elevations in feet, and a
    count of door panels whose extent could not be read at all.

    An unreadable door is counted rather than ignored, so a caller can
    treat "I cannot prove this cut is safe" the same way it treats a
    door plainly in the way -- which is what the basic-wall path
    already does with an insert whose bounding box comes back None.
    """
    tops = []
    unreadable = 0

    for panel in panels_of(doc, wall):
        if not is_door_panel(panel):
            continue
        try:
            bbox = panel.get_BoundingBox(None)
        except Exception:
            bbox = None
        if bbox is None:
            unreadable += 1
            continue
        tops.append(bbox.Max.Z)

    return tops, unreadable


def system_panel_id(wall):
    """The panel type *wall*'s own wall type lays its cells out with.

    That is the "system panel only" the new bands are held to: not a
    global default, but whatever this wall type was built to use.
    """
    try:
        p = wall.WallType.get_Parameter(BuiltInParameter.AUTO_PANEL)
    except Exception:
        return None
    if p is None:
        return None
    try:
        return p.AsElementId()
    except Exception:
        return None


def normalise_panels(doc, wall):
    """Make every non-door cell of *wall* the wall type's system panel.

    For a band this tool has just built this should find nothing: the
    band came out of Wall.Create with the type's own grid, and no panel
    was copied into it.  It is run anyway because that is the whole of
    the guarantee -- only doors are not system panels -- and a
    guarantee nobody checks is a hope.

    Returns ``(changed, notes)``.  A panel Revit will not retype is a
    note, not an exception: the band's constraints are right either
    way, and one stubborn cell must not cost the wall its split.
    """
    notes = []
    changed = 0

    target = system_panel_id(wall)
    if not _is_valid(target):
        # Nothing to hold the cells to.  Saying so beats retyping them
        # to whatever happened to be first.
        return 0, ["the wall type's system panel could not be read, so "
                   "its panels were left as Revit built them"]

    wanted = _eid(target)

    for panel in panels_of(doc, wall):
        if is_door_panel(panel):
            continue
        try:
            if _eid(panel.GetTypeId()) == wanted:
                continue
        except Exception:
            continue

        try:
            panel.ChangeTypeId(target)
            changed += 1
        except Exception as ex:
            logger.debug("Could not retype a panel: {0}".format(ex))
            notes.append("a panel could not be made the system panel: "
                         "{0}".format(ex))

    if changed:
        doc.Regenerate()

    return changed, notes
