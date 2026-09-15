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
    storey, each bound by the rule above -- the same cut Multi Wall
    Creation makes, through the same wall_constraints.plan_wall.  A wall
    crossing four levels becomes five walls; the original keeps the
    lowest band and its id.
  * Ends that are not on a level are rounded to the nearest whole inch.
    Ends that ARE on a level stay exactly where they are.

Rounding is unconditional.  Every wall's ends go to the nearest whole
inch however far they have to travel to get there -- basic and curtain,
sketched outline or not.  A sketched outline does move with the end it
was drawn against, and that is accepted rather than avoided: an end off
a whole inch is a defect wherever it came from, and up to half an inch
of outline following it is a smaller problem than a seam that will not
meet its neighbour.

A wall whose elevation profile is sketched is still never SPLIT.  Revit
will not carry an edited outline across a split at all, so the upper
band would come out with its openings missing.  That is the one thing
this tool leaves for a human, and the only thing it asks to be looked
at: a sketched wall crossing a level comes back as To Check, saying
which levels went uncut.  A sketched wall crossing none is as finished
as any other and says nothing.

Apart from that inch rounding, walls do not move: every offset is
computed so the wall keeps the absolute elevations it already had.

A CURTAIN wall follows the same rule at the base and none of it at the
top.  Its base is bound to the level at or below it exactly as any
other wall's is, and its BG_LEVEL is written from that level, because
that is what puts it on a storey.  Its top is left as an unconnected
height instead of being bound to a level: a curtain wall's grid,
mullions and panels are laid out against a height, and re-hanging the
top on a storey would re-lay them every time that storey moved.  For
the same reason it is never cut at a level -- a split curtain wall
loses every grid line, mullion and panel that was placed by hand.

Each wall's Base Constraint level is written into its BG_LEVEL
parameter afterwards, the same as Multi Wall Creation does for the
walls it builds.

ANY OTHER MODEL ELEMENT in the selection gets that BG_LEVEL and nothing
else.  No constraint of it is read, rewritten or checked -- the element
is looked at only for the level it already sits on, and the name of
that level is written into its BG_LEVEL.  The level is whichever Revit
itself calls the element's, falling back to the built-in parameters
that name a BASE level and then to a short list of parameter names; see
wall_bind.base_level_id.  An element with no BG_LEVEL parameter, or
none that Revit associates with a level, is passed over in silence:
there was never anything to write, and a selection that swept up a
category which does not carry the parameter is not a mistake to be told
about.

Walls whose top or base is attached to another element have their
CONSTRAINTS left alone: their parameters describe an extent their
geometry does not follow, and the API cannot re-create an attachment on
a wall this tool would make.  So do stacked walls, grouped walls, and
any wall whose extent cannot be read.

Every one of them still gets its BG_LEVEL, written from the Base
Constraint the wall already has.  Declining to touch a wall's
constraints is no reason to leave the parameter empty: it records only
the storey the wall sits on, which is as true of a wall hanging off a
roof as of any other, and the schedules read it either way.  A wall
this tool has looked at comes away with its BG_LEVEL whatever else it
was or was not allowed to do.

