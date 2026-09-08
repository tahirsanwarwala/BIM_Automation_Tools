# -*- coding: utf-8 -*-
"""Split a wall horizontally at a picked edge.

Revit splits a wall vertically and only vertically.  This does the
other cut: pick a wall, pick an edge or a line anywhere in the model --
host or linked -- and the wall becomes two, meeting at that elevation.

The ORIGINAL wall is always the lower one.  It keeps its id, its Mark,
its hosted doors and windows and everything else about it, and simply
stops at the cut.  A new wall is built above it, matching it in plan,
in type, in Location Line, in facing and in every writable instance
parameter except the vertical ones.  Nothing about which half is which
depends on where you clicked.

Both halves are bound to LEVELS, not left unconnected: the lower wall's
top and the upper wall's base hang off whichever level the house rule
picks for the cut, so the two meet exactly and neither crosses a level
it should not.  That is BG.wall_constraints, the same arithmetic Wall
Limits uses.

Both halves then get their Base Constraint level's name written into
BG_LEVEL.

WHAT THE REFERENCE IS FOR is only its ELEVATION.  Where it sits in
plan, how long it is and which way it runs are all ignored -- a
horizontal cut needs one number, and the thing you point at is a
convenient way to say it.

The pick comes in two goes, because no single Revit pick spans both
models.  A LINKED reference is offered first, since that is where the
references usually are; Esc moves the pick into this model, and Esc
again ends the run.

Five kinds of thing can name a height, tried in this order: a line --
model, detail or reference -- gives its own; a horizontal reference
plane gives its own; a level gives its elevation; a solid edge gives
its own; and anything else gives the height of the POINT you clicked,
which is still the height you pointed at.  Only the last of those is
approximate, and it says so.

A wall attached to a roof or floor, inside a group, or of a kind whose
constraints do not describe it -- curtain, stacked -- is refused rather
than half-cut.  So is a cut that would leave either half too short to
be a wall.
"""

__title__  = "Split\nWall"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Split a wall HORIZONTALLY, which Revit itself will not do.\n"
    "Pick the wall, then pick a reference at the height to cut at: a "
    "line, a reference plane, a level or an edge.  A LINKED one is "
    "offered first; Esc to pick in this model instead.\n"
    "The original wall keeps its id and becomes the LOWER half; a new "
    "wall is built above it, matching it in everything but height.\n"
    "Both halves are bound to levels and get BG_LEVEL written.\n"
    "Repeats until Esc."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    CurveElement,
    FilteredElementCollector,
    Level,
    ReferencePlane,
    RevitLinkInstance,
    Transaction,
    Wall,
    WallKind,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from BG import wall_bind, wall_constraints, window_cw

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

TOOL_TITLE = "Split Wall"

TOL = wall_bind.TOL

# Neither half may come out shorter than this, in feet.  Three inches:
# below that the cut is a mis-click, not a wall.
MIN_HALF = 0.25

# An edge is horizontal when its two ends are within this of each other
# in Z, in feet.  A sixteenth of an inch.
LEVEL_EDGE_TOL = 1.0 / 12.0 / 16.0

BARRED_KINDS = {
    WallKind.Curtain: "curtain wall - its panels carry their own extent",
    WallKind.Stacked: "stacked wall - its sub-walls carry their own extent",
    WallKind.Unknown: "unsupported wall kind",
}


# ===========================================================================
# HELPERS
# ===========================================================================

def report(rows):
    """Print the run's rows, or nothing at all when there are none."""
    if not rows:
        return
    output.print_md("### {} - {} wall(s)".format(TOOL_TITLE, len(rows)))
    output.print_table(
        table_data=rows,
        columns=["Wall", "Cut at", "Lower", "Upper", "Notes"])


def host_levels():
    """Every Level in this model as (ElementId, elevation) tuples."""
    return [(lvl.Id, lvl.Elevation)
            for lvl in (FilteredElementCollector(doc)
                        .OfClass(Level)
                        .WhereElementIsNotElementType())]


