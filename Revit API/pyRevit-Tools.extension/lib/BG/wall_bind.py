# -*- coding: utf-8 -*-
"""Binding a wall to a vertical extent, and cloning it into another.

Shared by the two tools that rewrite a wall's vertical constraints:
Wall Limits, which rewrites them to the house rule, and Split Wall,
which cuts one wall into two at a chosen elevation.  Both do the same
three awkward things, and neither should own its own copy of them.

The awkward part is not the arithmetic -- that is BG.wall_constraints,
and it is unit-tested outside Revit.  It is that Revit refuses a wall
whose top passes below its base at any point on the way, so HOW the
four parameters are written matters as much as what they are set to.
See bind_extent.
"""

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    Element,
    ElementId,
    Level,
    StorageType,
    SubTransaction,
    Transform,
    Wall,
    WallUtils,
    XYZ,
)
from pyrevit import script

from BG import wall_limits

logger = script.get_logger()

TOL = wall_limits.TOL_LEVEL_MATCH

# A height to park an unconnected wall at while its base is moved, and
# how far below its top level to park a base that would otherwise end
# up above it.  Both only ever exist between two regenerations.
SAFE_HEIGHT = 1.0
SAFE_MARGIN = 1.0

# The Base Constraint level's name goes here.
BG_LEVEL_PARAM = "BG_LEVEL"


def bip(name):
    """Look a BuiltInParameter up by name, or None when it is absent.

    The enum is not stable across Revit releases --
    WALL_BOTTOM_IS_ATTACHED, for instance, has no WALL_BASE_ prefixed
    twin -- and a missing member would otherwise kill a script at import
    time.  Everything that reads or skips a parameter tolerates None.
    """
    return getattr(BuiltInParameter, name, None)


TOP_IS_ATTACHED  = bip("WALL_TOP_IS_ATTACHED")
BASE_IS_ATTACHED = bip("WALL_BOTTOM_IS_ATTACHED")


def bip_int(name):
    """Integer value of a BuiltInParameter by name, or None if absent."""
    member = bip(name)
    if member is None:
        return None
    try:
        return int(member)
    except Exception:
        return None


# Parameters that describe the vertical extent.  They are driven by the
# plan, so they must never be copied from a source wall onto a new one.
# The Mark goes too: a split produces distinct elements, and cloning it
# would only raise a duplicate-mark warning for every band.
SKIP_BIP_NAMES = (
    "WALL_BASE_CONSTRAINT",
    "WALL_BASE_OFFSET",
    "WALL_HEIGHT_TYPE",
    "WALL_TOP_OFFSET",
    "WALL_USER_HEIGHT_PARAM",
    "WALL_BOTTOM_IS_ATTACHED",
    "WALL_TOP_IS_ATTACHED",
    "WALL_KEY_REF_PARAM",
    "ELEM_FAMILY_PARAM",
    "ELEM_TYPE_PARAM",
    "ELEM_FAMILY_AND_TYPE_PARAM",
    "ALL_MODEL_MARK",
)

SKIP_BIPS = set(
    v for v in (bip_int(n) for n in SKIP_BIP_NAMES) if v is not None
)


# ===========================================================================
# SMALL REVIT HELPERS
# ===========================================================================

def eid(value):
    """The integer behind an ElementId, or None.

    Identity is compared through this rather than with ``==`` because
    ElementId equality does not reliably cross the Python boundary.
    Revit 2024 renamed IntegerValue to Value, so both are tried.
    """
    if value is None:
        return None
    for attr in ("Value", "IntegerValue"):
        got = getattr(value, attr, None)
        if got is not None:
            return int(got)
    return None


def is_valid(element_id):
    """True when *element_id* points at a real element."""
    val = eid(element_id)
    return val is not None and val > 0


def pval(elem, which, default=None):
    """Read a built-in parameter, tolerating absent or unset parameters."""
    if which is None:
        return default
    p = elem.get_Parameter(which)
    if p is None or not p.HasValue:
        return default
    st = p.StorageType
    if st == StorageType.Double:
        return p.AsDouble()
    if st == StorageType.Integer:
        return p.AsInteger()
    if st == StorageType.ElementId:
        return p.AsElementId()
    if st == StorageType.String:
        return p.AsString()
    return default


def set_param(elem, which, value):
    """Write a built-in parameter when it exists and is writable."""
    if which is None:
        return False
    p = elem.get_Parameter(which)
    if p is None or p.IsReadOnly:
        return False
    p.Set(value)
    return True


