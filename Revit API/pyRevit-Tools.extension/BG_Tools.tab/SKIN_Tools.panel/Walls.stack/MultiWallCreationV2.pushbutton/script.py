# -*- coding: utf-8 -*-
"""Create host-model skin walls and sweep walls from one linked selection.

V2 also puts the openings back: every window in a picked wall becomes a
curtain wall on the new skin wall, and every rectangular opening is cut
out of the skin's elevation.  V1 is left alone -- it is a separate
button, and this one is where the openings work is being proved.

Select any mix of walls, wall sweeps and roof soffits in a LINKED model
-- by box or by click, adding and removing until the selection is right,
then Finish.

Each CAST STONE sweep becomes a wall in the host model, exactly as
Sweep To Wall makes one.
Each wall becomes one or more skin walls, exactly as Split Walls makes
them -- except that nobody picks a base and a top.

A wall's height comes from the CAST STONE sweeps running on it:

  * its top is the bottom of the stone course above it,
  * its base is the top of the stone course below it,
  * one part-way up cuts it in two, and every level it crosses cuts it
    again, so no new wall crosses either,
  * with no stone course above or below, that end falls back to the
    source wall's own Base and Top Constraint.

An EIFS sweep is ignored outright.  Picking one costs nothing and does
nothing: no wall is built for it, and it does not break the walls it
runs across.  Only cast stone becomes a sweep wall, and only cast stone
cuts a skin.

Only sweeps you actually pick cut a wall, and only sweeps hosted on that
wall -- the link's own GetHostIds() decides, so a sweep running along a
neighbouring wall never shortens this one.

Nothing is rounded.  A band end has to sit exactly on a sweep face or
a level, or a gap opens up in the elevation.  The one thing that does
move is an end within an inch of a level, which is pulled onto it --
once, on the measured extents, before anything is banded, so the sweep
and the walls above and below it all move together and stay met.

Sweep wall types are automatic: a sweep whose type name or material name
says STONE gets SKIN_CAST STONE PROFILE_0' 2", and one that says EIFS is
dropped.  Anything the rule cannot read is asked about once, per sweep
type -- and dropped too if the answer is the EIFS profile.  Wall skins
resolve their type from the finish material's Mark, as Split Walls does.

Where a sweep goes in plan is read off its own solid, not assumed to be
its host wall's full length.  A sweep that stops at an opening stops
there; one interrupted part-way along becomes two walls; and one that
steps down is built, and cuts, at the height it truly runs at on each
stretch.  Sweep walls at the same height and of the same type mitre into
each other at corners, whether or not they came from the same sweep, so
they trim instead of crossing.

Only the SWEEPS break at openings, and only at a DOOR or a CURTAIN WALL.
A band course runs on under a window sill.  A skin wall runs the whole
length of the wall it came from, openings and all -- cutting it at them
was tried and taken back out.  Neither turns into a reveal: a sweep that
stops at an opening is left ending at the jamb.

A picked ROOF SOFFIT is never built.  It is a limit and nothing else:
every wall in the run stops at its underside, exactly as they stop at a
stone course.  WHERE it sits in plan is not asked -- picking it is the
statement that it governs this run -- and a wall stops at its LOWEST
point, so nothing pokes through whatever the soffit turns out to be
doing.

A wall ALREADY STANDING where one would be built is left alone, and
nothing is built on top of it.  The test is per wall, not per source:
one sweep becomes a run of walls, and only the ones standing where a
wall already stands are dropped -- the rest of that sweep is built as
though nothing had happened.  Same type, same two ends, same base and
top: all four, or it is a different wall.  Windows and openings still
go onto the wall that was already there.

The linked model is never modified.
"""

__title__  = "Multi\nWalls"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Select any mix of walls, wall sweeps and roof soffits in a LINKED "
    "model -- drag a box or click, then click Finish.\n"
    "Each CAST STONE sweep becomes a wall in the host model; each wall "
    "becomes skin walls that stop at the stone sweeps running on it.  "
    "EIFS sweeps are ignored, picked or not.\n"
    "Walls are cut again at every level they cross.  A wall with no "
    "stone course above or below falls back to its own constraints.\n"
    "Sweep wall types come from STONE / EIFS in the sweep's type or "
    "material name; EIFS is dropped, and you are only asked about what "
    "that rule cannot read.\n"
    "A picked roof soffit is never built: every wall in the run just "
    "stops at its lowest point.\n"
    "A wall already standing where one would go is left alone -- per "
    "wall, so the rest of a sweep's run is still built.\n"
    "The linked model is left untouched."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    Arc,
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    JoinGeometryUtils,
    Level,
    Line,
    Opening,
    RevitLinkInstance,
    Transaction,
    Wall,
    WallKind,
    WallSweep,
    WallSweepType,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

from BG import (
    soffit as soffit_lib,
    wall_bands,
    wall_chain,
    wall_constraints,
    wall_exists,
    wall_materials,
    wall_miter,
    wall_naming,
    wall_skin,
    wall_sketch,
    window_cw,
)

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

# Shorter than this, in feet, and there is no wall worth making (~16 mm).
MIN_RUN_LENGTH = 0.05

# WallLocationLine values.  Every wall this tool makes is left
# referenced to its exterior finish face, whichever way it was built:
# setting Location Line re-references a wall without moving it, so this
# is a change of what the wall measures from, not of where it sits.
LOC_LINE_CENTRELINE           = 0
LOC_LINE_FINISH_FACE_EXTERIOR = 2

# The sweep type's Type Mark is carried onto each sweep wall here, and
# the name of each new wall's Base Constraint level goes here.
BG_PROFILE_PARAM = "BG_PROFILE"
BG_LEVEL_PARAM   = "BG_LEVEL"

# A break in a sweep shorter than this, in feet, is not a break: abutting
# sweep solids leave hairline seams and a mitred corner leaves a notch.
# Anything longer is an opening the sweep genuinely stops at.  One inch.
SWEEP_GAP_TOL = 1.0 / 12.0

# An opening whose bottom comes within this of the wall's base is not a
# hole in the wall -- it is a notch out of its base, and it is cut as
# one, so the profile runs straight through instead of leaving a
# hairline of wall under the opening.  One inch.
OPENING_BASE_MERGE_TOL = 1.0 / 12.0

TOOL_TITLE = "Multi Wall Creation V2"


# ===========================================================================
# HELPERS
# ===========================================================================

def get_element_name(element):
    """Safely get the Name of any Revit element.

    Element.Name is not dependable from IronPython, so this falls back
    to the Type Name parameter the way the other wall tools do.
    """
    if element is None:
        return "<null>"
    try:
        return element.Name
    except Exception:
        pass
    try:
        p = element.LookupParameter("Type Name")
        if p:
            return p.AsString()
    except Exception:
        pass
    return "<unknown>"


