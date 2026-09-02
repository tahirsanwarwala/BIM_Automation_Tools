# -*- coding: utf-8 -*-
"""
Create SKIN walls from compound walls

Supports walls in the host model AND walls in a linked Revit model.

For each selected compound wall, creates ONE new wall in the HOST model:
  - SKIN wall: Outermost exterior finish layer only

The SKIN wall is placed so that its outer face coincides exactly with the
exterior face of the original wall.  That exterior face is measured from
the original wall's real solid geometry, so asymmetric build-ups and any
Location Line setting are handled correctly.

The original wall is never modified or deleted — host or linked.
"""

__title__  = "Split\nWalls"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Run from an ELEVATION or SECTION view.\n"
    "Select one or more compound walls (host OR linked model), then click\n"
    "the elements marking the base and top of the new walls.\n"
    "For each wall a single SKIN wall is created:\n"
    "- SKIN wall: Outermost exterior finish layer only\n"
    "New walls are created in the HOST model, positioned so their outer\n"
    "face matches the original wall's exterior face, spanning between the\n"
    "two limits you picked.\n"
    "The original wall is left untouched (host and linked alike)."
)

import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    Color,
    CompoundStructureLayer,
    ElementId,
    ElementTransformUtils,
    FillPatternElement,
    FilteredElementCollector,
    GeometryInstance,
    Level,
    Line,
    Material,
    MaterialFunctionAssignment,
    Options,
    RevitLinkInstance,
    ShellLayerType,
    Solid,
    Transaction,
    Transform,
    ViewDetailLevel,
    Wall,
    WallKind,
    WallType,
    XYZ,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script
from System.Collections.Generic import List as NetList
from Tahir import wall_limits, wall_miter, wall_materials, wall_naming

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()


# ===============================================================================
# WALL DATA CONTAINER
# ===============================================================================

class WallData(object):
    """All data extracted from a wall (host or linked), normalised to host
    world coordinates, ready for creating new walls in the host document.
    """
    __slots__ = (
        "cs",          # CompoundStructure (from source doc)
        "source_doc",  # Document the wall lives in (host or linked)
        "loc_curve",   # Location curve in host world coordinates
        "orientation", # Exterior-face unit vector in host world coordinates
        "total_width", # Wall total width (float, feet)
        "loc_line",    # WALL_KEY_REF_PARAM integer (0–5)
        "level_id",    # ElementId of the matching level in the HOST doc
        "height",      # Unconnected height (feet)
        "base_off",    # Base offset (feet)
        "structural",  # bool
        "source_label",# Human-readable string for reporting
        "is_linked",   # True → do NOT delete; False → delete original
        "host_wall_id",# ElementId of the original wall in the HOST doc (or None)
        "orig_type_name",# Name of the original wall type
        "loc_to_ext",  # Measured distance loc curve -> exterior face (or None)
    )

    def __init__(self, cs, source_doc, loc_curve, orientation, total_width,
                 loc_line, level_id, height, base_off, structural,
                 source_label, is_linked, host_wall_id=None, orig_type_name="",
                 loc_to_ext=None):
        self.cs           = cs
        self.source_doc   = source_doc
        self.loc_curve    = loc_curve
        self.orientation  = orientation
        self.total_width  = total_width
        self.loc_line     = loc_line
        self.level_id     = level_id
        self.height       = height
        self.base_off     = base_off
        self.structural   = structural
        self.source_label = source_label
        self.is_linked    = is_linked
        self.host_wall_id = host_wall_id
        self.orig_type_name = orig_type_name
        self.loc_to_ext   = loc_to_ext


# ===============================================================================
# SELECTION FILTERS
# ===============================================================================

class HostWallFilter(ISelectionFilter):
    """Allow only Basic Wall elements in the HOST model."""

    def AllowElement(self, elem):
        if not isinstance(elem, Wall):
            return False
        try:
            return elem.WallType.Kind == WallKind.Basic
        except Exception:
            return False

    def AllowReference(self, ref, point):
        return False


class LinkedWallFilter(ISelectionFilter):
    """Allow Basic Wall elements inside a RevitLinkInstance.

    For linked elements Revit does NOT call AllowElement() on the wall
    itself — it calls AllowElement() on the RevitLinkInstance and then
    AllowReference() on each candidate reference within that link.
    We must therefore:
      1. Allow the link instance in AllowElement() so the link body is
         interactive.
      2. Resolve the reference in AllowReference() to check the wall.
    """

    def AllowElement(self, elem):
        return isinstance(elem, RevitLinkInstance)

    def AllowReference(self, ref, point):
        try:
            link_inst = doc.GetElement(ref.ElementId)
            if not isinstance(link_inst, RevitLinkInstance):
                return False
            linked_doc = link_inst.GetLinkDocument()
            if linked_doc is None:
                return False
            wall = linked_doc.GetElement(ref.LinkedElementId)
            if not isinstance(wall, Wall):
                return False
            return wall.WallType.Kind == WallKind.Basic
        except Exception:
            return False


