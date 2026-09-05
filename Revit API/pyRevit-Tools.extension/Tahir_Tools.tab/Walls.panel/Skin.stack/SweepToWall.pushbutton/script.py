# -*- coding: utf-8 -*-
"""
Convert LINKED wall sweeps into walls in the host model.

Pick as many wall sweeps in a linked model as you like, then choose one wall
type for the whole selection.  Every segment of every sweep is converted --
one new wall per wall a sweep is hosted on, with each sweep's corners MITRED
so its run continues around them instead of breaking.

Each new wall:

  - runs the full length of its host wall,
  - has its INTERIOR FINISH FACE on that host wall's EXTERIOR face, so it
    sits touching the wall and grows outwards from it,
  - takes its thickness from the wall type you pick, used exactly as is,
  - spans its own sweep's vertical envelope, so each sweep's run shares one
    base and height,
  - carries the sweep type's Type Mark in its BG_PROFILE parameter, so the
    profile a wall came from is recorded on it.

The host wall's exterior face is measured off its real solid, so the result
is right whatever that wall's own Location Line is set to and however
asymmetric its layer build-up is.

The linked model is never modified -- the sweep cannot be deleted from here,
because a link is read-only to the model that hosts it.

Cancelling either prompt abandons the run without creating or reporting
anything.
"""

__title__  = "Sweep\nWalls"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick any number of wall sweeps in a LINKED model, then choose one "
    "wall type for the whole selection.\n"
    "Every segment of every sweep is converted, one wall per wall a sweep "
    "is hosted on, mitred at the corners.\n"
    "Each wall runs the full length of its host wall, sits touching it "
    "with its interior finish face on the host wall's exterior face, and "
    "is as thick as the SKIN wall type you pick.\n"
    "Each sweep's run shares one base and height, from that sweep's "
    "vertical envelope, and every wall carries its sweep type's Type Mark "
    "in its BG_PROFILE parameter.\n"
    "The linked model is left untouched."
)

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    ElementId,
    Transaction,
    Wall,
    WallSweep,
    WallSweepType,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, script

from BG import wall_chain, wall_materials, wall_naming

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

# Shorter than this, in feet, and there is no wall worth making (~16 mm).
MIN_RUN_LENGTH = 0.05

# WallLocationLine values.
LOC_LINE_CENTRELINE           = 0
LOC_LINE_FINISH_FACE_INTERIOR = 3

# The sweep type's Type Mark is carried onto each new wall in this instance
# parameter.  Matched case-insensitively, so BG_PROFILE and BG_Profile are
# the same parameter as far as this tool is concerned.
BG_PROFILE_PARAM = "BG_PROFILE"


# ===============================================================================
# HELPERS
# ===============================================================================

