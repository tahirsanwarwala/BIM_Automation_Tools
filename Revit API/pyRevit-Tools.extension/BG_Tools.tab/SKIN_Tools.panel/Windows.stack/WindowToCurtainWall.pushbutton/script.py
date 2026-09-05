# -*- coding: utf-8 -*-
"""
Create a host-model curtain wall from an opening picked in a LINKED model.

Pick either a window in a linked Revit model - a real Windows-category
family or a custom Generic Model standing in for one - or a curtain wall
in that link, then pick the host-model wall it belongs on.  A curtain
wall is created on that wall to match what was picked.

From a WINDOW, sizes come from the family's own parameters: Sill Height
above the window's level for the base - read from both the instance and
the type, the higher of the two winning - then Rough Width/Height or
Width/Height, falling back to measured geometry only where a parameter
is missing.  Measuring the solids would start the wall at the bottom of
any sill trim, apron or cast stone hanging below the opening - but the
parameter is only trusted while it agrees with where the solids are, so
a family measuring Sill Height from something else cannot throw the wall
a storey out.  The wall is always a plain rectangle, arched windows
included: an arched head can only be recovered by tracing tessellated
solids, and that trace is not dependable enough to build from, so the
rectangle is simply made tall enough to cover the arch.

From a CURTAIN WALL, everything is read off that wall instead: its
length, its base and top constraints with their offsets, and - when its
elevation has been sketched - its actual profile, carried across onto
the picked wall as a rigid move, so arcs stay arcs and nothing mirrors.

A curtain wall that CROSSES A LEVEL is cut at it, one new wall per
storey, through the same wall_constraints.plan_wall the skin walls use
with allow_round=False - so a curtain wall and the skin around it can
never disagree about where a storey ends.  A sketched profile does not
survive being cut, since the outline belongs to the whole opening and
not to either half, so a split wall gives its profile up and says so.
Wall sweeps have no say in any of this.

The TYPE of a WINDOW is chosen from its Type Mark: the leading letters
name the type, so WA12 -> 'WA_Window', WS03 -> 'WS_Window', W04 ->
'W_Window'.  A mark whose serial is itself letters, like WSXX, still
resolves to WS.  With no matching type you are asked to pick one, once
per prefix - a type is never created or duplicated.

A CURTAIN WALL is always 'WA_WINDOW', by name.  Its Type Mark says
nothing worth matching on: a curtain wall carries the window number on
its INSTANCE mark, and its type mark is a different thing entirely.
You are asked to pick only when this model has no WA_WINDOW.

The new wall's centreline sits on the host wall's centreline.  Whatever
grid layout the matched type carries is stripped off the new wall right
away, leaving one plain panel: no grid lines and no mullions.  The type
itself is never touched.

Each new wall gets its BG_ parameters filled: BG_WINDOW NUMBER from the
source - the window's Type Mark, or a curtain wall's own instance Mark,
left blank when there is none - and BG_BUILDING ID, BG_ELEVATION and
BG_LEVEL copied straight off the host wall.  BG_PROFILE is left alone.
A parameter that is missing at either end is reported and left blank -
it never stops the wall being made.

Picking loops until Esc.  The linked model is never modified.
"""

__title__  = "Curtain\nWall"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick a window or a curtain wall in a LINKED model, then the host "
    "wall it sits on, and a curtain wall is created to match it.\n"
    "A window's type comes from its Type Mark prefix (WA12 -> "
    "WA_Window); a linked curtain wall is always WA_WINDOW.\n"
    "A window gives its width, height and sill from its own parameters "
    "and always comes out rectangular, arched ones included; a linked "
    "curtain wall gives its length, constraints and sketched profile, "
    "and is split at every level it crosses.\n"
    "Repeats until Esc.  The linked model is left untouched."
)

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FamilyInstance,
    FilteredElementCollector,
    Level,
    Line,
    Sketch,
    Transaction,
    Transform,
    Wall,
    WallKind,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, script

from BG import wall_constraints, wall_sketch, window_cw

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