The arithmetic lives in BG.wall_constraints and is unit-tested; this
script only reads Revit, applies the plan, and reports.
"""

__title__  = "Wall\nLimits"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Select elements (or pre-select them, then run).\n"
    "Any element that is not a wall has only its BG_LEVEL written,\n"
    "from the level it already sits on.  Nothing else about it is\n"
    "touched, and one without the parameter is passed over quietly.\n"
    "Walls get the full check:\n"
    "Each wall's Base/Top Constraint and offsets are rewritten so the\n"
    "base sits on the level at or below it and the top hangs from the\n"
    "level at or above it, without moving the wall.\n"
    "Walls that cross a level are split into one wall per storey; the\n"
    "original wall is kept as the lowest band.\n"
    "Ends that are not on a level are rounded to the nearest inch,\n"
    "however far they have to move to get there.\n"
    "Walls with a sketched profile are rounded too, but are never\n"
    "split: Revit will not carry the outline across a split.  One that\n"
    "crosses a level is listed as To Check so you can cut it by hand.\n"
    "The Base Constraint level is written into BG_LEVEL.\n"
    "A curtain wall has its base bound and its BG_LEVEL written the\n"
    "same way, but keeps an unconnected height and is never cut.\n"
    "Stacked walls, walls attached to a roof or floor and grouped\n"
    "walls keep their constraints untouched, and are reported - but\n"
    "they still get BG_LEVEL from the Base Constraint they already\n"
    "have.  Linked walls cannot be selected at all."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    ElementType,
    FilteredElementCollector,
    Level,
    Transaction,
    TransactionGroup,
    TransactionStatus,
    Wall,
    WallKind,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from BG import wall_bind
from BG import wall_constraints as wc

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TOL = wc.TOL

BG_LEVEL_PARAM = wall_bind.BG_LEVEL_PARAM

# Everything below is BG.wall_bind's, under this script's own names.
# Split Wall does the same three awkward things to a wall -- bind an
# extent without inverting it, clone one into a new band, write
# BG_LEVEL -- and neither tool should own a second copy of them.  The
# names are kept so the rest of this script reads as it did.
bip           = wall_bind.bip
_eid          = wall_bind.eid
_is_valid     = wall_bind.is_valid
_pval         = wall_bind.pval
_set          = wall_bind.set_param
_name         = wall_bind.name_of
_feet_to_text = wall_bind.feet_to_text
find_parameter = wall_bind.find_parameter

# Kinds this tool refuses, in its own words.  wall_bind holds no
# opinion about which kinds a caller can handle.
BARRED_KINDS = {
    WallKind.Stacked: "stacked wall (sub-walls carry their own constraints)",
    WallKind.Unknown: "unsupported wall kind",
}

# Refusals not worth a row.  Every refusal this tool makes now is worth
# saying: the user picked the wall and the tool would not touch it.  The
# tuple is kept because the reasons above are a per-tool decision and
# the next one added may well be quiet.  Matched on the opening words of
# a reason.
SILENT_SKIP_REASONS = ()


def blocking_reason(wall):
    """Why this wall must be left alone entirely, or None to process it."""
    return wall_bind.blocking_reason(doc, wall, BARRED_KINDS)


def wall_extent(wall):
    """The wall's absolute (base_z, top_z, current) from its parameters."""
    return wall_bind.wall_extent(doc, wall)


def apply_constraints(wall, band):
    """Bind *wall* to *band*, in a sub-transaction of its own."""
    return wall_bind.apply_constraints(doc, wall, band)


def verify(wall, band):
    """Confirm a wall really ended up where the plan said."""
    return wall_bind.verify(doc, wall, band)


def create_band_wall(src, band):
    """Build one new wall occupying *band*, matching *src* in plan."""
    return wall_bind.create_band_wall(doc, src, band)


def apply_bg_level(wall, band):
    """Write the name of *wall*'s Base Constraint level into BG_LEVEL."""
    return wall_bind.apply_bg_level(doc, wall, band)


# Said wherever BG_LEVEL would not take.  One wording, because the three
# causes are one thing to do about it.
BG_UNWRITTEN = ("{0} could not be written - parameter missing, read-only, "
                "or not a text parameter".format(BG_LEVEL_PARAM))


def base_constraint_level_id(wall):
    """A wall's Base Constraint level id, or its host level if unset.

    Read off the wall rather than from a plan, because this is for walls
    there is no plan for.
    """
    level_id = _pval(wall, BuiltInParameter.WALL_BASE_CONSTRAINT)
    if _is_valid(level_id):
        return level_id
    try:
        return wall.LevelId
    except Exception:
        return None


def bg_level_from_wall(wall):
    """Give a wall BG_LEVEL from its own Base Constraint, changing nothing
    else.  True when the parameter now holds the level's name.
    """
    return wall_bind.set_bg_level(
        doc, wall, base_constraint_level_id(wall)) in wall_bind.BG_OK


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

