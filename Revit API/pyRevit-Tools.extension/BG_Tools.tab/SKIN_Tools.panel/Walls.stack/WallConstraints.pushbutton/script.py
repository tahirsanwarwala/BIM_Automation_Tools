# -*- coding: utf-8 -*-
"""Audit and repair the vertical constraints of selected walls.

House rule enforced here (the same one SplitWalls applies to the walls
it creates):

  * Base Constraint  = the level at or immediately BELOW the wall base,
                       with a positive Base Offset.
  * Top Constraint   = the level at or immediately ABOVE the wall top,
                       with a negative Top Offset.  Never an unconnected
                       height.
  * No wall crosses a level.  One that does is cut into bands, one per
    storey, each bound by the rule above.
  * Ends that are not on a level are rounded to the nearest whole inch.
    Ends that ARE on a level stay exactly where they are.

Apart from that inch rounding, walls do not move: every offset is
computed so the wall keeps the absolute elevations it already had.

Each wall's Base Constraint level is written into its BG_LEVEL
parameter afterwards, the same as Multi Wall Creation does for the
walls it builds.

Walls whose top or base is attached to another element are left alone:
their parameters describe an extent their geometry does not follow, and
the API cannot re-create an attachment on a wall this tool would make.

The arithmetic lives in BG.wall_constraints and is unit-tested; this
script only reads Revit, applies the plan, and reports.
"""

__title__  = "Wall\nLimits"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Select walls (or pre-select them, then run).\n"
    "Each wall's Base/Top Constraint and offsets are rewritten so the\n"
    "base sits on the level at or below it and the top hangs from the\n"
    "level at or above it, without moving the wall.\n"
    "Walls that cross a level are split into one wall per storey; the\n"
    "original wall is kept as the lowest band.\n"
    "Ends that are not on a level are rounded to the nearest inch.\n"
    "The Base Constraint level is written into BG_LEVEL.\n"
    "Curtain walls, stacked walls, walls attached to a roof or floor,\n"
    "grouped walls and linked walls are reported but never touched."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    Element,
    ElementId,
    FilteredElementCollector,
    Level,
    StorageType,
    SubTransaction,
    Transaction,
    Transform,
    Wall,
    WallKind,
    WallUtils,
    XYZ,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from BG import wall_constraints as wc

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TOL = wc.TOL

# The Base Constraint level's name is written here, as Multi Wall
# Creation writes it for the walls it builds.
BG_LEVEL_PARAM = "BG_LEVEL"

# A height to park an unconnected wall at while its base is moved, and
# how far below its top level to park a base that would otherwise end
# up above it.  Both only ever exist between two regenerations.
SAFE_HEIGHT = 1.0
SAFE_MARGIN = 1.0


def bip(name):
    """Look a BuiltInParameter up by name, or None when it is absent.

    The enum is not stable across Revit releases -- WALL_BOTTOM_IS_ATTACHED,
    for instance, has no WALL_BASE_ prefixed twin -- and a missing member
    would otherwise kill the script at import time.  Everything that reads
    or skips a parameter tolerates None.
    """
    return getattr(BuiltInParameter, name, None)


TOP_IS_ATTACHED = bip("WALL_TOP_IS_ATTACHED")
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
# plan, so they must never be copied from the source wall onto a band.
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


# ===============================================================================
# SMALL REVIT HELPERS
# ===============================================================================

def _eid(value):
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


def _is_valid(element_id):
    """True when *element_id* points at a real element."""
    val = _eid(element_id)
    return val is not None and val > 0


def _pval(elem, which, default=None):
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


def _set(elem, which, value):
    """Write a built-in parameter when it exists and is writable."""
    if which is None:
        return False
    p = elem.get_Parameter(which)
    if p is None or p.IsReadOnly:
        return False
    p.Set(value)
    return True


def _feet_to_text(z):
    """Format a length in feet as feet-inches-sixteenths, e.g. 10'-4 1/2\"."""
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