# Module-level aliases so the rest of this file needs no further edits for
# names that moved to BG.window_cw but are still used bare here.
get_element_name  = window_cw.get_element_name
as_element_id     = window_cw.as_element_id
eid_value         = window_cw.eid_value
length_param      = window_cw.length_param
iter_solid_points = window_cw.iter_solid_points
is_category       = window_cw.is_category
wall_axis         = window_cw.wall_axis
type_mark         = window_cw.type_mark
mark_prefix       = window_cw.mark_prefix
feet_text         = window_cw.feet_text
project_base_elevation = window_cw.project_base_elevation

MIN_EXTENT      = 0.02    # feet, below this a measured width/height is junk

# A linked CURTAIN WALL is always rebuilt as this type.  Its Type Mark
# says nothing worth matching on -- a curtain wall's mark is the window
# number, not a family code -- so the prefix rule that answers for a
# window has nothing to answer with here.
CURTAIN_TYPE_NAME = "WA_WINDOW"

# Print the measurements table every run.  Off by default: a run that
# worked has nothing to say, and printing is what opens the output
# window, so a clean run now shows nothing at all.  Turn it on while
# dialling the numbers in on a troublesome window.
VERBOSE         = False


# ===============================================================================
# SELECTION
# ===============================================================================

def is_curtain_wall(elem):
    """True when *elem* is a curtain wall."""
    if not isinstance(elem, Wall):
        return False
    try:
        return elem.WallType.Kind == WallKind.Curtain
    except Exception:
        return False


class LinkedSourceFilter(ISelectionFilter):
    """Allow a linked window, Generic Model window, or curtain wall."""

    def AllowElement(self, elem):
        return True

    def AllowReference(self, ref, point):
        try:
            link_inst = doc.GetElement(ref.ElementId)
            link_doc  = link_inst.GetLinkDocument()
            if link_doc is None:
                return False
            elem = link_doc.GetElement(ref.LinkedElementId)
            if is_curtain_wall(elem):
                return True
            if not isinstance(elem, FamilyInstance):
                return False
            return (is_category(elem, BuiltInCategory.OST_Windows) or
                    is_category(elem, BuiltInCategory.OST_GenericModel))
        except Exception:
            return False


class WallFilter(ISelectionFilter):
    """Allow any Wall in the host model."""

    def AllowElement(self, elem):
        return isinstance(elem, Wall)

    def AllowReference(self, ref, point):
        return False


def pick_pairs():
    """Pick (link instance, linked source, host wall) triples until Esc.

    The source is a window or a curtain wall in the link.  Esc at either
    prompt ends the whole run; anything already picked is still built.
    """
    picked    = []
    seen      = set()
    src_filt  = LinkedSourceFilter()
    wall_filt = WallFilter()

    while True:
        try:
            win_ref = uidoc.Selection.PickObject(
                ObjectType.LinkedElement, src_filt,
                "Pick a window or curtain wall in a linked model "
                "(Esc when done)")
        except OperationCanceledException:
            break
        except Exception as ex:
            logger.debug("Source pick ended: {}".format(ex))
            break
        if win_ref is None:
            break

        link_inst = doc.GetElement(win_ref.ElementId)
        link_doc  = link_inst.GetLinkDocument()
        window    = link_doc.GetElement(win_ref.LinkedElementId)

        try:
            wall_ref = uidoc.Selection.PickObject(
                ObjectType.Element, wall_filt,
                "Pick the host wall this goes on (Esc to stop)")
        except OperationCanceledException:
            break
        except Exception as ex:
            logger.debug("Wall pick ended: {}".format(ex))
            break
        if wall_ref is None:
            break

        host_wall = doc.GetElement(wall_ref.ElementId)

        key = (eid_value(win_ref.ElementId),
               eid_value(win_ref.LinkedElementId),
               eid_value(wall_ref.ElementId))
        if key in seen:
            continue
        seen.add(key)
        picked.append((link_inst, window, host_wall))

    return picked


# ===============================================================================
# MEASUREMENT
# ===============================================================================

def measure_source(link_inst, source, host_wall):
    """Measure whichever kind of linked element was picked."""
    if is_curtain_wall(source):
        return measure_curtain_wall(link_inst, source, host_wall)
    return window_cw.measure_window(link_inst, source, host_wall)