class ModelElementFilter(ISelectionFilter):
    """Any model element in the host model.

    Walls this tool cannot process are allowed through on purpose, so
    they can be listed in the report rather than silently vanishing from
    the selection.  Everything else is allowed because everything else
    may still have a BG_LEVEL to fill in.  Linked elements are refused:
    they are read-only, and there is nothing to be done with one.
    """

    def AllowElement(self, elem):
        return is_model_element(elem)

    def AllowReference(self, ref, point):
        return False


def is_model_element(elem):
    """True when *elem* is an element instance this tool could write to.

    Element types, and anything owned by a view -- tags, dimensions,
    detail lines -- have no storey to record.

    Never raises.  Revit calls this from inside a selection filter, and
    an exception there does not skip the one element: it makes the whole
    pick refuse everything, silently.
    """
    if elem is None or isinstance(elem, ElementType):
        return False

    # Category is only asked whether it EXISTS.  Not is_valid(): the ids
    # of built-in categories are negative, so is_valid -- which means
    # "points at a real element" -- reads every one of them as nothing,
    # and every element in the model as unpickable.
    try:
        if elem.Category is None:
            return False
    except Exception:
        return False

    # OwnerViewId is a real, positive id only on a view-specific element.
    try:
        if _is_valid(elem.OwnerViewId):
            return False
    except Exception:
        pass

    return True


def get_selection():
    """Model elements from the current selection, or picked interactively.

    Returns (walls, others).  A wall gets its constraints checked; every
    other element gets BG_LEVEL and nothing else.
    """
    picked = [doc.GetElement(eid)
              for eid in uidoc.Selection.GetElementIds()]
    elements = [e for e in picked if is_model_element(e)]

    if not elements:
        try:
            refs = uidoc.Selection.PickObjects(
                ObjectType.Element, ModelElementFilter(),
                "Select the elements to check, then click Finish")
        except Exception:
            return [], []
        elements = [doc.GetElement(r.ElementId) for r in refs]
        elements = [e for e in elements if is_model_element(e)]

    walls  = [e for e in elements if isinstance(e, Wall)]
    others = [e for e in elements if not isinstance(e, Wall)]
    return walls, others


# ===============================================================================
# READING A WALL
# ===============================================================================

def is_curtain(wall):
    """True when this wall's panels are laid out by a curtain grid.

    A curtain wall gets its base bound to a level like any other wall,
    and its BG_LEVEL written from it, but its top is left unconnected
    and it is never cut at a level.  See wall_constraints.plan_unconnected
    for why.
    """
    try:
        return wall.WallType.Kind == WallKind.Curtain
    except Exception:
        return False


def is_profile_edited(wall):
    """True when the wall's elevation profile has been sketched."""
    try:
        return _is_valid(wall.SketchId)
    except Exception:
        # Older API surface: no SketchId, so assume a plain profile.
        return False


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
# PROCESS ONE WALL
# ===============================================================================

class Result(object):
    """One row of the report."""

    __slots__ = ("wall_id", "type_name", "before", "after", "status",
                 "notes", "to_check")

    def __init__(self, wall_id, type_name):
        self.wall_id   = wall_id
        self.type_name = type_name
        self.before    = ""
        self.after     = ""
        self.status    = ""
        self.notes     = []
        # Set for a wall this tool deliberately left work on, so the
        # wrapper can rename it without asking Revit a second time.
        self.to_check  = False


def describe(base_lvl_id, base_off, top_lvl_id, top_off):
    """Human-readable 'Base @ offset | Top @ offset'.

    An unconnected top is printed on its own.  It has no level to be
    offset from, and "Unconnected @ 0'-0"" reads like a wall of no
    height -- which is the one thing it never means.

    Exactly one "|" either way: the report splits these cells on it.
    """
    base = "{0} @ {1}".format(_level_name(base_lvl_id),
                              _feet_to_text(base_off))
    if not _is_valid(top_lvl_id):
        return "{0} | Unconnected".format(base)
    return "{0} | {1} @ {2}".format(
        base, _level_name(top_lvl_id), _feet_to_text(top_off))