def name_of(elem):
    """The Name of an element, whichever route IronPython allows.

    Element.Name is ambiguous under IronPython and raises on element
    types, so fall back to the static property and then to the type-name
    parameter.
    """
    if elem is None:
        return "<null>"
    try:
        return elem.Name
    except Exception:
        pass
    try:
        return Element.Name.GetValue(elem)
    except Exception:
        pass
    for candidate in ("SYMBOL_NAME_PARAM", "ALL_MODEL_TYPE_NAME"):
        val = pval(elem, bip(candidate))
        if val:
            return val
    return "<unknown>"


def find_parameter(elem, name):
    """Return *elem*'s parameter called *name*, ignoring case, or None.

    LookupParameter is case-sensitive, which is a poor match for
    parameter names written one way in a shared parameter file and
    another in the model -- BG_LEVEL against BG_Level, say.
    """
    try:
        p = elem.LookupParameter(name)
        if p is not None:
            return p
    except Exception:
        pass

    wanted = (name or "").strip().lower()
    try:
        for p in elem.Parameters:
            try:
                if p.Definition.Name.strip().lower() == wanted:
                    return p
            except Exception:
                continue
    except Exception:
        pass
    return None


def feet_to_text(z):
    """A length in feet as feet-inches-sixteenths, e.g. 10'-4 1/2"."""
    sign = "-" if z < 0 else ""
    z = abs(z)
    total_16ths = int(round(z * 12.0 * 16.0))
    feet, rem = divmod(total_16ths, 12 * 16)
    inches, sixteenths = divmod(rem, 16)

    frac = ""
    if sixteenths:
        num, den = sixteenths, 16
        while num % 2 == 0:
            num //= 2
            den //= 2
        frac = " {0}/{1}".format(num, den)

    return "{0}{1}'-{2}{3}\"".format(sign, feet, inches, frac)


# ===========================================================================
# READING A WALL
# ===========================================================================

def elevation_of(doc, level_id):
    """A level's elevation, or None when the id is not a level."""
    if not is_valid(level_id):
        return None
    level = doc.GetElement(level_id)
    return level.Elevation if isinstance(level, Level) else None


def wall_extent(doc, wall):
    """The wall's absolute (base_z, top_z, current) from its parameters.

    Geometry is deliberately not consulted: the parameters are what
    these tools rewrite, so working from them is what keeps the wall
    still.  *current* is (base level id, base offset, top level id, top
    offset), with the top id None for an unconnected wall.
    """
    base_lvl_id = pval(wall, BuiltInParameter.WALL_BASE_CONSTRAINT)
    if base_lvl_id is None:
        base_lvl_id = wall.LevelId
    base_lvl = doc.GetElement(base_lvl_id)
    if base_lvl is None:
        raise ValueError("base constraint is not a level")

    base_off = pval(wall, BuiltInParameter.WALL_BASE_OFFSET, 0.0)
    base_z = base_lvl.Elevation + base_off

    top_lvl_id = pval(wall, BuiltInParameter.WALL_HEIGHT_TYPE)
    top_lvl = doc.GetElement(top_lvl_id) if is_valid(top_lvl_id) else None

    if isinstance(top_lvl, Level):
        top_off = pval(wall, BuiltInParameter.WALL_TOP_OFFSET, 0.0)
        top_z = top_lvl.Elevation + top_off
        cur_top_id = top_lvl.Id
    else:
        height = pval(wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM, 0.0)
        top_z = base_z + height
        top_off = 0.0
        cur_top_id = None

    return base_z, top_z, (base_lvl.Id, base_off, cur_top_id, top_off)


def blocking_reason(doc, wall, wall_kinds_barred):
    """Why this wall must be left alone entirely, or None to process it.

    *wall_kinds_barred* is {WallKind: reason}, so each tool can bar the
    kinds it cannot handle without this module having an opinion.
    """
    try:
        kind = wall.WallType.Kind
    except Exception:
        return "wall type could not be read"

    if kind in wall_kinds_barred:
        return wall_kinds_barred[kind]

    # An attached wall's parameters describe its UNATTACHED extent while
    # its geometry follows the roof or floor it is attached to, so the
    # numbers these tools reason about are not the wall you see.
    # Splitting one is worse still: the API cannot re-create an
    # attachment, so the new band would come out loose.
    attached = []
    if pval(wall, TOP_IS_ATTACHED, 0):
        attached.append("top")
    if pval(wall, BASE_IS_ATTACHED, 0):
        attached.append("base")
    if attached:
        return "{0} attached to another element".format(
            " and ".join(attached))

    if is_valid(wall.GroupId):
        return "inside a Model Group"

    if wall.Location is None or not hasattr(wall.Location, "Curve"):
        return "no location curve"

    return None


# ===========================================================================
# WRITING A WALL
# ===========================================================================

