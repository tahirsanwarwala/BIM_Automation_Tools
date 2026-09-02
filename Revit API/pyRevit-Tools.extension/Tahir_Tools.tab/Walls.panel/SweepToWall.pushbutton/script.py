# -*- coding: utf-8 -*-
"""
Convert LINKED wall sweeps into basic walls in the host model.

Pick one or more wall sweeps in a linked Revit model.  For each sweep a
new Basic wall is created in the HOST model that:

  - follows the same path as the sweep (arcs stay arcs, because the path
    is derived from the sweep's own host wall curve),
  - spans the sweep's own vertical extent (bottom -> top of its solid),
  - is aligned so its EXTERIOR FINISH FACE sits on the sweep's outermost
    face, away from the host wall, and carries Location Line =
    'Finish Face: Exterior'.

Aligning to the outer face rather than the inner one means a run of
sweeps of differing depths still produces walls sharing one outer plane.

The wall type is always chosen by the user, once per distinct sweep
material: the prompt lists the host model's SKIN wall types and names the
linked finish material and its measured thickness.  Whatever is picked is
used exactly as it is -- no wall type or material is ever created, and
the wall's thickness is that of the type picked.

Cancelling any of those prompts abandons the whole run without creating
anything and without reporting anything.

The linked model is never modified.
"""

__title__  = "Sweep\nTo Wall"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick wall sweeps in a LINKED model and create a Basic wall in the "
    "host model for each one.\n"
    "The new wall follows the sweep's path, spans the sweep's own height, "
    "and has its exterior finish face flush with the sweep's OUTER face "
    "(away from the host wall).\n"
    "Location Line is set to 'Finish Face: Exterior'.\n"
    "You pick the SKIN wall type once per sweep material; it is used as "
    "is, so the wall is as thick as the type you pick.\n"
    "The linked model is left untouched."
)

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    ElementTransformUtils,
    FilteredElementCollector,
    GeometryInstance,
    Level,
    Options,
    Solid,
    Transaction,
    Transform,
    ViewDetailLevel,
    Wall,
    WallSweep,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, script
from Tahir import wall_materials, wall_naming

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

MIN_RUN_LENGTH = 0.05    # feet (~16 mm); shorter runs are skipped
LEVEL_TOL      = 1e-4    # feet, when matching a level at the sweep's base

# WallLocationLine value for 'Finish Face: Exterior'.
LOC_LINE_FINISH_FACE_EXTERIOR = 2


# ===============================================================================
# NAME / UNIT HELPERS
# ===============================================================================

def get_element_name(element):
    """Safely get the Name of any Revit element."""
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


# ===============================================================================
# SELECTION
# ===============================================================================

class LinkedWallSweepFilter(ISelectionFilter):
    """Allow only WallSweep elements living inside a linked model."""

    def AllowElement(self, elem):
        return True

    def AllowReference(self, ref, point):
        try:
            link_inst = doc.GetElement(ref.ElementId)
            link_doc  = link_inst.GetLinkDocument()
            if link_doc is None:
                return False
            elem = link_doc.GetElement(ref.LinkedElementId)
            return isinstance(elem, WallSweep)
        except Exception:
            return False


def pick_linked_sweeps():
    """Repeatedly pick linked wall sweeps until the user presses Esc.

    Returns a list of (RevitLinkInstance, WallSweep) pairs, de-duplicated.
    """
    picked = []
    seen   = set()
    filt   = LinkedWallSweepFilter()

    while True:
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.LinkedElement, filt,
                "Pick a wall sweep in a linked model (Esc when done)")
        except OperationCanceledException:
            break
        except Exception as ex:
            logger.debug("Pick ended: {}".format(ex))
            break

        if ref is None:
            break

        link_inst = doc.GetElement(ref.ElementId)
        link_doc  = link_inst.GetLinkDocument()
        sweep     = link_doc.GetElement(ref.LinkedElementId)

        key = (ref.ElementId.IntegerValue, ref.LinkedElementId.IntegerValue)
        if key in seen:
            continue
        seen.add(key)
        picked.append((link_inst, sweep))

    return picked