def find_parameter(elem, name):
    """Return *elem*'s parameter called *name*, ignoring case, or None.

    LookupParameter is case-sensitive, which is a poor match for
    parameter names written one way in a shared parameter file and
    another in the model -- BG_PROFILE against BG_Profile, say.
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


def note(notes, element_label, text):
    """Record one thing that went wrong, for the report at the end."""
    notes.append([element_label, text])


def feet_text(value):
    """A short, readable elevation for the report."""
    return "{0:.4f}".format(value)


def project_base_elevation(target_doc):
    """Return the offset between level elevations and model geometry.

    Levels report their elevation relative to the Project Base Point
    while solid geometry comes back in internal model coordinates.  When
    the base point sits at elevation 0 the two coincide and this returns
    0.0, so the conversion is harmless in ordinary projects.
    """
    try:
        col = FilteredElementCollector(target_doc) \
            .OfCategory(BuiltInCategory.OST_ProjectBasePoint) \
            .WhereElementIsNotElementType()
        for bp in col:
            p = bp.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)
            if p and p.HasValue:
                return p.AsDouble()
    except Exception as ex:
        logger.debug("Could not read project base elevation: {}".format(ex))
    return 0.0


def host_levels():
    """Return [(ElementId, elevation)] for every host Level.

    Elevations are converted into geometry space so they can be compared
    with sweep envelopes and wall spans directly.
    """
    delta = project_base_elevation(doc)
    return [(lvl.Id, lvl.Elevation - delta)
            for lvl in FilteredElementCollector(doc).OfClass(Level)]


# ===========================================================================
# SELECTION
# ===========================================================================

def sweep_is_convertible(sweep):
    """Return (ok, reason).  Reveals and vertical sweeps are not.

    A reveal is a void cut into the wall, so turning one into a solid
    wall would model the opposite of what is there.
    """
    try:
        info = sweep.GetWallSweepInfo()
    except Exception:
        return True, None          # cannot tell; let the geometry decide

    if info is None:
        return True, None
    try:
        if info.WallSweepType == WallSweepType.Reveal:
            return False, "reveal (a void, not a sweep)"
    except Exception:
        pass
    try:
        if info.IsVertical:
            return False, "vertical sweep"
    except Exception:
        pass
    return True, None


class LinkedSourceFilter(ISelectionFilter):
    """Allow Basic Walls, horizontal wall sweeps and roof soffits.

    For linked elements Revit calls AllowElement() on the
    RevitLinkInstance and AllowReference() on each candidate reference
    within it, so the real test has to live in AllowReference.
    """

    def AllowElement(self, elem):
        return isinstance(elem, RevitLinkInstance)

    def AllowReference(self, ref, point):
        try:
            link_inst = doc.GetElement(ref.ElementId)
            if not isinstance(link_inst, RevitLinkInstance):
                return False
            link_doc = link_inst.GetLinkDocument()
            if link_doc is None:
                return False
            elem = link_doc.GetElement(ref.LinkedElementId)

            if isinstance(elem, WallSweep):
                return sweep_is_convertible(elem)[0]
            if isinstance(elem, Wall):
                return elem.WallType.Kind == WallKind.Basic
            return soffit_lib.is_soffit(elem)
        except Exception:
            return False


def pick_sources():
    """Select walls, sweeps and roof soffits in links, then Finish.

    PickObjects rather than a loop of PickObject: it is what gives the
    selection Revit's own behaviour -- a rubber-band box as well as
    clicks, the picked elements highlighted for as long as the selection
    is open, Ctrl-click to add and Shift-click to remove, and a Finish
    button to run with what is selected.  Cancel or Esc abandons the run
    instead of proceeding, so nothing is created by accident.

    Whether a drag catches LINKED elements is Revit's own call, not
    ours: the "Select links" toggle at the bottom right of the Revit
    window must be on, or a box ignores link geometry.  Clicking works
    either way.

    The filter runs during the drag, so a box can only ever pick up
    things this tool can use -- reveals, vertical sweeps and non-Basic
    walls are never added in the first place.

    Returns (wall_picks, sweep_picks, soffit_picks), each a list of
    (RevitLinkInstance, element).  PickObjects de-duplicates its own
    result, so no list can hold the same element twice.
    """
    empty = ([], [], [])
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement, LinkedSourceFilter(),
            "Select walls, wall sweeps and roof soffits in a linked "
            "model, then click Finish")
    except OperationCanceledException:
        return empty
    except Exception as ex:
        logger.debug("Selection ended: {}".format(ex))
        return empty

    if not refs:
        return empty

    walls   = []
    sweeps  = []
    soffits = []
    for ref in refs:
        link_inst = doc.GetElement(ref.ElementId)
        link_doc  = link_inst.GetLinkDocument()
        if link_doc is None:
            continue
        elem = link_doc.GetElement(ref.LinkedElementId)

        if isinstance(elem, WallSweep):
            sweeps.append((link_inst, elem))
        elif isinstance(elem, Wall):
            walls.append((link_inst, elem))
        elif soffit_lib.is_soffit(elem):
            soffits.append((link_inst, elem))

    return walls, sweeps, soffits


# ===========================================================================
# SWEEPS
# ===========================================================================

class SweepRun(object):
    """One continuous stretch of a sweep along one of its host walls.

    A sweep is not one wall's worth of anything.  It runs along several
    walls, it stops at the openings in them, and it can sit at a
    different height on each -- so the unit that becomes a wall is a
    RUN: one uninterrupted stretch, on one host wall, at one height.

    *along_min* and *along_max* are measured from the host run frame's
    origin along its direction.  *wall_keys* is the set of (link
    instance id, wall id) pairs the run lies on -- a set, because a run
    can span several walls the link drew separately -- so band_walls can
    tell which walls this run cuts.
    """

    __slots__ = ("frame", "offset", "along_min", "along_max",
                 "base_z", "top_z", "wall_keys", "reach")


class SweepJob(object):
    """One sweep, measured and ready to build once its type is known."""

    __slots__ = ("label", "sweep", "runs", "material", "type_mark",
                 "type_name", "wall_type")


def merge_key(wall, frame):
    """What two walls must agree on before being treated as one.

    The wall type settles the finish material, the thickness and the
    whole layer build-up in a single test.  The facing direction is in
    here too: two colinear walls of one type can still be drawn in
    opposite directions, and merging those would put the new wall's
    finish face on the wrong side of one of them.
    """
    try:
        type_id = wall.WallType.Id.IntegerValue
    except Exception:
        type_id = None
    return (type_id,
            round(frame.normal.X, 4),
            round(frame.normal.Y, 4))


def merged_frame(frames, merged_ends):
    """A WallFrame spanning *merged_ends*, borrowing from *frames*[0].

    Members are colinear, one type and one facing, so the normal and the
    width are the same for all of them; only the extent is new.  The
    elevation comes from the first member's curve, which is where every
    member's does -- they are one wall.
    """
    z = frames[0].curve.GetEndPoint(0).Z
    (x0, y0), (x1, y1) = merged_ends
    curve = Line.CreateBound(XYZ(x0, y0, z), XYZ(x1, y1, z))
    return wall_chain.WallFrame(
        frames[0].wall, curve, frames[0].normal, frames[0].width)


class HostRun(object):
    """One straight run of host wall, however many walls drew it."""

    __slots__ = ("frame", "wall_keys", "walls", "openings")


def host_runs(link_inst, walls, transform, notes):
    """Turn a sweep's host walls into the straight runs they really are.

    A link routinely holds one physical wall as two or three end to end.
    Left separate they break the sweep measured against them: its solid
    is shared out between host walls by proximity, and a piece short
    enough that every nearby edge is closer to its neighbours gets no
    share at all -- so the sweep vanishes over that stretch.  Chaining
    the colinear ones back together is what stops that.
    """
    frames = []
    keys   = []
    hosts  = []
    for host in walls:
        host_label = "{} (id {})".format(get_element_name(host.WallType),
                                         host.Id.IntegerValue)

        frame = wall_chain.wall_frame(host, transform)
        if frame is None:
            note(notes, host_label, "wall has no location curve")
            continue
        if not frame.is_line:
            note(notes, host_label, "curved wall - not supported")
            continue
        if frame.length < MIN_RUN_LENGTH:
            note(notes, host_label, "wall too short")
            continue

        frames.append(frame)
        keys.append(merge_key(host, frame))
        hosts.append(host)

    if not frames:
        return []

    segments = []
    for frame in frames:
        p0 = frame.curve.GetEndPoint(0)
        p1 = frame.curve.GetEndPoint(1)
        segments.append(((p0.X, p0.Y), (p1.X, p1.Y)))

    runs = []
    for members, ends in wall_bands.colinear_chains(segments, keys):
        frame = merged_frame([frames[i] for i in members], ends)

        run = HostRun()
        run.frame = frame
        run.walls = [hosts[i] for i in members]
        # Keyed on (link instance id, linked element id), not the bare
        # element id: pick_sources() explicitly anticipates a selection
        # spanning two links (or two instances of the same link), and a
        # bare element id can collide across them.  A SET because one
        # run can be several walls; band_walls intersects it against a
        # wall job's own set.
        run.wall_keys = set(
            (link_inst.Id.IntegerValue, w.Id.IntegerValue)
            for w in run.walls)
        # Measured against the MERGED frame: openings are recorded as
        # distances along it, so one measured against a member's own
        # frame would be in the wrong place along this one.
        run.openings = openings_along(
            run.walls, transform, frame.origin, frame.direction,
            run.wall_keys)
        runs.append(run)

    return runs


def sweep_host_walls(sweep):
    """Return the walls *sweep* is hosted on, from the sweep's own doc."""
    try:
        ids = list(sweep.GetHostIds())
    except Exception:
        return []

    link_doc = sweep.Document
    walls    = []
    for wid in ids:
        elem = link_doc.GetElement(wid)
        if isinstance(elem, Wall):
            walls.append(elem)
    return walls


def _sweep_edge_spans(sweep, transform, frames):
    """Split a sweep's solid between its host walls.

    Returns (per_frame, reach, material_name).  *per_frame* is a list
    per frame of (along_lo, along_hi, z_lo, z_hi) tuples, one per edge
    of the sweep's solid.  *reach* is a list per frame of how far the
    sweep's furthest point stands off that wall's location curve, which
    is the scale its mitres are set back by at an inside corner.

    Each edge is assigned to the host wall it is nearest to, judged on
    its midpoint in plan.  That is what lets a sweep's real extent be
    read off its own geometry instead of being assumed to be its host
    wall's full length -- the assumption behind every sweep that ran
    straight past an opening or crossed another at a corner.
    """
    segments = []
    for frame in frames:
        p0 = frame.curve.GetEndPoint(0)
        p1 = frame.curve.GetEndPoint(1)
        segments.append(((p0.X, p0.Y), (p1.X, p1.Y)))

    per_frame = [[] for _f in frames]
    reach     = [0.0 for _f in frames]
    areas = {}

    for sol in wall_chain.iter_solids(sweep):
        for edge in sol.Edges:
            try:
                pts = [transform.OfPoint(pt) for pt in edge.Tessellate()]
            except Exception:
                continue
            if not pts:
                continue

            # The CENTROID, not pts[len(pts) // 2].  Edge.Tessellate()
            # returns just two points for a straight edge -- and almost
            # every edge of a sweep solid is straight -- so indexing the
            # middle picks the edge's END.  At a corner both host walls
            # are equidistant from that end, the tie hands the edge to
            # whichever wall came first, and one wall then swallows the
            # other's geometry while the other gets no run at all.
            cx = sum(pt.X for pt in pts) / len(pts)
            cy = sum(pt.Y for pt in pts) / len(pts)
            idx = wall_bands.nearest_segment_index((cx, cy), segments)
            if idx is None:
                continue

            frame = frames[idx]
            alongs = []
            zs     = []
            for pt in pts:
                delta = XYZ(pt.X - frame.origin.X,
                            pt.Y - frame.origin.Y,
                            pt.Z - frame.origin.Z)
                alongs.append(delta.DotProduct(frame.direction))
                zs.append(pt.Z)
                sideways = delta.DotProduct(frame.normal)
                if sideways > reach[idx]:
                    reach[idx] = sideways

            per_frame[idx].append((min(alongs), max(alongs),
                                   min(zs), max(zs)))

        for face in sol.Faces:
            try:
                mid_id = face.MaterialElementId
                if mid_id is None or mid_id == ElementId.InvalidElementId:
                    continue
                key = mid_id.IntegerValue
                areas[key] = areas.get(key, 0.0) + face.Area
            except Exception:
                continue

    material_name = None
    if areas:
        best = max(areas.keys(), key=lambda k: areas[k])
        material_name = get_element_name(
            sweep.Document.GetElement(ElementId(best)))

    return per_frame, reach, material_name


def sweep_runs(sweep, transform, host):
    """Return (runs, material_name) for one sweep.

    The sweep's solid is split between its host walls, each wall's share
    is unioned along that wall's axis, and every stretch that survives
    becomes a SweepRun.  Gaps shorter than SWEEP_GAP_TOL are bridged --
    abutting sweep solids leave seams and a mitred corner leaves a
    notch, and neither is a break.  Anything longer is an opening the
    sweep genuinely stops at.

    Each run's height is measured from the edges inside that run alone,
    so a sweep that steps down partway along a building is built, and
    cuts, at the height it actually runs at on each stretch.

    Each run is then cut by *openings* -- the same insert extents the
    skin walls are cut by, one list per frame.  The sweep's own geometry
    is not enough on its own: a sweep that mitres round into an opening
    reveal reaches, at its outer face, the better part of its own
    projection PAST the jamb, so a run measured from the solid alone
    stands proud of the wall behind it.  Cutting both with the same
    intervals is what makes the sweep wall stop on the same line as the
    skin wall under it.
    """
    frames = [h.frame for h in host]
    per_frame, reach, material_name = _sweep_edge_spans(
        sweep, transform, frames)

    runs = []
    for idx, frame in enumerate(frames):
        spans = per_frame[idx]
        if not spans:
            continue

        # Once per wall, not once per run: it tessellates the whole host
        # wall solid.
        exterior_offset = wall_chain.wall_exterior_offset(frame, transform)

        intervals = [(lo, hi) for lo, hi, _z0, _z1 in spans]
        for along_min, along_max in wall_bands.merge_intervals(
                intervals, SWEEP_GAP_TOL):
            if along_max - along_min < MIN_RUN_LENGTH:
                continue

            # Height from the edges inside THIS stretch only.
            z_lo = z_hi = None
            for lo, hi, e_z0, e_z1 in spans:
                if hi < along_min or lo > along_max:
                    continue
                if z_lo is None or e_z0 < z_lo:
                    z_lo = e_z0
                if z_hi is None or e_z1 > z_hi:
                    z_hi = e_z1
            if z_lo is None or (z_hi - z_lo) < MIN_RUN_LENGTH:
                continue

            # Snap a run end that all but reaches the wall end onto it,
            # so mitre_chain sees the two runs as adjacent.  Clamping
            # alone only covers an OUTSIDE corner, where the sweep wraps
            # round and overshoots the wall end.  Two cases fall short
            # instead, and both must be caught or the corner is left
            # open:
            #
            #   * a sweep that RETURNS into an outside corner rather
            #     than wrapping it stops at the neighbour's face, up to
            #     a wall thickness short;
            #   * at an INSIDE corner the two sweeps' offset faces
            #     converge, so Revit mitres the solids BACK from the
            #     corner by about the distance they stand off the wall
            #     -- which is why inside turns were the ones left
            #     crossing while outside turns came out right.
            #
            # Each case has its own scale, and the snap allows the
            # larger: a wall thickness for the return, and the sweep's
            # measured reach past the location curve for the inside
            # mitre.  Measured, not guessed at from the wall -- a deep
            # cornice is set back much further than a shallow band, and
            # a fixed allowance would either miss the one or over-reach
            # for the other.  The snap runs BEFORE the openings are
            # subtracted, so an opening genuinely sitting within that
            # distance of the corner still cuts the run back.
            snap = max(frame.width, reach[idx])
            if along_min < snap:
                along_min = 0.0
            if along_max > frame.length - snap:
                along_max = frame.length

            along_min = max(along_min, 0.0)
            along_max = min(along_max, frame.length)

            # Cut by the openings this stretch actually passes through,
            # by height, so an opening well above or below the sweep
            # leaves it alone.
            cutters = [(o_lo, o_hi)
                       for o_lo, o_hi, o_z_lo, o_z_hi in host[idx].openings
                       if o_z_hi > z_lo + wall_bands.TOL
                       and o_z_lo < z_hi - wall_bands.TOL]

            pieces, _dropped = wall_bands.subtract_spans(
                (along_min, along_max), cutters, MIN_RUN_LENGTH)

            for piece_min, piece_max in pieces:
                run = SweepRun()
                run.frame     = frame
                run.offset    = exterior_offset
                run.along_min = piece_min
                run.along_max = piece_max
                run.base_z    = z_lo
                run.top_z     = z_hi
                run.wall_keys = host[idx].wall_keys
                # How far the sweep's solid stands off the wall's
                # location curve.  Carried because it is also the scale
                # a corner sets this run back by -- see the mitring in
                # build_sweep_walls.
                run.reach     = reach[idx]
                runs.append(run)

    return runs, material_name