def _process_wall(wall, levels):
    """Fix one wall.  Returns a Result; never raises."""
    try:
        type_name = _name(wall.WallType)
    except Exception:
        type_name = "?"

    res = Result(wall.Id, type_name)

    reason = blocking_reason(wall)
    if reason:
        # Every refusal is worth saying out loud: the user picked the
        # wall and the tool would not touch it.  SILENT_SKIP_REASONS is
        # empty today and the branch is kept for the next reason that
        # is not worth a row.
        res.status = ("Not applicable"
                      if reason.startswith(SILENT_SKIP_REASONS)
                      else "Skipped")
        res.notes.append(reason)

        # Refusing to touch a wall's CONSTRAINTS is not a reason to leave
        # its BG_LEVEL empty.  The parameter only records the storey the
        # wall already sits on, and that is just as true of a wall
        # attached to a roof or living in a group as of any other -- the
        # schedules read it either way.  Written from the wall's own Base
        # Constraint, since there is no plan for one of these.
        if not bg_level_from_wall(wall):
            res.notes.append(BG_UNWRITTEN)
        return res

    try:
        base_z, top_z, current = wall_extent(wall)
    except Exception as ex:
        res.status = "Skipped"
        res.notes.append(str(ex))
        if not bg_level_from_wall(wall):
            res.notes.append(BG_UNWRITTEN)
        return res

    res.before = describe(*current)

    profile_edited = is_profile_edited(wall)

    # Splitting a sketched wall is never on: Revit will not carry an
    # edited outline across a split, so the upper band would come out
    # with its openings missing.
    allow_split = not profile_edited

    # Rounding is not a decision.  Both plans round both ends to the
    # nearest whole inch by default, however far the end has to move to
    # get there -- basic and curtain, sketched outline or not.  A
    # sketched outline does travel with the end it was drawn against,
    # and that is accepted: an end off a whole inch is a defect wherever
    # it came from, and up to half an inch of outline following it is a
    # smaller problem than a seam that will not meet its neighbour.
    curtain = is_curtain(wall)

    try:
        if curtain:
            # Base bound to its level, top left as a height, never cut.
            plan = wc.plan_unconnected(base_z, top_z, levels)
        else:
            plan = wc.plan_wall(base_z, top_z, levels,
                                allow_split=allow_split)
    except ValueError as ex:
        res.status = "Skipped"
        res.notes.append(str(ex))
        if not bg_level_from_wall(wall):
            res.notes.append(BG_UNWRITTEN)
        return res

    if profile_edited and plan["needs_split"]:
        # The one thing left for a human.  Being sketched is not itself
        # worth reporting, and neither is being rounded -- both are
        # handled now.  A level this tool could not cut is not: Revit
        # will not carry a sketched outline across a split, so the upper
        # band would come out with its openings missing, and the cut has
        # to be made by hand.
        res.to_check = True
        res.notes.append(
            "profile edited, so it was not split at the {0} level(s) it "
            "crosses - Revit will not carry a sketched outline across a "
            "split, so cut it by hand".format(len(plan["interior"])))

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

    # constraints_changed calls offsets within 1/16" equal, which is the
    # right rule for "has this wall drifted off its level" and the wrong
    # one for "did the plan move it".  A rounding of less than 1/16" is
    # deliberate and small, and comparing it away would compute it and
    # then throw it out.  So a plan that moved an end at all counts as a
    # change, however little it moved it by.
    rounding_moved = (abs(plan["base_z"] - base_z) > 1e-9
                      or abs(plan["top_z"] - top_z) > 1e-9)

    if not changed and not rounding_moved and len(bands) == 1:
        res.status = "Already correct"
        res.after = res.before
        # BG_LEVEL is written even here.  The constraints being right
        # already says nothing about whether the parameter was ever
        # filled, and a wall this tool has looked at should come away
        # with both.
        if not apply_bg_level(wall, bands[0]):
            res.notes.append(BG_UNWRITTEN)
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


# A wall whose outcome was worse than "needs a human eye" keeps its own
# status: To Check would read as a softening of it.
URGENT_STATUSES = ("Failed", "Partly failed", "Skipped")

TO_CHECK = "To Check"

