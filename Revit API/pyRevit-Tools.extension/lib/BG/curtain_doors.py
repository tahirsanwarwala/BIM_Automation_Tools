# -*- coding: utf-8 -*-
"""Carrying a door panel out of a linked curtain wall into a new one.

A curtain wall in the linked model can have a door standing in one of
its cells -- not a door hosted in a wall, but a door family used AS a
curtain panel.  Window To Curtain Wall rebuilds that wall as one plain
sheet of glass, and this is what puts the door back.

Three things have to happen, and only the first is obvious:

  * the door panel is measured in the SOURCE wall's own frame, so its
    jambs and head are known as distances along and up the wall rather
    than as coordinates that mean nothing on the new one;
  * its family type is found in the host model, or copied out of the
    link when it is not there.  Copying between documents cannot happen
    inside a transaction, so resolve_symbols has to run before the one
    that places anything;
  * grid lines are added back to the new wall -- two at the jambs, one
    at the head -- because a door needs a cell of its own to stand in,
    and the tool has just stripped every line the type came with.  The
    jambs run the full height, since that is what makes the bay; the
    head runs across that bay only, since a full-width line there would
    divide the glass either side of the door as well.

Only DOORS are carried.  A linked curtain wall's other panels, mullions
and grid lines are all left behind: the new wall is glass everywhere
the door is not.

A panel is measured from its solids where that works and from its
bounding box where it does not -- a curtain panel is a slab standing
flat in its own wall, so the box around it is the panel.  Panels
covering the same patch of wall are then collapsed into one, because a
door family with nested shared components puts several Doors-category
instances in a single cell and they are all one door.  A panel with no
geometry by either route is not a door at all but a slot the linked
wall keeps for a cell something else occupies, and it is skipped
without a word.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    CopyPasteOptions,
    ElementId,
    ElementTransformUtils,
    FamilyInstance,
    FamilySymbol,
    FilteredElementCollector,
    Transform,
    XYZ,
)
from System.Collections.Generic import List
from pyrevit import script

from BG import window_cw

logger = script.get_logger()

# A grid line this close to an end of the wall, in feet, is the end of
# the wall: Revit will not take it, and it would divide nothing.
EDGE_TOL = 0.02

# Narrower or shorter than this, in feet, and whatever was measured is
# not a door.
MIN_DOOR = 0.5


class DoorPanel(object):
    """One door panel from a linked curtain wall, in the wall's frame.

    *u_lo* and *u_hi* are distances along the source wall from the
    plan's own CENTRE, signed along its direction, so they carry onto a
    new wall of the same width without knowing where either wall
    starts; *z_lo* and *z_hi* are absolute elevations in host
    coordinates.  *symbol_id* is the door's type in the LINK, which is
    all that survives until resolve_symbols finds or copies it here.
    """

    __slots__ = ("symbol_id", "family_name", "type_name",
                 "u_lo", "u_hi", "z_lo", "z_hi")

    def __init__(self):
        self.symbol_id   = None
        self.family_name = ""
        self.type_name   = ""

    @property
    def label(self):
        return "{}: {}".format(self.family_name or "?",
                               self.type_name or "?")


def _is_door(elem):
    """True when this panel is a door family rather than glass."""
    if not isinstance(elem, FamilyInstance):
        return False
    try:
        cat = elem.Category
        return (cat is not None
                and cat.Id == ElementId(BuiltInCategory.OST_Doors))
    except Exception:
        return False


def _symbol_names(symbol):
    """(family name, type name) for a FamilySymbol, as best as can be read."""
    family = ""
    try:
        family = symbol.Family.Name
    except Exception:
        pass
    return family, window_cw.get_element_name(symbol)


def _extent_from_solids(panel, transform, origin, direction):
    """(u_lo, u_hi, z_lo, z_hi) from the panel's own solids, or None.

    The exact answer where it works: the solids are tessellated and
    every vertex projected onto the wall, so a panel is measured where
    it truly is rather than where a box around it reaches.
    """
    us = []
    zs = []
    try:
        for p in window_cw.iter_solid_points(panel, transform):
            us.append((p.X - origin.X) * direction.X
                      + (p.Y - origin.Y) * direction.Y)
            zs.append(p.Z)
    except Exception as ex:
        logger.debug("Solid measure failed: {}".format(ex))

    if len(us) < 2 or len(zs) < 2:
        return None
    return min(us), max(us), min(zs), max(zs)


def _extent_from_bbox(panel, transform, origin, direction):
    """The same, from the panel's bounding box.  Cruder, and enough.

    A door panel whose geometry cannot be walked still has a box, and
    for a panel standing flat in its own wall the box IS the panel --
    a curtain panel is a slab with no overhang to inflate it.  The box
    comes back axis-aligned in the LINK's coordinates, so all eight
    corners are transformed rather than just the two.
    """
    try:
        bbox = panel.get_BoundingBox(None)
    except Exception:
        return None
    if bbox is None:
        return None

    lo, hi = bbox.Min, bbox.Max
    us = []
    zs = []
    for x in (lo.X, hi.X):
        for y in (lo.Y, hi.Y):
            for z in (lo.Z, hi.Z):
                p = XYZ(x, y, z)
                if bbox.Transform is not None:
                    p = bbox.Transform.OfPoint(p)
                p = transform.OfPoint(p)
                us.append((p.X - origin.X) * direction.X
                          + (p.Y - origin.Y) * direction.Y)
                zs.append(p.Z)

    if len(us) < 2:
        return None
    return min(us), max(us), min(zs), max(zs)


def _overlaps(door, other, tol=0.02):
    """True when two measured doors are really the same opening.

    A door family with nested shared components can put more than one
    Doors-category instance in one cell, and each measures to the same
    patch of wall.  Rather than build three doors on top of each other,
    the ones that cover the same ground are collapsed into one.
    """
    return (door.u_lo < other.u_hi - tol and other.u_lo < door.u_hi - tol
            and door.z_lo < other.z_hi - tol
            and other.z_lo < door.z_hi - tol)


def find_door_panels(wall, link_doc, transform, origin, direction):
    """Measure every DOOR panel in a linked curtain wall.

    *origin* is the plan's own centre and *direction* the source
    wall's direction, both in host coordinates -- the same frame the
    sketched profile is carried in -- so a door measured here lands in
    the same place a profile would.

    Panels covering the same patch of wall are collapsed into one: a
    door family with nested shared components puts several
    Doors-category instances in a single cell, and they are one door.

    Returns (list of DoorPanel, list of notes).
    """
    notes = []
    found = []

    if origin is None or direction is None:
        return found, ["the source wall's frame could not be read, so "
                       "its door panels were left out"]

    try:
        grid = wall.CurtainGrid
    except Exception:
        return found, notes
    if grid is None:
        return found, notes

    try:
        panel_ids = list(grid.GetPanelIds())
    except Exception:
        return found, notes

    for pid in panel_ids:
        try:
            panel = link_doc.GetElement(pid)
        except Exception:
            continue
        if not _is_door(panel):
            continue

        label = "door panel id {}".format(window_cw.eid_value(pid))
        try:
            symbol = panel.Symbol
            family, type_name = _symbol_names(symbol)
            label = "{} ({}: {})".format(label, family or "?",
                                         type_name or "?")
        except Exception:
            notes.append("{} has no readable type and was left out"
                         .format(label))
            continue

        extent = _extent_from_solids(panel, transform, origin, direction)
        if extent is None:
            extent = _extent_from_bbox(panel, transform, origin, direction)
            if extent is not None:
                logger.debug("{} measured from its bounding box"
                             .format(label))

        if extent is None:
            # No solids AND no bounding box means no geometry at all,
            # and a panel with no geometry is not a door -- it is a
            # slot the linked wall keeps for a cell something else
            # occupies.  One real door came with two of these beside
            # it, so they are skipped rather than reported: a note per
            # phantom would open the output window on every clean run.
            logger.debug("{} has no geometry; skipped".format(label))
            continue

        door = DoorPanel()
        door.symbol_id   = symbol.Id
        door.family_name = family
        door.type_name   = type_name
        door.u_lo, door.u_hi, door.z_lo, door.z_hi = extent

        if door.u_hi - door.u_lo < MIN_DOOR or door.z_hi - door.z_lo < MIN_DOOR:
            notes.append("{} measured to nothing and was left out"
                         .format(label))
            continue

        twin = next((d for d in found if _overlaps(door, d)), None)
        if twin is not None:
            # Keep the larger of the two: the outer panel, not a handle
            # or a vision light nested inside it.
            if ((door.u_hi - door.u_lo) * (door.z_hi - door.z_lo) >
                    (twin.u_hi - twin.u_lo) * (twin.z_hi - twin.z_lo)):
                found[found.index(twin)] = door
            continue

        found.append(door)

    return found, notes


# ===========================================================================
# THE TYPE, IN THE HOST MODEL
# ===========================================================================

def _host_door_symbols(doc):
    """{(family, type): FamilySymbol} for every door type in *doc*."""
    table = {}
    for sym in (FilteredElementCollector(doc)
                .OfClass(FamilySymbol)
                .OfCategory(BuiltInCategory.OST_Doors)):
        family = ""
        try:
            family = sym.Family.Name
        except Exception:
            pass
        table[(family, window_cw.get_element_name(sym))] = sym
    return table


def resolve_symbols(doc, link_doc, doors):
    """Find each door's type here, copying it from the link if need be.

    MUST run outside a transaction.  A cross-document copy opens its
    own, and Revit refuses it inside one -- which is the whole reason
    this is a step of its own rather than part of placing the doors.

    Returns ({(family, type): FamilySymbol or None}, notes).
    """
    notes = []
    table = _host_door_symbols(doc)
    found = {}

    wanted = {}
    for door in doors:
        wanted.setdefault((door.family_name, door.type_name), door)

    for key, door in wanted.items():
        if key in table:
            found[key] = table[key]
            continue

        try:
            ids = List[ElementId]()
            ids.Add(door.symbol_id)
            copied = ElementTransformUtils.CopyElements(
                link_doc, ids, doc, Transform.Identity, CopyPasteOptions())
        except Exception as ex:
            found[key] = None
            notes.append("could not copy the door type '{}' out of the "
                         "link: {}".format(door.label, ex))
            continue

        symbol = None
        for new_id in copied or []:
            candidate = doc.GetElement(new_id)
            if isinstance(candidate, FamilySymbol):
                symbol = candidate
                break

        if symbol is None:
            found[key] = None
            notes.append("the door type '{}' was not in this model and "
                         "could not be copied".format(door.label))
        else:
            found[key] = symbol
            notes.append("door type '{}' was copied out of the link"
                         .format(door.label))

    return found, notes


# ===========================================================================
# PUTTING THEM BACK
# ===========================================================================

def _wall_frame(wall):
    """(origin, direction) for a host wall, or (None, None)."""
    try:
        curve = wall.Location.Curve
    except Exception:
        return None, None
    if curve is None:
        return None, None
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    d = p1 - p0
    length = (d.X ** 2 + d.Y ** 2) ** 0.5
    if length < 1e-9:
        return None, None
    return p0, XYZ(d.X / length, d.Y / length, 0.0)


def _at(origin, direction, u, z):
    """A point on the wall's centreline, *u* along it and at elevation *z*."""
    return XYZ(origin.X + direction.X * u,
               origin.Y + direction.Y * u,
               z)