def sweep_type_mark(sweep):
    """Return the Type Mark of the sweep's type, or None when blank."""
    try:
        sweep_type = sweep.Document.GetElement(sweep.GetTypeId())
    except Exception:
        return None
    if sweep_type is None:
        return None

    getters = (
        lambda e: e.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_MARK),
        lambda e: find_parameter(e, "Type Mark"),
    )
    for getter in getters:
        try:
            p = getter(sweep_type)
        except Exception:
            continue
        if p is None:
            continue
        try:
            if not p.HasValue:
                continue
            value = p.AsString()
        except Exception:
            continue
        if value and value.strip():
            return value.strip()
    return None


def sweep_type_name(sweep):
    """Return the name of *sweep*'s type, for the STONE/EIFS rule."""
    try:
        return get_element_name(sweep.Document.GetElement(sweep.GetTypeId()))
    except Exception:
        return None


def plan_sweep(link_inst, sweep):
    """Measure one sweep.  Returns (SweepJob or None, notes)."""
    notes     = []
    transform = link_inst.GetTotalTransform()
    label     = "sweep id {}".format(sweep.Id.IntegerValue)

    ok, reason = sweep_is_convertible(sweep)
    if not ok:
        return None, [[label, reason]]

    walls = sweep_host_walls(sweep)
    if not walls:
        return None, [[label, "sweep is not hosted on any wall"]]

    host = host_runs(link_inst, walls, transform, notes)
    if not host:
        return None, notes

    runs, material_name = sweep_runs(sweep, transform, host)
    if not runs:
        return None, notes + [[label,
                               "no usable sweep geometry (check the "
                               "link's view detail level)"]]

    job = SweepJob()
    job.label     = label
    job.sweep     = sweep
    job.runs      = runs
    job.material  = material_name
    job.type_mark = sweep_type_mark(sweep)
    job.type_name = sweep_type_name(sweep)
    job.wall_type = None          # filled in by resolve_sweep_types
    return job, notes


# ===========================================================================
# SOFFITS
# ===========================================================================

class SoffitJob(object):
    """One linked roof soffit, measured.  Never built, only obeyed."""

    __slots__ = ("label", "shape")


def plan_soffit(link_inst, soffit):
    """Measure one soffit.  Returns (SoffitJob or None, notes)."""
    label = "soffit id {}".format(soffit.Id.IntegerValue)

    shape, reasons = soffit_lib.measure(
        soffit, link_inst.GetTotalTransform())
    notes = [[label, reason] for reason in reasons]

    if shape is None:
        return None, notes

    job = SoffitJob()
    job.label = label
    job.shape = shape
    return job, notes


def soffit_cutters(soffit_jobs):
    """The (base_z, top_z) spans the picked soffits impose.

    Every picked soffit, on every wall in the run.  Whether one happens
    to overhang a given wall in plan is not asked: picking it IS the
    statement that it governs this run, and a plan test could only
    disagree with what was asked for.
    """
    return [(job.shape.base_z, job.shape.top_z) for job in soffit_jobs]


# ===========================================================================
# WALLS
# ===========================================================================

class WallJob(object):
    """One linked wall, measured and ready to band."""

    __slots__ = ("label", "wall_keys", "type_id", "cs", "source_doc",
                 "loc_curve", "orientation", "total_width", "loc_line",
                 "loc_to_ext", "base_z", "top_z", "structural", "bands",
                 "windows", "rect_openings", "link_inst", "direction",
                 "built_bands", "curved")


def _length_param(elements, names, builtin_names):
    """First length found on *elements*, in feet, or None.

    Built-in parameters first, fetched by name so one missing from this
    Revit version cannot raise, then plain lookups.  The same order
    WindowToCurtainWall reads a window's size in.
    """
    for elem in elements:
        if elem is None:
            continue
        for bip_name in builtin_names:
            bip = getattr(BuiltInParameter, bip_name, None)
            if bip is None:
                continue
            try:
                param = elem.get_Parameter(bip)
            except Exception:
                continue
            if param is not None and param.HasValue:
                try:
                    value = param.AsDouble()
                except Exception:
                    continue
                if value > MIN_RUN_LENGTH:
                    return value

    for elem in elements:
        if elem is None:
            continue
        for name in names:
            try:
                param = elem.LookupParameter(name)
            except Exception:
                continue
            if param is not None and param.HasValue:
                try:
                    value = param.AsDouble()
                except Exception:
                    continue
                if value > MIN_RUN_LENGTH:
                    return value
    return None


def _insert_solid_extent(insert, link_tf, origin, direction):
    """(along_lo, along_hi, z_lo, z_hi) from the insert's solid, or None.

    Falls back to the bounding box when there is no readable solid.
    """
    alongs = []
    zs     = []

    def take(pt):
        world = link_tf.OfPoint(pt)
        delta = XYZ(world.X - origin.X,
                    world.Y - origin.Y,
                    world.Z - origin.Z)
        alongs.append(delta.DotProduct(direction))
        zs.append(world.Z)

    try:
        for sol in wall_chain.iter_solids(insert):
            for edge in sol.Edges:
                try:
                    for pt in edge.Tessellate():
                        take(pt)
                except Exception:
                    continue
    except Exception as ex:
        logger.debug("Could not read insert geometry: {}".format(ex))

    if not alongs:
        try:
            bbox = insert.get_BoundingBox(None)
        except Exception:
            return None
        if bbox is None:
            return None
        for x in (bbox.Min.X, bbox.Max.X):
            for y in (bbox.Min.Y, bbox.Max.Y):
                for z in (bbox.Min.Z, bbox.Max.Z):
                    take(XYZ(x, y, z))

    if not alongs:
        return None
    return min(alongs), max(alongs), min(zs), max(zs)


def _insert_extent(insert, link_tf, origin, direction):
    """Return (along_lo, along_hi, z_lo, z_hi) for one insert, or None.

    The ALONG extent is the rough opening -- the void actually cut in
    the wall -- taken from the insert's Rough Width, or its Width where
    there is no rough dimension, centred on its location point.  It is
    emphatically NOT the width of the insert's solid: a window family
    carries exterior trim and casing that lap onto the wall either side
    of the opening, and cutting the skin and sweep walls back to that
    ate into the pier between two openings and left both standing
    narrower than the wall behind them.

    The HEIGHT range still comes from the solid.  Vertically the solid
    errs the right way -- an arched head, a projecting sill or a deep
    surround all mean the opening genuinely interrupts more of the
    elevation than a bare rough height would say -- and this range is
    only ever used to ask whether an opening reaches a given course.

    Falls back to the solid for the along extent too when the insert
    carries no width parameter, which is the case for a plain
    rectangular opening.
    """
    solid = _insert_solid_extent(insert, link_tf, origin, direction)
    if solid is None:
        return None

    try:
        symbol = insert.Document.GetElement(insert.GetTypeId())
    except Exception:
        symbol = None

    width = _length_param(
        [insert, symbol],
        ["Rough Width", "Width"],
        ["FAMILY_ROUGH_WIDTH_PARAM", "WINDOW_WIDTH", "DOOR_WIDTH",
         "FAMILY_WIDTH_PARAM", "GENERIC_WIDTH"])
    if width is None:
        return solid

    centre = None
    try:
        loc = insert.Location
        if loc is not None and hasattr(loc, "Point"):
            world = link_tf.OfPoint(loc.Point)
            delta = XYZ(world.X - origin.X,
                        world.Y - origin.Y,
                        world.Z - origin.Z)
            centre = delta.DotProduct(direction)
    except Exception:
        centre = None

    if centre is None:
        # No location point to centre the rough width on -- the solid's
        # own midpoint is the best available stand-in.
        centre = (solid[0] + solid[1]) / 2.0

    half = width / 2.0
    return centre - half, centre + half, solid[2], solid[3]


# Reading a wall's inserts means tessellating each one's solid, and a
# single wall is commonly host to several picked sweeps as well as being
# picked itself.  The script runs once, so caching for its lifetime is
# enough; the key is the (link id, wall id) pair used everywhere else.
_OPENING_CACHE = {}


def openings_along(walls, link_tf, origin, direction, wall_keys):
    """Every opening in *walls*, as distances along one shared frame.

    Cached on the set of walls AND the frame, because the answer is in
    distances along that frame -- and the frame is not settled by the
    member set alone.  Its direction comes from the longest member, and
    two members of equal length tie, so the same walls reached in a
    different order can give a frame pointing the other way.  Keyed on
    the walls alone, the second sweep would then read the first one's
    openings mirrored end for end and stop in the wrong places.

    Several sweeps commonly share a run of host walls, and reading the
    inserts means tessellating each one's solid, so where the frame IS
    the same the second sweep should not pay for it again.
    """
    cache_key = (tuple(sorted(wall_keys)),
                 round(origin.X, 4), round(origin.Y, 4),
                 round(direction.X, 4), round(direction.Y, 4))
    if cache_key not in _OPENING_CACHE:
        found = []
        for wall in walls:
            found.extend(wall_openings(wall, link_tf, origin, direction))
        _OPENING_CACHE[cache_key] = found
    return _OPENING_CACHE[cache_key]


def is_category(elem, bic):
    """True when *elem* belongs to the given BuiltInCategory."""
    try:
        cat = elem.Category
        if cat is None:
            return False
    except Exception:
        return False
    try:
        return cat.BuiltInCategory == bic
    except Exception:
        pass
    try:
        return cat.Id.IntegerValue == ElementId(bic).IntegerValue
    except Exception:
        return False


def is_curtain_wall(elem):
    """True when *elem* is a curtain wall."""
    if not isinstance(elem, Wall):
        return False
    try:
        return elem.WallType.Kind == WallKind.Curtain
    except Exception:
        return False