# A wall that crosses a level and that Revit would not let this tool cut
# there.  Not a failure to explain -- a wall to hand back.  The whole
# wall is rolled back, constraints included, so what the user opens is
# the wall they had, ready to be split by hand.
NOT_SPLIT = "Not split"

# The statuses _process_wall uses to say a cut was attempted.  After a
# rollback they are the difference between a wall to hand back and a
# wall that failed for some other reason worth printing in full.
SPLIT_ATTEMPTED = ("Split into", "Partly failed")


def process_wall(wall, levels):
    """Fix one wall, and flag it when work was left for a human.

    A sketched wall that still wants rounding or cutting comes back
    bound to its levels and no more, which is not the same as finished --
    and a status of "Fixed" would say it was.  So it is renamed here,
    once, at the point where every path out of _process_wall has come
    back together.  A sketched wall with nothing outstanding never sets
    the flag and stays as quiet as any other finished wall.
    """
    res = _process_wall(wall, levels)
    if res.status not in URGENT_STATUSES and res.to_check:
        res.status = TO_CHECK
    return res


# ===============================================================================
# BG_LEVEL ON EVERYTHING ELSE
# ===============================================================================

# How each set_bg_level outcome reads in the report.
ELEMENT_OUTCOMES = {
    wall_bind.BG_WRITTEN:  "Level written",
    wall_bind.BG_ALREADY:  "Already correct",
    wall_bind.BG_MISSING:  "Not applicable",
    wall_bind.BG_NO_LEVEL: "Not applicable",
    wall_bind.BG_READONLY: "Failed",
    wall_bind.BG_NOT_TEXT: "Failed",
    wall_bind.BG_REFUSED:  "Failed",
}

# Nothing here is worth a row, or a count.  A level written is the tool
# doing exactly what it was asked; an element without the parameter, or
# without a level, is not a mistake to be told about -- the selection
# swept up a category that does not carry BG_LEVEL and there was never
# anything to write.  Only a failure gets printed.
ELEMENT_QUIET_STATUSES = ("Level written", "Already correct",
                          "Not applicable")

ELEMENT_REASONS = {
    wall_bind.BG_MISSING:  "no {0} parameter".format(BG_LEVEL_PARAM),
    wall_bind.BG_NO_LEVEL: "not associated with a level",
    wall_bind.BG_READONLY: "{0} is read-only".format(BG_LEVEL_PARAM),
    wall_bind.BG_NOT_TEXT: "{0} is not a text parameter".format(
        BG_LEVEL_PARAM),
    wall_bind.BG_REFUSED:  "Revit refused the value",
}


class ElementResult(object):
    """One row of the BG_LEVEL-only table."""

    __slots__ = ("element_id", "category", "level", "was", "status", "notes")

    def __init__(self, element_id):
        self.element_id = element_id
        self.category   = "?"
        self.level      = ""
        self.was        = ""
        self.status     = ""
        self.notes      = []

    @property
    def reportable(self):
        """True only for a failure.

        Matched on the status this row will PRINT, not on the outcome it
        came from: the two are different vocabularies, and looking one
        up in the other's table silently reported everything.
        """
        return self.status not in ELEMENT_QUIET_STATUSES


def process_element(elem):
    """Give one non-wall element its BG_LEVEL, and change nothing else.

    Never raises: one element Revit will not take must not stop the rest
    of a selection.
    """
    res = ElementResult(elem.Id)

    try:
        res.category = elem.Category.Name if elem.Category else "?"
    except Exception:
        pass

    try:
        existing = wall_bind.find_parameter(elem, BG_LEVEL_PARAM)
        res.was = (existing.AsString() or "") if existing else ""
    except Exception:
        res.was = ""

    try:
        level_id = wall_bind.base_level_id(doc, elem)
        res.level = _level_name(level_id) if level_id else ""
        outcome = wall_bind.set_bg_level(doc, elem, level_id)
    except Exception as ex:
        res.status = "Failed"
        res.notes.append(str(ex))
        return res

    res.status = ELEMENT_OUTCOMES.get(outcome, "Failed")
    reason = ELEMENT_REASONS.get(outcome)
    if reason and res.status == "Failed":
        res.notes.append(reason)
    return res