def _add_line(grid, is_horizontal, point, one_segment=False):
    """Add one grid line, and say whether it took.

    *one_segment* keeps the line inside the single cell the point falls
    in, instead of running it the whole way across the wall.  That is
    what the door's HEAD needs: a full-width line there would divide
    the glass either side of the door as well, which is a line the
    building does not have.  The jambs are the opposite case -- they
    have to run full height to make the bay in the first place.
    """
    try:
        grid.AddGridLine(is_horizontal, point, one_segment)
        return True
    except Exception as ex:
        logger.debug("Could not add a grid line: {}".format(ex))
        return False


def _panel_at(doc, grid, origin, direction, u, z):
    """The panel whose centre is nearest (u, z), or None."""
    best = None
    best_gap = None
    try:
        panel_ids = list(grid.GetPanelIds())
    except Exception:
        return None

    for pid in panel_ids:
        panel = doc.GetElement(pid)
        if panel is None:
            continue
        try:
            bbox = panel.get_BoundingBox(None)
        except Exception:
            continue
        if bbox is None:
            continue

        cx = (bbox.Min.X + bbox.Max.X) / 2.0
        cy = (bbox.Min.Y + bbox.Max.Y) / 2.0
        cz = (bbox.Min.Z + bbox.Max.Z) / 2.0
        cu = (cx - origin.X) * direction.X + (cy - origin.Y) * direction.Y

        gap = ((cu - u) ** 2 + (cz - z) ** 2) ** 0.5
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best = panel

    return best