def breaks_a_sweep(insert):
    """True when a sweep running past *insert* has to stop at it.

    Only a door or a curtain wall does.  A window does NOT, whatever its
    geometry suggests: a band course runs on under the sill, and it is
    the sill and apron hanging below the opening that made a window look
    like it reached down to the course at all.  Measuring harder would
    not have fixed that -- a window that genuinely interrupts a course
    and one that merely hangs trim into it are the same shape.  Which
    openings break a run is a decision about the building, so it is
    written here as one.
    """
    if is_curtain_wall(insert):
        return True
    return is_category(insert, BuiltInCategory.OST_Doors)


def wall_openings(wall, link_tf, origin, direction):
    """Openings in *wall* that break a sweep, as (lo, hi, z_lo, z_hi).

    Only the inserts breaks_a_sweep() accepts -- doors and curtain walls
    -- appear here.  Windows are left out entirely, so a band course
    runs on under their sills.

    Measured in the wall's own frame: *along* from *origin* along
    *direction*, both already in host coordinates.  Along the wall the
    extent is the ROUGH OPENING, the void actually cut in the wall, so
    a sweep wall stops on the same line as the wall behind it.
    Vertically it is the insert's whole solid, which is only ever asked
    whether an opening reaches a given course.  See _insert_extent for
    why the two ends are measured differently.
    """
    try:
        ids = list(wall.FindInserts(True, False, True, True))
    except Exception as ex:
        logger.debug("Could not read inserts: {}".format(ex))
        return []

    link_doc = wall.Document
    found    = []
    for iid in ids:
        insert = link_doc.GetElement(iid)
        if insert is None or not breaks_a_sweep(insert):
            continue
        extent = _insert_extent(insert, link_tf, origin, direction)
        if extent is not None:
            found.append(extent)

    return found


def wall_inserts(wall, link_tf, origin, direction):
    """Return (windows, rectangular openings) in *wall*.

    Windows are measured the same way wall_openings measures a door:
    along the wall from *origin*, as (lo, hi, z_lo, z_hi, insert).  That
    frame is fine for them because Task 6 re-derives a window's position
    from the window element itself and only uses these numbers for
    reporting.

    Rectangular openings are cut from later, once the skin wall exists,
    and that wall may be reversed from the source, a merge of several
    source walls, or mitred at its ends -- none of which share the
    source wall's frame.  So an opening is instead stored as its WORLD
    centre point and width: (centre_xyz, width, z_lo, z_hi, insert).
    cut_openings re-projects that onto whichever built wall it ends up
    cutting, which is correct regardless of how that wall's own curve
    relates to this one.  z_lo / z_hi are absolute elevations already
    and need no reframing either way.

    Doors are not here.  They break the sweeps, as in V1, and the skin
    is left solid across them.
    """
    try:
        ids = list(wall.FindInserts(True, False, True, True))
    except Exception as ex:
        logger.debug("Could not read inserts: {}".format(ex))
        return [], []

    link_doc = wall.Document
    windows  = []
    openings = []

    for iid in ids:
        insert = link_doc.GetElement(iid)
        if insert is None:
            continue

        extent = _insert_extent(insert, link_tf, origin, direction)
        if extent is None:
            continue
        lo, hi, z_lo, z_hi = extent

        if window_cw.is_category(insert, BuiltInCategory.OST_Windows):
            windows.append((lo, hi, z_lo, z_hi, insert))
        elif isinstance(insert, Opening):
            centre_along = (lo + hi) / 2.0
            centre = XYZ(origin.X + direction.X * centre_along,
                        origin.Y + direction.Y * centre_along,
                        origin.Z + direction.Z * centre_along)
            openings.append((centre, hi - lo, z_lo, z_hi, insert))

    return windows, openings


def _level_elevation(link_doc, level_id, link_tf):
    """Elevation of a LINKED level, in host geometry space.

    Read from the linked document and pushed through the link transform,
    rather than matched to a host level by name: a link whose levels are
    named differently would otherwise silently bind to the wrong storey.
    """
    lvl = link_doc.GetElement(level_id)
    if lvl is None:
        return None
    raw = lvl.Elevation - project_base_elevation(link_doc)
    return link_tf.OfPoint(XYZ(0.0, 0.0, raw)).Z


def plan_wall(link_inst, wall):
    """Measure one linked wall.  Returns (WallJob or None, notes)."""
    label = "wall id {} ({})".format(wall.Id.IntegerValue,
                                     get_element_name(wall.WallType))

    if wall.WallType.Kind != WallKind.Basic:
        return None, [[label, "not a Basic Wall"]]

    cs = wall.WallType.GetCompoundStructure()
    if cs is None:
        return None, [[label, "wall type has no compound structure"]]
    if cs.LayerCount < 2:
        return None, [[label, "fewer than 2 layers - nothing to split"]]
    if cs.GetFirstCoreLayerIndex() < 1:
        return None, [[label,
                       "no exterior finish layer before the core boundary"]]

    link_doc = wall.Document
    link_tf  = link_inst.GetTotalTransform()

    raw_curve = wall.Location.Curve if wall.Location is not None else None
    if raw_curve is None:
        return None, [[label, "wall has no location curve"]]
    if not isinstance(raw_curve, (Line, Arc)):
        return None, [[label, "location curve is neither a line nor an "
                              "arc - not supported"]]

    loc_curve = raw_curve.CreateTransformed(link_tf)
    curved    = not isinstance(loc_curve, Line)

    pt0 = loc_curve.GetEndPoint(0)
    pt1 = loc_curve.GetEndPoint(1)
    if loc_curve.Length < MIN_RUN_LENGTH:
        return None, [[label, "wall too short"]]

    # Rotate the orientation vector: transforming origin+direction and
    # subtracting the transformed origin isolates the rotation.
    raw_orient  = wall.Orientation
    origin_tf   = link_tf.OfPoint(XYZ.Zero)
    orient_tip  = link_tf.OfPoint(
        XYZ(raw_orient.X, raw_orient.Y, raw_orient.Z))
    orientation = XYZ(orient_tip.X - origin_tf.X,
                      orient_tip.Y - origin_tf.Y,
                      orient_tip.Z - origin_tf.Z).Normalize()

    # Measured off the solid for a straight wall, and NOT for a curved
    # one: the measurement projects every solid point onto one normal,
    # and a curved wall's normal turns as it goes, so the far face would
    # come back as wherever the arc bulges furthest that way.  A curved
    # wall falls back to the compound structure's own arithmetic in
    # prepare_bands, which is exact whatever shape the wall is.
    loc_to_ext = None
    if not curved:
        try:
            meas = wall_skin.measure_face_offsets(
                wall, pt0, orientation, link_tf)
            if meas:
                loc_to_ext = meas[0]
        except Exception as ex:
            logger.debug("Face measurement failed on {}: {}".format(
                label, ex))

    # ---- Vertical extent, from the constraint parameters only.
    base_p = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
    base_elev = _level_elevation(
        link_doc, base_p.AsElementId(), link_tf) if base_p else None
    if base_elev is None:
        return None, [[label, "wall has no readable Base Constraint"]]

    bo_p = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    base_offset = bo_p.AsDouble() if (bo_p and bo_p.HasValue) else 0.0

    top_p = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
    top_elev = None
    if top_p and top_p.HasValue:
        top_id = top_p.AsElementId()
        if top_id is not None and top_id != ElementId.InvalidElementId:
            top_elev = _level_elevation(link_doc, top_id, link_tf)

    to_p = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
    top_offset = to_p.AsDouble() if (to_p and to_p.HasValue) else 0.0

    h_p = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
    height = h_p.AsDouble() if (h_p and h_p.HasValue) else 0.0

    base_z, top_z = wall_bands.wall_span(
        base_elev, base_offset, top_elev, top_offset, height)

    if top_z - base_z <= wall_bands.TOL:
        return None, [[label, "wall constraints give no height"]]

    st_p = wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
    structural = bool(st_p.AsInteger()) if (st_p and st_p.HasValue) else False

    job = WallJob()
    job.label       = label
    # (link instance id, linked element id) -- see the matching comment
    # on HostRun.wall_keys for why the link id is part of the key.  A
    # SET because merge_wall_jobs can fold several walls into this one;
    # band_walls intersects it against a sweep run's own set.
    job.wall_keys   = set([(link_inst.Id.IntegerValue,
                            wall.Id.IntegerValue)])
    try:
        job.type_id = wall.WallType.Id.IntegerValue
    except Exception:
        job.type_id = None
    job.cs          = cs
    job.source_doc  = link_doc
    job.loc_curve   = loc_curve
    job.link_inst   = link_inst
    job.curved      = curved
    # No single direction for an arc, and nothing that still wants one
    # is asked to work on a curved wall.
    job.direction   = None if curved else (pt1 - pt0).Normalize()
    job.orientation = orientation
    job.total_width = wall.Width
    job.loc_line    = (wall.get_Parameter(
        BuiltInParameter.WALL_KEY_REF_PARAM).AsInteger()
        if wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM) else 0)
    job.loc_to_ext  = loc_to_ext
    job.base_z      = base_z
    job.top_z       = top_z
    job.structural  = structural
    job.bands       = []          # filled in by band_walls
    job.built_bands = []          # filled in by build_bands

    if curved:
        # An insert is measured as a distance ALONG a straight frame,
        # and everything downstream of that -- the curtain wall on a
        # window, the hole cut for an opening -- lays it back down the
        # same way.  A curved wall's skin is built; what is in it is
        # not, and saying so is better than placing a window on the
        # chord of the arc it belongs to.
        job.windows, job.rect_openings = [], []
        return job, [[label,
                      "curved wall: the skin is built, but its windows "
                      "and openings are not - say so if you need them"]]

    job.windows, job.rect_openings = wall_inserts(
        wall, link_tf, pt0, (pt1 - pt0).Normalize())
    return job, notes_none()