def _name(elem):
    """The Name of an element, whichever route IronPython allows.

    Element.Name is ambiguous under IronPython and raises on element
    types, so fall back to the static property and then to the type-name
    parameter -- the same problem SplitWalls works around.
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
    for name in ("SYMBOL_NAME_PARAM", "ALL_MODEL_TYPE_NAME"):
        val = _pval(elem, bip(name))
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


def apply_bg_level(wall, band):
    """Write the name of *wall*'s Base Constraint level into BG_LEVEL.

    The level comes from the BAND the wall was bound to rather than
    read back off the wall, so it says the same thing the constraint
    says even if Revit later re-hosts it.

    Returns False when the parameter is missing, read-only or not text.
    The wall's constraints are correct either way, so the caller reports
    it rather than treating the wall as failed.
    """
    level = doc.GetElement(band["base_level_id"])
    if level is None:
        return False

    p = find_parameter(wall, BG_LEVEL_PARAM)
    if p is None or p.IsReadOnly:
        return False
    try:
        return bool(p.Set(_name(level)))
    except Exception:
        return False


def _level_name(level_id):
    if not _is_valid(level_id):
        return "Unconnected"
    return _name(doc.GetElement(level_id))


def collect_levels():
    """Every Level in the host model as (ElementId, elevation) tuples."""
    levels = (FilteredElementCollector(doc)
              .OfClass(Level)
              .WhereElementIsNotElementType()
              .ToElements())
    return [(lvl.Id, lvl.Elevation) for lvl in levels]


# ===============================================================================
# SELECTION
# ===============================================================================

class WallFilter(ISelectionFilter):
    """Any wall in the host model.  Types we cannot process are allowed
    through here on purpose so they can be listed in the report rather
    than silently vanishing from the selection.
    """

    def AllowElement(self, elem):
        return isinstance(elem, Wall)

    def AllowReference(self, ref, point):
        return False


def get_walls():
    """Walls from the current selection, or picked interactively."""
    selected = [doc.GetElement(eid) for eid in uidoc.Selection.GetElementIds()]
    walls = [e for e in selected if isinstance(e, Wall)]
    if walls:
        return walls

    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, WallFilter(),
            "Select the walls to check, then click Finish")
    except Exception:
        return []

    return [doc.GetElement(r.ElementId) for r in refs
            if isinstance(doc.GetElement(r.ElementId), Wall)]


# ===============================================================================
# READING A WALL
# ===============================================================================

def is_profile_edited(wall):
    """True when the wall's elevation profile has been sketched."""
    try:
        return _is_valid(wall.SketchId)
    except Exception:
        # Older API surface: no SketchId, so assume a plain profile.
        return False


def blocking_reason(wall):
    """Why this wall must be left alone entirely, or None to process it."""
    try:
        kind = wall.WallType.Kind
    except Exception:
        return "wall type could not be read"

    if kind == WallKind.Curtain:
        return "curtain wall (not supported in this version)"
    if kind == WallKind.Stacked:
        return "stacked wall (sub-walls carry their own constraints)"
    if kind == WallKind.Unknown:
        return "unsupported wall kind"

    # An attached wall's parameters describe its UNATTACHED extent while
    # its geometry follows the roof or floor it is attached to, so the
    # numbers this tool reasons about are not the wall you see.  Splitting
    # one is worse still: the API cannot re-create an attachment, so the
    # new band would come out loose.  Left alone entirely.
    attached = []
    if _pval(wall, TOP_IS_ATTACHED, 0):
        attached.append("top")
    if _pval(wall, BASE_IS_ATTACHED, 0):
        attached.append("base")
    if attached:
        return "{0} attached to another element".format(" and ".join(attached))

    if _is_valid(wall.GroupId):
        return "inside a Model Group"

    if wall.Location is None or not hasattr(wall.Location, "Curve"):
        return "no location curve"

    return None