def get_element_name(element):
    """Safely get the Name of any Revit element.

    Element.Name is not dependable from IronPython, so this falls back to
    the Type Name parameter the way the other wall tools do.
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

    LookupParameter is case-sensitive, which is a poor match for parameter
    names that are written one way in a shared parameter file and another in
    the model -- BG_PROFILE against BG_Profile, say.
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


def report(notes):
    """Print the notes table, or nothing when there is nothing to say."""
    if not notes:
        return
    output.print_md("### Sweep To Wall - {} note(s)".format(len(notes)))
    output.print_table(table_data=notes, columns=["Wall", "Note"])


# ===============================================================================
# SELECTION
# ===============================================================================

def sweep_is_convertible(sweep):
    """Return (ok, reason).  Reveals and vertical sweeps are not convertible."""
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


class LinkedSweepFilter(ISelectionFilter):
    """Allow horizontal wall SWEEPS inside a link, but not reveals.

    A reveal is a void cut into the wall, so turning one into a solid wall
    would model the opposite of what is there.
    """

    def AllowElement(self, elem):
        return True

    def AllowReference(self, ref, point):
        try:
            link_inst = doc.GetElement(ref.ElementId)
            link_doc  = link_inst.GetLinkDocument()
            if link_doc is None:
                return False
            elem = link_doc.GetElement(ref.LinkedElementId)
            if not isinstance(elem, WallSweep):
                return False
            return sweep_is_convertible(elem)[0]
        except Exception:
            return False


def pick_sweeps():
    """Pick wall sweeps in links until Esc.

    Returns a de-duplicated list of (RevitLinkInstance, WallSweep).  One
    wall type is then chosen for the whole selection.
    """
    picked = []
    seen   = set()
    filt   = LinkedSweepFilter()

    while True:
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.LinkedElement, filt,
                "Pick wall sweeps in a linked model (Esc when done)")
        except OperationCanceledException:
            break
        except Exception as ex:
            logger.debug("Sweep pick ended: {}".format(ex))
            break

        if ref is None:
            break

        key = (ref.ElementId.IntegerValue, ref.LinkedElementId.IntegerValue)
        if key in seen:
            continue
        seen.add(key)

        link_inst = doc.GetElement(ref.ElementId)
        link_doc  = link_inst.GetLinkDocument()
        picked.append((link_inst, link_doc.GetElement(ref.LinkedElementId)))

    return picked


def sweep_host_walls(sweep):
    """Return the walls *sweep* is hosted on, from the sweep's own document.

    A sweep knows its own hosts, so there is nothing to pick: every wall it
    runs along is converted in one go.
    """
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


# ===============================================================================
# SWEEP GEOMETRY
# ===============================================================================

def sweep_extent(sweep, transform):
    """Return (base_elev, height, material_name) measured off the sweep.

    Elevations come back in HOST coordinates.  Only the vertical envelope is
    taken from the sweep -- where each wall goes in plan comes from the host
    wall itself, which is both simpler and far more dependable than trying to
    work out which stretch of a sweep belongs to which of its host walls.
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

    return z_min, z_max - z_min, material_name


def sweep_type_mark(sweep):
    """Return the Type Mark of the sweep's type, or None when it is blank."""
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


def set_bg_profile(wall, value):
    """Write *value* into the wall's BG_PROFILE parameter.

    Returns False when the parameter is absent, read-only, or not a text
    parameter -- the caller reports that rather than failing the wall, since
    the wall itself is correct either way.
    """
    p = find_parameter(wall, BG_PROFILE_PARAM)
    if p is None or p.IsReadOnly:
        return False
    try:
        return bool(p.Set(value))
    except Exception:
        return False


# ===============================================================================
# WALL CREATION
# ===============================================================================

def set_location_line(wall, value):
    """Set the Location Line parameter on *wall*."""
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
        if p and p.HasValue and not p.IsReadOnly:
            p.Set(value)
        doc.Regenerate()
    except Exception:
        pass


def create_wall(curve, frame, wall_type, level, level_geom_elev,
                base_elev, height):
    """Create one wall of the chain along *curve* and return it.

    *curve* is the new wall's CENTRELINE, worked out beforehand so that its
    interior face lands on the host wall's exterior face.  Placing the
    centreline explicitly is what makes this dependable: relying on Revit's
    Location Line to shift the wall for us put the centreline on the host
    wall's face instead of the interior face.  The Location Line is set to
    'Finish Face: Interior' afterwards, which re-references the wall without
    moving it.
    """
    base_off = base_elev - level_geom_elev

    wall = Wall.Create(doc, curve, wall_type.Id, level.Id,
                       height, base_off, False, False)
    doc.Regenerate()

    # Make the curve mean the centreline, whatever the type's default was.
    set_location_line(wall, LOC_LINE_CENTRELINE)

    # Face the same way as the host wall, so 'interior' is the side against
    # it.  Reversing the curve keeps the same endpoints, so a mitred corner
    # survives the swap, and the centreline does not move either way.
    try:
        if frame.normal.DotProduct(wall.Orientation) < 0:
            doc.Delete(wall.Id)
            doc.Regenerate()
            wall = Wall.Create(doc, curve.CreateReversed(), wall_type.Id,
                               level.Id, height, base_off, False, False)
            doc.Regenerate()
            set_location_line(wall, LOC_LINE_CENTRELINE)
    except Exception:
        pass

    set_location_line(wall, LOC_LINE_FINISH_FACE_INTERIOR)
    return wall


# ===============================================================================
# MAIN
# ===============================================================================

class Job(object):
    """One sweep, measured and ready to build once a wall type is chosen.

    The frames and their exterior-face offsets are worked out up front, but
    the walls themselves cannot be until the type is known -- the centreline
    sits half the NEW wall's thickness beyond the host wall's face.
    """

    __slots__ = ("label", "frames", "offsets", "base_elev", "height",
                 "material", "type_mark")