def merge_wall_jobs(wall_jobs):
    """Fold colinear picked walls into one job apiece.

    The link holds one physical wall as two or three end to end more
    often than not, and building a skin wall for each leaves a seam
    down the elevation where there is no joint in the building.  Walls
    that are one straight run of one type, facing one way and spanning
    one height, are built as one wall instead.

    The span has to match as well as the type: a merged job carries a
    single set of constraints, so two pieces at different heights are
    two walls whatever else they share.  Everything else is taken from
    the first member, which the shared key has already guaranteed is
    the same for all of them.
    """
    # A curved wall is colinear with nothing, and colinear_chains works
    # on 2D segments -- an arc's chord, which is not where the wall is.
    curved   = [job for job in wall_jobs if job.curved]
    straight = [job for job in wall_jobs if not job.curved]

    if len(straight) < 2:
        return wall_jobs

    wall_jobs = straight

    segments = []
    keys     = []
    for job in wall_jobs:
        p0 = job.loc_curve.GetEndPoint(0)
        p1 = job.loc_curve.GetEndPoint(1)
        segments.append(((p0.X, p0.Y), (p1.X, p1.Y)))
        # The link instance is part of the key, not just the type,
        # orientation and span: merged_frame below borrows its curve's
        # transform from the first member and plan_windows measures every
        # member's windows through that one instance's transform.  Two
        # instances of the same link placed abutting and colinear -- a
        # repeated bay or wing -- would otherwise merge, and every
        # curtain wall on the second instance's walls would be built at
        # the first instance's coordinates.
        keys.append((job.type_id,
                     round(job.orientation.X, 4),
                     round(job.orientation.Y, 4),
                     round(job.base_z, 4),
                     round(job.top_z, 4),
                     job.link_inst.Id.IntegerValue))

    merged = []
    for members, ends in wall_bands.colinear_chains(segments, keys):
        first = wall_jobs[members[0]]
        if len(members) == 1:
            merged.append(first)
            continue

        z = first.loc_curve.GetEndPoint(0).Z
        (x0, y0), (x1, y1) = ends

        job = WallJob()
        job.label       = "{} (+{} colinear)".format(
            first.label, len(members) - 1)
        job.wall_keys   = set()
        for i in members:
            job.wall_keys |= wall_jobs[i].wall_keys
        job.type_id     = first.type_id
        job.cs          = first.cs
        job.source_doc  = first.source_doc
        job.loc_curve   = Line.CreateBound(XYZ(x0, y0, z), XYZ(x1, y1, z))
        job.link_inst   = first.link_inst
        # A merged run is straight by construction: only straight jobs
        # reach here at all.  Spelled out because WallJob uses __slots__
        # and an unset one raises rather than reading as False.
        job.curved      = False
        # Derived from the MERGED curve, not copied from *first*: a
        # merged run is one wall and the direction is its own, not
        # whichever member happened to come first.
        job.direction   = (job.loc_curve.GetEndPoint(1)
                           - job.loc_curve.GetEndPoint(0)).Normalize()
        job.orientation = first.orientation
        job.total_width = first.total_width
        job.loc_line    = first.loc_line
        job.loc_to_ext  = first.loc_to_ext
        job.base_z      = first.base_z
        job.top_z       = first.top_z
        job.structural  = first.structural
        job.bands       = []
        job.built_bands = []
        # Every member's inserts, or the windows/openings on the second
        # and third piece are silently lost.  Windows are measured along
        # each MEMBER's own frame -- Task 6 re-derives their position
        # from the window element itself, so that frame is only ever
        # used for reporting.  Rectangular openings carry a WORLD centre
        # point and width instead of an along value, so they need no
        # reprojection here at all: cut_openings re-projects each onto
        # the BUILT wall's own curve at cut time, whatever frame that
        # wall ends up in.
        job.windows       = []
        job.rect_openings = []
        for i in members:
            job.windows.extend(wall_jobs[i].windows)
            job.rect_openings.extend(wall_jobs[i].rect_openings)
        merged.append(job)

    # The curved ones went nowhere near any of this, and come back
    # untouched.
    return merged + curved


def notes_none():
    """An empty note list, spelled out so plan_wall reads symmetrically."""
    return []


# ===========================================================================
# WALL TYPES
# ===========================================================================

def find_wall_type_by_name(name):
    """Return the host WallType named exactly *name*, or None."""
    from Autodesk.Revit.DB import WallType
    for wt in FilteredElementCollector(doc).OfClass(WallType):
        if get_element_name(wt) == name:
            return wt
    return None


def resolve_sweep_types(sweep_jobs, notes):
    """Give every sweep job a wall type, asking only where it must.

    An EIFS profile is dropped here and goes no further, whether the
    name rule recognised it or the user chose it by hand.  It is the
    resolved TYPE that decides, so the two routes to being EIFS are
    answered the same way.  Dropping it is silent -- ignoring an EIFS
    sweep is what the tool does now, not something that went wrong --
    so a selection may be swept clean of them without the report saying
    a word.

    The STONE / EIFS name rule answers most of the rest outright.  What
    it cannot read -- and any profile whose named type is missing from
    this model -- falls back to one dialog per sweep TYPE, so a run with
    twenty identical sweeps asks once.

    Returns the jobs that ended up with a type.  A sweep left without
    one is dropped: it neither becomes a wall nor cuts one, and unless
    it was EIFS it is reported.
    """
    asked = {}          # sweep type name -> WallType or None
    resolved = []

    for job in sweep_jobs:
        wanted = wall_bands.sweep_wall_type_name(job.type_name, job.material)

        if wanted == wall_bands.EIFS_TYPE_NAME:
            continue

        if wanted is not None:
            wall_type = find_wall_type_by_name(wanted)
            if wall_type is not None:
                job.wall_type = wall_type
                resolved.append(job)
                continue
            note(notes, job.label,
                 "wall type '{}' is not in this model - asking "
                 "instead".format(wanted))

        key = job.type_name or "<unnamed sweep type>"
        if key not in asked:
            asked[key] = wall_materials.pick_skin_wall_type(
                doc,
                "Pick the wall type for sweep type '{}'".format(key),
                job.material or "<unknown>",
                "{} high".format(wall_naming.feet_to_imperial(
                    max(r.top_z - r.base_z for r in job.runs))))

        if asked[key] is None:
            note(notes, job.label,
                 "no wall type chosen for sweep type '{}' - skipped, and "
                 "it does not cut any wall".format(key))
            continue

        if get_element_name(asked[key]) == wall_bands.EIFS_TYPE_NAME:
            continue

        job.wall_type = asked[key]
        resolved.append(job)

    return resolved


def _material_of_layer(cs, layer_index, source_doc):
    """Return the Material element for a layer, or None.

    The material belongs to *source_doc*, which is the linked document.
    """
    try:
        mat_id = cs.GetMaterialId(layer_index)
    except Exception:
        return None
    if mat_id and mat_id != ElementId.InvalidElementId:
        return source_doc.GetElement(mat_id)
    return None


def skin_plan_key(cs, source_doc):
    """Key a wall by the SKIN type it needs, so each is resolved once.

    Walls whose finishes share a Mark share a wall type; a finish with
    no Mark falls back to its material name, so those are still only
    asked about once each.
    """
    source_mat = _material_of_layer(cs, 0, source_doc)
    mark       = wall_materials.material_mark(source_mat)
    if not mark:
        mark = "name:{}".format(
            wall_materials.element_name(source_mat) or "Unknown")
    return wall_materials.type_match_key(mark, cs.GetLayerWidth(0))


def collect_skin_plans(wall_jobs):
    """Resolve the SKIN wall type once per Mark across the selection.

    Returns {skin_plan_key: plan}.  Called before the transaction opens
    so the dialogs do not appear mid-transaction.
    """
    plans = {}
    for job in wall_jobs:
        key = skin_plan_key(job.cs, job.source_doc)
        if key in plans:
            continue
        plans[key] = wall_materials.plan_skin_wall_type(
            doc, _material_of_layer(job.cs, 0, job.source_doc),
            job.source_doc, job.cs.GetLayerWidth(0), TOOL_TITLE)
    return plans


# ===========================================================================
# BANDING
# ===========================================================================

def sweep_cuts_walls(job):
    """True when this sweep interrupts the walls it runs across.

    Only a CAST STONE course does.  EIFS never reaches here at all --
    resolve_sweep_types drops it -- so what this still guards against is
    a sweep whose type the user picked by hand: it becomes a wall of its
    own and mitres into its neighbours, but it does not decide where the
    skin walls around it start and stop.

    The test is the wall type the sweep RESOLVED to, not its name or its
    material: those are what resolve_sweep_types reads to reach the type
    in the first place, and a sweep the name rule could not read has had
    its type chosen by hand.  What the sweep is being built as is the
    honest answer to what it is.
    """
    return get_element_name(job.wall_type) == wall_bands.CAST_STONE_TYPE_NAME


def snap_to_levels(wall_jobs, sweep_jobs, soffit_jobs, levels):
    """Pull every end that all but reaches a level onto it.

    A sweep an inch shy of a level binds its base to the level BELOW
    that one and its top to the one above -- the house rule working as
    written and reading as nonsense, a parapet spanning LEVEL 03 to
    LEVEL 05 when it plainly sits on 04.

    This runs ONCE, here, on the measured extents, before anything is
    banded or built.  That is the whole reason it can be done safely: a
    sweep's run and the wall bands above and below it are cut from the
    SAME number, so moving it moves all three together and no gap or
    overlap can open between them.  Snapping the finished walls one at
    a time afterwards is what would open one.

    Each end moves on its own, so a span is stretched onto the levels
    rather than slid between them.  A span too short to survive it --
    a shallow sweep sitting astride a level, both ends reaching for it
    -- is left exactly where it was.
    """
    for job in sweep_jobs:
        for run in job.runs:
            run.base_z, run.top_z, _moved = \
                wall_constraints.snap_span_to_levels(
                    run.base_z, run.top_z, levels,
                    min_height=MIN_RUN_LENGTH)

    for job in wall_jobs:
        job.base_z, job.top_z, _moved = \
            wall_constraints.snap_span_to_levels(
                job.base_z, job.top_z, levels, min_height=MIN_RUN_LENGTH)

    # Soffits snap for the same reason sweeps do.  A soffit an inch shy
    # of a level would stop the wall under it an inch shy of that level
    # too, and that wall would then be constrained to the level BELOW.
    for job in soffit_jobs:
        job.shape.base_z, job.shape.top_z, _moved = \
            wall_constraints.snap_span_to_levels(
                job.shape.base_z, job.shape.top_z, levels,
                min_height=MIN_RUN_LENGTH)


def band_walls(wall_jobs, sweep_jobs, soffit_jobs, levels, notes):
    """Work out the bands each wall is cut into.

    Three things cut a wall.  A picked ROOF SOFFIT cuts EVERY wall in
    the run, at its own full extent -- picking it is the statement that
    it governs them, so no plan test stands between the two.  Unlike a
    course it is never suppressed by a window either, because a soffit
    is a limit of the same kind a level is: where one comes down, the
    wall stops.

    The other two are as they were.  The CAST STONE sweeps hosted
    on it -- hosted decided by the link's own GetHostIds(), so a sweep
    on a neighbouring wall is never mistaken for one on this one, and
    cast stone by sweep_cuts_walls, so a hand-typed sweep passes a wall
    by without breaking it.  And every level a leftover stretch crosses,
    because a wall crossing a level is the one thing the house rule
    never allows.

    Nothing is rounded: wall_constraints.plan_wall is called with
    allow_round=False so a band end stays exactly on the sweep face or
    the level that produced it.  Rounding it to the nearest inch would
    open a gap between the band and the sweep wall above it.

    Fills job.bands in place.
    """
    cutting      = [j for j in sweep_jobs if sweep_cuts_walls(j)]
    soffit_spans = soffit_cutters(soffit_jobs)

    for job in wall_jobs:
        # One cutter per RUN, not per sweep: a run knows which wall it
        # lies on and how high it sits there, so a sweep that steps down
        # cuts each of its walls at the height it actually runs at.
        cutters = [(run.base_z, run.top_z)
                   for sweep_job in cutting
                   for run in sweep_job.runs
                   if run.wall_keys & job.wall_keys]

        # A course running across a window would split the wall behind
        # it, putting a joint in the elevation the building does not
        # have.  Where one crosses a window, it stops governing this
        # wall's heights entirely.
        cutters = wall_bands.cutters_clear_of_windows(
            cutters, [(w[2], w[3]) for w in job.windows])

        # Soffits are added AFTER that exemption, never inside it.
        cutters = cutters + soffit_spans

        gaps, dropped = wall_bands.subtract_spans(
            (job.base_z, job.top_z), cutters)

        for lo, hi in dropped:
            note(notes, job.label,
                 "sliver between sweeps at {} to {} is too thin to "
                 "build".format(feet_text(lo), feet_text(hi)))

        if not gaps:
            note(notes, job.label,
                 "sweeps cover the whole wall - nothing left to build")
            continue

        for lo, hi in gaps:
            try:
                plan = wall_constraints.plan_wall(
                    lo, hi, levels, allow_round=False)
            except ValueError as ex:
                note(notes, job.label,
                     "band {} to {}: {}".format(
                         feet_text(lo), feet_text(hi), ex))
                continue
            job.bands.extend(plan["bands"])

        if not job.bands:
            note(notes, job.label, "no band could be constrained")