def wall_extent(wall):
    """The wall's absolute (base_z, top_z) as its parameters describe it.

    Geometry is deliberately not consulted: the parameters are what this
    tool rewrites, so working from them is what keeps the wall still.
    """
    base_lvl_id = _pval(wall, BuiltInParameter.WALL_BASE_CONSTRAINT)
    if base_lvl_id is None:
        base_lvl_id = wall.LevelId
    base_lvl = doc.GetElement(base_lvl_id)
    if base_lvl is None:
        raise ValueError("base constraint is not a level")

    base_off = _pval(wall, BuiltInParameter.WALL_BASE_OFFSET, 0.0)
    base_z = base_lvl.Elevation + base_off

    top_lvl_id = _pval(wall, BuiltInParameter.WALL_HEIGHT_TYPE)
    top_lvl = doc.GetElement(top_lvl_id) if _is_valid(top_lvl_id) else None

    if isinstance(top_lvl, Level):
        top_off = _pval(wall, BuiltInParameter.WALL_TOP_OFFSET, 0.0)
        top_z = top_lvl.Elevation + top_off
        cur_top_id = top_lvl.Id
    else:
        height = _pval(wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM, 0.0)
        top_z = base_z + height
        top_off = 0.0
        cur_top_id = None

    current = (base_lvl.Id, base_off, cur_top_id, top_off)
    return base_z, top_z, current


def inserts_outside(wall, band_top_z):
    """Count hosted inserts that are not wholly below *band_top_z*.

    The original wall is kept as the lowest band, so anything reaching
    above that band would be destroyed by the split.  Doors, windows,
    openings and embedded walls all count.
    """
    try:
        ids = wall.FindInserts(True, True, True, True)
    except Exception:
        return 0

    count = 0
    for eid in ids:
        elem = doc.GetElement(eid)
        if elem is None:
            continue
        try:
            bb = elem.get_BoundingBox(None)
        except Exception:
            bb = None
        if bb is None:
            # Cannot prove it is safe, so treat it as in the way.
            count += 1
            continue
        if bb.Max.Z > band_top_z + TOL:
            count += 1
    return count


# ===============================================================================
# WRITING A WALL
# ===============================================================================

def _elevation_of(level_id):
    """A level's elevation, or None when the id is not a level."""
    if not _is_valid(level_id):
        return None
    level = doc.GetElement(level_id)
    return level.Elevation if isinstance(level, Level) else None


def bind_extent(wall, band):
    """Move a wall onto *band* without ever inverting it on the way.

    "The top of the Wall is lower than the base" is not a complaint
    about where the wall ends up -- the plan always has the top above
    the base -- but about where it passes through.  Two moments can
    invert a wall mid-flight, and each is closed here rather than
    retried:

    1. Moving the BASE while the top is still bound to the old level.
       Raise a wall two storeys and its base overtakes a top that has
       not moved yet.  So the top is UNBOUND first, and given a height
       of its own; an unconnected wall's top follows its base, and
       cannot be overtaken by it.

    2. Binding the TOP to its level before the offset lands.  Binding
       snaps the top to the level itself, and Revit reports the offset
       as read-only until it regenerates -- so there is a regeneration
       in between whether we want one or not.  Where that snap would
       put the top under the base (a band hanging above the topmost
       level, with a positive offset) the BASE is parked below the
       level for those two steps and restored after.

    Neither parked value survives the function; both exist only between
    regenerations, and both are inside the caller's sub-transaction.
    """
    base_lvl_z = _elevation_of(band["base_level_id"])
    top_lvl_z  = _elevation_of(band["top_level_id"])
    if base_lvl_z is None:
        raise ValueError("the band's base level could not be read")

    # 1. Let the top go, so the base can move freely under it.
    _set(wall, BuiltInParameter.WALL_HEIGHT_TYPE, ElementId.InvalidElementId)
    _set(wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM,
         max(band["height"], SAFE_HEIGHT))
    doc.Regenerate()

    _set(wall, BuiltInParameter.WALL_BASE_CONSTRAINT, band["base_level_id"])
    _set(wall, BuiltInParameter.WALL_BASE_OFFSET, band["base_offset"])
    doc.Regenerate()

    if top_lvl_z is None:
        # No top level to bind to.  The unconnected height above IS the
        # answer, and it is already the band's own.
        _set(wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM, band["height"])
        doc.Regenerate()
        return

    # 2. Park the base if binding the top would otherwise dip under it.
    parked = None
    if top_lvl_z <= base_lvl_z + band["base_offset"] + TOL:
        parked = band["base_offset"]
        _set(wall, BuiltInParameter.WALL_BASE_OFFSET,
             top_lvl_z - base_lvl_z - SAFE_MARGIN)
        doc.Regenerate()

    _set(wall, BuiltInParameter.WALL_HEIGHT_TYPE, band["top_level_id"])
    doc.Regenerate()

    p = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
    if p is None or p.IsReadOnly:
        raise ValueError("Top Offset is not writable on this wall")
    p.Set(band["top_offset"])
    doc.Regenerate()

    if parked is not None:
        _set(wall, BuiltInParameter.WALL_BASE_OFFSET, parked)
        doc.Regenerate()