def wall_vertical_extent(wall, source_doc):
    """Return (base elevation, height) for *wall* in its own document.

    Elevations come back in geometry space, matching what
    project_base_elevation corrects for.  Returns (None, None) when the
    wall's constraints cannot be read.
    """
    delta = project_base_elevation(source_doc)

    def level_elev(level_id):
        if level_id is None or level_id == ElementId.InvalidElementId:
            return None
        level = source_doc.GetElement(level_id)
        if level is None:
            return None
        try:
            return level.Elevation - delta
        except Exception:
            return None

    def offset(bip_name):
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is None:
            return 0.0
        try:
            p = wall.get_Parameter(bip)
        except Exception:
            return 0.0
        return p.AsDouble() if (p is not None and p.HasValue) else 0.0

    try:
        base = level_elev(wall.LevelId)
    except Exception:
        base = None
    if base is None:
        return None, None
    base += offset("WALL_BASE_OFFSET")

    top = None
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
        if p is not None and p.HasValue:
            top_level = level_elev(p.AsElementId())
            if top_level is not None:
                top = top_level + offset("WALL_TOP_OFFSET")
    except Exception:
        top = None

    if top is None:
        try:
            p = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
        except Exception:
            p = None
        if p is None or not p.HasValue:
            return None, None
        top = base + p.AsDouble()

    height = top - base
    if height < MIN_EXTENT:
        return None, None
    return base, height


def linked_wall_profile(wall, source_doc, transform):
    """Return the wall's sketched elevation profile in host coordinates.

    Revit only gives a wall a profile sketch once its elevation has been
    edited, so a plain rectangular wall returns None and needs no profile
    work at all.
    """
    try:
        sketch_id = wall.SketchId
    except Exception:
        return None
    if sketch_id is None or sketch_id == ElementId.InvalidElementId:
        return None

    sketch = source_doc.GetElement(sketch_id)
    if not isinstance(sketch, Sketch):
        return None

    curves = []
    try:
        for arr in sketch.Profile:
            for curve in arr:
                curves.append(curve.CreateTransformed(transform))
    except Exception as ex:
        logger.debug("Could not read linked wall profile: {}".format(ex))
        return None
    return curves or None


def instance_mark(elem):
    """Return *elem*'s own Mark, or None when it is blank.

    The INSTANCE mark, not the type's.  A linked curtain wall carries
    its window number here, and that is what BG_WINDOW NUMBER wants;
    the Type Mark on a curtain wall type is a different thing entirely.
    """
    for getter in (lambda e: e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK),
                   lambda e: e.LookupParameter("Mark")):
        try:
            p = getter(elem)
        except Exception:
            continue
        if p is None or not p.HasValue:
            continue
        try:
            text = p.AsString()
        except Exception:
            continue
        if text and text.strip():
            return text.strip()
    return None


def host_levels():
    """Return [(ElementId, elevation)] for every host Level.

    Elevations come back in geometry space, so they can be compared with
    a plan's own sill and height directly.
    """
    delta = project_base_elevation(doc)
    return [(lvl.Id, lvl.Elevation - delta)
            for lvl in FilteredElementCollector(doc).OfClass(Level)]


def split_at_levels(plan, levels):
    """One plan per storey for a curtain wall that crosses a level.

    A linked curtain wall is split exactly as a skin wall is, through
    the same wall_constraints.plan_wall with allow_round=False, so the
    two can never disagree about where a storey ends.  A wall that
    crosses nothing comes back as itself.

    A SKETCHED profile cannot survive being cut in two -- the outline
    belongs to the whole opening, not to either half -- so a split plan
    gives up its profile and says so.  A rectangle in the right place
    beats an arch in two.
    """
    if plan.source_kind != "curtain wall" or not levels:
        return [plan]

    try:
        cut = wall_constraints.plan_wall(
            plan.sill, plan.sill + plan.height, levels, allow_round=False)
    except ValueError as ex:
        plan.notes.append("could not split at levels: {}".format(ex))
        return [plan]

    bands = cut.get("bands") or []
    if len(bands) < 2:
        return [plan]

    pieces = []
    for band in bands:
        piece = window_cw.copy_plan(plan)
        piece.sill   = band["base_z"]
        piece.height = band["top_z"] - band["base_z"]
        if piece.profile_curves:
            piece.profile_curves = None
            piece.notes.append(
                "split at a level, so its sketched profile was dropped")
        else:
            piece.notes.append("split at a level")
        pieces.append(piece)
    return pieces