# ===========================================================================
# WINDOWS -> CURTAIN WALLS
# ===========================================================================

def plan_windows(wall_jobs, notes):
    """Measure every window and settle its curtain wall type.

    Runs BEFORE the transaction: prompt_curtain_type raises a dialog,
    and this tool never opens one inside a transaction.  The type is
    asked once per Type Mark prefix and cached, as Window To Curtain
    Wall does, so a facade of twenty identical windows asks once.

    The curtain-type lookup is deferred until a window has actually
    been found: checking it first means a model with no curtain wall
    types reports that on every run, even a selection of plain walls
    with no windows at all, which breaks the tool's silent-on-success
    rule for a run that has nothing to place.
    """
    if not any(job.windows for job in wall_jobs):
        return []

    types = window_cw.curtain_wall_types(doc)
    if not types:
        note(notes, "-", "no curtain wall types in this model")
        return []

    asked   = {}
    planned = []

    for job in wall_jobs:
        for _lo, _hi, _z_lo, _z_hi, window in job.windows:
            # No host wall: the skin wall this window will sit on is not
            # built yet, and cannot be -- choosing its type raises a
            # dialog, so all of this runs before the transaction.  The
            # merged frame's direction is the only thing measure_window
            # wanted a wall for, and it is the direction the skin wall
            # will have.
            plan, reason = window_cw.measure_window(
                job.link_inst, window, None, direction=job.direction)
            if plan is None:
                note(notes, job.label,
                     "window {}: {}".format(window.Id.IntegerValue, reason))
                continue

            wall_type = window_cw.match_curtain_type(plan, types)
            if wall_type is None:
                prefix = window_cw.mark_prefix(plan.mark)
                if prefix not in asked:
                    asked[prefix] = window_cw.prompt_curtain_type(
                        types, plan.mark, prefix)
                wall_type = asked[prefix]

            if wall_type is None:
                note(notes, job.label,
                     "window {}: no curtain wall type chosen".format(
                         window.Id.IntegerValue))
                continue

            planned.append((job, plan, wall_type))

    return planned


def build_curtain_walls(planned, levels, notes):
    """Create one curtain wall per window, per storey.  In a transaction.

    A window crossing a level becomes one curtain wall per storey,
    split at exactly the elevations the skin bands split at -- the same
    wall_constraints.plan_wall, called with allow_round=False, so the
    two can never disagree about where a storey ends.

    Each piece is hosted on whichever skin band covers its own middle.
    That is what makes a split window work: the lower piece embeds in
    the lower band and the upper piece in the upper one.
    """
    for job, plan, wall_type in planned:
        try:
            cut = wall_constraints.plan_wall(
                plan.sill, plan.sill + plan.height, levels,
                allow_round=False)
        except ValueError as ex:
            note(notes, job.label,
                 "window {}: {}".format(plan.window_id, ex))
            continue

        for band in cut["bands"]:
            mid  = (band["base_z"] + band["top_z"]) / 2.0
            host = None
            for base_z, top_z, wall in job.built_bands:
                if base_z - wall_bands.TOL <= mid <= top_z + wall_bands.TOL:
                    host = wall
                    break

            if host is None:
                note(notes, job.label,
                     "window {}: no skin wall at {} to host it".format(
                         plan.window_id, feet_text(mid)))
                continue

            piece = window_cw.copy_plan(plan)
            piece.sill   = band["base_z"]
            piece.height = band["top_z"] - band["base_z"]

            try:
                wall, reason = window_cw.create_curtain_wall(
                    doc, piece, host, wall_type)
            except Exception as ex:
                note(notes, job.label,
                     "window {}: curtain wall failed: {}".format(
                         plan.window_id, ex))
                continue

            if wall is None:
                note(notes, job.label,
                     "window {}: {}".format(plan.window_id, reason))
            elif reason:
                note(notes, job.label,
                     "window {}: {}".format(plan.window_id, reason))

            # apply_bg_parameters appends one note per BG_ parameter it
            # could not fill onto piece.notes, and piece goes out of
            # scope right after this -- an unfilled BG_ parameter is
            # exactly what this tool exists to surface, so fold every
            # note into the run's report before it is lost.
            for piece_note in piece.notes:
                note(notes, job.label,
                     "window {}: {}".format(plan.window_id, piece_note))


# ===========================================================================
# BUILDING
# ===========================================================================

def set_location_line(wall, value):
    """Set the Location Line parameter on *wall*."""
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
        if p and p.HasValue and not p.IsReadOnly:
            p.Set(value)
        doc.Regenerate()
    except Exception:
        pass


def set_bg_profile(wall, value):
    """Write *value* into the wall's BG_PROFILE parameter.

    Returns False when the parameter is absent, read-only, or not a text
    parameter -- the caller reports that rather than failing the wall,
    since the wall itself is correct either way.
    """
    p = find_parameter(wall, BG_PROFILE_PARAM)
    if p is None or p.IsReadOnly:
        return False
    try:
        return bool(p.Set(value))
    except Exception:
        return False


def apply_constraints(wall, band):
    """Bind *wall*'s base and top to the levels *band* names.

    The base level was already set at creation, so only the offset is
    written here; the top is bound outright, which is what turns an
    unconnected wall into one that follows its level.
    """
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
        if p and not p.IsReadOnly:
            p.Set(band["base_offset"])
    except Exception as ex:
        logger.debug("Could not set base offset: {}".format(ex))

    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
        if p and not p.IsReadOnly:
            p.Set(band["top_level_id"])
        p = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
        if p and not p.IsReadOnly:
            p.Set(band["top_offset"])
        doc.Regenerate()
    except Exception as ex:
        logger.debug("Could not bind top constraint: {}".format(ex))


def create_sweep_wall(curve, frame, wall_type, band):
    """Create one wall of a sweep's run and return it.

    *curve* is the new wall's CENTRELINE, worked out beforehand so its
    interior face lands on the host wall's exterior face.  Placing the
    centreline explicitly is what makes this dependable: relying on
    Revit's Location Line to shift the wall put the centreline on the
    host wall's face instead of the interior face.  Location Line is set
    to 'Finish Face: Interior' afterwards, which re-references the wall
    without moving it.
    """
    height   = band["height"]
    base_off = band["base_offset"]
    level_id = band["base_level_id"]

    wall = Wall.Create(doc, curve, wall_type.Id, level_id,
                       height, base_off, False, False)
    doc.Regenerate()

    set_location_line(wall, LOC_LINE_CENTRELINE)

    # Face the same way as the host wall, so 'interior' is the side
    # against it.  Reversing the curve keeps the same endpoints, so a
    # mitred corner survives the swap and the centreline does not move.
    try:
        if frame.normal.DotProduct(wall.Orientation) < 0:
            doc.Delete(wall.Id)
            doc.Regenerate()
            wall = Wall.Create(doc, curve.CreateReversed(), wall_type.Id,
                               level_id, height, base_off, False, False)
            doc.Regenerate()
            set_location_line(wall, LOC_LINE_CENTRELINE)
    except Exception:
        pass

    set_location_line(wall, LOC_LINE_FINISH_FACE_EXTERIOR)
    apply_constraints(wall, band)
    return wall


def curve_ends(curve):
    """A curve's two ends as the plain 2D pairs wall_miter works in."""
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    return ((p0.X, p0.Y), (p1.X, p1.Y))


def join_at_junctions(built):
    """Join new walls that touch, so Revit cleans the junction itself.

    *built* is [(final_centreline, wall)] -- the centreline each wall
    was actually BUILT on, after mitring, not the source centreline the
    mitring was decided from.  The two are not the same question, and
    joining on the wrong one is what produced Revit's "elements joined
    but do not intersect": a corner the mitring failed to close leaves
    two walls a foot apart, and they were handed to Revit anyway.  Now
    only walls that genuinely share an end or cross are joined, so a
    corner that did not close stays visibly open instead of raising a
    warning about it.

    Mitring puts the walls in the right place; joining is what stops a
    line being drawn between them and lets Revit resolve the overlap
    inside a corner, which moving centrelines cannot.
    """
    for i in range(len(built)):
        seg_i, first = built[i]
        if first is None:
            continue
        for j in range(i + 1, len(built)):
            seg_j, second = built[j]
            if second is None:
                continue
            if not wall_miter.segments_meet(seg_i, seg_j):
                continue
            try:
                if JoinGeometryUtils.AreElementsJoined(doc, first, second):
                    continue
                JoinGeometryUtils.JoinGeometry(doc, first, second)
            except Exception as ex:
                logger.debug("Could not join two new walls: {}".format(ex))


def report_unwritten(notes, tally, param_name):
    """Report a parameter that could not be written, once per element."""
    for label, count in tally.items():
        note(notes, label,
             "{} could not be written on {} wall(s) - parameter missing, "
             "read-only, or not a text parameter".format(param_name, count))


def unmitred_curve(segment):
    """The segment's own offset line, for when mitring could not run.

    wall_chain.Segment holds its offset ends and their elevations but
    hands back a curve only through mitre_segments, so this rebuilds the
    plain line from them.  Returns None if even that fails.
    """
    try:
        (x0, y0), (x1, y1) = segment.offset_ends
        z0, z1 = segment.z
        return Line.CreateBound(XYZ(x0, y0, z0), XYZ(x1, y1, z1))
    except Exception:
        return None


def apply_bg_level(wall, band):
    """Write the name of *wall*'s Base Constraint level into BG_LEVEL.

    The level comes from the band the wall was built to rather than from
    the wall itself, so it says the same thing the constraint does even
    if Revit later re-hosts the wall.  Returns False when the parameter
    is missing, read-only or not text -- the wall itself is correct
    either way, so the caller reports it rather than failing the wall.
    """
    level = doc.GetElement(band["base_level_id"])
    if level is None:
        return False

    p = find_parameter(wall, BG_LEVEL_PARAM)
    if p is None or p.IsReadOnly:
        return False
    try:
        return bool(p.Set(get_element_name(level)))
    except Exception:
        return False