def plan_sweep(link_inst, sweep):
    """Measure one sweep.  Returns (Job or None, notes)."""
    notes     = []
    transform = link_inst.GetTotalTransform()
    label     = "sweep id {}".format(sweep.Id.IntegerValue)

    ok, reason = sweep_is_convertible(sweep)
    if not ok:
        return None, [[label, reason]]

    walls = sweep_host_walls(sweep)
    if not walls:
        return None, [[label, "sweep is not hosted on any wall"]]

    base_elev, height, material_name = sweep_extent(sweep, transform)
    if base_elev is None or height is None or height < MIN_RUN_LENGTH:
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
            notes.append([host_label, "wall has no location curve"])
            continue
        if not frame.is_line:
            notes.append([host_label, "curved wall - not supported"])
            continue
        if frame.length < MIN_RUN_LENGTH:
            notes.append([host_label, "wall too short"])
            continue

        frames.append(frame)
        offsets.append(wall_chain.wall_exterior_offset(frame, transform))

    if not frames:
        return None, notes

    job = Job()
    job.label     = label
    job.frames    = frames
    job.offsets   = offsets
    job.base_elev = base_elev
    job.height    = height
    job.material  = material_name
    job.type_mark = sweep_type_mark(sweep)
    return job, notes


def summarise(values):
    """One value if they all agree, otherwise a count of how many differ."""
    unique = sorted(set(values))
    if len(unique) == 1:
        return unique[0]
    return "{} different".format(len(unique))


def build_jobs(jobs, wall_type, levels, notes):
    """Create the walls for every planned sweep.  Must run in a transaction."""
    half = wall_type.Width / 2.0

    for job in jobs:
        level, level_geom_elev = levels.below(job.base_elev)
        if level is None:
            notes.append([job.label, "no levels in this model"])
            continue

        # Interior face of the new wall on the exterior face of the host, so
        # its centreline sits half a thickness further out again.  Mitring is
        # per sweep: each sweep is its own run of walls.
        segments = [wall_chain.Segment(frame, offset + half)
                    for frame, offset in zip(job.frames, job.offsets)]
        curves   = wall_chain.mitre_segments(segments)

        unwritten = 0
        for segment, curve in zip(segments, curves):
            label = get_element_name(segment.frame.wall.WallType)
            if curve is None:
                notes.append([label, "could not build a curve for this wall"])
                continue
            try:
                wall = create_wall(curve, segment.frame, wall_type, level,
                                   level_geom_elev, job.base_elev, job.height)
            except Exception as ex:
                notes.append([label, "wall creation failed: {}".format(ex)])
                continue

            if job.type_mark and not set_bg_profile(wall, job.type_mark):
                unwritten += 1

        if unwritten:
            notes.append([job.label,
                          "{} could not be written on {} wall(s) - parameter "
                          "missing, read-only, or not a text parameter"
                          .format(BG_PROFILE_PARAM, unwritten)])


def main():
    levels = wall_chain.LevelFinder(doc)

    picks = pick_sweeps()
    if not picks:
        return          # cancelled: create nothing, report nothing

    # ---- Measure every sweep first, so one wall type can be chosen for the
    # ---- whole selection.
    notes = []
    jobs  = []
    for link_inst, sweep in picks:
        job, job_notes = plan_sweep(link_inst, sweep)
        notes.extend(job_notes)
        if job is not None:
            jobs.append(job)

    if not jobs:
        report(notes)
        return

    if not wall_materials.find_skin_wall_types(doc):
        report(notes + [["-", "no SKIN wall types in this model"]])
        return

    wall_type = wall_materials.pick_skin_wall_type(
        doc,
        "Pick the wall type for {} sweep(s)".format(len(jobs)),
        summarise([job.material or "<unknown>" for job in jobs]),
        summarise([wall_naming.feet_to_imperial(job.height) for job in jobs]))
    if wall_type is None:
        return          # cancelled: create nothing, report nothing

    t = Transaction(doc, "Convert wall sweeps to walls")
    t.Start()
    try:
        build_jobs(jobs, wall_type, levels, notes)
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    # Silence on success: only problems open the output window.
    report(notes)


main()
