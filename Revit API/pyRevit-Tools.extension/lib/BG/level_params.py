# -*- coding: utf-8 -*-
"""Reading and writing an element's level reference, whatever it is.

Every category names its level and its offset from that level in its
own parameters, and re-pointing an element is only safe when BOTH can
be written: the level alone moves the element by a storey, and that is
the one thing this must never do.  So everything here works in PAIRS,
and an element whose pair cannot be completed is left alone and
reported rather than half-changed.

It decides nothing.  Which level an element belongs to is
BG.level_ref, which imports no Revit and is tested without it; reading
a parameter needs the API, and choosing a level does not.

WHY A WRONG ENTRY IS SAFE.  The BuiltInParameter enum is not stable
across Revit releases, and these names cannot be checked against the
API from outside Revit.  They do not have to be: wall_bind.bip returns
None for a name this release has never heard of, an incomplete pair
never matches, and the element falls through to the next pair or out of
the table entirely -- into the report, as unhandled.  The cost of a
wrong name is an element nobody touched; there is no path by which it
becomes an element written wrongly.

WALLS ARE NOT HERE.  A wall carries a base and a top, can be split at a
storey and stopped under a slab; BG.wall_bind does all of that and this
would only be a worse copy of its base half.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import Level, StorageType, SubTransaction
from pyrevit import script

from BG import level_ref
from BG import wall_bind

logger = script.get_logger()

# (parameter naming the level, parameter holding the offset from it).
#
# Tried in order.  Floors and ceilings share LEVEL_PARAM and are told
# apart by their offsets: a ceiling has no FLOOR_HEIGHTABOVELEVEL_PARAM,
# so the floor pair simply does not match it and the next one does.
# That is why the table can be a flat list rather than a map keyed by
# category -- the parameters an element HAS are what identify it.
PAIRS = (
    ("LEVEL_PARAM",                    "FLOOR_HEIGHTABOVELEVEL_PARAM"),
    ("LEVEL_PARAM",                    "CEILING_HEIGHTABOVELEVEL_PARAM"),
    ("ROOF_BASE_LEVEL_PARAM",          "ROOF_LEVEL_OFFSET_PARAM"),
    ("FAMILY_BASE_LEVEL_PARAM",        "FAMILY_BASE_LEVEL_OFFSET_PARAM"),
    ("FAMILY_LEVEL_PARAM",             "INSTANCE_ELEVATION_PARAM"),
    ("INSTANCE_REFERENCE_LEVEL_PARAM", "INSTANCE_FREE_HOST_OFFSET_PARAM"),
    ("STAIRS_BASE_LEVEL_PARAM",        "STAIRS_BASE_OFFSET"),
    ("RBS_START_LEVEL_PARAM",          "RBS_OFFSET_PARAM"),
)

_eid = wall_bind.eid
_is_valid = wall_bind.is_valid


class Misplaced(Exception):
    """An element whose level and offset do not say where it stands.

    Raised rather than returned as None because the two mean different
    things to a caller: None is "nothing here to do", which is most of
    a model and says nothing; this is "there was something here and it
    did not add up", which is worth a row in the report.  The curtain
    panel that started all this would have been silently skipped under
    None, and the next category like it would be too.
    """


class Reference(object):
    """What an element says about where it sits, and how to change it.

    *level_id* and *offset* are what it carries now, *z* the absolute
    elevation those two make, and the two parameters are kept so the
    answer can be written back through the very ones it was read from.
    """

    __slots__ = ("level_id", "offset", "z", "level_param", "offset_param")

    def __init__(self):
        self.level_id     = None
        self.offset       = 0.0
        self.z            = None
        self.level_param  = None
        self.offset_param = None


def _level_elevation(doc, level_id):
    """The elevation of a level id, or None when it is not a Level."""
    if not _is_valid(level_id):
        return None
    element = doc.GetElement(level_id)
    if not isinstance(element, Level):
        return None
    try:
        return element.Elevation
    except Exception:
        return None


def _writable(p, storage):
    """True when this parameter exists, holds *storage*, and can be set."""
    if p is None:
        return False
    try:
        return not p.IsReadOnly and p.StorageType == storage
    except Exception:
        return False


def reference_of(doc, elem):
    """How *elem* is referenced to a level, or None when it cannot be.

    None is the answer for everything this module will not touch: an
    element with no pair in the table, one whose level or offset is
    read-only -- a window whose level follows the wall hosting it, say
    -- and one whose level parameter does not resolve to a Level.  All
    of them are elements to leave alone and say so about, not elements
    to guess at.
    """
    if host_reason(elem):
        # Placed by its host, not by its level.  See host_reason.
        return None

    for level_name, offset_name in PAIRS:
        level_bip = wall_bind.bip(level_name)
        offset_bip = wall_bind.bip(offset_name)
        if level_bip is None or offset_bip is None:
            # Not in this release of Revit.  Nothing to do but move on.
            continue

        try:
            p_level = elem.get_Parameter(level_bip)
            p_offset = elem.get_Parameter(offset_bip)
        except Exception:
            continue

        if not _writable(p_level, StorageType.ElementId):
            continue
        if not _writable(p_offset, StorageType.Double):
            continue

        try:
            level_id = p_level.AsElementId()
            offset = p_offset.AsDouble()
        except Exception:
            continue

        elevation = _level_elevation(doc, level_id)
        if elevation is None:
            continue

        z = level_ref.reference_z(elevation, offset)

        # Does that point actually describe this element?  The rule is
        # built on level + offset being where Revit places a thing, and
        # where that is not true the arithmetic is fed a number that
        # was never a position.  See level_ref.describes.
        low, high = extent_of(elem)
        if not level_ref.describes(z, low, high):
            raise Misplaced(
                "its level and offset put it at {0}, which is nowhere "
                "near where it stands ({1} to {2}) - so they do not say "
                "where it is, and it was left alone".format(
                    wall_bind.feet_to_text(z),
                    wall_bind.feet_to_text(low),
                    wall_bind.feet_to_text(high)))

        ref = Reference()
        ref.level_id     = level_id
        ref.offset       = offset
        ref.z            = z
        ref.level_param  = p_level
        ref.offset_param = p_offset
        return ref

    return None


def host_reason(elem):
    """Why this element's level is a label rather than a placement.

    An element placed by a HOST is put where the host puts it: a
    curtain panel by its curtain grid, a door by its wall, a light by
    its ceiling.  Its level parameter records which storey it is filed
    under, and its offset records something of its own -- neither is
    the point Revit positions it from, which is the one thing the
    re-referencing rule needs.

    A curtain wall door panel is what taught this.  It reported Level
    01 with an offset of -13'-0", a reference point of 0'-0", below
    every level in the building; it was dutifully re-pointed at the
    lowest one and its level name came out as the basement, while the
    door itself stood at 13'-0" where the grid had always put it.

    Being writable is NOT the test -- that panel's level parameter was
    perfectly writable -- so having a host is.
    """
    try:
        if elem.Host is not None:
            return "hosted, so its level follows what hosts it"
    except Exception:
        # No Host property at all: not a hosted family instance.
        pass
    return None


def extent_of(elem):
    """(lowest, highest) z of an element, or (None, None).

    Only ever used to sanity-check a reference point, so a bounding box
    is enough and its cost is paid only by elements that got as far as
    matching a pair.
    """
    try:
        bbox = elem.get_BoundingBox(None)
    except Exception:
        return None, None
    if bbox is None:
        return None, None
    try:
        return bbox.Min.Z, bbox.Max.Z
    except Exception:
        return None, None


def group_reason(elem):
    """Why this element must be left alone entirely, or None.

    Grouped elements only.  Revit refuses edits to a group member in
    ways that surface at commit rather than where they happen, which is
    exactly the failure the wall pass already declines to walk into.
    """
    try:
        if _is_valid(elem.GroupId):
            return "in a group (Revit will not take the change)"
    except Exception:
        pass
    return None


def verify(doc, ref, z, tol=level_ref.TOL):
    """Read the written values back and confirm the element has not moved.

    The arithmetic conserves the elevation by construction, so this is
    not checking the sums -- it is checking that Revit took what it was
    given.  A parameter that silently refuses a value, or rounds it to
    something of its own, would otherwise move the element quietly, and
    the whole promise of this feature is that it does not.

    Returns a problem as text, or None when the element is where it was.
    """
    try:
        level_id = ref.level_param.AsElementId()
        offset = ref.offset_param.AsDouble()
    except Exception as ex:
        return "the new level reference could not be read back: {0}".format(ex)

    elevation = _level_elevation(doc, level_id)
    if elevation is None:
        return "the new level is not a level"

    landed = level_ref.reference_z(elevation, offset)
    if abs(landed - z) > tol:
        return ("the element moved: it was referenced at {0} and is now at "
                "{1}".format(wall_bind.feet_to_text(z),
                             wall_bind.feet_to_text(landed)))
    return None


def apply(doc, elem, ref, level_id, offset):
    """Write a new level and offset, or leave the element as it was.

    Both writes happen inside a SubTransaction of its own, so an
    element Revit will not take costs nothing but itself -- and
    crucially not a commit, which is what a Transaction per element
    would have cost across a thousand of them.

    Returns a problem as text, or None when it is done.
    """
    st = SubTransaction(doc)
    st.Start()
    try:
        ref.level_param.Set(level_id)
        ref.offset_param.Set(offset)

        problem = verify(doc, ref, ref.z)
        if problem:
            st.RollBack()
            return problem

        st.Commit()
        return None
    except Exception as ex:
        try:
            st.RollBack()
        except Exception:
            pass
        logger.debug("Could not re-reference an element: {0}".format(ex))
        return "Revit refused the new level reference: {0}".format(ex)