def build_sweep_walls(sweep_jobs, levels, notes, existing):
    """Create the walls for every measured sweep.  Inside a transaction.

    Mitring is across sweeps, not within one.  Two sweeps meeting at a
    building corner are two separate picks, and mitring each on its own
    left them running past each other and crossing -- so every run from
    every sweep is gathered first and grouped by the height it sits at
    AND the wall type it resolved to.  A stone band then trims into a
    stone band and not into a course at a different height, or of a
    different type where one was picked by hand.

    A run standing where a wall of its own type already stands at its
    own height is skipped, and only that run.  The mitre has already
    happened by then, so what is compared is the curve the wall would
    actually have been built on -- not the one it was measured as.
    """
    items = []
    for job in sweep_jobs:
        half = job.wall_type.Width / 2.0
        for run in job.runs:
            try:
                # Interior face of the new wall on the exterior face of
                # the host, so its centreline sits half a thickness
                # further out again.  The run's own ends are what get
                # offset, so a stretch that stops at an opening is never
                # stretched to a corner it does not reach.
                segment = wall_chain.Segment(
                    run.frame, run.offset + half,
                    run.along_min, run.along_max)
            except Exception as ex:
                note(notes, job.label,
                     "could not lay out a run of this sweep: {}".format(ex))
                continue
            items.append({"job": job, "run": run, "segment": segment})

    if not items:
        return 0          # nothing laid out, so nothing skipped either

    groups = {}
    span_ids = wall_bands.group_indices(
        [(item["run"].base_z, item["run"].top_z) for item in items])
    for item, span_id in zip(items, span_ids):
        groups.setdefault(
            (span_id, item["job"].wall_type.Id.IntegerValue), []).append(item)

    unwritten = {}
    no_level  = {}
    skipped   = [0]           # a list, so the inner loop can add to it
    for group in groups.values():
        built = []
        try:
            # A sweep's runs do NOT reach the corners of the walls
            # they lie on.  Revit mitres the sweep's own solid back from
            # a corner by roughly how far it stands off the wall, so a
            # run measured off that solid stops short at both ends -- at
            # the default 1/64 inch the two runs either side of a corner
            # are nowhere near each other and no corner is seen, which
            # is why a coping was still being built short at its
            # returns.  Judging adjacency at the scale of that shortfall
            # finds the corner; the mitre point itself comes from where
            # the offset LINES cross, so it is exact however slack the
            # test that found it.
            reach = max(item["segment"].frame.width for item in group)
            reach = max([reach] + [item["run"].reach for item in group])
            curves = wall_chain.mitre_segments(
                [item["segment"] for item in group], tol=reach,
                tees=True, tee_reach=reach)
        except Exception as ex:
            # An unmitred corner is a far better outcome than no wall.
            note(notes, group[0]["job"].label,
                 "could not mitre this run of sweep walls, leaving the "
                 "corners open: {}".format(ex))
            curves = [unmitred_curve(item["segment"]) for item in group]

        for item, curve in zip(group, curves):
            job     = item["job"]
            segment = item["segment"]
            run     = item["run"]
            label   = get_element_name(segment.frame.wall.WallType)

            if curve is None:
                note(notes, label, "could not build a curve for this wall")
                continue

            try:
                band = wall_constraints.constraints_for(
                    run.base_z, run.top_z, levels)
            except ValueError as ex:
                note(notes, job.label,
                     "could not constrain a run of this sweep: {}".format(ex))
                continue

            type_id = job.wall_type.Id.IntegerValue
            standing = wall_exists.find(
                existing, type_id, curve, run.base_z, run.top_z)
            if standing is not None:
                skipped[0] += 1
                # Still offered for joining.  The wall is there, its new
                # neighbours meet it, and a corner left unjoined because
                # one side of it was built last week looks no better than
                # any other unjoined corner.
                built.append((curve_ends(curve), standing))
                continue

            try:
                wall = create_sweep_wall(
                    curve, segment.frame, job.wall_type, band)
            except Exception as ex:
                note(notes, label, "wall creation failed: {}".format(ex))
                continue

            wall_exists.register(existing, type_id, curve,
                                 run.base_z, run.top_z, wall)

            if not apply_bg_level(wall, band):
                no_level[job.label] = no_level.get(job.label, 0) + 1
            if job.type_mark and not set_bg_profile(wall, job.type_mark):
                unwritten[job.label] = unwritten.get(job.label, 0) + 1

            built.append((curve_ends(curve), wall))

        join_at_junctions(built)

    report_unwritten(notes, unwritten, BG_PROFILE_PARAM)
    report_unwritten(notes, no_level, BG_LEVEL_PARAM)
    return skipped[0]


def resolve_skin_type(plan, job, executed, key):
    """Carry out one skin-type plan, once per plan key.

    The memo is only to save repeating the work: reusing a type that is
    already named what a plan wants is wall_materials' job, and it does
    it for every tool that builds skin types, not just this one.
    """
    if key not in executed:
        executed[key] = wall_materials.execute_skin_wall_type_plan(
            doc, plan, _material_of_layer(job.cs, 0, job.source_doc),
            job.source_doc)
    return executed[key]


def prepare_bands(wall_jobs, skin_plans, notes):
    """Work out a centreline and a type for every band, building nothing.

    Creation is deferred so that bands sharing an elevation can have
    their corners mitred against each other first.

    A band runs the whole length of the wall it came from.  Cutting it
    in plan at the wall's openings was tried and taken back out: only
    the sweeps break at openings.

    Returns [{"job", "band", "curve", "original", "type"}], where
    "original" is the source wall's own centreline, which is what
    mitre_prepared judges adjacency on.
    """
    prepared = []
    executed = {}

    for job in wall_jobs:
        if not job.bands:
            continue

        try:
            key  = skin_plan_key(job.cs, job.source_doc)
            plan = skin_plans.get(key)
            if plan is None or plan.get("action") == "skip":
                note(notes, job.label,
                     plan.get("reason", "no wall type resolved")
                     if plan else "no wall type resolved")
                continue

            skin_type = resolve_skin_type(plan, job, executed, key)

            if skin_type is None:
                note(notes, job.label, "no wall type resolved")
                continue

            first_core = job.cs.GetFirstCoreLayerIndex()
            last_core  = job.cs.GetLastCoreLayerIndex()
            skin_w, gap_w, core_w, _int_w, _ext = \
                wall_skin.layer_group_widths(job.cs, first_core, last_core)

            if job.loc_to_ext is not None:
                d = job.loc_to_ext
            else:
                d = wall_skin.dist_loc_to_exterior(
                    job.loc_line, job.total_width, skin_w, gap_w, core_w)

            curve = wall_skin.skin_centreline(
                job.loc_curve, job.orientation, d, skin_w)
            if curve is None:
                note(notes, job.label,
                     "its skin would have to be offset to or past the "
                     "centre this wall curves on, and no arc does that")
                continue

            # "original" is what mitre_prepared judges adjacency on, and
            # it is a straight segment.  A curved wall has none -- its
            # chord is not where it runs -- so it is handed None and
            # mitring passes it by.  Joining still happens, so Revit
            # cleans whatever junction it can.
            if job.curved:
                original = None
            else:
                o0 = job.loc_curve.GetEndPoint(0)
                o1 = job.loc_curve.GetEndPoint(1)
                original = ((o0.X, o0.Y), (o1.X, o1.Y))

            for band in job.bands:
                prepared.append({
                    "job": job,
                    "band": band,
                    "curve": curve,
                    "original": original,
                    "type": skin_type,
                })
        except Exception as ex:
            note(notes, job.label, "could not prepare bands: {}".format(ex))
            continue

    return prepared


def mitre_prepared(prepared, notes):
    """Close the corners between bands that sit at the same elevation.

    Adjacency is judged on the source wall's centreline, which still
    shares its endpoints with its neighbour; the corner point is where
    the two OFFSET lines cross.  Bands at different elevations are
    mitred separately -- two walls that never touch must not have a
    corner dragged between them.

    Curves are replaced in place inside *prepared*.  A group whose
    mitre fails (a very shallow corner can push the intersection past
    Revit's maximum curve length) is left with its unmitred curves --
    an open corner is a far better outcome than losing the whole run.
    """
    spans = [(item["band"]["base_z"], item["band"]["top_z"])
             for item in prepared]
    ids   = wall_bands.group_indices(spans)

    groups = {}
    for item, key in zip(prepared, ids):
        groups.setdefault(key, []).append(item)

    for key, items in groups.items():
        for item in items:
            item["group"] = key

        # Only the straight ones.  A curved band still belongs to its
        # elevation group -- that is what it is joined within -- but it
        # has no straight centreline to judge a corner on, and handing
        # its chord to the mitre would drag a corner to where the wall
        # is not.
        straight = [item for item in items if item["original"] is not None]
        if len(straight) < 2:
            continue

        try:
            originals = []
            offsets   = []
            zs        = []
            for item in straight:
                sc = item["curve"]
                s0, s1 = sc.GetEndPoint(0), sc.GetEndPoint(1)
                originals.append(item["original"])
                offsets.append(((s0.X, s0.Y), (s1.X, s1.Y)))
                zs.append((s0.Z, s1.Z))

            # See the matching note in build_sweep_walls for why the
            # reach is the thickest wall in the group.
            reach = max(item["job"].total_width for item in straight)
            mitred = wall_miter.miter_chain(originals, offsets,
                                            tees=True, tee_reach=reach)

            for idx, item in enumerate(straight):
                (x0, y0), (x1, y1) = mitred[idx]
                z0, z1 = zs[idx]
                item["curve"] = Line.CreateBound(XYZ(x0, y0, z0),
                                                 XYZ(x1, y1, z1))
        except Exception as ex:
            note(notes, "elevation group {}".format(key),
                 "could not mitre corners for this band - left unmitred: "
                 "{}".format(ex))
            continue


def build_bands(prepared, notes, existing):
    """Create one skin wall per prepared band.  Inside a transaction.

    Walls are joined afterwards, group by group, so Revit cleans each
    corner and tee it can -- see join_at_junctions.

    A band standing where a wall of its own type already stands at its
    own elevations is not built again.  The wall that IS there goes into
    job.built_bands in its place, so the windows and openings that
    belong to that band are still hosted and still cut -- they are what
    the band was for, and the wall being older does not change that.
    """
    no_level = {}
    skipped  = 0
    for item in prepared:
        item["wall"] = None
        job  = item["job"]
        band = item["band"]

        standing = wall_exists.find(
            existing, item["type"].Id.IntegerValue, item["curve"],
            band["base_z"], band["top_z"])
        if standing is not None:
            item["wall"] = standing
            job.built_bands.append(
                (band["base_z"], band["top_z"], standing))
            skipped += 1
            continue

        try:
            wall = wall_skin.create_oriented_wall(
                doc, item["curve"], item["type"].Id,
                band["base_level_id"], band["height"],
                band["base_offset"], job.structural, job.orientation)
            # create_oriented_wall leaves the wall on Centreline, which
            # is what lets it measure and re-centre the wall on the
            # curve it was given.  Re-reference it only once that is
            # done, and only here: the helper is shared with SplitWalls,
            # which is not part of this change.
            set_location_line(wall, LOC_LINE_FINISH_FACE_EXTERIOR)
            apply_constraints(wall, band)
            item["wall"] = wall
            job.built_bands.append((band["base_z"], band["top_z"], wall))
            wall_exists.register(
                existing, item["type"].Id.IntegerValue, item["curve"],
                band["base_z"], band["top_z"], wall)
            if not apply_bg_level(wall, band):
                no_level[job.label] = no_level.get(job.label, 0) + 1
        except Exception as ex:
            note(notes, job.label,
                 "band {} to {} failed: {}".format(
                     feet_text(band["base_z"]), feet_text(band["top_z"]),
                     ex))

    by_group = {}
    for item in prepared:
        by_group.setdefault(item.get("group"), []).append(item)
    for group in by_group.values():
        join_at_junctions(
            [(curve_ends(item["curve"]), item["wall"]) for item in group])

    report_unwritten(notes, no_level, BG_LEVEL_PARAM)
    return skipped


# ===========================================================================
# OPENINGS
# ===========================================================================