def measure_curtain_wall(link_inst, wall, host_wall):
    """Return (WindowPlan, skip_reason) for a curtain wall picked in a link."""
    link_doc  = link_inst.GetLinkDocument()
    transform = link_inst.GetTotalTransform()

    host_curve, host_dir = wall_axis(host_wall)
    if host_curve is None or host_dir is None:
        return None, "picked wall has no usable location curve"

    try:
        src_curve = wall.Location.Curve.CreateTransformed(transform)
    except Exception:
        return None, "linked curtain wall has no usable location curve"

    base, height = wall_vertical_extent(wall, link_doc)
    if base is None:
        return None, "could not read the linked curtain wall's height"

    base = transform.OfPoint(XYZ(0.0, 0.0, base)).Z

    width = src_curve.Length
    if width < MIN_EXTENT:
        return None, "linked curtain wall is too short to rebuild"

    plan = window_cw.WindowPlan()
    plan.source_kind = "curtain wall"
    plan.window_id = eid_value(wall.Id)
    plan.link_name = get_element_name(link_inst)
    # The instance Mark, and no prefix.  BG_WINDOW NUMBER is filled from
    # plan.mark, and the type is settled by name rather than by prefix,
    # so a curtain wall with no Mark simply leaves the number blank.
    plan.mark      = instance_mark(wall)
    plan.prefix    = None
    plan.wall_dir  = host_dir
    plan.width     = width
    plan.height    = height
    plan.sill      = base

    mid = src_curve.Evaluate(0.5, True)
    plan.centre = XYZ(mid.X, mid.Y, base)

    profile = linked_wall_profile(wall, link_doc, transform)

    if not isinstance(src_curve, Line):
        if profile:
            plan.notes.append("curved source wall; sketched profile not copied")
        return plan, None

    # Keep the source frame so the sketched profile can be carried across to
    # whichever host wall is picked, however that wall happens to run.
    d = src_curve.Direction
    plan.src_dir = XYZ(d.X, d.Y, 0.0).Normalize()
    plan.profile_curves = profile

    if profile:
        # Size the new wall to the profile itself rather than to the source
        # wall's constraints.  A sketched wall's base and height say nothing
        # about where its outline actually runs, and it is the outline the
        # reference planes have to land on - the sill and the crown of the
        # arch, not the floor below and the springing line.
        extent = profile_extent(profile, mid, plan.src_dir)
        if extent is not None:
            u_lo, u_hi, z_lo, z_hi = extent
            plan.width  = u_hi - u_lo
            plan.height = z_hi - z_lo
            plan.sill   = z_lo
            u_mid = (u_lo + u_hi) / 2.0
            plan.centre = XYZ(mid.X + plan.src_dir.X * u_mid,
                              mid.Y + plan.src_dir.Y * u_mid,
                              z_lo)

    plan.src_origin = XYZ(plan.centre.X, plan.centre.Y, plan.sill)
    return plan, None


def profile_extent(curves, ref, direction):
    """Return (u_lo, u_hi, z_lo, z_hi) bounding *curves* in the wall plane.

    *u* is measured from *ref* along *direction*; *z* is absolute.  None
    comes back when the curves are degenerate in either axis.
    """
    us = []
    zs = []
    for curve in curves:
        try:
            points = list(curve.Tessellate())
        except Exception:
            try:
                points = [curve.GetEndPoint(0), curve.GetEndPoint(1)]
            except Exception:
                continue
        for p in points:
            us.append((p.X - ref.X) * direction.X + (p.Y - ref.Y) * direction.Y)
            zs.append(p.Z)

    if not us or not zs:
        return None
    u_lo, u_hi = min(us), max(us)
    z_lo, z_hi = min(zs), max(zs)
    if (u_hi - u_lo) < MIN_EXTENT or (z_hi - z_lo) < MIN_EXTENT:
        return None
    return u_lo, u_hi, z_lo, z_hi


# ===============================================================================
# MAIN
# ===============================================================================