# ===============================================================================
# MATERIALS AND WALL TYPES
# ===============================================================================

def sweep_material(sweep, link_doc):
    """Return (name, Material) for the material covering most of *sweep*'s
    faces, or (None, None) if it could not be determined.

    Read off the real geometry rather than the sweep type's parameters, so
    it reflects what the sweep actually looks like in the link.
    """
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Fine

    areas = {}
    try:
        geo_elem = sweep.get_Geometry(opts)
    except Exception:
        geo_elem = None
    if geo_elem is None:
        return None, None

    for gobj in geo_elem:
        solids = []
        if isinstance(gobj, Solid):
            solids.append(gobj)
        elif isinstance(gobj, GeometryInstance):
            try:
                for g2 in gobj.GetInstanceGeometry():
                    if isinstance(g2, Solid):
                        solids.append(g2)
            except Exception:
                continue

        for sol in solids:
            for face in sol.Faces:
                try:
                    mid = face.MaterialElementId
                    if mid is None or mid == ElementId.InvalidElementId:
                        continue
                    areas[mid.IntegerValue] = \
                        areas.get(mid.IntegerValue, 0.0) + face.Area
                except Exception:
                    continue

    if not areas:
        return None, None

    best_id = max(areas.keys(), key=lambda k: areas[k])
    mat = link_doc.GetElement(ElementId(best_id))
    if mat is None:
        return None, None
    return mat.Name, mat


# ===============================================================================
# GEOMETRY HELPERS
# ===============================================================================

def iter_solid_points(elem, transform=None):
    """Yield every tessellated vertex of *elem*'s solid geometry.

    If *transform* is given (linked models), points are converted into
    host world coordinates.
    """
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Fine

    geo_elem = elem.get_Geometry(opts)
    if geo_elem is None:
        return

    for gobj in geo_elem:
        solids = []
        if isinstance(gobj, Solid):
            solids.append(gobj)
        elif isinstance(gobj, GeometryInstance):
            try:
                for g2 in gobj.GetInstanceGeometry():
                    if isinstance(g2, Solid):
                        solids.append(g2)
            except Exception:
                continue

        for sol in solids:
            try:
                if sol.Volume <= 0:
                    continue
            except Exception:
                continue
            for edge in sol.Edges:
                try:
                    for pt in edge.Tessellate():
                        yield transform.OfPoint(pt) if transform else pt
                except Exception:
                    continue


def measure_face_offsets(elem, ref_pt, orient, transform=None):
    """Return (hi, lo): the extreme signed distances from *ref_pt* along
    *orient* across the element's solid, or None if unmeasurable.
    """
    try:
        n = orient.Normalize()
    except Exception:
        return None

    hi = None
    lo = None
    for pt in iter_solid_points(elem, transform):
        d = (pt - ref_pt).DotProduct(n)
        if hi is None or d > hi:
            hi = d
        if lo is None or d < lo:
            lo = d

    if hi is None or lo is None:
        return None
    return hi, lo


