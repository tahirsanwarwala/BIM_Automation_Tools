# -*- coding: utf-8 -*-
"""Create host-model skin walls and sweep walls from one linked selection.

Select any mix of walls and wall sweeps in a LINKED model -- by box or
by click, adding and removing until the selection is right, then Finish.

Each sweep becomes a wall in the host model, exactly as Sweep To Wall
makes one.
Each wall becomes one or more skin walls, exactly as Split Walls makes
them -- except that nobody picks a base and a top.

A wall's height comes from the sweeps running on it:

  * its top is the bottom of the sweep above it,
  * its base is the top of the sweep below it,
  * a sweep part-way up cuts it in two, and every level it crosses cuts
    it again, so no new wall crosses either,
  * with no sweep above or below, that end falls back to the source
    wall's own Base and Top Constraint.

Only sweeps you actually pick cut a wall, and only sweeps hosted on that
wall -- the link's own GetHostIds() decides, so a sweep running along a
neighbouring wall never shortens this one.

Nothing is rounded.  A band end has to sit exactly on a sweep face or a
level, or a gap opens up in the elevation.

Sweep wall types are automatic: a sweep whose type name or material name
says STONE gets SKIN_CAST STONE PROFILE_0' 2", one that says EIFS gets
SKIN_EIFS PROFILE_0' 2".  Anything the rule cannot read is asked about
once, per sweep type.  Wall skins resolve their type from the finish
material's Mark, as Split Walls does.

Where a sweep goes in plan is read off its own solid, not assumed to be
its host wall's full length.  A sweep that stops at an opening stops
there; one interrupted part-way along becomes two walls; and one that
steps down is built, and cuts, at the height it truly runs at on each
stretch.  Sweep walls at the same height and of the same type mitre into
each other at corners, whether or not they came from the same sweep, so
they trim instead of crossing.

Only the SWEEPS break at openings.  A skin wall runs the whole length of
the wall it came from, openings and all -- cutting it at them was tried
and taken back out.  Neither turns into a reveal: a sweep that wraps
into an opening is left ending at the jamb.

The linked model is never modified.
"""

__title__  = "Multi Wall\nCreation V1"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Select any mix of walls and wall sweeps in a LINKED model -- drag "
    "a box or click, then click Finish.\n"
    "Each sweep becomes a wall in the host model; each wall becomes "
    "skin walls that stop at the sweeps running on it.\n"
    "Walls are cut again at every level they cross.  A wall with no "
    "sweep above or below falls back to its own constraints.\n"
    "Sweep wall types come from STONE / EIFS in the sweep's type or "
    "material name; you are only asked about what that cannot read.\n"
    "The linked model is left untouched."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    Level,
    Line,
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

