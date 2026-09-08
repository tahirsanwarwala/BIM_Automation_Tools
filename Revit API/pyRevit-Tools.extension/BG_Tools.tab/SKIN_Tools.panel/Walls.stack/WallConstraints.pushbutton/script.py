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

A wall whose elevation profile is sketched is treated more carefully,
because moving an end carries the outline with it.  It is never split --
Revit will not carry an outline across a split at all, so the upper band
would come out with its openings missing.  It IS rounded, but only while
the move stays within 1/16", the same distance this tool already treats
as one elevation; a move that small is not worth refusing and not worth
mentioning.  An end further off a whole inch than that is a real shift
in the sketch, so the wall is left exactly where it is.

Which is not the same as finished, so such a wall comes back as To
Check.  To Check is about what the sketch PREVENTED, never about the
sketch: a wall rounded within tolerance and crossing no level had
nothing prevented, and says nothing at all.  A wall left unrounded has
ends that will not meet a rounded neighbour, and that seam is exactly
what To Check is asking to be looked at.

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
    "Walls with a sketched profile are never split, and are rounded\n"
    "only while the end moves 1/16\" or less - further would shift the\n"
    "outline.  They are listed as To Check when that leaves an end off\n"
    "a whole inch, or a level uncut.\n"
    "The Base Constraint level is written into BG_LEVEL.\n"
    "Stacked walls, walls attached to a roof or floor, grouped walls\n"
    "and linked walls are reported but never touched.  Curtain walls\n"
    "are passed over in silence: they have no constraints to fix."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    FilteredElementCollector,
    Level,
    Transaction,
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
    WallKind.Curtain: "curtain wall (no base/top constraints to put right)",
    WallKind.Stacked: "stacked wall (sub-walls carry their own constraints)",
    WallKind.Unknown: "unsupported wall kind",
}

# Refusals not worth a row.  Every other refusal is: the user picked the
# wall and the tool would not touch it, which is worth saying.  A curtain
# wall is different in kind -- it has no base and top constraints for
# this tool to be right or wrong about, so one swept up in a selection is
# not a mistake to be told about.  Matched on the opening words of the
# reason above.
SILENT_SKIP_REASONS = ("curtain wall",)


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
    """Human-readable 'Base @ offset -> Top @ offset'."""
    return "{0} @ {1} | {2} @ {3}".format(
        _level_name(base_lvl_id), _feet_to_text(base_off),
        _level_name(top_lvl_id), _feet_to_text(top_off))


def _process_wall(wall, levels):
    """Fix one wall.  Returns a Result; never raises."""
    try:
        type_name = _name(wall.WallType)
    except Exception:
        type_name = "?"

    res = Result(wall.Id, type_name)

    reason = blocking_reason(wall)
    if reason:
        # Most refusals are worth saying out loud: the user picked the
        # wall and the tool would not touch it.  A curtain wall is not
        # like that -- it has no base and top constraints to put right
        # in the first place, so there is nothing to report, only noise
        # to make in a selection that swept one up.
        res.status = ("Not applicable"
                      if reason.startswith(SILENT_SKIP_REASONS)
                      else "Skipped")
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

    # Splitting a sketched wall is never on: Revit will not carry an
    # edited outline across a split, so the upper band would come out
    # with its openings missing.
    allow_split = not profile_edited

    # Rounding one is a matter of degree.  The end that moves carries the
    # sketch with it, so the only question is how far -- and a move no
    # bigger than the distance this tool already calls "the same
    # elevation" is not a move worth refusing, nor worth telling anyone
    # about.  Past that it is a real shift in the outline, and the wall
    # is left exactly where it is for a human to deal with.
    allow_round = True
    if profile_edited:
        base_snap, _ = wc.snap_end(base_z, levels)
        top_snap, _  = wc.snap_end(top_z, levels)
        drift = max(abs(base_snap - base_z), abs(top_snap - top_z))
        # A hair of slack, for the same reason snap_span_to_levels needs
        # it: an end exactly a sixteenth off a whole inch does not come
        # out exactly a sixteenth away in binary, and the rule is that
        # only a drift of MORE than a sixteenth is left for a human.
        allow_round = drift <= TOL + 1e-9

    try:
        plan = wc.plan_wall(base_z, top_z, levels,
                            allow_split=allow_split, allow_round=allow_round)
    except ValueError as ex:
        res.status = "Skipped"
        res.notes.append(str(ex))
        return res

    if profile_edited:
        # Being sketched is not itself worth reporting.  What is worth
        # reporting is what the sketch PREVENTED, and on a wall that was
        # rounded anyway and crosses no level, it prevented nothing --
        # the wall is as finished as any other.
        outstanding = []
        if not allow_round:
            outstanding.append(
                'the ends are more than 1/16" off a whole inch, so they '
                'were not rounded')
        if plan["needs_split"]:
            outstanding.append("the wall was not split at the {0} level(s) "
                               "it crosses".format(len(plan["interior"])))

        res.to_check = bool(outstanding)
        if res.to_check:
            res.notes.append(
                "profile edited: {0}; doing that automatically would move "
                "the sketched outline, so it is left for you".format(
                    " and ".join(outstanding)))

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


# A wall whose outcome was worse than "needs a human eye" keeps its own
# status: To Check would read as a softening of it.
URGENT_STATUSES = ("Failed", "Partly failed", "Skipped")

TO_CHECK = "To Check"


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
# REPORT
# ===============================================================================

# Outcomes that need no telling: the wall was put right, it was already
# right, or it was never this tool's business.  Every other status --
# Skipped, To Check, Failed, Partly failed, Needs split, Split into N --
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


def report(results):
    """Print every wall whose outcome is not self-evident, or nothing.

    Printing is what opens the output window, so staying quiet on a run
    with nothing to say is still the point.  A wall that was simply put
    right has nothing to say.  Anything else does, and the reason the
    net is wider than "problems" is that the two quietest outcomes --
    a wall SKIPPED, and a wall fixed but knowingly left unrounded --
    look from the model exactly like the tool not working.
    """
    shown = [r for r in results if is_reportable(r)]
    if not shown:
        return

    counts = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    output.print_md("## Fix Wall Constraints - {0} of {1} wall(s) worth "
                    "a look".format(len(shown), len(results)))
    output.print_md(" | ".join(
        "**{0}**: {1}".format(k, v) for k, v in sorted(counts.items())))

    rows = []
    for r in shown:
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