def project_base_elevation(target_doc):
    """Return the offset between level elevations and model geometry.

    Levels report their elevation relative to the Project Base Point, while
    solid geometry and pick points come back in internal model coordinates.
    When the base point sits at elevation 0 the two spaces coincide and this
    returns 0.0, so the conversion is harmless in ordinary projects.

    Measured example: a project base point at 895 ft makes LEVEL 04 report
    995 ft while its geometry sits at 100 ft.
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


def find_level_below(elevation):
    """Return (Level, geometry-space elevation) for the host level at or
    below *elevation*, else the lowest level.  Returns (None, 0.0) if the
    host model has no levels.

    *elevation* is in geometry space (the space sweep solids live in), so
    each level's reported elevation is converted into that same space
    before comparing -- otherwise walls land on the wrong level in any
    project whose Project Base Point is not at zero.
    """
    levels = list(FilteredElementCollector(doc).OfClass(Level))
    if not levels:
        return None, 0.0

    delta = project_base_elevation(doc)
    pairs = [(lvl, lvl.Elevation - delta) for lvl in levels]

    below = [p for p in pairs if p[1] <= elevation + LEVEL_TOL]
    if below:
        return max(below, key=lambda p: p[1])
    return min(pairs, key=lambda p: p[1])


def offset_curve(curve, distance, normal):
    """Offset *curve* sideways by *distance* along *normal*.

    Handles both lines and arcs.  Curve.CreateOffset's sign convention
    depends on the curve's direction, so the result is verified against
    *normal* and rebuilt with the opposite sign when it went the wrong way.
    """
    if abs(distance) < 1e-9:
        return curve

    try:
        result  = curve.CreateOffset(distance, XYZ.BasisZ)
        mid_old = curve.Evaluate(0.5, True)
        mid_new = result.Evaluate(0.5, True)
        if (mid_new - mid_old).DotProduct(normal) < 0:
            result = curve.CreateOffset(-distance, XYZ.BasisZ)
        return result
    except Exception:
        # Fall back to a straight translation (exact for lines).
        vec = XYZ(normal.X * distance,
                  normal.Y * distance,
                  normal.Z * distance)
        return curve.CreateTransformed(Transform.CreateTranslation(vec))


# ===============================================================================
# SWEEP MEASUREMENT
# ===============================================================================

class SweepRun(object):
    """One run of a sweep along one of its host walls, in host coordinates."""

    __slots__ = ("sweep", "host_wall_name", "host_wall_type_name",
                 "material_name", "link_material", "link_doc",
                 "base_curve", "orientation", "front_offset",
                 "outward_sign", "measured_thickness", "base_elev", "height")

    def exterior_face_offset(self):
        """Signed distance from the host wall's centreline to the plane the
        new wall's exterior finish face must land on -- the sweep's outermost
        face, away from the host wall.
        """
        return self.front_offset

    def path_curve(self, wall_width):
        """Centreline for a wall of *wall_width* whose EXTERIOR FINISH FACE
        sits on the sweep's outer face, the wall growing back towards the
        host wall from there.
        """
        centre_off = self.front_offset - self.outward_sign * (wall_width / 2.0)
        if centre_off >= 0:
            return offset_curve(self.base_curve, centre_off, self.orientation)
        return offset_curve(self.base_curve, -centre_off,
                            self.orientation.Negate())


def assign_points_to_walls(points, wall_curves):
    """Group *points* by the wall curve they lie closest to in plan.

    Returns {index_of_curve: [(point, projection_result), ...]}.
    """
    buckets = {}
    for pt in points:
        best_i    = None
        best_dist = None
        best_res  = None
        for i, curve in enumerate(wall_curves):
            try:
                res = curve.Project(pt)
            except Exception:
                continue
            if res is None:
                continue
            v = res.XYZPoint - pt
            dist = (v.X * v.X + v.Y * v.Y) ** 0.5   # plan distance only
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_i    = i
                best_res  = res
        if best_i is not None:
            buckets.setdefault(best_i, []).append((pt, best_res))
    return buckets


def build_runs(link_inst, sweep):
    """Measure *sweep* and return (runs, skip_reason).

    On success skip_reason is None; on failure runs is an empty list.
    """
    link_doc = link_inst.GetLinkDocument()
    tf       = link_inst.GetTotalTransform()

    try:
        info = sweep.GetWallSweepInfo()
        if info is not None and info.IsVertical:
            return [], "vertical sweep - not supported"
    except Exception:
        pass

    try:
        host_ids = list(sweep.GetHostIds())
    except Exception:
        host_ids = []
    if not host_ids:
        return [], "sweep has no host wall"

    host_walls   = []
    wall_curves  = []
    orientations = []
    for wid in host_ids:
        w = link_doc.GetElement(wid)
        if not isinstance(w, Wall):
            continue
        loc = w.Location
        if loc is None or not hasattr(loc, "Curve"):
            continue
        host_walls.append(w)
        wall_curves.append(loc.Curve.CreateTransformed(tf))
        orientations.append(tf.OfVector(w.Orientation).Normalize())

    if not wall_curves:
        return [], "host wall has no location curve"

    points = list(iter_solid_points(sweep, tf))
    if not points:
        return [], "no solid geometry (check link view detail level)"

    buckets = assign_points_to_walls(points, wall_curves)
    if not buckets:
        return [], "could not project sweep onto its host wall"

    material_name, link_material = sweep_material(sweep, link_doc)

    runs = []
    for i, pts in buckets.items():
        curve  = wall_curves[i]
        normal = orientations[i]

        raw_params = [res.Parameter for _pt, res in pts]
        raw_min, raw_max = min(raw_params), max(raw_params)

        offsets = [(pt - res.XYZPoint).DotProduct(normal) for pt, res in pts]
        off_min, off_max = min(offsets), max(offsets)

        zs = [pt.Z for pt, _res in pts]
        z_min, z_max = min(zs), max(zs)

        try:
            seg = curve.Clone()
            seg.MakeBound(raw_min, raw_max)
            if seg.Length < MIN_RUN_LENGTH:
                continue
        except Exception:
            continue

        if (z_max - z_min) < MIN_RUN_LENGTH:
            continue

        # The near face is the sweep face closest to the host wall's
        # centreline; the far face is the outermost one, which is what the new
        # wall is aligned to.
        if abs(off_min) <= abs(off_max):
            near, far = off_min, off_max
        else:
            near, far = off_max, off_min
        outward = 1.0 if (far - near) >= 0 else -1.0

        host_wall = host_walls[i]
        run = SweepRun()
        run.sweep               = sweep
        run.host_wall_name      = get_element_name(host_wall)
        run.host_wall_type_name = get_element_name(host_wall.WallType)
        run.material_name       = material_name
        run.link_material       = link_material
        run.link_doc            = link_doc
        run.orientation         = normal
        run.measured_thickness  = abs(off_max - off_min)
        run.base_elev           = z_min
        run.height              = z_max - z_min
        run.base_curve          = seg
        run.front_offset        = far
        run.outward_sign        = outward
        runs.append(run)

    if not runs:
        return [], "sweep run too short to build a wall"
    return runs, None


# ===============================================================================
# WALL CREATION
# ===============================================================================

def align_exterior_face(wall, run):
    """Move *wall* so its exterior face lands exactly on the sweep's outer face.

    Rather than trusting the offset arithmetic, this measures the wall's real
    solid and cancels whatever perpendicular error is left.  It is measured
    against the host wall's own curve, the same reference the sweep offsets
    were taken from.
    """
    try:
        n      = run.orientation.Normalize()
        ref_pt = run.base_curve.GetEndPoint(0)

        meas = measure_face_offsets(wall, ref_pt, n)
        if not meas:
            return

        hi, lo = meas
        # The exterior face is whichever extreme lies outward from the host.
        actual = hi if run.outward_sign >= 0 else lo
        err    = actual - run.exterior_face_offset()

        if abs(err) > 1e-7:
            move_vec = XYZ(n.X * -err, n.Y * -err, n.Z * -err)
            ElementTransformUtils.MoveElement(doc, wall.Id, move_vec)
            doc.Regenerate()
    except Exception as ex:
        logger.debug("Could not align new wall to the sweep face: {}"
                     .format(ex))


def set_location_line(wall, value):
    """Set the Location Line parameter on *wall*."""
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
        if p and p.HasValue and not p.IsReadOnly:
            p.Set(value)
        doc.Regenerate()
    except Exception:
        pass


def create_wall_for_run(run, wall_type, level, level_geom_elev):
    """Create the host-model wall for one sweep run and return it.

    *level_geom_elev* is the level's elevation expressed in geometry space,
    so it is directly comparable with the sweep's measured base elevation.
    """
    base_off = run.base_elev - level_geom_elev

    # Wall.Create places the CENTRELINE on the curve it is given, whatever the
    # type's Location Line default, so the curve handed over is a centreline.
    curve = run.path_curve(wall_type.Width)

    wall = Wall.Create(doc, curve, wall_type.Id, level.Id,
                       run.height, base_off, False, False)
    doc.Regenerate()
    set_location_line(wall, 0)   # 0 = Wall Centerline, matching *curve*

    # Match the host wall's exterior side; re-create reversed if flipped.  The
    # exterior side has to agree with the host wall before the Location Line
    # can be switched to the exterior finish face.
    try:
        if run.orientation.DotProduct(wall.Orientation) < 0:
            doc.Delete(wall.Id)
            doc.Regenerate()
            wall = Wall.Create(doc, curve.CreateReversed(),
                               wall_type.Id, level.Id, run.height,
                               base_off, False, False)
            doc.Regenerate()
            set_location_line(wall, 0)
    except Exception:
        pass

    # Switch to the requested Location Line, then align: measuring after the
    # switch means the wall ends up correct whether or not Revit shifted the
    # geometry when the reference changed.
    set_location_line(wall, LOC_LINE_FINISH_FACE_EXTERIOR)
    align_exterior_face(wall, run)
    return wall


# ===============================================================================
# MAIN
# ===============================================================================

def run_material_key(run):
    """Key a run by its sweep material, so each material is asked about once."""
    return run.material_name or "<none>"


def report_skipped(skipped):
    """Print the skipped table, or nothing at all when there is nothing to say."""
    if not skipped:
        return
    output.print_md("### Sweep To Wall - {} skipped".format(len(skipped)))
    output.print_table(
        table_data=skipped,
        columns=["Sweep Id", "Link", "Reason"])


def main():
    picks = pick_linked_sweeps()
    if not picks:
        return          # nothing picked is a cancellation; stay silent

    skipped = []

    # ---- Measure everything first; both the geometry reads and any type
    # ---- prompts stay outside the transaction.
    all_runs = []
    for link_inst, sweep in picks:
        link_name = get_element_name(link_inst)
        try:
            runs, reason = build_runs(link_inst, sweep)
        except Exception as ex:
            runs, reason = [], "measurement failed: {}".format(ex)

        if reason:
            skipped.append([sweep.Id.IntegerValue, link_name, reason])
            continue
        for run in runs:
            all_runs.append((run, link_name))

    if not all_runs:
        report_skipped(skipped)
        return

    if not wall_materials.find_skin_wall_types(doc):
        report_skipped([[r.sweep.Id.IntegerValue, n,
                         "no SKIN wall types in the host model"]
                        for r, n in all_runs] + skipped)
        return

    # ---- Ask for the wall type once per sweep material, before the
    # ---- transaction opens.  Cancelling any prompt abandons the run.
    chosen = {}
    for run, _link_name in all_runs:
        key = run_material_key(run)
        if key in chosen:
            continue

        picked = wall_materials.pick_skin_wall_type(
            doc, "Pick the wall type for this sweep",
            run.material_name or "<unknown>",
            wall_naming.feet_to_imperial(run.measured_thickness))

        if picked is None:
            return      # cancelled: create nothing, report nothing
        chosen[key] = picked

    t = Transaction(doc, "Convert linked wall sweeps to walls")
    t.Start()
    try:
        for run, link_name in all_runs:
            sweep_id  = run.sweep.Id.IntegerValue
            wall_type = chosen[run_material_key(run)]

            level, level_geom_elev = find_level_below(run.base_elev)
            if level is None:
                skipped.append([sweep_id, link_name,
                                "no levels in host model"])
                continue
            try:
                wall = create_wall_for_run(
                    run, wall_type, level, level_geom_elev)
            except Exception as ex:
                skipped.append([sweep_id, link_name,
                                "wall creation failed: {}".format(ex)])
                continue

        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    # Silence on success: only problems are worth opening the output window
    # for, so a clean run shows nothing at all.
    report_skipped(skipped)


main()