def describe(band):
    """'Base @ offset | Top @ offset' for one band."""
    return "{0} @ {1} | {2} @ {3}".format(
        wall_bind.name_of(doc.GetElement(band["base_level_id"])),
        wall_bind.feet_to_text(band["base_offset"]),
        wall_bind.name_of(doc.GetElement(band["top_level_id"])),
        wall_bind.feet_to_text(band["top_offset"]))


# ===========================================================================
# SELECTION
# ===========================================================================

class WallFilter(ISelectionFilter):
    """Any wall in this model.

    Kinds this tool cannot cut are let through on purpose, so they can
    be reported rather than silently refusing to highlight.
    """

    def AllowElement(self, elem):
        return isinstance(elem, Wall)

    def AllowReference(self, ref, point):
        return False


class AnythingFilter(ISelectionFilter):
    """Anything at all.

    Only an elevation is wanted, and everything in a model has one
    somewhere -- so refusing categories here would only stop the user
    pointing at the thing they can see.  A linked pick needs
    AllowElement to accept the RevitLinkInstance and AllowReference to
    accept what is inside it, and saying yes to both covers a host pick
    as well.
    """

    def AllowElement(self, elem):
        return True

    def AllowReference(self, ref, point):
        return True


def pick_wall():
    """Pick one wall, or None when the user is done."""
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, WallFilter(),
            "Pick the wall to split horizontally (Esc when done)")
    except OperationCanceledException:
        return None
    except Exception as ex:
        logger.debug("Wall pick ended: {}".format(ex))
        return None

    if ref is None:
        return None
    elem = doc.GetElement(ref.ElementId)
    return elem if isinstance(elem, Wall) else None


def _levelish_z(elem, transform):
    """The elevation *elem* names, or None, with the kind that named it.

    Five kinds of thing can name a height, and they are asked in the
    order of how exactly they answer:

      * a LINE -- model, detail or reference.  ObjectType.Edge never
        reaches one of these: a line has no solid and so no edges, which
        is why a detail line drawn to mark a course could not be picked
        at all.  GeometryCurve is where its geometry actually lives.
      * a REFERENCE PLANE, which in an elevation view looks exactly like
        a line and is a natural thing to point at.
      * a LEVEL, whose elevation is the whole point of it.
      * a solid EDGE, for a reference whose geometry carries one.

    Returns (z, kind) or (None, None).  *transform* is the link's, or
    None for something in this model.
    """
    def moved(point):
        return transform.OfPoint(point) if transform is not None else point

    if isinstance(elem, CurveElement):
        try:
            curve = elem.GeometryCurve
            a = moved(curve.GetEndPoint(0))
            b = moved(curve.GetEndPoint(1))
        except Exception:
            return None, None
        if abs(a.Z - b.Z) > LEVEL_EDGE_TOL:
            return None, "sloped line"
        return (a.Z + b.Z) / 2.0, "line"

    if isinstance(elem, ReferencePlane):
        try:
            a = moved(elem.BubbleEnd)
            b = moved(elem.FreeEnd)
        except Exception:
            return None, None
        if abs(a.Z - b.Z) > LEVEL_EDGE_TOL:
            return None, "sloped reference plane"
        return (a.Z + b.Z) / 2.0, "reference plane"

    if isinstance(elem, Level):
        try:
            return moved(XYZ(0.0, 0.0, elem.Elevation)).Z, "level"
        except Exception:
            return None, None

    return None, None