class AnyHostElementFilter(ISelectionFilter):
    """Allow any element in the host model (levels included)."""

    def AllowElement(self, elem):
        return True

    def AllowReference(self, ref, point):
        return False


class AnyLinkedElementFilter(ISelectionFilter):
    """Allow any element inside a RevitLinkInstance."""

    def AllowElement(self, elem):
        return isinstance(elem, RevitLinkInstance)

    def AllowReference(self, ref, point):
        return True


class PickedLimit(object):
    """One resolved vertical limit."""

    __slots__ = ("elevation", "level_id", "label")

    def __init__(self, elevation, level_id, label):
        self.elevation = elevation
        self.level_id  = level_id
        self.label     = label


# ===============================================================================
# HELPER UTILITIES
# ===============================================================================

def _iter_solid_points(elem, transform=None):
    """Yield every tessellated vertex of *elem*'s solid geometry.

    If *transform* is given (linked models), points are converted into
    host world coordinates.
    """
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Medium

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
    """Measure a wall's real face positions instead of inferring them.

    Projects every vertex of the wall's solid onto *orient* (the exterior
    normal), relative to *ref_pt* (a point on the wall's location curve).

    Returns (d_ext, d_int) where:
        d_ext = signed distance from the location curve to the EXTERIOR face
        d_int = signed distance from the location curve to the INTERIOR face
                (negative when the interior face is behind the location curve)

    Returns None if the geometry could not be measured.

    This is immune to the Location Line parameter, to asymmetric layer
    build-ups, and to which side Revit considers 'exterior' -- it reads the
    answer off the actual solid.
    """
    try:
        n = orient.Normalize()
    except Exception:
        return None

    hi = None
    lo = None
    for pt in _iter_solid_points(elem, transform):
        d = (pt - ref_pt).DotProduct(n)
        if hi is None or d > hi:
            hi = d
        if lo is None or d < lo:
            lo = d

    if hi is None or lo is None:
        return None
    return hi, lo


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