from Tahir import (
    wall_bands,
    wall_chain,
    wall_constraints,
    wall_materials,
    wall_miter,
    wall_naming,
    wall_skin,
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

TOOL_TITLE = "Multi Wall Creation V1"


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


class LinkedWallOrSweepFilter(ISelectionFilter):
    """Allow Basic Walls and horizontal wall sweeps inside a link.

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
            return False
        except Exception:
            return False


def pick_sources():
    """Select walls and sweeps in links, then Finish.

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

    Returns (wall_picks, sweep_picks), each a list of
    (RevitLinkInstance, element).  PickObjects de-duplicates its own
    result, so neither list can hold the same element twice.
    """
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement, LinkedWallOrSweepFilter(),
            "Select walls and wall sweeps in a linked model, then click "
            "Finish")
    except OperationCanceledException:
        return [], []
    except Exception as ex:
        logger.debug("Selection ended: {}".format(ex))
        return [], []

    if not refs:
        return [], []

    walls  = []
    sweeps = []
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

    return walls, sweeps


# ===========================================================================
# SWEEPS
# ===========================================================================

class SweepRun(object):
    """One continuous stretch of a sweep along one of its host walls.

    A sweep is not one wall's worth of anything.  It runs along several
    walls, it stops at the openings in them, and it can sit at a
    different height on each -- so the unit that becomes a wall is a
    RUN: one uninterrupted stretch, on one host wall, at one height.

    *along_min* and *along_max* are measured from the host wall frame's
    origin along its direction.  *wall_key* is the (link instance id,
    wall id) pair of the host wall, so band_walls can tell which wall
    this run cuts.
    """

    __slots__ = ("frame", "offset", "along_min", "along_max",
                 "base_z", "top_z", "wall_key")


class SweepJob(object):
    """One sweep, measured and ready to build once its type is known."""

    __slots__ = ("label", "sweep", "runs", "material", "type_mark",
                 "type_name", "wall_type")


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


def sweep_runs(sweep, transform, frames, wall_keys, openings):
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
                       for o_lo, o_hi, o_z_lo, o_z_hi in openings[idx]
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
                run.wall_key  = wall_keys[idx]
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

    frames    = []
    wall_keys = []
    openings  = []
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
        # Keyed on (link instance id, linked element id), not the bare
        # element id: pick_sources() explicitly anticipates a selection
        # spanning two links (or two instances of the same link), and a
        # bare element id can collide across them.  Do not "simplify"
        # this back to just the element id -- plan_wall's job.wall_id is
        # keyed the same way, and band_walls's membership test compares
        # the two.
        wall_key = (link_inst.Id.IntegerValue, host.Id.IntegerValue)
        wall_keys.append(wall_key)
        openings.append(cached_wall_openings(
            wall_key, host, transform, frame.origin, frame.direction))

    if not frames:
        return None, notes

    runs, material_name = sweep_runs(
        sweep, transform, frames, wall_keys, openings)
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
# WALLS
# ===========================================================================

class WallJob(object):
    """One linked wall, measured and ready to band."""

    __slots__ = ("label", "wall_id", "cs", "source_doc", "loc_curve",
                 "orientation", "total_width", "loc_line", "loc_to_ext",
                 "base_z", "top_z", "structural", "bands")


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


def cached_wall_openings(wall_key, wall, link_tf, origin, direction):
    """wall_openings, remembered per wall for the life of the run.

    Both callers -- plan_sweep for a sweep's host wall, and plan_wall
    for a picked wall -- measure from the same frame origin and
    direction, derived the same way from the same transformed location
    curve, so one cached list means the same thing to each.  Change how
    either derives its frame and this cache starts handing back
    intervals measured against the other one.
    """
    if wall_key not in _OPENING_CACHE:
        _OPENING_CACHE[wall_key] = wall_openings(
            wall, link_tf, origin, direction)
    return _OPENING_CACHE[wall_key]


def wall_openings(wall, link_tf, origin, direction):
    """Return the openings in *wall* as (along_lo, along_hi, z_lo, z_hi).

    Measured in the wall's own frame: *along* from *origin* along
    *direction*, both already in host coordinates.  A skin wall stops at
    these the way the sweeps do, so a band does not run solid across a
    window.

    Along the wall the extent is the ROUGH OPENING, the void actually
    cut in the wall, so a new wall stops on the same line as the wall
    behind it.  Vertically it is the insert's whole solid, which errs
    the generous way on an arched head or a projecting sill and is only
    ever asked whether an opening reaches a given course.  See
    _insert_extent for why the two ends are measured differently.
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
        if insert is None:
            continue
        extent = _insert_extent(insert, link_tf, origin, direction)
        if extent is not None:
            found.append(extent)

    return found


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
    if not isinstance(raw_curve, Line):
        return None, [[label, "curved wall - not supported"]]

    pt0 = link_tf.OfPoint(raw_curve.GetEndPoint(0))
    pt1 = link_tf.OfPoint(raw_curve.GetEndPoint(1))
    if pt0.DistanceTo(pt1) < MIN_RUN_LENGTH:
        return None, [[label, "wall too short"]]
    loc_curve = Line.CreateBound(pt0, pt1)

    # Rotate the orientation vector: transforming origin+direction and
    # subtracting the transformed origin isolates the rotation.
    raw_orient  = wall.Orientation
    origin_tf   = link_tf.OfPoint(XYZ.Zero)
    orient_tip  = link_tf.OfPoint(
        XYZ(raw_orient.X, raw_orient.Y, raw_orient.Z))
    orientation = XYZ(orient_tip.X - origin_tf.X,
                      orient_tip.Y - origin_tf.Y,
                      orient_tip.Z - origin_tf.Z).Normalize()

    loc_to_ext = None
    try:
        meas = wall_skin.measure_face_offsets(
            wall, pt0, orientation, link_tf)
        if meas:
            loc_to_ext = meas[0]
    except Exception as ex:
        logger.debug("Face measurement failed on {}: {}".format(label, ex))

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
    # on SweepRun.wall_key in plan_sweep for why the link id is part of
    # the key.  band_walls compares the two directly.
    job.wall_id     = (link_inst.Id.IntegerValue, wall.Id.IntegerValue)
    job.cs          = cs
    job.source_doc  = link_doc
    job.loc_curve   = loc_curve
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
    return job, notes_none()


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

    The STONE / EIFS name rule answers most of them outright.  What it
    cannot read -- and any profile whose named type is missing from this
    model -- falls back to one dialog per sweep TYPE, so a run with
    twenty identical sweeps asks once.

    Returns the jobs that ended up with a type.  A sweep left without
    one is dropped: it neither becomes a wall nor cuts one, and it is
    reported.
    """
    asked = {}          # sweep type name -> WallType or None
    resolved = []

    for job in sweep_jobs:
        wanted = wall_bands.sweep_wall_type_name(job.type_name, job.material)

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

def band_walls(wall_jobs, sweep_jobs, levels, notes):
    """Work out the bands each wall is cut into.

    Two things cut a wall.  The sweeps hosted on it, which come from the
    link's own GetHostIds() so a sweep on a neighbouring wall is never
    mistaken for one on this one; and every level a leftover stretch
    crosses, because a wall crossing a level is the one thing the house
    rule never allows.

    Nothing is rounded: wall_constraints.plan_wall is called with
    allow_round=False so a band end stays exactly on the sweep face or
    the level that produced it.  Rounding it to the nearest inch would
    open a gap between the band and the sweep wall above it.

    Fills job.bands in place.
    """
    for job in wall_jobs:
        # One cutter per RUN, not per sweep: a run knows which wall it
        # lies on and how high it sits there, so a sweep that steps down
        # cuts each of its walls at the height it actually runs at.
        cutters = [(run.base_z, run.top_z)
                   for sweep_job in sweep_jobs
                   for run in sweep_job.runs
                   if run.wall_key == job.wall_id]

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


def build_sweep_walls(sweep_jobs, levels, notes):
    """Create the walls for every measured sweep.  Inside a transaction.

    Mitring is across sweeps, not within one.  Two sweeps meeting at a
    building corner are two separate picks, and mitring each on its own
    left them running past each other and crossing -- so every run from
    every sweep is gathered first and grouped by the height it sits at
    AND the wall type it resolved to.  A stone band then trims into a
    stone band, an EIFS cornice into an EIFS cornice, and neither into
    the other or into a course at a different height.
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
        return

    groups = {}
    span_ids = wall_bands.group_indices(
        [(item["run"].base_z, item["run"].top_z) for item in items])
    for item, span_id in zip(items, span_ids):
        groups.setdefault(
            (span_id, item["job"].wall_type.Id.IntegerValue), []).append(item)

    unwritten = {}
    no_level  = {}
    for group in groups.values():
        try:
            curves = wall_chain.mitre_segments(
                [item["segment"] for item in group])
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

            try:
                wall = create_sweep_wall(
                    curve, segment.frame, job.wall_type, band)
            except Exception as ex:
                note(notes, label, "wall creation failed: {}".format(ex))
                continue

            if not apply_bg_level(wall, band):
                no_level[job.label] = no_level.get(job.label, 0) + 1
            if job.type_mark and not set_bg_profile(wall, job.type_mark):
                unwritten[job.label] = unwritten.get(job.label, 0) + 1

    report_unwritten(notes, unwritten, BG_PROFILE_PARAM)
    report_unwritten(notes, no_level, BG_LEVEL_PARAM)


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

            if key in executed:
                skin_type = executed[key]
            else:
                skin_type = wall_materials.execute_skin_wall_type_plan(
                    doc, plan, _material_of_layer(job.cs, 0, job.source_doc),
                    job.source_doc)
                executed[key] = skin_type

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
        if len(items) < 2:
            continue

        try:
            originals = []
            offsets   = []
            zs        = []
            for item in items:
                sc = item["curve"]
                s0, s1 = sc.GetEndPoint(0), sc.GetEndPoint(1)
                originals.append(item["original"])
                offsets.append(((s0.X, s0.Y), (s1.X, s1.Y)))
                zs.append((s0.Z, s1.Z))

            mitred = wall_miter.miter_chain(originals, offsets)

            for idx, item in enumerate(items):
                (x0, y0), (x1, y1) = mitred[idx]
                z0, z1 = zs[idx]
                item["curve"] = Line.CreateBound(XYZ(x0, y0, z0),
                                                 XYZ(x1, y1, z1))
        except Exception as ex:
            note(notes, "elevation group {}".format(key),
                 "could not mitre corners for this band - left unmitred: "
                 "{}".format(ex))
            continue


def build_bands(prepared, notes):
    """Create one skin wall per prepared band.  Inside a transaction."""
    no_level = {}
    for item in prepared:
        job  = item["job"]
        band = item["band"]
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
            if not apply_bg_level(wall, band):
                no_level[job.label] = no_level.get(job.label, 0) + 1
        except Exception as ex:
            note(notes, job.label,
                 "band {} to {} failed: {}".format(
                     feet_text(band["base_z"]), feet_text(band["top_z"]),
                     ex))

    report_unwritten(notes, no_level, BG_LEVEL_PARAM)


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
    wall_picks, sweep_picks = pick_sources()
    if not wall_picks and not sweep_picks:
        return          # cancelled: create nothing, report nothing

    notes      = []
    sweep_jobs = []
    wall_jobs  = []

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

    band_walls(wall_jobs, sweep_jobs, levels, notes)

    t = Transaction(doc, "Multi Wall Creation")
    t.Start()
    try:
        build_sweep_walls(sweep_jobs, levels, notes)

        prepared = prepare_bands(wall_jobs, skin_plans, notes)
        mitre_prepared(prepared, notes)
        build_bands(prepared, notes)

        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

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