def process_elements(elements):
    """Write BG_LEVEL across every non-wall element, in one transaction.

    One transaction for the lot, unlike the wall pass.  A wall's
    constraints are rewritten in a sequence Revit can reject halfway
    through, which is why each wall gets a transaction it can be rolled
    back inside.  Writing one text parameter cannot invalidate a
    geometry, so there is nothing here to contain per element -- and a
    transaction per element over a whole floor's worth of them would
    cost far more than it protects.
    """
    if not elements:
        return []

    handler = wall_bind.RollBackOnError()
    t = Transaction(doc, "Wall Limits - BG_LEVEL")
    t.Start()

    try:
        wall_bind.guard(t, handler)
        results = [process_element(e) for e in elements]
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        return [_element_failure(e, str(ex)) for e in elements]

    try:
        status = t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        status = None
        handler.messages.append(str(ex))

    if status == TransactionStatus.Committed and not handler.messages:
        return results

    note = "; ".join(["Revit rejected the change and nothing was written"]
                     + handler.messages)
    return [_element_failure(e, note) for e in elements]


def _element_failure(elem, note):
    """A row for an element whose whole batch was rolled back."""
    res = ElementResult(elem.Id)
    try:
        res.category = elem.Category.Name if elem.Category else "?"
    except Exception:
        pass
    res.status = "Failed"
    res.notes.append(note)
    return res


def not_split(wall_id, type_name, before):
    """One row for a wall this tool crossed a level on and put back.

    Its constraints are not reported as "before" and "after" because
    there is no after: the wall is untouched, and saying otherwise
    would send someone looking for a change that was rolled back.
    """
    res = Result(wall_id, type_name)
    res.before = before
    res.status = NOT_SPLIT
    res.notes.append("crosses a level the tool could not cut there - "
                     "left untouched, split it by hand")
    return res


def process_wall_safely(wall, levels):
    """Fix one wall inside a transaction of its own, and never lie about it.

    One wall, one transaction, for two reasons.

    Revit posts some disagreements at COMMIT rather than raising where
    they happen -- "the top of the Wall is lower than the base" is the
    one this tool meets -- so a single transaction around the whole
    selection meant one wall Revit would not take discarded every other
    wall's work along with it, behind a dialog whose only button was
    Cancel.  A transaction per wall makes the blast radius one wall.

    And the report was written from what the tool INTENDED, then printed
    after the commit, so a run that rolled back still claimed the walls
    were split.  A rolled-back wall is rebuilt here as what it actually
    is -- untouched, and why -- because the transaction's own status is
    the only honest account of it.
    """
    try:
        type_name = _name(wall.WallType)
    except Exception:
        type_name = "?"

    handler = wall_bind.RollBackOnError()
    t = Transaction(doc, "Wall Limits")
    t.Start()

    try:
        wall_bind.guard(t, handler)
        res = process_wall(wall, levels)
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        res = Result(wall.Id, type_name)
        res.status = "Failed"
        res.notes.append(str(ex))
        return res

    # A wall that lost a band is worse off than one left alone: the
    # original has already been shortened to make room for a band that
    # does not exist, so the storeys above it are simply gone.  Hand the
    # whole wall back instead, the same as a cut Revit refused outright.
    if res.status == "Partly failed":
        try:
            t.RollBack()
        except Exception:
            pass
        return not_split(wall.Id, type_name, res.before)

    try:
        status = t.Commit()
    except Exception as ex:
        try:
            t.RollBack()
        except Exception:
            pass
        status = None
        handler.messages.append(str(ex))

    if status == TransactionStatus.Committed and not handler.messages:
        return res

    # Rolled back: whatever res says happened, did not.
    rolled = Result(wall.Id, type_name)
    rolled.before = res.before

    if res.status.startswith(SPLIT_ATTEMPTED):
        # A cut Revit would not make.  Nothing here is worth quoting at
        # the user: they cannot act on Revit's wording, only on the wall,
        # and the wall is exactly as they left it.
        return not_split(wall.Id, type_name, res.before)

    rolled.status = "Failed"
    rolled.notes.append("Revit rejected the change and the wall was left "
                        "as it was")
    for message in handler.messages:
        rolled.notes.append(message)
    return rolled