def bind_extent(doc, wall, band):
    """Move a wall onto *band* without ever inverting it on the way.

    "The top of the Wall is lower than the base" is not a complaint
    about where the wall ends up -- a plan always has the top above the
    base -- but about where it passes THROUGH.  Two moments can invert
    a wall mid-flight, and each is closed here rather than retried:

    1. Moving the BASE while the top is still bound to the old level.
       Raise a wall two storeys and its base overtakes a top that has
       not moved yet.  So the top is UNBOUND first, and given a height
       of its own; an unconnected wall's top follows its base, and
       cannot be overtaken by it.

    2. Binding the TOP to its new level while the OLD offset is still
       on the wall.  Revit reports the offset as read-only until it has
       regenerated, so there is a regeneration between naming the level
       and writing the offset whether we want one or not -- and that
       regeneration does NOT put the top on the level.  It puts it at
       the level plus whatever offset the wall is still carrying, which
       is the old wall's, not this band's.

       A wall topping out 10'-8" below LEVEL 03, rebound to LEVEL 02,
       tries to top out 10'-8" below LEVEL 02 -- under its own base at
       LEVEL 01.  Revit queues that as a failure it will not let anyone
       ignore and posts it at COMMIT, long after this tool has read the
       finished constraints back and found every one of them correct.

       So the offset is tried FIRST, before any regeneration: when
       Revit takes it, level and offset land together and there is no
       intermediate state to guard at all.  When it will not, the BASE
       is parked below wherever that regeneration is going to put the
       top, and restored after.

    Neither parked value survives the call; both exist only between
    regenerations, and both belong inside the caller's sub-transaction.
    """
    base_lvl_z = elevation_of(doc, band["base_level_id"])
    top_lvl_z  = elevation_of(doc, band["top_level_id"])
    if base_lvl_z is None:
        raise ValueError("the band's base level could not be read")

    # Read before anything moves.  Once the top is unbound this offset is
    # no longer on show, and it is one of the answers to where Revit will
    # put the top when it rebinds.
    prior_top_off = pval(wall, BuiltInParameter.WALL_TOP_OFFSET)

    # 1. Let the top go, so the base can move freely under it.
    set_param(wall, BuiltInParameter.WALL_HEIGHT_TYPE,
              ElementId.InvalidElementId)
    set_param(wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM,
              max(band["height"], SAFE_HEIGHT))
    doc.Regenerate()

    set_param(wall, BuiltInParameter.WALL_BASE_CONSTRAINT,
              band["base_level_id"])
    set_param(wall, BuiltInParameter.WALL_BASE_OFFSET, band["base_offset"])
    doc.Regenerate()

    if top_lvl_z is None:
        # No top level to bind to.  The unconnected height above IS the
        # answer, and it is already the band's own.
        set_param(wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM,
                  band["height"])
        doc.Regenerate()
        return

    # 2. Name the new level and try the offset in the same breath.  When
    # Revit takes both, nothing is evaluated in between and there is
    # nothing to guard against.
    set_param(wall, BuiltInParameter.WALL_HEIGHT_TYPE, band["top_level_id"])

    p = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
    if p is not None and not p.IsReadOnly:
        p.Set(band["top_offset"])
        doc.Regenerate()
        return

    # It would not take the offset yet, so a regeneration is coming and
    # the top will land somewhere of Revit's choosing.  There are three
    # readings of where, and no way from outside to tell which one Revit
    # means: the offset it reports now, the offset the wall arrived
    # carrying, and none at all -- the top sitting on the level itself.
    # The lowest of the three is the only one safe to plan for, and
    # parking deeper than necessary costs nothing, because the base comes
    # straight back up two regenerations later.
    stale = None
    try:
        if p is not None and p.HasValue:
            stale = p.AsDouble()
    except Exception:
        stale = None

    worst   = min(x for x in (stale, prior_top_off, 0.0) if x is not None)
    landing = top_lvl_z + worst
    base_z  = base_lvl_z + band["base_offset"]

    parked = None
    if landing <= base_z + TOL:
        parked = band["base_offset"]
        set_param(wall, BuiltInParameter.WALL_BASE_OFFSET,
                  landing - base_lvl_z - SAFE_MARGIN)

    doc.Regenerate()

    p = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
    if p is None or p.IsReadOnly:
        raise ValueError("Top Offset is not writable on this wall")
    p.Set(band["top_offset"])
    doc.Regenerate()

    if parked is not None:
        set_param(wall, BuiltInParameter.WALL_BASE_OFFSET, parked)
        doc.Regenerate()


def apply_constraints(doc, wall, band):
    """Bind *wall* to *band*, inside a sub-transaction of its own.

    One route, not two.  Trying base-then-top and then top-then-base was
    a way of hoping one order happened to avoid inverting the wall;
    bind_extent avoids it by construction, so there is nothing left to
    hope for.  The sub-transaction is what leaves nothing behind when
    Revit refuses a wall anyway.
    """
    st = SubTransaction(doc)
    st.Start()
    try:
        bind_extent(doc, wall, band)
        doc.Regenerate()
        st.Commit()
    except Exception as ex:
        try:
            st.RollBack()
        except Exception:
            pass
        raise ValueError("Revit rejected the new constraints: {0}".format(ex))


