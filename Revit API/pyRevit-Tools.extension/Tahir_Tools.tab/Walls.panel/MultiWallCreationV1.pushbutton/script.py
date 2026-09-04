# -*- coding: utf-8 -*-
"""Create host-model skin walls and sweep walls from one linked selection.

Pick any mix of walls and wall sweeps in a LINKED model.  Each sweep
becomes a wall in the host model, exactly as Sweep To Wall makes one.
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

KNOWN LIMITATION: a sweep is measured as one vertical envelope across
all its host walls, as Sweep To Wall measures it.  A stepped sweep that
runs at different heights on different walls is therefore built, and
cuts, at its overall extent.  Split such a sweep in the link first.

The linked model is never modified.
"""

__title__  = "Multi Wall\nCreation V1"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick any mix of walls and wall sweeps in a LINKED model, then "
    "press Esc.\n"
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
    wall_naming,
    wall_skin,
)

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

# Shorter than this, in feet, and there is no wall worth making (~16 mm).
MIN_RUN_LENGTH = 0.05

# WallLocationLine values.
LOC_LINE_CENTRELINE           = 0
LOC_LINE_FINISH_FACE_INTERIOR = 3

# The sweep type's Type Mark is carried onto each sweep wall here.
BG_PROFILE_PARAM = "BG_PROFILE"

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
    """Pick walls and sweeps in links until Esc.

    Returns (wall_picks, sweep_picks), each a de-duplicated list of
    (RevitLinkInstance, element).
    """
    walls  = []
    sweeps = []
    seen   = set()
    filt   = LinkedWallOrSweepFilter()

    while True:
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.LinkedElement, filt,
                "Pick walls and wall sweeps in a linked model "
                "(Esc when done)")
        except OperationCanceledException:
            break
        except Exception as ex:
            logger.debug("Pick ended: {}".format(ex))
            break

        if ref is None:
            break

        key = (ref.ElementId.IntegerValue, ref.LinkedElementId.IntegerValue)
        if key in seen:
            continue
        seen.add(key)

        link_inst = doc.GetElement(ref.ElementId)
        link_doc  = link_inst.GetLinkDocument()
        elem      = link_doc.GetElement(ref.LinkedElementId)

        if isinstance(elem, WallSweep):
            sweeps.append((link_inst, elem))
        elif isinstance(elem, Wall):
            walls.append((link_inst, elem))

    return walls, sweeps


# ===========================================================================
# SWEEPS
# ===========================================================================

class SweepJob(object):
    """One sweep, measured and ready to build once its type is known."""

    __slots__ = ("label", "sweep", "frames", "offsets", "host_ids",
                 "base_z", "top_z", "material", "type_mark", "type_name",
                 "wall_type")


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


def sweep_extent(sweep, transform):
    """Return (base_z, top_z, material_name) measured off the sweep.

    Elevations come back in HOST coordinates.  Only the vertical
    envelope is taken from the sweep -- where each wall goes in plan
    comes from the host wall itself, which is far more dependable than
    working out which stretch of a sweep belongs to which host wall.
    """
    z_min = z_max = None
    areas = {}

    for sol in wall_chain.iter_solids(sweep):
        for edge in sol.Edges:
            try:
                for pt in edge.Tessellate():
                    z = transform.OfPoint(pt).Z
                    if z_min is None or z < z_min:
                        z_min = z
                    if z_max is None or z > z_max:
                        z_max = z
            except Exception:
                continue

        for face in sol.Faces:
            try:
                mid = face.MaterialElementId
                if mid is None or mid == ElementId.InvalidElementId:
                    continue
                areas[mid.IntegerValue] = \
                    areas.get(mid.IntegerValue, 0.0) + face.Area
            except Exception:
                continue

    if z_min is None:
        return None, None, None

    material_name = None
    if areas:
        best = max(areas.keys(), key=lambda k: areas[k])
        material_name = get_element_name(
            sweep.Document.GetElement(ElementId(best)))

    return z_min, z_max, material_name


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

    base_z, top_z, material_name = sweep_extent(sweep, transform)
    if base_z is None or (top_z - base_z) < MIN_RUN_LENGTH:
        return None, [[label,
                       "no usable sweep geometry (check the link's view "
                       "detail level)"]]

    frames  = []
    offsets = []
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
        offsets.append(wall_chain.wall_exterior_offset(frame, transform))

    if not frames:
        return None, notes

    job = SweepJob()
    job.label     = label
    job.sweep     = sweep
    job.frames    = frames
    job.offsets   = offsets
    job.host_ids  = set(w.Id.IntegerValue for w in walls)
    job.base_z    = base_z
    job.top_z     = top_z
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
    job.wall_id     = wall.Id.IntegerValue
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

    notes       = []
    sweep_jobs  = []
    wall_jobs   = []

    for link_inst, sweep in sweep_picks:
        job, job_notes = plan_sweep(link_inst, sweep)
        notes.extend(job_notes)
        if job is not None:
            sweep_jobs.append(job)

    for link_inst, wall in wall_picks:
        job, job_notes = plan_wall(link_inst, wall)
        notes.extend(job_notes)
        if job is not None:
            wall_jobs.append(job)

    # TEMPORARY diagnostic, replaced in Task 7 by the build.
    rows = []
    for job in sweep_jobs:
        rows.append([job.label,
                     "sweep {} to {} on {} wall(s), type '{}'".format(
                         feet_text(job.base_z), feet_text(job.top_z),
                         len(job.frames), job.type_name)])
    for job in wall_jobs:
        rows.append([job.label,
                     "wall {} to {}".format(
                         feet_text(job.base_z), feet_text(job.top_z))])
    output.print_md("### {} - measured".format(TOOL_TITLE))
    output.print_table(table_data=rows, columns=["Element", "Measured"])

    report(notes)


try:
    main()
except Exception as ex:
    logger.error("{} failed: {}".format(TOOL_TITLE, ex))
    output.print_md("**{} - unexpected error**".format(TOOL_TITLE))
    output.print_code(traceback.format_exc())
    forms.alert("Unexpected error:\n{}\n\nSee the output window for "
                "details.".format(ex), title=TOOL_TITLE)