def apply_constraints(wall, band):
    """Set one wall's four constraint parameters.

    One route, not two.  Trying base-then-top and then top-then-base was
    a way of hoping one order happened to avoid inverting the wall;
    bind_extent avoids it by construction, so there is nothing left to
    hope for.  The sub-transaction stays, so a wall Revit still refuses
    leaves nothing behind.
    """
    st = SubTransaction(doc)
    st.Start()
    try:
        bind_extent(wall, band)
        doc.Regenerate()
        st.Commit()
    except Exception as ex:
        try:
            st.RollBack()
        except Exception:
            pass
        raise ValueError("Revit rejected the new constraints: {0}".format(ex))


def verify(wall, band):
    """Confirm a wall really ended up where the plan said.

    A parameter Set that Revit quietly refuses leaves an invalid wall
    behind and surfaces as a blocking error at commit time, long after
    the tool could explain it.  Reading the result back turns that into
    a reported row instead.
    """
    got_base, got_top, current = wall_extent(wall)

    if abs(got_base - band["base_z"]) > TOL:
        return "base landed at {0}, expected {1}".format(
            _feet_to_text(got_base), _feet_to_text(band["base_z"]))
    if abs(got_top - band["top_z"]) > TOL:
        return "top landed at {0}, expected {1}".format(
            _feet_to_text(got_top), _feet_to_text(band["top_z"]))
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
            # A single stubborn parameter must not abort the whole band.
            continue


def create_band_wall(src, band):
    """Build one new wall occupying *band*, matching *src* in plan."""
    src_curve = src.Location.Curve
    level = doc.GetElement(band["base_level_id"])

    dz = level.Elevation - src_curve.GetEndPoint(0).Z
    curve = src_curve.CreateTransformed(
        Transform.CreateTranslation(XYZ(0, 0, dz)))

    structural = bool(_pval(
        src, BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT, 0))

    new_wall = Wall.Create(
        doc, curve, src.WallType.Id, band["base_level_id"],
        band["height"], band["base_offset"], src.Flipped, structural)
    doc.Regenerate()

    # Match the Location Line first, then re-assert the curve: changing
    # the reference plane afterwards would slide the wall sideways.
    loc_line = _pval(src, BuiltInParameter.WALL_KEY_REF_PARAM)
    if loc_line is not None:
        _set(new_wall, BuiltInParameter.WALL_KEY_REF_PARAM, loc_line)
        doc.Regenerate()
        try:
            new_wall.Location.Curve = curve
            doc.Regenerate()
        except Exception as ex:
            logger.debug("Could not re-assert location curve: {0}".format(ex))

    if src.Orientation.DotProduct(new_wall.Orientation) < 0:
        new_wall.Flip()
        doc.Regenerate()

    bind_extent(new_wall, band)

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