def _edge_z(ref, owner, transform):
    """The elevation of the solid edge behind *ref*, or (None, None).

    Linked geometry needs the reference re-expressed inside the link
    before the linked document will recognise it.  The whole thing is
    wrapped because a reference to something that is not an edge -- a
    face, a whole element -- simply will not resolve, which is an answer
    rather than a failure.
    """
    try:
        if transform is not None:
            link_doc = owner.GetLinkDocument()
            inner = link_doc.GetElement(ref.LinkedElementId)
            geo = inner.GetGeometryObjectFromReference(
                ref.CreateReferenceInLink())
        else:
            geo = owner.GetGeometryObjectFromReference(ref)
        curve = geo.AsCurve()
        a = curve.GetEndPoint(0)
        b = curve.GetEndPoint(1)
        if transform is not None:
            a = transform.OfPoint(a)
            b = transform.OfPoint(b)
    except Exception:
        return None, None

    if abs(a.Z - b.Z) > LEVEL_EDGE_TOL:
        return None, "sloped edge"
    return (a.Z + b.Z) / 2.0, "edge"


def _elevation_from(ref):
    """(z, note) in MODEL coordinates for whatever was picked."""
    try:
        owner = doc.GetElement(ref.ElementId)
    except Exception:
        owner = None
    if owner is None:
        return None, "that pick could not be read"

    transform = None
    elem = owner
    if isinstance(owner, RevitLinkInstance):
        link_doc = owner.GetLinkDocument()
        if link_doc is None:
            return None, "that link is not loaded"
        transform = owner.GetTotalTransform()
        try:
            elem = link_doc.GetElement(ref.LinkedElementId)
        except Exception:
            elem = None

    kind = None
    z = None

    if elem is not None:
        z, kind = _levelish_z(elem, transform)

    if z is None:
        edge_z, edge_kind = _edge_z(ref, owner, transform)
        if edge_z is not None:
            z, kind = edge_z, edge_kind
        elif edge_kind is not None:
            kind = kind or edge_kind

    if z is not None:
        return z, None

    # Nothing readable was horizontal, so fall back to where the user
    # actually clicked.  That is still the height they pointed at, and
    # for a sloped reference it is the only sensible reading of it.
    try:
        point = ref.GlobalPoint
    except Exception:
        point = None
    if point is None:
        return None, "that pick has no readable height"

    return point.Z, "{0} - the height of the point picked was used".format(
        "that {0} is not horizontal".format(kind) if kind
        else "no line, plane, level or edge behind that pick")


def pick_elevation():
    """Pick a reference and return (elevation, note) in LEVEL space.

    Two picks offered, not one, because no single Revit pick spans both
    documents: ObjectType.LinkedElement reaches into a link and refuses
    this model, ObjectType.Element the other way round.  The LINKED one
    goes first, since that is where the references usually are, and Esc
    moves into this model rather than ending the run.

    Level elevations are measured from the Project Base Point while
    picked geometry comes back in internal model coordinates, so the
    difference is taken out here -- once, at the boundary -- and
    everything downstream is in one space.
    """
    attempts = (
        (ObjectType.LinkedElement,
         "Pick a reference in a LINK at the height to cut at "
         "(Esc to pick in this model instead)"),
        (ObjectType.Element,
         "Pick a line, reference plane, level or edge in THIS model "
         "at the height to cut at"),
    )

    ref = None
    for object_type, prompt in attempts:
        try:
            ref = uidoc.Selection.PickObject(
                object_type, AnythingFilter(), prompt)
        except OperationCanceledException:
            ref = None
        except Exception as ex:
            logger.debug("Reference pick ended: {}".format(ex))
            ref = None
        if ref is not None:
            break

    if ref is None:
        return None, None

    z, note = _elevation_from(ref)
    if z is None:
        return None, note

    return z - window_cw.project_base_elevation(doc), note


# ===========================================================================
# SPLITTING
# ===========================================================================