def merge_notches(notches):
    """Overlapping base notches become one, as deep as the deeper.

    Two openings that both run to the floor and overlap in plan cannot
    be two notches: their outlines would cross, and the profile would
    be self-intersecting rather than merely wrong.  One notch spanning
    both, at the greater height, is the shape they actually describe.
    """
    merged = []
    for lo, hi, z_hi in sorted(notches):
        if merged and lo <= merged[-1][1]:
            prev_lo, prev_hi, prev_z = merged[-1]
            merged[-1] = (prev_lo, max(prev_hi, hi), max(prev_z, z_hi))
        else:
            merged.append((lo, hi, z_hi))
    return merged


def opening_profile(wall, holes, notches, base, top):
    """Curves for *wall*'s elevation, cut by its holes and its notches.

    Returns the wall's own outline followed by one loop per hole, all
    as closed loops in the wall's elevation plane.  Revit takes the
    first loop as the outline and the rest as holes in it.  Every hole
    for a given wall MUST reach this in one call: wall_sketch.apply_profile
    deletes every existing sketch curve before drawing, so a second call
    on the same wall would silently erase the first hole.

    *holes* is a list of (lo, hi, z_lo, z_hi), each already measured
    along THIS wall's own curve -- not the source wall's -- and already
    clamped to fall strictly inside it.  cut_openings does both the
    projection and the clamping before calling this, because a hole
    that clamps to nothing there is reported and dropped before it gets
    here.

    *notches* is (lo, hi, z_hi) for the openings that reach the wall's
    BASE.  Those are not holes at all.  Drawn as one, a hole's bottom
    edge has to be held clear of the outline's bottom edge or the two
    loops would touch, and that clearance is a hairline of wall left
    standing under the opening -- which is what this exists to stop.
    A notch is instead cut INTO the outline: the profile walks up one
    jamb, across the head and down the other, and the opening runs
    clean into the base.

    *base* and *top* are the elevations this wall was actually BUILT to
    -- the matching entry from job.built_bands -- not read back off the
    wall's own parameters.  Every wall this tool builds is level-bound,
    so Unconnected Height does not govern its true extent, and
    level.Elevation is in level space while this function works in
    geometry space, which differ whenever the Project Base Point is not
    at zero.
    """
    curve = wall.Location.Curve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    direction = (p1 - p0).Normalize()

    length = p0.DistanceTo(p1)

    def at(along, z):
        return XYZ(p0.X + direction.X * along,
                   p0.Y + direction.Y * along,
                   z)

    outline = [(0.0, base)]
    for lo, hi, z_hi in merge_notches(notches):
        outline.append((lo, base))
        outline.append((lo, z_hi))
        outline.append((hi, z_hi))
        outline.append((hi, base))
    outline.append((length, base))
    outline.append((length, top))
    outline.append((0.0, top))

    loops = [outline]
    for lo, hi, z_lo, z_hi in holes:
        loops.append([(lo, z_lo), (hi, z_lo), (hi, z_hi), (lo, z_hi)])

    curves = []
    for loop in loops:
        for idx in range(len(loop)):
            a = loop[idx]
            b = loop[(idx + 1) % len(loop)]
            curves.append(Line.CreateBound(at(a[0], a[1]), at(b[0], b[1])))
    return curves


def cut_openings(wall_jobs, notes):
    """Cut every rectangular opening out of the skin wall covering it.

    Runs AFTER the transaction has committed, and it has no choice:
    SketchEditScope refuses to start inside an open transaction, and a
    sketched profile is drawn against the wall's constraints, so those
    have to be final first.  Window To Curtain Wall sequences it the
    same way, for the same reasons.

    A failure here therefore cannot roll the walls back -- they are
    already committed.  That is the right trade: a wall standing uncut
    is worth more than a run that throws away everything it built.

    Openings are grouped by the host wall they land in BEFORE anything
    is cut: wall_sketch.apply_profile deletes every existing sketch
    curve on a wall before drawing its own, so two openings hosted in
    the same wall must reach it in a single call with the outline
    followed by both holes, or the second call would silently erase the
    first hole.

    Each host wall's cut is wrapped in its own try/except, so one bad
    wall or opening costs a note, not the rest of the run's report.
    """
    for job in wall_jobs:
        by_host = {}
        for centre, width, z_lo, z_hi, opening in job.rect_openings:
            host = None
            host_base = host_top = None
            for base_z, top_z, wall in job.built_bands:
                if (base_z - wall_bands.TOL <= z_lo
                        and z_hi <= top_z + wall_bands.TOL):
                    host = wall
                    host_base = base_z
                    host_top = top_z
                    break

            if host is None:
                note(notes, job.label,
                     "opening {} spans more than one band, or no band "
                     "covers it - left uncut".format(
                         opening.Id.IntegerValue))
                continue

            entry = by_host.setdefault(
                host.Id.IntegerValue,
                {"wall": host, "base": host_base, "top": host_top,
                 "holes": []})
            entry["holes"].append((centre, width, z_lo, z_hi, opening))

        for entry in by_host.values():
            host = entry["wall"]
            base = entry["base"]
            top  = entry["top"]
            try:
                curve = host.Location.Curve
                p0 = curve.GetEndPoint(0)
                p1 = curve.GetEndPoint(1)
                direction = (p1 - p0).Normalize()
                length = p0.DistanceTo(p1)

                valid   = []
                notches = []
                for centre, width, z_lo, z_hi, opening in entry["holes"]:
                    along = (centre - p0).DotProduct(direction)
                    lo = max(along - width / 2.0, wall_bands.TOL)
                    hi = min(along + width / 2.0, length - wall_bands.TOL)
                    hole_z_hi = min(z_hi, top - wall_bands.TOL)

                    # An opening that all but reaches the wall's base is
                    # cut INTO the base rather than held a hairline
                    # clear of it.  The test is the opening's own
                    # bottom, before any clamping, since the clamp is
                    # what would have opened the gap.
                    to_base = z_lo <= base + OPENING_BASE_MERGE_TOL

                    hole_z_lo = base if to_base else max(
                        z_lo, base + wall_bands.TOL)

                    if (hi - lo < MIN_RUN_LENGTH
                            or hole_z_hi - hole_z_lo < MIN_RUN_LENGTH):
                        note(notes, job.label,
                             "opening {} is too small or falls outside "
                             "the wall - left uncut".format(
                                 opening.Id.IntegerValue))
                        continue

                    if to_base:
                        notches.append((lo, hi, hole_z_hi))
                    else:
                        valid.append((lo, hi, hole_z_lo, hole_z_hi))

                if not valid and not notches:
                    continue

                curves = opening_profile(host, valid, notches, base, top)

                failure = wall_sketch.apply_profile(
                    doc, host, curves,
                    "Create skin profile sketch",
                    "Cut the opening out of the skin wall")
                if failure:
                    note(notes, job.label,
                         "wall id {}: {}".format(
                             host.Id.IntegerValue, failure))
            except Exception as ex:
                note(notes, job.label,
                     "wall id {}: could not cut its opening(s) - "
                     "{}".format(host.Id.IntegerValue, ex))


# ===========================================================================
# REPORTING
# ===========================================================================

def report(notes):
    """Print the notes table, or nothing when there is nothing to say."""
    if not notes:
        return
    output.print_md("### {} - {} note(s)".format(TOOL_TITLE, len(notes)))
    output.print_table(table_data=notes, columns=["Element", "Note"])


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    wall_picks, sweep_picks, soffit_picks = pick_sources()
    if not wall_picks and not sweep_picks and not soffit_picks:
        return          # cancelled: create nothing, report nothing

    notes       = []
    sweep_jobs  = []
    wall_jobs   = []
    soffit_jobs = []

    for link_inst, sweep in sweep_picks:
        try:
            job, job_notes = plan_sweep(link_inst, sweep)
        except Exception as ex:
            note(notes, "sweep id {}".format(sweep.Id.IntegerValue),
                 "could not measure this sweep: {}".format(ex))
            continue
        notes.extend(job_notes)
        if job is not None:
            sweep_jobs.append(job)

    for link_inst, wall in wall_picks:
        try:
            job, job_notes = plan_wall(link_inst, wall)
        except Exception as ex:
            note(notes, "wall id {}".format(wall.Id.IntegerValue),
                 "could not measure this wall: {}".format(ex))
            continue
        notes.extend(job_notes)
        if job is not None:
            wall_jobs.append(job)

    for link_inst, soffit in soffit_picks:
        try:
            job, job_notes = plan_soffit(link_inst, soffit)
        except Exception as ex:
            note(notes, "soffit id {}".format(soffit.Id.IntegerValue),
                 "could not measure this soffit: {}".format(ex))
            continue
        notes.extend(job_notes)
        if job is not None:
            soffit_jobs.append(job)

    wall_jobs = merge_wall_jobs(wall_jobs)

    if not sweep_jobs and not wall_jobs:
        report(notes)
        return

    levels = host_levels()
    if not levels:
        report(notes + [["-", "this model has no levels"]])
        return

    # Every dialog happens here, before the transaction opens.
    sweep_jobs = resolve_sweep_types(sweep_jobs, notes)
    skin_plans = collect_skin_plans(wall_jobs)
    window_plans = plan_windows(wall_jobs, notes)

    # Before banding: the bands are cut at the sweeps' own elevations,
    # so the snap has to reach the sweeps first or the walls would be
    # cut where the sweeps used to be.
    snap_to_levels(wall_jobs, sweep_jobs, soffit_jobs, levels)

    band_walls(wall_jobs, sweep_jobs, soffit_jobs, levels, notes)

    # What is already here, read once.  Both builders check against it
    # and add to it, so nothing is built twice within a run either.
    existing = wall_exists.host_index(doc)

    t = Transaction(doc, "Multi Wall Creation")
    t.Start()
    try:
        # build_curtain_walls -> window_cw.create_curtain_wall strips each
        # curtain wall's grid lines and mullions, which raises the same
        # mullion errors the profile edit does.  Answered here the same
        # way WindowToCurtainWall answers it on its own transaction, so a
        # mullion layout Revit cannot clear cleanly cannot pop a modal
        # failure dialog at Commit() and roll back every skin and sweep
        # wall this run built.
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(wall_sketch.SketchFailureSwallower())
        opts.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(opts)
    except Exception as ex:
        logger.debug("Could not set failure handling: {}".format(ex))

    try:
        sweeps_skipped = build_sweep_walls(
            sweep_jobs, levels, notes, existing)

        prepared = prepare_bands(wall_jobs, skin_plans, notes)
        mitre_prepared(prepared, notes)
        bands_skipped = build_bands(prepared, notes, existing)

        build_curtain_walls(window_plans, levels, notes)

        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    # After the transaction, and it cannot be otherwise: SketchEditScope
    # will not start inside one, and a sketched profile is drawn against
    # constraints that have to be final first.  Guarded the same way as
    # the rest of the run: a failure here must not cost the report.
    try:
        cut_openings(wall_jobs, notes)
    except Exception as ex:
        note(notes, "-", "cutting openings failed: {}".format(ex))

    already = sweeps_skipped + bands_skipped
    if already:
        note(notes, "-",
             "{} wall(s) were already standing in the right place and "
             "were left alone".format(already))

    # Silence on success: only problems open the output window.
    report(notes)


try:
    main()
except Exception as ex:
    logger.error("{} failed: {}".format(TOOL_TITLE, ex))
    output.print_md("**{} - unexpected error**".format(TOOL_TITLE))
    output.print_code(traceback.format_exc())
    forms.alert("Unexpected error:\n{}\n\nSee the output window for "
                "details.".format(ex), title=TOOL_TITLE)