def place_doors(doc, wall, doors, symbols):
    """Cut cells into *wall* for each door and swap the panels in.

    Runs INSIDE a transaction, and after the grid has been stripped for
    the last time: Revit rebuilds a wall's grid from its type whenever
    the wall is reshaped, so anything added before the last strip would
    be swept away with it.

    A door's u is measured from the PLAN's centre, and the new wall is
    built centred on that same point, so the wall's own half-length is
    all that is needed to lay it back down.

    Returns a list of notes.
    """
    notes = []
    if not doors:
        return notes

    origin, direction = _wall_frame(wall)
    if origin is None:
        return ["the new wall has no usable centreline, so its doors "
                "were left out"]

    try:
        grid = wall.CurtainGrid
    except Exception:
        grid = None
    if grid is None:
        return ["the new wall has no curtain grid to put a door in"]

    try:
        curve  = wall.Location.Curve
        length = curve.GetEndPoint(0).DistanceTo(curve.GetEndPoint(1))
    except Exception:
        length = None
    if not length:
        return ["the new wall has no measurable length, so its doors "
                "were left out"]
    half = length / 2.0

    bbox = None
    try:
        bbox = wall.get_BoundingBox(None)
    except Exception:
        pass
    top_z = bbox.Max.Z if bbox is not None else None

    for door in doors:
        key = (door.family_name, door.type_name)
        symbol = symbols.get(key)
        if symbol is None:
            notes.append("no door type for '{}', so its panel was left "
                         "as glass".format(door.label))
            continue

        u_lo = door.u_lo + half
        u_hi = door.u_hi + half
        z_mid = (door.z_lo + door.z_hi) / 2.0
        u_mid = (u_lo + u_hi) / 2.0

        # Jambs.  A jamb sitting on an end of the wall divides nothing,
        # and Revit will not take a line there, so it is skipped rather
        # than reported: the wall's own end is already that edge.
        for u in (u_lo, u_hi):
            if u <= EDGE_TOL:
                continue
            if u >= length - EDGE_TOL:
                continue
            _add_line(grid, False, _at(origin, direction, u, z_mid))

        # The head, only when there is glass above -- and only across
        # the door's own bay, which is why the jambs went in first.
        if top_z is None or door.z_hi <= top_z - EDGE_TOL:
            _add_line(grid, True, _at(origin, direction, u_mid, door.z_hi),
                      one_segment=True)

        doc.Regenerate()

        panel = _panel_at(doc, grid, origin, direction, u_mid, z_mid)
        if panel is None:
            notes.append("could not find the cell for '{}'".format(
                door.label))
            continue

        if not symbol.IsActive:
            try:
                symbol.Activate()
                doc.Regenerate()
            except Exception:
                pass

        try:
            panel.ChangeTypeId(symbol.Id)
            doc.Regenerate()
        except Exception as ex:
            notes.append("could not make '{}' the panel: {}".format(
                door.label, ex))

    return notes