def split_wall(wall, cut_z, levels, pick_note):
    """Cut one wall at *cut_z*.  Returns one report row."""
    label = output.linkify(wall.Id)
    cut_text = wall_bind.feet_to_text(cut_z)
    notes = [pick_note] if pick_note else []

    def row(lower="-", upper="-", extra=None):
        return [label, cut_text, lower, upper,
                "; ".join(notes + ([extra] if extra else []))]

    reason = wall_bind.blocking_reason(doc, wall, BARRED_KINDS)
    if reason:
        return row(extra=reason)

    try:
        base_z, top_z, _current = wall_bind.wall_extent(doc, wall)
    except Exception as ex:
        return row(extra=str(ex))

    if cut_z - base_z < MIN_HALF or top_z - cut_z < MIN_HALF:
        return row(extra="that height is at or outside the wall's own "
                         "extent ({0} to {1}) - nothing to cut".format(
                             wall_bind.feet_to_text(base_z),
                             wall_bind.feet_to_text(top_z)))

    # The same arithmetic Wall Limits uses, so the two halves meet on a
    # level the house rule chose rather than on a bare number.
    try:
        lower = wall_constraints.constraints_for(base_z, cut_z, levels)
        upper = wall_constraints.constraints_for(cut_z, top_z, levels)
    except ValueError as ex:
        return row(extra="could not constrain the halves: {0}".format(ex))

    # The ORIGINAL becomes the lower half.  It keeps its id and its
    # inserts, so the half a schedule already knows about is the half
    # that stays.
    try:
        wall_bind.apply_constraints(doc, wall, lower)
    except Exception as ex:
        return row(extra="the original wall could not be shortened: "
                         "{0}".format(ex))

    problem = wall_bind.verify(doc, wall, lower)
    if problem:
        return row(extra="the original wall ended up wrong: {0}".format(
            problem))

    lower_text = describe(lower)

    try:
        new_wall = wall_bind.create_band_wall(doc, wall, upper)
    except Exception as ex:
        notes.append("THE ORIGINAL WALL HAS BEEN SHORTENED but the upper "
                     "half could not be built: {0}".format(ex))
        return row(lower=lower_text)

    problem = wall_bind.verify(doc, new_wall, upper)
    if problem:
        # Better no wall than an invalid one that blocks the commit.
        doc.Delete(new_wall.Id)
        doc.Regenerate()
        notes.append("THE ORIGINAL WALL HAS BEEN SHORTENED but the upper "
                     "half was rejected: {0}".format(problem))
        return row(lower=lower_text)

    unwritten = 0
    if not wall_bind.apply_bg_level(doc, wall, lower):
        unwritten += 1
    if not wall_bind.apply_bg_level(doc, new_wall, upper):
        unwritten += 1
    if unwritten:
        notes.append(
            "{0} could not be written on {1} of the two - parameter "
            "missing, read-only, or not a text parameter".format(
                wall_bind.BG_LEVEL_PARAM, unwritten))

    notes.append("new wall {0}".format(wall_bind.eid(new_wall.Id)))
    return row(lower=lower_text, upper=describe(upper))


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    levels = host_levels()
    if not levels:
        forms.alert("This model has no levels, so neither half of a split "
                    "wall could be constrained to anything.",
                    title=TOOL_TITLE)
        return

    rows = []
    while True:
        wall = pick_wall()
        if wall is None:
            break

        cut_z, pick_note = pick_elevation()
        if cut_z is None:
            if pick_note:
                rows.append([output.linkify(wall.Id), "-", "-", "-",
                             pick_note])
            break

        t = Transaction(doc, "Split wall horizontally")
        t.Start()
        try:
            rows.append(split_wall(wall, cut_z, levels, pick_note))
            t.Commit()
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            raise

    report(rows)


try:
    main()
except Exception as ex:
    logger.error("{} failed: {}".format(TOOL_TITLE, ex))
    output.print_md("**{} - unexpected error**".format(TOOL_TITLE))
    output.print_code(traceback.format_exc())
    forms.alert("Unexpected error:\n{0}\n\nSee the output window for "
                "details.".format(ex), title=TOOL_TITLE)