def report(rows):
    """Print the problems table, or nothing when there were none.

    Only genuine shortfalls reach here - a window skipped, a profile that
    could not be applied, a BG_ parameter left blank.  A fallback that
    worked is logged instead, so a run that produced the right walls says
    nothing at all.
    """
    if not rows:
        return
    output.print_md("### Window To Curtain Wall - {} note(s)".format(len(rows)))
    output.print_table(
        table_data=rows,
        columns=["Window Id", "Link", "Type Mark", "Note"])


def report_measurements(plans):
    """Print what was actually measured, so wrong numbers are visible."""
    if not VERBOSE or not plans:
        return
    rows = []
    for plan in plans:
        rows.append([
            plan.window_id,
            plan.source_kind,
            plan.mark or "-",
            feet_text(plan.width),
            feet_text(plan.height),
            feet_text(plan.sill),
            feet_text(plan.sill_param) if plan.sill_param is not None else "-",
            feet_text(plan.geom_bottom) if plan.geom_bottom is not None else "-",
            "{} + {}".format(plan.level_name, feet_text(plan.base_offset)),
            len(plan.profile_curves) if plan.profile_curves else 0,
            " + ".join(str(n) for n in plan.grid_removed) or "0",
            plan.new_wall_id if plan.new_wall_id is not None else "-",
        ])
    output.print_md("### Window To Curtain Wall - measurements")
    output.print_table(
        table_data=rows,
        columns=["Source Id", "Kind", "Type Mark", "Width", "Height",
                 "Base elev", "Sill param", "Geom bottom",
                 "Level + offset", "Profile curves",
                 "Grid removed", "New wall Id"])


def frame_at(origin, direction):
    """A right-handed transform whose X runs along *direction* and Y is up."""
    x = direction.Normalize()
    y = XYZ.BasisZ
    t = Transform.Identity
    t.Origin = origin
    t.BasisX = x
    t.BasisY = y
    t.BasisZ = x.CrossProduct(y)
    return t


def move_profile(curves, src_origin, src_dir, dst_origin, dst_dir):
    """Carry sketched profile *curves* from the source wall onto the new one.

    Both frames are orthonormal and share an up axis, so the map between
    them is a rigid motion: lines stay lines and arcs stay arcs.  The
    source direction is flipped when the two walls run opposite ways,
    which keeps the profile the right way round instead of mirrored.
    """
    if src_dir.DotProduct(dst_dir) < 0:
        dst_dir = dst_dir.Negate()
    mapping = frame_at(dst_origin, dst_dir).Multiply(
        frame_at(src_origin, src_dir).Inverse)
    return [c.CreateTransformed(mapping) for c in curves]


def resolve_profile(plan, wall):
    """Reshape *wall* to the profile sketched on its source, if any.

    Only a linked curtain wall carries one.  A window always produces a
    plain rectangle: its head shape can only be recovered by tracing
    tessellated solids, and that trace is not reliable enough to put in
    the model - an arched window gets a rectangle tall enough to cover
    the arch instead.
    """
    if plan.profile_curves:
        try:
            curve = wall.Location.Curve
            if not isinstance(curve, Line):
                plan.notes.append(
                    "curved host wall; sketched profile not copied")
                return
            mid = curve.Evaluate(0.5, True)
            dst_origin = XYZ(mid.X, mid.Y, plan.sill)
            moved = move_profile(plan.profile_curves,
                                 plan.src_origin, plan.src_dir,
                                 dst_origin, plan.wall_dir)
        except Exception as ex:
            plan.notes.append("profile could not be carried over ({})"
                              .format(ex))
            return
        failure = wall_sketch.apply_profile(
            doc, wall, moved,
            "Create wall profile sketch",
            "Reshape curtain wall to the window")
        if failure:
            plan.notes.append(failure)