# ===============================================================================
# PROCESS ONE WALL
# ===============================================================================

class Result(object):
    """One row of the report."""

    __slots__ = ("wall_id", "type_name", "before", "after", "status", "notes")

    def __init__(self, wall_id, type_name):
        self.wall_id   = wall_id
        self.type_name = type_name
        self.before    = ""
        self.after     = ""
        self.status    = ""
        self.notes     = []


def describe(base_lvl_id, base_off, top_lvl_id, top_off):
    """Human-readable 'Base @ offset -> Top @ offset'."""
    return "{0} @ {1} | {2} @ {3}".format(
        _level_name(base_lvl_id), _feet_to_text(base_off),
        _level_name(top_lvl_id), _feet_to_text(top_off))


def process_wall(wall, levels):
    """Fix one wall.  Returns a Result; never raises."""
    try:
        type_name = _name(wall.WallType)
    except Exception:
        type_name = "?"

    res = Result(wall.Id, type_name)

    reason = blocking_reason(wall)
    if reason:
        res.status = "Skipped"
        res.notes.append(reason)
        return res

    try:
        base_z, top_z, current = wall_extent(wall)
    except Exception as ex:
        res.status = "Skipped"
        res.notes.append(str(ex))
        return res

    res.before = describe(*current)

    profile_edited = is_profile_edited(wall)

    # A sketched profile is measured from the constraints it was drawn
    # against, so nudging those ends would drag the sketch with them.
    allow_round = not profile_edited
    allow_split = not profile_edited

    try:
        plan = wc.plan_wall(base_z, top_z, levels,
                            allow_split=allow_split, allow_round=allow_round)
    except ValueError as ex:
        res.status = "Skipped"
        res.notes.append(str(ex))
        return res

    if profile_edited:
        res.notes.append("profile edited: constraints only, no rounding, "
                         "never split")

    # The original wall keeps the lowest band, so nothing hosted in it may
    # reach above that band -- Revit would delete such inserts outright.
    if plan["needs_split"] and len(plan["bands"]) > 1:
        stranded = inserts_outside(wall, plan["bands"][0]["top_z"])
        if stranded:
            plan = wc.plan_wall(base_z, top_z, levels, allow_split=False)
            res.notes.append(
                "crosses {0} level(s) but {1} hosted element(s) sit above "
                "the first storey - not split".format(
                    len(plan["interior"]), stranded))

    bands = plan["bands"]
    changed = wc.constraints_changed(
        (_eid(current[0]), current[1], _eid(current[2]), current[3]),
        {"base_level_id": _eid(bands[0]["base_level_id"]),
         "base_offset":   bands[0]["base_offset"],
         "top_level_id":  _eid(bands[0]["top_level_id"]),
         "top_offset":    bands[0]["top_offset"]})

    if not changed and len(bands) == 1:
        res.status = "Already correct"
        res.after = res.before
        # BG_LEVEL is written even here.  The constraints being right
        # already says nothing about whether the parameter was ever
        # filled, and a wall this tool has looked at should come away
        # with both.
        if not apply_bg_level(wall, bands[0]):
            res.notes.append(
                "{0} could not be written - parameter missing, "
                "read-only, or not a text parameter".format(BG_LEVEL_PARAM))
        if plan["needs_split"]:
            res.status = "Needs split"
        return res

    try:
        apply_constraints(wall, bands[0])
    except Exception as ex:
        res.status = "Failed"
        res.notes.append(str(ex))
        return res

    res.after = describe(bands[0]["base_level_id"], bands[0]["base_offset"],
                         bands[0]["top_level_id"], bands[0]["top_offset"])

    problem = verify(wall, bands[0])
    if problem:
        res.status = "Failed"
        res.notes.append(problem)
        return res

    unwritten = 0
    if not apply_bg_level(wall, bands[0]):
        unwritten += 1

    new_ids = []
    for band in bands[1:]:
        try:
            new_wall = create_band_wall(wall, band)
            problem = verify(new_wall, band)
            if problem:
                # Better no wall than an invalid one that blocks the commit.
                doc.Delete(new_wall.Id)
                doc.Regenerate()
                raise ValueError(problem)
            if not apply_bg_level(new_wall, band):
                unwritten += 1
            new_ids.append(new_wall.Id)
        except Exception as ex:
            res.status = "Partly failed"
            res.notes.append("band {0} not created: {1}".format(
                describe(band["base_level_id"], band["base_offset"],
                         band["top_level_id"], band["top_offset"]), ex))

    if res.status != "Partly failed":
        res.status = "Split into {0}".format(len(bands)) if new_ids else "Fixed"

    if new_ids:
        res.notes.append("new walls: {0}".format(
            ", ".join(str(_eid(i)) for i in new_ids)))

    if unwritten:
        res.notes.append(
            "{0} could not be written on {1} wall(s) - parameter "
            "missing, read-only, or not a text parameter".format(
                BG_LEVEL_PARAM, unwritten))

    if plan["rounded"]:
        res.notes.append("rounded to the nearest inch")

    if plan["needs_split"] and len(bands) == 1:
        # Constraints were still corrected; the crossing just could not be
        # resolved automatically, so say both things.
        res.status = "Fixed - still needs split"

    return res