def project_base_elevation(target_doc):
    """Return the offset between level elevations and model geometry.

    Levels report their elevation relative to the Project Base Point, while
    bounding boxes and pick points come back in internal model coordinates.
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


def host_levels_as_tuples():
    """Return [(ElementId, elevation)] for every Level in the host doc,
    converted into the same coordinate space as bounding boxes and pick
    points so the two can be compared directly.
    """
    delta = project_base_elevation(doc)
    return [(lvl.Id, lvl.Elevation - delta)
            for lvl in FilteredElementCollector(doc).OfClass(Level)]


def _tf_tuple(tf):
    """Convert a Revit Transform into the plain tuple form wall_limits wants."""
    if tf is None:
        return None
    return (
        (tf.BasisX.X, tf.BasisX.Y, tf.BasisX.Z),
        (tf.BasisY.X, tf.BasisY.Y, tf.BasisY.Z),
        (tf.BasisZ.X, tf.BasisZ.Y, tf.BasisZ.Z),
        (tf.Origin.X, tf.Origin.Y, tf.Origin.Z),
    )


def _resolve_level(level_elem, link_tf_tuple, host_levels):
    """Return (elevation, host_level_id) for a picked Level.

    The elevation is converted out of level space and into the model's
    geometry space, so it is directly comparable with bounding boxes and
    pick points.
    """
    if link_tf_tuple is None:
        # Host level: convert straight out of level space.
        elev = level_elem.Elevation - project_base_elevation(
            level_elem.Document)
        return elev, level_elem.Id

    # ── Linked level ───────────────────────────────────────────────────
    # A linked level can only be bound to by finding its HOST counterpart,
    # so match by name first and take that host level's elevation.  This
    # deliberately avoids depending on the linked document's own base
    # point, which is not reliably readable across links.
    linked_name = get_element_name(level_elem)
    for lvl in FilteredElementCollector(doc).OfClass(Level):
        if lvl.Name == linked_name:
            elev = lvl.Elevation - project_base_elevation(doc)
            return elev, lvl.Id

    # No host level of that name: fall back to converting the linked
    # elevation and matching by height instead.
    raw_elev = level_elem.Elevation - project_base_elevation(
        level_elem.Document)
    lo, _hi = wall_limits.transform_bbox_z_range(
        (0.0, 0.0, raw_elev), (0.0, 0.0, raw_elev), link_tf_tuple)
    matched = wall_limits.match_level_by_elevation(lo, host_levels)
    return lo, matched


def _resolve_solid_element(elem, link_tf_tuple, want_top):
    """Return the top (*want_top*) or bottom elevation of *elem*.

    Which end is used is fixed by which limit is being picked, not by
    where the user clicked: a base limit sits on TOP of the element
    below it, a top limit sits under the BOTTOM of the element above.

    Returns None when the element has no bounding box.
    """
    bbox = elem.get_BoundingBox(None)
    if bbox is None:
        return None

    lo, hi = wall_limits.transform_bbox_z_range(
        (bbox.Min.X, bbox.Min.Y, bbox.Min.Z),
        (bbox.Max.X, bbox.Max.Y, bbox.Max.Z),
        link_tf_tuple,
    )
    return hi if want_top else lo


def pick_limit(what):
    """Ask the user to pick one vertical reference from the linked model.

    *what* is "BASE" or "TOP", used only in prompts.
    Returns a PickedLimit, or None when the user cancels.
    """
    host_levels = host_levels_as_tuples()

    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.LinkedElement,
            AnyLinkedElementFilter(),
            "Click the element marking the {} limit".format(what),
        )
        link_inst  = doc.GetElement(ref.ElementId)
        linked_doc = link_inst.GetLinkDocument()
        if linked_doc is None:
            forms.alert("That link is not loaded.",
                        title="Split Walls – Pick Failed")
            return None
        elem     = linked_doc.GetElement(ref.LinkedElementId)
        tf_tuple = _tf_tuple(link_inst.GetTotalTransform())
    except Exception:
        return None  # Esc

    if elem is None:
        return None

    if isinstance(elem, Level):
        elev, level_id = _resolve_level(elem, tf_tuple, host_levels)
        return PickedLimit(
            elev, level_id, "Level '{}'".format(get_element_name(elem)))

    # A base limit sits on TOP of the element below it; a top limit sits
    # under the BOTTOM of the element above it.  No clicking near an edge,
    # and no prompt -- so this works in plan as readily as in elevation.
    want_top = (what == "BASE")

    elev = _resolve_solid_element(elem, tf_tuple, want_top)
    if elev is None:
        forms.alert(
            "That element has no geometry to measure. Pick another.",
            title="Split Walls – Pick Failed",
        )
        return None

    which = "top" if want_top else "bottom"
    return PickedLimit(
        elev, None,
        "{} of {}".format(which, get_element_name(elem)))


def get_material_name(cs, layer_index, source_doc):
    """Return the material name for a layer, reading from *source_doc*."""
    mat = _material_of_layer(cs, layer_index, source_doc)
    return wall_materials.element_name(mat) or "Unknown"


def _material_of_layer(cs, layer_index, source_doc):
    """Return the Material element for a layer, or None.

    The material belongs to *source_doc*, which is the linked document when
    the wall being split lives in a link.
    """
    try:
        mat_id = cs.GetMaterialId(layer_index)
    except Exception:
        return None
    if mat_id and mat_id != ElementId.InvalidElementId:
        return source_doc.GetElement(mat_id)
    return None


def find_wall_type_by_name(name):
    """Return an existing WallType in the HOST doc with the given name."""
    for wt in FilteredElementCollector(doc).OfClass(WallType):
        if get_element_name(wt) == name:
            return wt
    return None


def find_base_host_type():
    """Return any Basic WallType from the host document to use as a
    duplication base when creating new types from linked-model data.
    Prefer types that already have a CompoundStructure.
    """
    for wt in FilteredElementCollector(doc).OfClass(WallType):
        if wt.Kind == WallKind.Basic and wt.GetCompoundStructure() is not None:
            return wt
    return None


def find_host_level(level_name):
    """Find a Level in the host document whose Name matches *level_name*.
    Falls back to the lowest level (by elevation) if no name match.
    """
    levels = list(FilteredElementCollector(doc).OfClass(Level))
    if not levels:
        return None

    for lvl in levels:
        if lvl.Name == level_name:
            return lvl

    # Fallback: lowest level by elevation
    return min(levels, key=lambda l: l.Elevation)


def _find_solid_fill_pattern():
    """Return the ElementId of the '<Solid fill>' FillPatternElement, or
    ElementId.InvalidElementId if not found.
    """
    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
        pat = fp.GetFillPattern()
        if pat and pat.IsSolidFill:
            return fp.Id
    return ElementId.InvalidElementId


def _set_material_colors(mat, shading_rgb, surface_rgb, cut_rgb):
    """Set the shading, surface-pattern and cut-pattern colours on *mat*."""
    try:
        mat.Color = Color(shading_rgb[0], shading_rgb[1], shading_rgb[2])
    except Exception:
        pass
    try:
        mat.SurfaceForegroundPatternColor = Color(
            surface_rgb[0], surface_rgb[1], surface_rgb[2])
        mat.SurfaceBackgroundPatternColor = Color(
            surface_rgb[0], surface_rgb[1], surface_rgb[2])
    except Exception:
        pass
    try:
        solid_id = _find_solid_fill_pattern()
        if solid_id != ElementId.InvalidElementId:
            mat.CutForegroundPatternId = solid_id
        mat.CutForegroundPatternColor = Color(
            cut_rgb[0], cut_rgb[1], cut_rgb[2])
        mat.CutBackgroundPatternColor = Color(120, 120, 120)
    except Exception:
        pass


def get_or_create_ext_material():
    """Return the ElementId of the 'Exterior wall' material in the host doc.
    Creates it with the standard yellow scheme if it doesn't exist.

    Shading:  RGB(255, 255, 128)  – yellow
    Surface:  RGB(120, 120, 120)  – grey, no pattern
    Cut:      RGB(255, 255, 128)  – yellow, Solid fill
    """
    mat_name = "Exterior wall"
    for mat in FilteredElementCollector(doc).OfClass(Material):
        if mat.Name == mat_name:
            return mat.Id

    new_id = Material.Create(doc, mat_name)
    mat    = doc.GetElement(new_id)
    _set_material_colors(
        mat,
        shading_rgb=(255, 255, 128),
        surface_rgb=(120, 120, 120),
        cut_rgb=(255, 255, 128),
    )
    return new_id




# ===============================================================================
# NAMING HELPERS
# ===============================================================================

def compute_ext_type_name(cs, first_core, last_core):
    """EXT_MTL_<TotalThickness>  (core + interior layers)."""
    total_w = 0.0
    for i in range(first_core, cs.LayerCount):
        total_w += cs.GetLayerWidth(i)
    return "EXT_MTL_{}".format(wall_naming.feet_to_imperial(total_w))


# NOTE: SKIN type names are no longer derived from the original wall type
# name.  They come from the finish material's Mark, via Tahir.wall_naming --
# see plan_skin_type below.


# ===============================================================================
# SELECTION – BUILD WallData OBJECTS
# ===============================================================================

def _wall_data_from_host_wall(wall):
    """Extract WallData from a wall element in the host document."""
    wt = wall.WallType
    cs = wt.GetCompoundStructure()

    loc_param = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
    loc_line  = loc_param.AsInteger() if loc_param else 0

    h_param  = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
    height   = h_param.AsDouble() if (h_param and h_param.HasValue) else 10.0

    bo_param = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    base_off = bo_param.AsDouble() if (bo_param and bo_param.HasValue) else 0.0

    st_param   = wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
    structural = bool(st_param.AsInteger()) if (st_param and st_param.HasValue) else False

    level_elem = doc.GetElement(wall.LevelId)
    level_name = level_elem.Name if level_elem else ""
    host_level = find_host_level(level_name)

    orig_type_name = get_element_name(wt)

    host_curve = wall.Location.Curve

    # Measure the real exterior-face offset rather than inferring it from
    # the Location Line parameter (which mis-places asymmetric walls).
    loc_to_ext = None
    try:
        meas = measure_face_offsets(
            wall, host_curve.GetEndPoint(0), wall.Orientation)
        if meas:
            loc_to_ext = meas[0]
    except Exception as ex:
        logger.debug("Face measurement failed on host wall: {}".format(ex))

    return WallData(
        cs           = cs,
        source_doc   = doc,
        loc_curve    = host_curve,
        orientation  = wall.Orientation,
        total_width  = wall.Width,
        loc_line     = loc_line,
        level_id     = host_level.Id if host_level else wall.LevelId,
        height       = height,
        base_off     = base_off,
        structural   = structural,
        source_label = "Host wall {}".format(wall.Id.IntegerValue),
        is_linked    = False,
        host_wall_id = wall.Id,
        orig_type_name = orig_type_name,
        loc_to_ext   = loc_to_ext,
    )


def _wall_data_from_linked_ref(ref):
    """Extract WallData from a Reference to a wall in a linked model.
    Applies the link transform to convert all geometry to host world coords.
    Returns a WallData, or raises RuntimeError with a descriptive message.
    """
    link_inst = doc.GetElement(ref.ElementId)
    if not isinstance(link_inst, RevitLinkInstance):
        raise RuntimeError("Reference does not point to a RevitLinkInstance")

    linked_doc = link_inst.GetLinkDocument()
    if linked_doc is None:
        raise RuntimeError("Linked document is not loaded")

    wall = linked_doc.GetElement(ref.LinkedElementId)
    if not isinstance(wall, Wall):
        raise RuntimeError("Linked element is not a Wall")

    if wall.WallType.Kind != WallKind.Basic:
        raise RuntimeError("Linked wall is not a Basic Wall")

    cs = wall.WallType.GetCompoundStructure()
    if cs is None:
        raise RuntimeError("Linked wall type has no compound structure")

    # Transform: linked-model coords → host world coords
    # NOTE: Transform.OfCurve() and OfVector() are not available in IronPython
    # bindings. We manually transform endpoints with OfPoint() and reconstruct
    # the line. For the orientation (a direction, not a position) we apply the
    # rotation by transforming the origin+direction and subtracting the origin.
    link_tf = link_inst.GetTotalTransform()

    raw_curve  = wall.Location.Curve
    raw_orient = wall.Orientation

    # Transform the two endpoints of the location line
    pt0 = link_tf.OfPoint(raw_curve.GetEndPoint(0))
    pt1 = link_tf.OfPoint(raw_curve.GetEndPoint(1))
    host_curve = Line.CreateBound(pt0, pt1)

    # Rotate the orientation vector (OfPoint on origin+direction minus
    # transformed origin isolates the pure rotational component)
    origin_tf   = link_tf.OfPoint(XYZ.Zero)
    orient_tip  = link_tf.OfPoint(XYZ(raw_orient.X, raw_orient.Y, raw_orient.Z))
    host_orient = XYZ(
        orient_tip.X - origin_tf.X,
        orient_tip.Y - origin_tf.Y,
        orient_tip.Z - origin_tf.Z,
    ).Normalize()

    # Measure the real exterior-face offset from the linked wall's solid,
    # transformed into host coordinates.  This replaces inferring the offset
    # from the Location Line parameter, which mis-places asymmetric walls.
    loc_to_ext = None
    try:
        meas = measure_face_offsets(wall, pt0, host_orient, link_tf)
        if meas:
            loc_to_ext = meas[0]
    except Exception as ex:
        logger.debug("Face measurement failed on linked wall: {}".format(ex))

    loc_param  = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
    loc_line   = loc_param.AsInteger() if loc_param else 0

    h_param  = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
    height   = h_param.AsDouble() if (h_param and h_param.HasValue) else 10.0

    bo_param = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    base_off = bo_param.AsDouble() if (bo_param and bo_param.HasValue) else 0.0

    st_param   = wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
    structural = bool(st_param.AsInteger()) if (st_param and st_param.HasValue) else False

    level_elem = linked_doc.GetElement(wall.LevelId)
    level_name = level_elem.Name if level_elem else ""
    host_level = find_host_level(level_name)

    link_name = get_element_name(link_inst)
    source_lbl = "Linked wall {} (from '{}')".format(
        wall.Id.IntegerValue, link_name
    )

    orig_type_name = get_element_name(wall.WallType)

    return WallData(
        cs           = cs,
        source_doc   = linked_doc,
        loc_curve    = host_curve,
        orientation  = host_orient,
        total_width  = wall.Width,
        loc_line     = loc_line,
        level_id     = host_level.Id if host_level else ElementId.InvalidElementId,
        height       = height,
        base_off     = base_off,
        structural   = structural,
        source_label = source_lbl,
        is_linked    = True,
        host_wall_id = None,
        orig_type_name = orig_type_name,
        loc_to_ext   = loc_to_ext,
    )


def get_walls():
    """Return a list of WallData objects for user-picked linked walls.

    Always picks interactively: the tool runs in a loop, so honouring a
    pre-selection would re-process the same walls on every pass.

    Returns None if the user cancels or nothing is selected.
    """
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.LinkedElement,
            LinkedWallFilter(),
            "Select compound walls from the linked model – press Finish when done",
        )
    except Exception:
        return None  # user pressed Escape

    if not refs:
        return None

    result = []
    skipped = []
    for ref in refs:
        try:
            result.append(_wall_data_from_linked_ref(ref))
        except Exception as ex:
            skipped.append(str(ex))
            logger.warning("Skipping linked wall reference: {}".format(ex))

    if skipped and not result:
        forms.alert(
            "None of the selected elements could be processed:\n\n"
            + "\n".join("- " + s for s in skipped),
            title="Split Walls – Selection Error",
        )
        return None

    return result if result else None


# ===============================================================================
# WALL TYPE CREATION / REUSE (host doc, with cross-doc material resolution)
# ===============================================================================

def get_or_create_ext_type(cs, first_core, last_core):
    """Return (WallType, name) for the EXT type.

    The wall type has a SINGLE Structure core layer whose thickness
    equals the sum of all core + interior layers from the original wall.
    Its material is the standard 'Exterior wall' yellow material.
    """
    name     = compute_ext_type_name(cs, first_core, last_core)
    existing = find_wall_type_by_name(name)
    if existing:
        return existing, name

    base = find_base_host_type()
    if base is None:
        raise RuntimeError("No Basic WallType in host to use as duplication base")

    # Total thickness = core + interior layers
    total_w = sum(cs.GetLayerWidth(i) for i in range(first_core, cs.LayerCount))

    ext_mat_id = get_or_create_ext_material()

    new_type = base.Duplicate(name)
    new_cs   = new_type.GetCompoundStructure()

    layers = NetList[CompoundStructureLayer]()
    layers.Add(CompoundStructureLayer(
        total_w,
        MaterialFunctionAssignment.Structure,
        ext_mat_id,
    ))

    new_cs.SetLayers(layers)
    new_cs.SetNumberOfShellLayers(ShellLayerType.Exterior, 0)
    new_cs.SetNumberOfShellLayers(ShellLayerType.Interior, 0)
    new_type.SetCompoundStructure(new_cs)

    return new_type, name


def skin_plan_key(cs, source_doc):
    """Key a wall by the SKIN type it needs, so each is resolved once.

    Walls whose finishes share a Mark share a wall type; a finish with no
    Mark falls back to its material name, so those are still only asked
    about once each.
    """
    source_mat = _material_of_layer(cs, 0, source_doc)
    mark       = wall_materials.material_mark(source_mat)
    if not mark:
        mark = "name:{}".format(get_material_name(cs, 0, source_doc))
    return wall_materials.type_match_key(mark, cs.GetLayerWidth(0))


def plan_skin_type(cs, source_doc):
    """Decide which wall type this wall's SKIN needs, asking as required.

    Raises every dialog it needs, so it must be called before the
    transaction opens.
    """
    return wall_materials.plan_skin_wall_type(
        doc, _material_of_layer(cs, 0, source_doc), source_doc,
        cs.GetLayerWidth(0), "Split Walls")


def get_or_create_skin_type(cs, source_doc, orig_type_name, plans=None):
    """Return (WallType, name) for the SKIN type, or (None, reason) when the
    plan for it was to skip.

    The type is resolved from the finish material's Mark: an existing host
    material and wall type carrying that Mark are reused whatever they are
    named, a type at the wrong thickness is duplicated to the right one, and
    an unmatched Mark yields a new material and type under the convention.
    All of that was decided by plan_skin_type before the transaction opened;
    this only carries it out.
    """
    key  = skin_plan_key(cs, source_doc)
    plan = (plans or {}).get(key) or plan_skin_type(cs, source_doc)

    if plan.get("action") == "skip":
        return None, plan.get("reason", "no wall type resolved")

    source_mat = _material_of_layer(cs, 0, source_doc)
    new_type   = wall_materials.execute_skin_wall_type_plan(
        doc, plan, source_mat, source_doc)

    if new_type is None:
        return None, "no wall type resolved"
    return new_type, get_element_name(new_type)


# ===============================================================================
# GEOMETRY – OFFSET COMPUTATION
# ===============================================================================

def _layer_group_widths(cs, first_core, last_core):
    """Return (skin_w, gap_w, core_w, interior_w, ext_total_w) in feet."""
    skin_w = cs.GetLayerWidth(0)
    gap_w  = sum(cs.GetLayerWidth(i) for i in range(1, first_core))
    core_w = sum(cs.GetLayerWidth(i) for i in range(first_core, last_core + 1))
    int_w  = sum(cs.GetLayerWidth(i) for i in range(last_core + 1, cs.LayerCount))
    return skin_w, gap_w, core_w, int_w, core_w + int_w


def _dist_loc_to_exterior(loc_line, total_w, skin_w, gap_w, core_w):
    """Distance from the wall's location curve to its exterior face (feet).

    Covers all six WallLocationLine settings:
        0 = Wall Centerline          3 = Finish Face: Interior
        1 = Core Centerline          4 = Core Face: Exterior
        2 = Finish Face: Exterior    5 = Core Face: Interior
    """
    ext_shell = skin_w + gap_w
    mapping = {
        0: total_w / 2.0,
        1: ext_shell + core_w / 2.0,
        2: 0.0,
        3: total_w,
        4: ext_shell,
        5: ext_shell + core_w,
    }
    return mapping.get(loc_line, total_w / 2.0)


def compute_skin_curve(wd, first_core, last_core):
    """Compute the host-coordinate centerline for the new SKIN wall.

    The SKIN wall occupies the outermost finish layer of the original wall,
    so its centerline sits half its own thickness inboard of the original
    wall's exterior face.

    Returns (skin_curve, gap_width).
    """
    skin_w, gap_w, core_w, _int_w, _ext_total_w = \
        _layer_group_widths(wd.cs, first_core, last_core)

    # Prefer the offset measured off the wall's real solid geometry.  Fall
    # back to deriving it from the Location Line parameter only when the
    # geometry could not be read.
    if wd.loc_to_ext is not None:
        d = wd.loc_to_ext
    else:
        d = _dist_loc_to_exterior(
            wd.loc_line, wd.total_width, skin_w, gap_w, core_w)

    skin_off = d - skin_w / 2.0

    orient = wd.orientation.Normalize()
    vec    = XYZ(orient.X * skin_off, orient.Y * skin_off, orient.Z * skin_off)

    skin_curve = wd.loc_curve.CreateTransformed(
        Transform.CreateTranslation(vec))

    return skin_curve, gap_w


# ===============================================================================
# ORIENTED WALL CREATION
# ===============================================================================

def _center_wall_on_curve(wall, target_curve, orient):
    """Translate *wall* so that the mid-plane of its actual solid lands
    exactly on *target_curve*.

    *target_curve* is the intended CENTERLINE of the new wall.  Rather than
    trusting whichever Location Line default Wall.Create() applied, this
    measures the wall's real faces and cancels out any residual
    perpendicular error.
    """
    try:
        n      = orient.Normalize()
        ref_pt = target_curve.GetEndPoint(0)

        meas = measure_face_offsets(wall, ref_pt, n)
        if not meas:
            return

        hi, lo = meas
        center_err = (hi + lo) / 2.0   # 0.0 when perfectly centred

        if abs(center_err) > 1e-7:
            move_vec = XYZ(n.X * -center_err,
                           n.Y * -center_err,
                           n.Z * -center_err)
            ElementTransformUtils.MoveElement(doc, wall.Id, move_vec)
            doc.Regenerate()
    except Exception as ex:
        logger.debug("Could not re-centre new wall: {}".format(ex))


def create_oriented_wall(curve, type_id, level_id, height, base_off,
                          structural, orig_orient):
    """Create a wall along *curve*, ensuring its centerline is aligned 100%
    with *curve* and its Orientation matches *orig_orient*.
    """
    wall = Wall.Create(doc, curve, type_id, level_id, height, base_off,
                        False, structural)
    doc.Regenerate()

    # Force Location Line = Wall Centerline (whatever ambient default was
    # in effect at creation time becomes irrelevant once this is set).
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
        if p and p.HasValue:
            p.Set(0)  # 0 = Wall Centerline
        doc.Regenerate()
    except Exception:
        pass

    # Check orientation; if reversed, re-create on reversed curve
    try:
        if orig_orient.DotProduct(wall.Orientation) < 0:
            doc.Delete(wall.Id)
            doc.Regenerate()
            curve = curve.CreateReversed()
            wall = Wall.Create(doc, curve, type_id,
                                level_id, height, base_off, False, structural)
            doc.Regenerate()
            p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
            if p and p.HasValue:
                p.Set(0)
            doc.Regenerate()
    except Exception:
        pass

    # Measure the wall's real faces and cancel out any residual
    # perpendicular offset so its mid-plane sits on the target curve.
    _center_wall_on_curve(wall, curve, orig_orient)

    return wall


# ===============================================================================
# COPY INSTANCE PARAMETERS  (host→host only)
# ===============================================================================

def copy_instance_params(source_wall, target_wall):
    """Copy essential instance parameters from *source_wall* (host) to
    *target_wall* (host).  Not called for linked-wall splits because
    the source wall lives in a different document.
    """
    # NOTE: WALL_BASE_OFFSET, WALL_USER_HEIGHT_PARAM and WALL_HEIGHT_TYPE are
    # deliberately NOT copied -- the new wall's vertical extent comes from the
    # limits the user picked, and copying them would silently overwrite it.
    bip_list = [
        BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT,
    ]
    for bip in bip_list:
        try:
            sp = source_wall.get_Parameter(bip)
            tp = target_wall.get_Parameter(bip)
            if sp and tp and sp.HasValue and not tp.IsReadOnly:
                st = sp.StorageType.ToString()
                if st == "Double":
                    tp.Set(sp.AsDouble())
                elif st == "Integer":
                    tp.Set(sp.AsInteger())
                elif st == "ElementId":
                    tp.Set(sp.AsElementId())
                elif st == "String":
                    val = sp.AsString()
                    if val is not None:
                        tp.Set(val)
        except Exception:
            pass

    for pname in ("Comments", "Mark"):
        try:
            sp = source_wall.LookupParameter(pname)
            tp = target_wall.LookupParameter(pname)
            if sp and tp and sp.HasValue and not tp.IsReadOnly:
                val = sp.AsString()
                if val is not None:
                    tp.Set(val)
        except Exception:
            pass


# ===============================================================================
# SPLIT ONE WALL (from WallData)
# ===============================================================================

def collect_skin_type_plans(wall_data_list):
    """Resolve the SKIN wall type once per Mark across the whole selection.

    Returns {skin_plan_key: plan}.  Called before the transaction opens so
    the dialogs do not appear mid-transaction.
    """
    plans = {}
    for wd in wall_data_list:
        cs = wd.cs
        if cs is None or cs.LayerCount < 2:
            continue

        key = skin_plan_key(cs, wd.source_doc)
        if key in plans:
            continue
        plans[key] = plan_skin_type(cs, wd.source_doc)
    return plans


def prepare_skin(wd, limits, plans=None):
    """Work out the SKIN type and centreline for one wall, without
    creating anything yet.

    Creation is deferred so that every wall in the selection can have its
    corners mitred against its neighbours first.

    Returns (True, {"wd", "type", "curve", "name"}) on success,
            (False, error_message) on failure.
    """
    cs = wd.cs
    if cs is None:
        return False, "Wall type has no compound structure"

    if cs.LayerCount < 2:
        return False, "Fewer than 2 layers – nothing to split"

    first_core = cs.GetFirstCoreLayerIndex()
    last_core  = cs.GetLastCoreLayerIndex()

    if first_core < 1:
        return False, "No exterior finish layer before the core boundary"

    if limits["base_level_id"] == ElementId.InvalidElementId:
        return False, "No valid host level to host the new wall"

    skin_type, skin_name = get_or_create_skin_type(
        cs, wd.source_doc, wd.orig_type_name, plans
    )
    if skin_type is None:
        return False, skin_name          # skin_name carries the skip reason

    skin_curve, _gap_w = compute_skin_curve(wd, first_core, last_core)

    return True, {
        "wd":    wd,
        "type":  skin_type,
        "curve": skin_curve,
        "name":  skin_name,
    }


def miter_prepared(prepared):
    """Close the corners between the prepared SKIN centrelines.

    Adjacency is judged on the ORIGINAL wall curves, which still share
    their endpoints; the corner point is where the two OFFSET lines
    cross.  Curves are replaced in place inside *prepared*.
    """
    if len(prepared) < 2:
        return

    originals = []
    offsets   = []
    zs        = []
    for item in prepared:
        oc = item["wd"].loc_curve
        sc = item["curve"]
        o0, o1 = oc.GetEndPoint(0), oc.GetEndPoint(1)
        s0, s1 = sc.GetEndPoint(0), sc.GetEndPoint(1)
        originals.append(((o0.X, o0.Y), (o1.X, o1.Y)))
        offsets.append(((s0.X, s0.Y), (s1.X, s1.Y)))
        zs.append((s0.Z, s1.Z))

    mitred = wall_miter.miter_chain(originals, offsets)

    for idx, item in enumerate(prepared):
        (x0, y0), (x1, y1) = mitred[idx]
        z0, z1 = zs[idx]
        new_curve = Line.CreateBound(XYZ(x0, y0, z0), XYZ(x1, y1, z1))
        item["curve"] = new_curve


def create_skin(item, limits):
    """Create one prepared SKIN wall.

    Returns (True, summary_string) or (False, error_message).
    """
    wd = item["wd"]

    skin_wall = create_oriented_wall(
        item["curve"], item["type"].Id, limits["base_level_id"],
        limits["height"], limits["base_offset"],
        wd.structural, wd.orientation,
    )

    # Bind the top to a level when there is one, so the wall follows it.
    if limits["top_level_id"] is not None:
        try:
            tp = skin_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
            if tp and not tp.IsReadOnly:
                tp.Set(limits["top_level_id"])
            op = skin_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
            if op and not op.IsReadOnly:
                op.Set(limits["top_offset"])
            doc.Regenerate()
        except Exception as ex:
            logger.debug("Could not bind top constraint: {}".format(ex))

    # Copy instance parameters only when source is a host wall
    if not wd.is_linked and wd.host_wall_id is not None:
        source_wall = doc.GetElement(wd.host_wall_id)
        if source_wall:
            copy_instance_params(source_wall, skin_wall)

    return True, "SKIN='{}' from {}".format(item["name"], wd.source_label)


# ===============================================================================
# MAIN
# ===============================================================================

def run_once():
    """One pass: pick walls, pick limits, create the SKIN walls.

    Returns True to keep looping, False when the user is finished.
    """
    wall_data_list = get_walls()
    if not wall_data_list:
        return False

    # Picking must happen outside the transaction.
    base_pick = pick_limit("BASE")
    if base_pick is None:
        return False

    top_pick = pick_limit("TOP")
    if top_pick is None:
        return False

    try:
        limits = wall_limits.compute_wall_limits(
            base_pick.elevation, base_pick.level_id,
            top_pick.elevation,  top_pick.level_id,
            host_levels_as_tuples(),
        )
    except ValueError as ex:
        # Bad limits should not end the session -- let them try again.
        forms.alert(str(ex), title="Split Walls – Invalid Limits")
        return True

    fail_list = []

    # Resolve wall types before opening the transaction, so no dialog
    # appears mid-transaction.
    skin_plans = collect_skin_type_plans(wall_data_list)

    with Transaction(doc, "Create SKIN Walls") as t:
        t.Start()
        try:
            # Work out every centreline first, mitre the shared corners,
            # then build. Creating one wall at a time would leave each
            # corner open.
            prepared = []
            for wd in wall_data_list:
                try:
                    success, payload = prepare_skin(wd, limits, skin_plans)
                    if success:
                        prepared.append(payload)
                    else:
                        fail_list.append("{}: {}".format(
                            wd.source_label, payload))
                except Exception as ex:
                    fail_list.append("{}: {}".format(wd.source_label, str(ex)))

            miter_prepared(prepared)

            for item in prepared:
                try:
                    success, msg = create_skin(item, limits)
                    if not success:
                        fail_list.append("{}: {}".format(
                            item["wd"].source_label, msg))
                except Exception as ex:
                    fail_list.append("{}: {}".format(
                        item["wd"].source_label, str(ex)))
            t.Commit()
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            forms.alert("Transaction failed:\n{}".format(str(ex)),
                        title="Split Walls – Error")
            return True

    # Silence on success.  Only failures surface, and printing them is what
    # opens the output window -- so a clean run shows nothing at all.
    if fail_list:
        output.print_md("**Split Walls — {} wall(s) failed**".format(
            len(fail_list)))
        for m in fail_list:
            output.print_md("- {}".format(m))

    return True


def main():
    while True:
        try:
            if not run_once():
                break
        except Exception as ex:
            # Never let one bad pass kill the session silently.  The message
            # alone is often a single unhelpful word, so the traceback goes
            # to the output window where it can actually be read.
            logger.error("Split Walls pass failed: {}".format(ex))
            output.print_md("**Split Walls — unexpected error**")
            output.print_code(traceback.format_exc())
            forms.alert("Unexpected error:\n{}\n\n"
                        "See the output window for details.".format(ex),
                        title="Split Walls – Error")
            break


main()