def main():
    picks = pick_pairs()
    if not picks:
        return          # nothing picked is a cancellation; stay silent

    rows   = []
    levels = host_levels()

    # ---- Measure everything first, so geometry reads and type prompts all
    # ---- stay outside the transaction.
    plans = []
    for link_inst, window, host_wall in picks:
        try:
            plan, reason = measure_source(link_inst, window, host_wall)
        except Exception as ex:
            plan, reason = None, "measurement failed: {}".format(ex)
        if plan is None:
            rows.append([eid_value(window.Id), get_element_name(link_inst),
                         "-", reason])
            continue
        for piece in split_at_levels(plan, levels):
            plans.append((piece, host_wall))

    if not plans:
        report(rows)
        return

    types = window_cw.curtain_wall_types(doc)
    if not types:
        report(rows + [[p.window_id, p.link_name, p.mark or "-",
                        "no curtain wall types in the host model"]
                       for p, _w in plans])
        return

    # ---- Resolve the curtain wall type once per Type Mark prefix.
    chosen = {}
    ready  = []
    for plan, host_wall in plans:
        from_curtain = plan.source_kind == "curtain wall"
        key = CURTAIN_TYPE_NAME if from_curtain else (plan.prefix or "<none>")

        if key not in chosen:
            if from_curtain:
                # Settled by name, not by prefix.  Only when the named
                # type is missing from this model is there anything to
                # ask about.
                wall_type = window_cw.type_named(CURTAIN_TYPE_NAME, types)
                if wall_type is None:
                    wall_type = window_cw.prompt_curtain_type(
                        types, CURTAIN_TYPE_NAME, CURTAIN_TYPE_NAME)
            else:
                wall_type = window_cw.match_curtain_type(plan, types)
                if wall_type is None:
                    wall_type = window_cw.prompt_curtain_type(
                        types, plan.mark, plan.prefix)
                    if wall_type is not None:
                        logger.debug("Type picked by hand for prefix {}"
                                     .format(plan.prefix))
            chosen[key] = wall_type

        wall_type = chosen[key]
        if wall_type is None:
            rows.append([plan.window_id, plan.link_name, plan.mark or "-",
                         "'{}' is not in this model and none was picked; "
                         "skipped".format(CURTAIN_TYPE_NAME)
                         if from_curtain else
                         "no curtain wall type for prefix '{}'; skipped"
                         .format(plan.prefix or "?")])
            continue
        ready.append((plan, host_wall, wall_type))

    if not ready:
        report(rows)
        return

    # ---- Create every wall in one transaction.  Arched heads are re-sketched
    # ---- afterwards: SketchEditScope cannot run inside a transaction.
    made = []

    t = Transaction(doc, "Create curtain walls from linked windows")
    t.Start()
    try:
        # Clearing the grid raises the same mullion errors the profile edit
        # does, so this transaction answers them the same way.
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(wall_sketch.SketchFailureSwallower())
        opts.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(opts)
    except Exception as ex:
        logger.debug("Could not set failure handling: {}".format(ex))

    try:
        for plan, host_wall, wall_type in ready:
            try:
                wall, reason = window_cw.create_curtain_wall(
                    doc, plan, host_wall, wall_type)
            except Exception as ex:
                wall, reason = None, "wall creation failed: {}".format(ex)

            if wall is None:
                rows.append([plan.window_id, plan.link_name,
                             plan.mark or "-", reason])
                continue
            if reason:
                plan.notes.append(reason)
            plan.new_wall_id = eid_value(wall.Id)
            made.append((plan, wall))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    for plan, wall in made:
        resolve_profile(plan, wall)

    if made:
        # Revit rebuilds the grid from the type's layout when a wall is
        # reshaped, so the panels have to be cleared again afterwards.
        cleanup = Transaction(doc, "Remove curtain grid")
        cleanup.Start()
        try:
            opts = cleanup.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(wall_sketch.SketchFailureSwallower())
            cleanup.SetFailureHandlingOptions(opts)
        except Exception as ex:
            logger.debug("Could not set failure handling: {}".format(ex))
        try:
            for plan, wall in made:
                plan.grid_removed.append(
                    window_cw.strip_curtain_grid(doc, wall))
            cleanup.Commit()
        except Exception:
            if cleanup.HasStarted() and not cleanup.HasEnded():
                cleanup.RollBack()
            raise

    for plan, wall in made:
        if plan.notes:
            rows.append([plan.window_id, plan.link_name, plan.mark or "-",
                         "; ".join(plan.notes)])

    # Silence on a clean run: only notes are worth opening the output for.
    report_measurements([p for p, _w in made])
    report(rows)


main()