# ===============================================================================
# REPORT
# ===============================================================================

# Statuses worth opening the output window for: a wall that could not be
# fixed, or one fixed only as far as it could go.  Everything else -
# fixed, split, already correct, skipped - is a run that did its job and
# has nothing to say.
PROBLEM_STATUSES = ("Needs split", "Failed", "Partly failed",
                    "Fixed - still needs split")


def report(results):
    """Print the walls that need a human, or nothing at all.

    Printing is what opens the output window, so staying quiet on a clean
    run is the whole point: anything printed here is something to act on.
    """
    problems = [r for r in results if r.status in PROBLEM_STATUSES]
    if not problems:
        return

    counts = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    output.print_md("## Fix Wall Constraints - {0} of {1} wall(s) need "
                    "attention".format(len(problems), len(results)))
    output.print_md(" | ".join(
        "**{0}**: {1}".format(k, v) for k, v in sorted(counts.items())))

    rows = []
    for r in problems:
        rows.append([
            output.linkify(r.wall_id),
            r.type_name,
            r.before,
            r.after,
            r.status,
            "; ".join(r.notes),
        ])

    output.print_table(
        table_data=rows,
        columns=["Wall", "Type", "Before (base | top)",
                 "After (base | top)", "Status", "Notes"],
    )


# ===============================================================================
# MAIN
# ===============================================================================

def main():
    walls = get_walls()
    if not walls:
        return

    levels = collect_levels()
    if not levels:
        forms.alert("This model has no levels, so wall constraints cannot "
                    "be bound to anything.",
                    title="Fix Wall Constraints")
        return

    results = []
    with Transaction(doc, "Fix Wall Constraints") as t:
        t.Start()
        try:
            for wall in walls:
                results.append(process_wall(wall, levels))
            t.Commit()
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            output.print_md("**Fix Wall Constraints - transaction failed**")
            output.print_code(traceback.format_exc())
            forms.alert("Transaction failed:\n{0}".format(ex),
                        title="Fix Wall Constraints - Error")
            return

    report(results)


try:
    main()
except Exception as ex:
    logger.error("Fix Wall Constraints failed: {0}".format(ex))
    output.print_md("**Fix Wall Constraints - unexpected error**")
    output.print_code(traceback.format_exc())
    forms.alert("Unexpected error:\n{0}\n\nSee the output window for "
                "details.".format(ex),
                title="Fix Wall Constraints - Error")