# ===============================================================================
# REPORT
# ===============================================================================

# Outcomes that need no telling: the wall was put right, it was already
# right, or it was never this tool's business.  Every other status --
# Skipped, To Check, Failed, Not split, Needs split, Split into N --
# is either something to act on or a change to the model's element
# count, and says so.
QUIET_STATUSES = ("Fixed", "Already correct", "Not applicable")

# ...and even a quiet status speaks when the tool held something back.
# A sketched wall says so through its own To Check status; a BG_LEVEL
# that would not take has no status of its own, so it is matched on the
# opening words of the note that records it.
CAVEAT_NOTES = (BG_LEVEL_PARAM,)


def is_reportable(res):
    """True when this wall's outcome is worth printing."""
    if res.status not in QUIET_STATUSES:
        return True
    return any(n.startswith(CAVEAT_NOTES) for n in res.notes)


def report(results, elements):
    """Print every outcome that is not self-evident, or nothing.

    Printing is what opens the output window, so staying quiet on a run
    with nothing to say is still the point.  A wall that was simply put
    right has nothing to say.  Anything else does, and the reason the
    net is wider than "problems" is that the two quietest outcomes --
    a wall SKIPPED, and a wall fixed but knowingly left unrounded --
    look from the model exactly like the tool not working.
    """
    shown = [r for r in results if is_reportable(r)]
    element_shown = [r for r in elements if r.reportable]

    if not shown and not element_shown:
        return

    output.print_md("## Wall Limits")

    if results:
        counts = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        output.print_md("**{0} wall(s)**, {1} worth a look - {2}".format(
            len(results), len(shown),
            " | ".join("**{0}**: {1}".format(k, v)
                       for k, v in sorted(counts.items()))))

    if element_shown:
        # Only the failures are counted, let alone listed.  How many
        # elements took BG_LEVEL, and how many never had it to take, is
        # the tool working -- not news.
        output.print_md(
            "**{0} of {1} other element(s)** could not be given {2}".format(
                len(element_shown), len(elements), BG_LEVEL_PARAM))

    if shown:
        output.print_table(
            table_data=[[
                output.linkify(r.wall_id),
                r.type_name,
                r.before,
                r.after,
                r.status,
                "; ".join(r.notes),
            ] for r in shown],
            columns=["Wall", "Type", "Before (base | top)",
                     "After (base | top)", "Status", "Notes"],
        )

    if element_shown:
        output.print_table(
            table_data=[[
                output.linkify(r.element_id),
                r.category,
                r.level,
                r.was,
                r.status,
                "; ".join(r.notes),
            ] for r in element_shown],
            columns=["Element", "Category", "Level",
                     "{0} was".format(BG_LEVEL_PARAM), "Status", "Notes"],
        )


# ===============================================================================
# MAIN
# ===============================================================================

def main():
    walls, others = get_selection()
    if not walls and not others:
        return

    levels = collect_levels()
    if not levels:
        forms.alert("This model has no levels, so nothing here can be "
                    "bound to one.",
                    title="Wall Limits")
        return

    group = TransactionGroup(doc, "Wall Limits")
    group.Start()
    try:
        results = [process_wall_safely(wall, levels) for wall in walls]
        element_results = process_elements(others)
        group.Assimilate()
    except Exception as ex:
        try:
            group.RollBack()
        except Exception:
            pass
        output.print_md("**Wall Limits - run failed**")
        output.print_code(traceback.format_exc())
        forms.alert("Run failed:\n{0}".format(ex),
                    title="Wall Limits - Error")
        return

    report(results, element_results)


try:
    main()
except Exception as ex:
    logger.error("Wall Limits failed: {0}".format(ex))
    output.print_md("**Wall Limits - unexpected error**")
    output.print_code(traceback.format_exc())
    forms.alert("Unexpected error:\n{0}\n\nSee the output window for "
                "details.".format(ex),
                title="Wall Limits - Error")