def verify(doc, wall, band):
    """Confirm a wall really ended up where the plan said, or say why not.

    A parameter Set that Revit quietly refuses leaves an invalid wall
    behind and surfaces as a blocking error at commit time, long after
    the tool could explain it.  Reading the result back turns that into
    a reported row instead.
    """
    got_base, got_top, _current = wall_extent(doc, wall)

    if abs(got_base - band["base_z"]) > TOL:
        return "base landed at {0}, expected {1}".format(
            feet_to_text(got_base), feet_to_text(band["base_z"]))
    if abs(got_top - band["top_z"]) > TOL:
        return "top landed at {0}, expected {1}".format(
            feet_to_text(got_top), feet_to_text(band["top_z"]))
    if got_top - got_base <= TOL:
        return "wall has no height after the change"
    return None


def copy_instance_params(src, dst):
    """Copy every writable instance parameter except the vertical ones."""
    for sp in src.Parameters:
        try:
            if not sp.HasValue:
                continue
            definition = sp.Definition
            if definition is None:
                continue
            # Shared and project parameters have no BuiltInParameter, and
            # asking for one can throw rather than return INVALID.
            try:
                member = definition.BuiltInParameter
                member_int = int(member)
            except Exception:
                member, member_int = None, None

            if member_int is not None and member_int in SKIP_BIPS:
                continue

            dp = None
            if member is not None:
                dp = dst.get_Parameter(member)
            if dp is None:
                dp = dst.LookupParameter(definition.Name)
            if dp is None or dp.IsReadOnly:
                continue

            st = sp.StorageType
            if st != dp.StorageType:
                continue
            if st == StorageType.Double:
                dp.Set(sp.AsDouble())
            elif st == StorageType.Integer:
                dp.Set(sp.AsInteger())
            elif st == StorageType.ElementId:
                dp.Set(sp.AsElementId())
            elif st == StorageType.String:
                val = sp.AsString()
                if val is not None:
                    dp.Set(val)
        except Exception:
            # A single stubborn parameter must not abort the whole wall.
            continue


def create_band_wall(doc, src, band):
    """Build one new wall occupying *band*, matching *src* in plan."""
    src_curve = src.Location.Curve
    level = doc.GetElement(band["base_level_id"])

    dz = level.Elevation - src_curve.GetEndPoint(0).Z
    curve = src_curve.CreateTransformed(
        Transform.CreateTranslation(XYZ(0, 0, dz)))

    structural = bool(pval(
        src, BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT, 0))

    new_wall = Wall.Create(
        doc, curve, src.WallType.Id, band["base_level_id"],
        band["height"], band["base_offset"], src.Flipped, structural)
    doc.Regenerate()

    # Match the Location Line first, then re-assert the curve: changing
    # the reference plane afterwards would slide the wall sideways.
    loc_line = pval(src, BuiltInParameter.WALL_KEY_REF_PARAM)
    if loc_line is not None:
        set_param(new_wall, BuiltInParameter.WALL_KEY_REF_PARAM, loc_line)
        doc.Regenerate()
        try:
            new_wall.Location.Curve = curve
            doc.Regenerate()
        except Exception as ex:
            logger.debug("Could not re-assert location curve: {0}".format(ex))

    if src.Orientation.DotProduct(new_wall.Orientation) < 0:
        new_wall.Flip()
        doc.Regenerate()

    bind_extent(doc, new_wall, band)

    copy_instance_params(src, new_wall)

    # Wall joins are a per-end setting and are not carried by Wall.Create.
    for end in (0, 1):
        try:
            if not WallUtils.IsWallJoinAllowedAtEnd(src, end):
                WallUtils.DisallowWallJoinAtEnd(new_wall, end)
        except Exception:
            pass

    doc.Regenerate()
    return new_wall


def apply_bg_level(doc, wall, band):
    """Write the name of *wall*'s Base Constraint level into BG_LEVEL.

    The level comes from the BAND the wall was bound to rather than read
    back off the wall, so it says the same thing the constraint says
    even if Revit later re-hosts it.

    Returns False when the parameter is missing, read-only or not text.
    The wall's constraints are correct either way, so a caller reports
    it rather than treating the wall as failed.
    """
    level = doc.GetElement(band["base_level_id"])
    if level is None:
        return False

    p = find_parameter(wall, BG_LEVEL_PARAM)
    if p is None or p.IsReadOnly:
        return False
    try:
        return bool(p.Set(name_of(level)))
    except Exception:
        return False
