# -*- coding: utf-8 -*-
"""
Create a host-model curtain wall from an opening picked in a LINKED model.

Pick either a window in a linked Revit model - a real Windows-category
family or a custom Generic Model standing in for one - or a curtain wall
in that link, then pick the host-model wall it belongs on.  A curtain
wall is created on that wall to match what was picked.

From a WINDOW, sizes come from the family's own parameters: Sill Height
above the window's level for the base, then Rough Width/Height or
Width/Height, falling back to measured geometry only where a parameter
is missing.  Measuring the solids would start the wall at the bottom of
any sill trim, apron or cast stone hanging below the opening - but the
parameter is only trusted while it agrees with where the solids are, so
a family measuring Sill Height from something else cannot throw the wall
a storey out.  The head is traced from the linked geometry and the new
wall's elevation profile is re-sketched to suit: a head that fits one
circle becomes a true arc, and one that does not - a segmental head
carrying trim, say - is followed as a simplified polyline instead.

From a CURTAIN WALL, everything is read off that wall instead: its
length, its base and top constraints with their offsets, and - when its
elevation has been sketched - its actual profile, carried across onto
the picked wall as a rigid move, so arcs stay arcs and nothing mirrors.

The TYPE is chosen from the Type Mark: the leading letters name the
type, so WA12 -> 'WA_Window', WS03 -> 'WS_Window', W04 -> 'W_Window'.  A
mark whose serial is itself letters, like WSXX, still resolves to WS.
With no matching type you are asked to pick one, once per prefix - a
type is never created or duplicated.

The new wall's centreline sits on the host wall's centreline.  Whatever
grid layout the matched type carries is stripped off the new wall right
away, leaving one plain panel: no grid lines and no mullions.  The type
itself is never touched.

Each new wall gets its BG_ parameters filled: BG_WINDOW NUMBER from the
source's Type Mark, and BG_BUILDING ID, BG_ELEVATION and BG_LEVEL copied
straight off the host wall.  BG_PROFILE is left alone.  A parameter that
is missing at either end is reported and left blank - it never stops the
wall being made.

Picking loops until Esc.  The linked model is never modified.
"""

__title__  = "Window To\nCurtain Wall"
__author__ = "Tahir Sanwarwala"
__doc__    = (
    "Pick a window or a curtain wall in a LINKED model, then the host "
    "wall it sits on, and a curtain wall is created to match it.\n"
    "The type comes from the Type Mark prefix (WA12 -> WA_Window, "
    "W04 -> W_Window); you are asked to pick a type when no match "
    "exists.\n"
    "A window gives its width, height and sill from its own parameters, "
    "and arched heads are reproduced where they can be fitted; a linked "
    "curtain wall gives its length, constraints and sketched profile.\n"
    "Repeats until Esc.  The linked model is left untouched."
)

import re

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    Arc,
    BuiltInCategory,
    BuiltInParameter,
    CurveElement,
    ElementId,
    FailureProcessingResult,
    FailureSeverity,
    FamilyInstance,
    FilteredElementCollector,
    GeometryInstance,
    IFailuresPreprocessor,
    Level,
    Line,
    Options,
    Sketch,
    SketchEditScope,
    Solid,
    StorageType,
    Transaction,
    Transform,
    ViewDetailLevel,
    Wall,
    WallKind,
    WallType,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, forms, script

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

LEVEL_TOL       = 1e-4    # feet, when matching a level under the sill
MIN_EXTENT      = 0.02    # feet, below this a measured width/height is junk
FLAT_TOP_TOL    = 0.01    # feet (~3 mm), rise below this counts as a flat head
ARC_FIT_TOL     = 0.02    # feet (~6 mm), max deviation of the fitted arch
POLY_SIMPLIFY_TOL = 0.01  # feet (~3 mm), chord error kept when tracing a head
SILL_TRIM_MAX   = 2.0     # feet; further than this below the opening and a
                          # Sill Height reading is wrong, not just trimmed
TOP_SAMPLE_BINS = 48      # buckets used to trace the window's top boundary
CURTAIN_SUFFIX  = "_Window"

# Shared parameters filled on every wall this tool makes.  BG_PROFILE is
# deliberately left alone.
BG_NUMBER_NAME  = "BG_WINDOW NUMBER"
BG_COPIED_NAMES = ["BG_BUILDING ID", "BG_ELEVATION", "BG_LEVEL"]

# Print the measurements every run while the tool is being dialled in.
# Set to False once the numbers are trusted and it goes quiet on success.
VERBOSE         = True


# ===============================================================================
# SMALL HELPERS
# ===============================================================================

def as_element_id(thing):
    """Return an ElementId for *thing*, whether it is one or an element.

    Some API calls hand back the element they made and others hand back
    its id, and which one you get varies by version.
    """
    if thing is None:
        return None
    if isinstance(thing, ElementId):
        return thing
    try:
        return thing.Id
    except Exception:
        return None


def eid_value(element_id):
    """Return an ElementId's integer value across Revit API versions."""
    try:
        return element_id.Value
    except Exception:
        return element_id.IntegerValue


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
        return eid_value(cat.Id) == eid_value(ElementId(bic))
    except Exception:
        return False


def length_param(elements, names, builtin_names):
    """Return the first length value found on *elements*, in feet.

    Built-in parameters are tried first, looked up by name so a parameter
    missing from this Revit version cannot raise, then plain lookups by
    parameter name.
    """
    for elem in elements:
        if elem is None:
            continue
        for bip_name in builtin_names:
            bip = getattr(BuiltInParameter, bip_name, None)
            if bip is None:
                continue
            try:
                p = elem.get_Parameter(bip)
            except Exception:
                p = None
            if p is not None and p.HasValue:
                v = p.AsDouble()
                if v > MIN_EXTENT:
                    return v
    for elem in elements:
        if elem is None:
            continue
        for name in names:
            try:
                p = elem.LookupParameter(name)
            except Exception:
                p = None
            if p is not None and p.HasValue:
                try:
                    v = p.AsDouble()
                except Exception:
                    continue
                if v > MIN_EXTENT:
                    return v
    return None


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
# GEOMETRY
# ===============================================================================

def iter_solid_points(elem, transform=None):
    """Yield every tessellated vertex of *elem*'s solid geometry.

    Nested family geometry is followed all the way down, and points are
    converted into host world coordinates when *transform* is given.
    """
    opts = Options()
    opts.ComputeReferences = False
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Fine

    try:
        geo_elem = elem.get_Geometry(opts)
    except Exception:
        geo_elem = None
    if geo_elem is None:
        return

    for pt in _iter_geo_points(geo_elem, transform):
        yield pt


def _iter_geo_points(geo_elem, transform):
    """Walk a GeometryElement, yielding transformed solid edge points."""
    for gobj in geo_elem:
        if isinstance(gobj, Solid):
            try:
                if gobj.Volume <= 0:
                    continue
            except Exception:
                continue
            for edge in gobj.Edges:
                try:
                    pts = edge.Tessellate()
                except Exception:
                    continue
                for pt in pts:
                    yield transform.OfPoint(pt) if transform else pt
        elif isinstance(gobj, GeometryInstance):
            try:
                inner = gobj.GetInstanceGeometry()
            except Exception:
                continue
            if inner is None:
                continue
            for pt in _iter_geo_points(inner, transform):
                yield pt


def project_base_elevation(target_doc):
    """Return the offset between level elevations and model geometry.

    Levels report elevations relative to the Project Base Point while
    solids and pick points come back in internal model coordinates.  With
    the base point at zero the two coincide and this returns 0.0.
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
    """Return (Level, geometry-space elevation) at or below *elevation*.

    Falls back to the lowest level, and to (None, 0.0) when the host model
    has no levels at all.
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


# ===============================================================================
# CURTAIN WALL TYPES
# ===============================================================================

def type_mark(window, link_doc):
    """Return the window's Type Mark, or None."""
    win_type = None
    try:
        win_type = link_doc.GetElement(window.GetTypeId())
    except Exception:
        pass

    for elem in (win_type, window):
        if elem is None:
            continue
        p = None
        try:
            p = elem.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_MARK)
        except Exception:
            p = None
        if p is None:
            try:
                p = elem.LookupParameter("Type Mark")
            except Exception:
                p = None
        if p is not None and p.HasValue:
            try:
                text = p.AsString()
            except Exception:
                text = None
            if text and text.strip():
                return text.strip()
    return None


def mark_letters(mark):
    """The run of letters a Type Mark starts with, upper-cased."""
    if not mark:
        return ""
    m = re.match(r"^\s*([A-Za-z]+)", mark)
    return m.group(1).upper() if m else ""


def mark_prefix(mark):
    """The type prefix a Type Mark names: at most its first two letters.

    'WA12' -> 'WA', 'W04' -> 'W', 'WSXX' -> 'WS'.  The cap matters: a
    mark whose serial is itself letters, like WSXX, would otherwise ask
    for a 'WSXX_Window' type that does not exist.
    """
    return mark_letters(mark)[:2] or None


def candidate_prefixes(mark):
    """Prefixes to look for, longest first: 'WSXX' -> ['WS', 'W']."""
    letters = mark_letters(mark)
    out = []
    for n in (2, 1):
        if len(letters) >= n and letters[:n] not in out:
            out.append(letters[:n])
    return out


def curtain_wall_types():
    """Return every curtain wall type in the host model."""
    types = []
    for wt in FilteredElementCollector(doc).OfClass(WallType):
        try:
            if wt.Kind == WallKind.Curtain:
                types.append(wt)
        except Exception:
            continue
    return types


def type_named(name, types):
    """Return the curtain wall type called *name*, or None."""
    if not name:
        return None
    wanted = name.strip().lower()
    for wt in types:
        if get_element_name(wt).strip().lower() == wanted:
            return wt
    return None


def match_curtain_type(plan, types):
    """Return the host curtain wall type for *plan*, or None.

    Only the Type Mark decides it - '<prefix>_Window' - never the source
    element's own type name.  Matching on that name would quietly pick up
    a type carried in from the link, which is exactly what must not
    happen: the host's own types are the whole point.
    """
    for prefix in candidate_prefixes(plan.mark):
        found = type_named(prefix + CURTAIN_SUFFIX, types)
        if found is not None:
            return found
    return None


def prompt_curtain_type(types, mark, prefix):
    """Ask the user to pick a curtain wall type.  None means cancelled."""
    by_name = {}
    for wt in types:
        by_name[get_element_name(wt)] = wt
    if not by_name:
        return None

    chosen = forms.SelectFromList.show(
        sorted(by_name.keys()),
        title="No '{}{}' type - pick one for Type Mark '{}'".format(
            prefix or "?", CURTAIN_SUFFIX, mark or "<none>"),
        button_name="Use this type",
        multiselect=False)

    if not chosen:
        return None
    return by_name.get(chosen)


# ===============================================================================
# MEASUREMENT
# ===============================================================================

class WindowPlan(object):
    """Everything needed to build one curtain wall, in host coordinates.

    A plan built from a window carries *top_profile*, the traced outline
    its arched head is fitted from.  A plan built from a linked curtain
    wall instead carries *profile_curves* - that wall's own sketched
    profile, already in host coordinates - together with *src_origin* and
    *src_dir*, the frame those curves are measured in, so the profile can
    be moved onto whichever wall is picked.
    """

    __slots__ = ("window_id", "link_name", "mark", "prefix",
                 "centre", "width", "height", "sill",
                 "top_profile", "profile_curves", "src_origin", "src_dir",
                 "wall_dir", "notes", "source_kind", "level_name",
                 "base_offset", "new_wall_id", "grid_removed",
                 "sill_param", "geom_bottom")

    def __init__(self):
        self.top_profile    = None
        self.profile_curves = None
        self.src_origin     = None
        self.src_dir        = None
        self.source_kind    = "window"
        self.level_name     = "-"
        self.base_offset    = 0.0
        self.new_wall_id    = None
        self.grid_removed   = []
        self.sill_param     = None
        self.geom_bottom    = None
        self.notes          = []


def wall_axis(host_wall):
    """Return (location curve, unit direction at its midpoint).

    Returns (None, None) when the wall has no usable location curve.
    """
    try:
        curve = host_wall.Location.Curve
    except Exception:
        return None, None
    if curve is None:
        return None, None
    try:
        d = curve.ComputeDerivatives(0.5, True).BasisX
        return curve, XYZ(d.X, d.Y, 0.0).Normalize()
    except Exception:
        return curve, None


def window_centre(window, transform):
    """Return the window's location point in host coordinates, or None."""
    try:
        loc = window.Location
        if loc is not None and hasattr(loc, "Point"):
            return transform.OfPoint(loc.Point)
    except Exception:
        pass
    return None


def sill_from_parameters(window, link_doc, transform):
    """Return the window's sill elevation in host coordinates, or None.

    Read as Sill Height above the window's own level rather than measured
    off the solids: sill trims, cast stone and aprons routinely hang below
    the sill, and measuring would start the curtain wall at the bottom of
    those instead of at the opening.
    """
    sill = None
    for name_or_bip in ("INSTANCE_SILL_HEIGHT_PARAM", "Sill Height"):
        p = None
        bip = getattr(BuiltInParameter, name_or_bip, None)
        try:
            p = window.get_Parameter(bip) if bip is not None \
                else window.LookupParameter(name_or_bip)
        except Exception:
            p = None
        if p is not None and p.HasValue:
            try:
                sill = p.AsDouble()
                break
            except Exception:
                sill = None
    if sill is None:
        return None

    try:
        level = link_doc.GetElement(window.LevelId)
    except Exception:
        level = None
    if level is None:
        return None

    try:
        link_elev = level.Elevation - project_base_elevation(link_doc) + sill
    except Exception:
        return None

    # Carry the elevation through the link transform using the window's own
    # plan position, so a link that is moved or rotated still lands right.
    try:
        loc = window.Location
        base = loc.Point if (loc is not None and hasattr(loc, "Point")) \
            else XYZ(0.0, 0.0, 0.0)
        return transform.OfPoint(XYZ(base.X, base.Y, link_elev)).Z
    except Exception:
        return None


def measure_source(link_inst, source, host_wall):
    """Measure whichever kind of linked element was picked."""
    if is_curtain_wall(source):
        return measure_curtain_wall(link_inst, source, host_wall)
    return measure_window(link_inst, source, host_wall)


def measure_window(link_inst, window, host_wall):
    """Return (WindowPlan, skip_reason).  On failure the plan is None."""
    link_doc  = link_inst.GetLinkDocument()
    transform = link_inst.GetTotalTransform()

    curve, direction = wall_axis(host_wall)
    if curve is None or direction is None:
        return None, "picked wall has no usable location curve"

    points = list(iter_solid_points(window, transform))
    if not points:
        return None, "no solid geometry found on the linked window"

    origin = points[0]
    u_vals = [(p - origin).DotProduct(direction) for p in points]
    z_vals = [p.Z for p in points]

    u_min, u_max = min(u_vals), max(u_vals)
    z_min, z_max = min(z_vals), max(z_vals)

    geo_width  = u_max - u_min
    geo_height = z_max - z_min
    if geo_width < MIN_EXTENT or geo_height < MIN_EXTENT:
        return None, "linked window measures as flat along the picked wall"

    plan = WindowPlan()
    plan.window_id = eid_value(window.Id)
    plan.link_name = get_element_name(link_inst)
    plan.mark      = type_mark(window, link_doc)
    plan.prefix    = mark_prefix(plan.mark)
    plan.wall_dir  = direction

    win_type = None
    try:
        win_type = link_doc.GetElement(window.GetTypeId())
    except Exception:
        pass
    sources = [window, win_type]

    width = length_param(
        sources,
        ["Rough Width", "Width"],
        ["FAMILY_ROUGH_WIDTH_PARAM", "WINDOW_WIDTH", "FAMILY_WIDTH_PARAM",
         "GENERIC_WIDTH"])
    height = length_param(
        sources,
        ["Rough Height", "Height"],
        ["FAMILY_ROUGH_HEIGHT_PARAM", "WINDOW_HEIGHT", "FAMILY_HEIGHT_PARAM",
         "GENERIC_HEIGHT"])

    plan.geom_bottom = z_min
    plan.sill_param  = sill_from_parameters(window, link_doc, transform)

    # The parameter is the better base - it ignores sill trim hanging below
    # the opening - but only when it agrees with where the solids actually
    # are.  A family whose Sill Height is measured from something other than
    # the level this reads can put it a whole storey out, and the geometry
    # is the only thing that cannot lie about where the window is.
    sill = plan.sill_param
    if sill is None:
        sill = z_min
        plan.notes.append("sill measured from geometry")
    elif abs(sill - z_min) > SILL_TRIM_MAX:
        plan.notes.append(
            "Sill Height puts the base at {} but the geometry starts at {}; "
            "used the geometry".format(feet_text(sill), feet_text(z_min)))
        sill = z_min
    plan.sill = sill

    if width is None:
        width = geo_width
        plan.notes.append("width measured from geometry")
    if height is None:
        # Measure up from the real sill, not from the bottom of whatever
        # trim hangs below it, so the head still lands in the right place.
        height = z_max - sill
        plan.notes.append("height measured from geometry")
        if height < MIN_EXTENT:
            return None, "window head sits at or below its sill height"

    plan.width  = width
    plan.height = height

    centre = window_centre(window, transform)
    if centre is None:
        mid_u  = (u_min + u_max) / 2.0
        centre = XYZ(origin.X + direction.X * mid_u,
                     origin.Y + direction.Y * mid_u,
                     sill)
    plan.centre = centre

    u_centre = (centre - origin).DotProduct(direction)
    plan.top_profile = trace_top_boundary(u_vals, z_vals, u_centre,
                                          plan.width, plan.sill, plan.height)
    return plan, None


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

    plan = WindowPlan()
    plan.source_kind = "curtain wall"
    plan.window_id = eid_value(wall.Id)
    plan.link_name = get_element_name(link_inst)
    plan.mark      = type_mark(wall, link_doc)
    plan.prefix    = mark_prefix(plan.mark)
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


def trace_top_boundary(u_vals, z_vals, u_centre, width, sill, height):
    """Return the window's upper outline as normalised (s, t) samples.

    *s* runs 0..1 across the curtain wall's width, measured out from the
    window's centre, and *t* runs 0..1 from its sill to its head, so the
    samples replay onto the wall that is actually built rather than onto
    the raw extents of the geometry.  Returns None when the outline
    cannot be traced.
    """
    if width < MIN_EXTENT or height < MIN_EXTENT:
        return None

    tops = {}
    for u, z in zip(u_vals, z_vals):
        s = ((u - u_centre) + width / 2.0) / width
        if s < 0.0 or s > 1.0:
            continue        # trim reaching past the jambs is not the outline
        i = int(round(s * (TOP_SAMPLE_BINS - 1)))
        if i < 0:
            i = 0
        elif i > TOP_SAMPLE_BINS - 1:
            i = TOP_SAMPLE_BINS - 1
        if i not in tops or z > tops[i]:
            tops[i] = z

    if len(tops) < TOP_SAMPLE_BINS / 2:
        return None

    samples = []
    for i in sorted(tops.keys()):
        s = float(i) / (TOP_SAMPLE_BINS - 1)
        t = (tops[i] - sill) / height
        samples.append((s, t))
    return samples


# ===============================================================================
# ARCHED HEAD
# ===============================================================================

def plane_point(origin, direction, u, z):
    """A point in the wall's plane, *u* along it and at absolute height *z*."""
    return XYZ(origin.X + direction.X * u,
               origin.Y + direction.Y * u,
               z)


def solve3(matrix, rhs):
    """Solve a 3x3 system by Gaussian elimination.  None if singular."""
    m = [list(row) + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(3):
            if r == col:
                continue
            factor = m[r][col] / m[col][col]
            for c in range(col, 4):
                m[r][c] -= factor * m[col][c]
    return [m[i][3] / m[i][i] for i in range(3)]


def fit_circle(points):
    """Least-squares circle through (x, y) *points*.  (cx, cy, r) or None.

    Uses the algebraic form x^2 + y^2 + Dx + Ey + F = 0, which is linear in
    D, E and F, so three normal equations settle it.
    """
    if len(points) < 3:
        return None

    sxx = sxy = syy = sx = sy = 0.0
    sxz = syz = sz = 0.0
    n = float(len(points))
    for x, y in points:
        z = x * x + y * y
        sxx += x * x
        sxy += x * y
        syy += y * y
        sx  += x
        sy  += y
        sxz += x * z
        syz += y * z
        sz  += z

    sol = solve3([[sxx, sxy, sx],
                  [sxy, syy, sy],
                  [sx,  sy,  n]],
                 [-sxz, -syz, -sz])
    if sol is None:
        return None

    d, e, f = sol
    cx, cy = -d / 2.0, -e / 2.0
    inner = cx * cx + cy * cy - f
    if inner <= 0:
        return None
    return cx, cy, inner ** 0.5


def fit_circle_trimmed(points):
    """Fit a circle, drop the worst outliers, refit.  (cx, cy, r, worst).

    Head trim that stops short of the jambs, or a transom sitting proud of
    the arch, throws a handful of samples well off the curve.  Refitting
    without them recovers the arch the rest of the samples describe.
    """
    fit = fit_circle(points)
    if fit is None:
        return None

    def residuals(circle, pts):
        cx, cy, r = circle
        return [abs((((x - cx) ** 2 + (y - cy) ** 2) ** 0.5) - r)
                for x, y in pts]

    res = residuals(fit, points)
    ordered = sorted(res)
    median = ordered[len(ordered) // 2]
    cutoff = max(median * 3.0, ARC_FIT_TOL)

    kept = [p for p, d in zip(points, res) if d <= cutoff]
    if len(kept) >= max(3, len(points) // 2) and len(kept) < len(points):
        refit = fit_circle(kept)
        if refit is not None:
            fit = refit
            res = residuals(fit, kept)

    return fit[0], fit[1], fit[2], (max(res) if res else 0.0)


def simplify_chain(points, tolerance):
    """Douglas-Peucker reduction of a (x, y) polyline."""
    if len(points) < 3:
        return list(points)

    x0, y0 = points[0]
    x1, y1 = points[-1]
    dx, dy = x1 - x0, y1 - y0
    span = (dx * dx + dy * dy) ** 0.5

    worst_i = 0
    worst_d = 0.0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        if span < 1e-9:
            d = ((x - x0) ** 2 + (y - y0) ** 2) ** 0.5
        else:
            d = abs(dy * x - dx * y + x1 * y0 - y1 * x0) / span
        if d > worst_d:
            worst_d, worst_i = d, i

    if worst_d <= tolerance:
        return [points[0], points[-1]]
    left  = simplify_chain(points[:worst_i + 1], tolerance)
    right = simplify_chain(points[worst_i:], tolerance)
    return left[:-1] + right


def close_profile(top_chain, origin, direction, width, base_z):
    """Close a left-to-right *top_chain* of (u, z) into a wall profile."""
    p_bl = plane_point(origin, direction, 0.0, base_z)
    p_br = plane_point(origin, direction, width, base_z)

    curves = [Line.CreateBound(p_bl, p_br)]
    previous = p_br
    for u, z in reversed(top_chain):
        point = plane_point(origin, direction, u, z)
        if previous.DistanceTo(point) > 1e-6:
            curves.append(Line.CreateBound(previous, point))
        previous = point
    if previous.DistanceTo(p_bl) > 1e-6:
        curves.append(Line.CreateBound(previous, p_bl))
    return curves


def build_arch_profile(samples, origin, direction, width, height, base_z):
    """Return (curves, reason) for the head shape *samples* describe.

    A head that fits one circle becomes a true arc with straight jambs.
    One that does not - a segmental head carrying trim, say - is followed
    as a simplified polyline instead, which is far better than throwing
    the shape away and leaving a rectangle.  *curves* is None only when
    the head is flat, and then *reason* is None too.
    """
    if not samples:
        return None, "top of the window could not be traced"

    t_top  = max(t for _s, t in samples)
    t_side = min(t for _s, t in samples)
    if (t_top - t_side) * height < FLAT_TOP_TOL:
        return None, None          # flat head: the rectangle is already right

    points = sorted((s * width, base_z + t * height) for s, t in samples)

    fit = fit_circle_trimmed(points)
    if fit is not None:
        cx, cy, r, worst = fit

        def on_circle(u):
            """Height of the circle's upper half at *u*, or None."""
            inner = r * r - (u - cx) ** 2
            if inner < 0:
                return None
            return cy + inner ** 0.5

        z_left  = on_circle(0.0)
        z_apex  = on_circle(width / 2.0)
        z_right = on_circle(width)

        if (worst <= ARC_FIT_TOL and None not in (z_left, z_apex, z_right)
                and cy < base_z + t_top * height
                and min(z_left, z_right) >= base_z):
            p_left  = plane_point(origin, direction, 0.0, z_left)
            p_right = plane_point(origin, direction, width, z_right)
            p_apex  = plane_point(origin, direction, width / 2.0, z_apex)
            p_bl    = plane_point(origin, direction, 0.0, base_z)
            p_br    = plane_point(origin, direction, width, base_z)
            try:
                arc = Arc.Create(p_right, p_left, p_apex)
            except Exception as ex:
                return None, "arched head could not be fitted ({})".format(ex)

            curves = [Line.CreateBound(p_bl, p_br)]
            if p_br.DistanceTo(p_right) > 1e-6:
                curves.append(Line.CreateBound(p_br, p_right))
            curves.append(arc)
            if p_left.DistanceTo(p_bl) > 1e-6:
                curves.append(Line.CreateBound(p_left, p_bl))
            return curves, None

        note = ("head is not a single arc (off by {:.3f} ft); "
                "followed as a polyline".format(worst))
    else:
        note = "head could not be fitted to an arc; followed as a polyline"

    # Pin the ends to the jambs so the profile closes on the wall's sides.
    chain = [(0.0, points[0][1])] + \
            [p for p in points if 0.0 < p[0] < width] + \
            [(width, points[-1][1])]
    chain = simplify_chain(chain, POLY_SIMPLIFY_TOL)
    if len(chain) < 2:
        return None, "head shape could not be traced into a profile"
    return close_profile(chain, origin, direction, width, base_z), note


class SketchFailureSwallower(IFailuresPreprocessor):
    """Keep Revit's failure dialog out of the way.

    Warnings are dropped outright.  Errors are resolved by deleting the
    elements that failed - in practice mullions Revit could not keep on a
    reshaped wall - so the edit commits instead of stopping on a dialog
    the script cannot answer.
    """

    def PreprocessFailures(self, failures_accessor):
        try:
            failures_accessor.DeleteAllWarnings()
        except Exception:
            pass

        removed = False
        try:
            for failure in failures_accessor.GetFailureMessages():
                if failure.GetSeverity() != FailureSeverity.Error:
                    continue
                ids = list(failure.GetFailingElementIds())
                if not ids:
                    continue
                if failures_accessor.IsElementsDeletionPermitted(ids):
                    failures_accessor.DeleteElements(ids)
                    removed = True
        except Exception as ex:
            logger.debug("Could not resolve a failure: {}".format(ex))

        if removed:
            return FailureProcessingResult.ProceedWithCommit
        return FailureProcessingResult.Continue


def sketch_curve_ids(sketch):
    """Return the element ids of a sketch's profile curves.

    A sketch owns more than its curves - reference planes and dimensions
    live there too - so the ids are filtered down to CurveElements before
    anything gets deleted.
    """
    ids = []
    try:
        for cid in sketch.GetAllElements():
            if isinstance(doc.GetElement(cid), CurveElement):
                ids.append(cid)
    except Exception:
        pass
    if ids:
        return ids

    try:
        for arr in sketch.Profile:
            for curve in arr:
                ref = curve.Reference
                if ref is not None:
                    ids.append(ref.ElementId)
    except Exception:
        pass
    return ids


def apply_arch_profile(wall, curves):
    """Re-sketch *wall*'s elevation profile.  Returns None, or a reason.

    Runs outside any open transaction: SketchEditScope refuses to start
    inside one.
    """
    t = Transaction(doc, "Create wall profile sketch")
    try:
        t.Start()
        sketch_id = wall.SketchId
        if sketch_id is None or sketch_id == ElementId.InvalidElementId:
            # CreateProfileSketch hands back the Sketch itself, not its id.
            sketch_id = as_element_id(wall.CreateProfileSketch())
        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        return "profile sketch unavailable on this wall ({})".format(ex)

    if sketch_id is None:
        return "profile sketch could not be created"

    sketch = doc.GetElement(sketch_id)
    if not isinstance(sketch, Sketch):
        return "profile sketch could not be read back"

    scope = SketchEditScope(doc, "Reshape curtain wall to the window")
    try:
        scope.Start(sketch.Id)
    except Exception as ex:
        return "profile sketch could not be opened ({})".format(ex)

    inner = Transaction(doc, "Replace profile curves")
    try:
        inner.Start()
        try:
            opts = inner.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(SketchFailureSwallower())
            inner.SetFailureHandlingOptions(opts)
        except Exception as ex:
            logger.debug("Could not set failure handling: {}".format(ex))
        plane = sketch.SketchPlane
        for cid in sketch_curve_ids(sketch):
            try:
                doc.Delete(cid)
            except Exception:
                continue
        for curve in curves:
            doc.Create.NewModelCurve(curve, plane)
        inner.Commit()
    except Exception as ex:
        if inner.HasStarted() and not inner.HasEnded():
            inner.RollBack()
        try:
            scope.Cancel()
        except Exception:
            pass
        return "profile could not be re-sketched ({})".format(ex)

    try:
        scope.Commit(SketchFailureSwallower())
    except Exception as ex:
        try:
            scope.Cancel()
        except Exception:
            pass
        return "profile edit was rejected ({})".format(ex)
    return None


# ===============================================================================
# WALL CREATION
# ===============================================================================

def segment_on_wall(host_wall, centre, width):
    """Return (curve, reason) for a *width*-long segment of the host wall.

    The segment is centred on *centre* projected onto the wall.  Straight
    walls are handled directly so a window may overhang the wall's ends;
    curved walls are clamped to the wall and say so.
    """
    curve, direction = wall_axis(host_wall)
    if curve is None or direction is None:
        return None, "picked wall has no usable location curve"

    base_z = curve.GetEndPoint(0).Z
    flat   = XYZ(centre.X, centre.Y, base_z)

    if isinstance(curve, Line):
        try:
            mid = curve.Project(flat).XYZPoint
        except Exception:
            return None, "window does not project onto the picked wall"
        half = width / 2.0
        p0 = XYZ(mid.X - direction.X * half, mid.Y - direction.Y * half, base_z)
        p1 = XYZ(mid.X + direction.X * half, mid.Y + direction.Y * half, base_z)
        return Line.CreateBound(p0, p1), None

    try:
        res = curve.Project(flat)
        t0  = curve.ComputeNormalizedParameter(res.Parameter)
    except Exception:
        return None, "window does not project onto the picked wall"

    half_n = (width / 2.0) / curve.Length
    ta, tb = t0 - half_n, t0 + half_n
    reason = None
    if ta < 0.0 or tb > 1.0:
        reason = "window overhangs the picked curved wall; trimmed to it"
        ta = max(ta, 0.0)
        tb = min(tb, 1.0)
    if tb - ta < 1e-6:
        return None, "no room on the picked wall for this window"

    try:
        p0  = curve.Evaluate(ta, True)
        p1  = curve.Evaluate(tb, True)
        mid = curve.Evaluate((ta + tb) / 2.0, True)
        return Arc.Create(p0, p1, mid), reason
    except Exception as ex:
        return None, "segment on the curved wall failed ({})".format(ex)


def strip_curtain_grid(wall):
    """Strip *wall* back to one plain panel.

    The matched host type usually carries a grid layout, so Revit fills
    the new wall with grid lines and mullions.  They are not wanted, and
    they are also what breaks the profile edit: reshaping the wall leaves
    mullions sitting on grid segments that no longer exist, which Revit
    raises as an error rather than a warning.  Clearing them first means
    there is nothing left to break.

    Returns how many elements were removed.  Revit re-applies the type's
    layout after a profile edit, so this has to run again afterwards.
    """
    try:
        grid = wall.CurtainGrid
    except Exception:
        return 0
    if grid is None:
        return 0

    removed = 0
    for getter in ("GetMullionIds", "GetVGridLineIds", "GetUGridLineIds"):
        try:
            ids = list(getattr(grid, getter)())
        except Exception:
            continue
        for gid in ids:
            try:
                doc.Delete(gid)
                removed += 1
            except Exception:
                continue
    doc.Regenerate()
    return removed


def params_by_name(elem):
    """Map an element's parameters by upper-cased definition name."""
    table = {}
    try:
        for p in elem.Parameters:
            try:
                table[p.Definition.Name.strip().upper()] = p
            except Exception:
                continue
    except Exception:
        pass
    return table


def pick_param(table, name):
    """Find a parameter by name, ignoring case and stray whitespace."""
    return table.get(name.strip().upper())


def set_param_text(param, text):
    """Write *text* into *param*, whatever it stores.  True when written."""
    if param is None or param.IsReadOnly:
        return False
    try:
        storage = param.StorageType
        if storage == StorageType.String:
            return param.Set(text or "")
        if storage == StorageType.Integer:
            return param.Set(int(float(text)))
        if storage == StorageType.Double:
            return param.Set(float(text))
    except Exception as ex:
        logger.debug("Could not write '{}': {}".format(text, ex))
    return False


def copy_param(source, target):
    """Copy a parameter value across.  True when it was written."""
    if source is None or target is None or target.IsReadOnly:
        return False
    try:
        storage = source.StorageType
        if storage != target.StorageType:
            text = source.AsValueString() or source.AsString() or ""
            return set_param_text(target, text)
        if storage == StorageType.String:
            return target.Set(source.AsString() or "")
        if storage == StorageType.Integer:
            return target.Set(source.AsInteger())
        if storage == StorageType.Double:
            return target.Set(source.AsDouble())
        if storage == StorageType.ElementId:
            return target.Set(source.AsElementId())
    except Exception as ex:
        logger.debug("Could not copy a parameter: {}".format(ex))
    return False


def apply_bg_parameters(plan, wall, host_wall):
    """Fill the BG_ parameters on the new wall, noting anything missing.

    Whatever cannot be filled is left blank rather than blocking the wall,
    so a project missing one of these still gets its curtain walls.
    BG_PROFILE is deliberately untouched.
    """
    target = params_by_name(wall)
    source = params_by_name(host_wall)

    number = pick_param(target, BG_NUMBER_NAME)
    if number is None:
        plan.notes.append("{} not on the new curtain wall"
                          .format(BG_NUMBER_NAME))
    elif not set_param_text(number, plan.mark or ""):
        plan.notes.append("could not write {}".format(BG_NUMBER_NAME))

    for name in BG_COPIED_NAMES:
        from_host = pick_param(source, name)
        to_wall   = pick_param(target, name)
        if from_host is None:
            plan.notes.append("{} not on the host wall".format(name))
            continue
        if to_wall is None:
            plan.notes.append("{} not on the new curtain wall".format(name))
            continue
        if not copy_param(from_host, to_wall):
            plan.notes.append("could not copy {}".format(name))


def create_curtain_wall(plan, host_wall, wall_type):
    """Create the curtain wall for *plan*.  Returns (wall, reason)."""
    curve, reason = segment_on_wall(host_wall, plan.centre, plan.width)
    if curve is None:
        return None, reason

    level, level_elev = find_level_below(plan.sill)
    if level is None:
        return None, "no levels in the host model"

    base_off = plan.sill - level_elev
    wall = Wall.Create(doc, curve, wall_type.Id, level.Id,
                       plan.height, base_off, False, False)
    doc.Regenerate()
    plan.grid_removed.append(strip_curtain_grid(wall))
    apply_bg_parameters(plan, wall, host_wall)

    plan.level_name = get_element_name(level)
    plan.base_offset = base_off
    return wall, reason


# ===============================================================================
# MAIN
# ===============================================================================

def report(rows):
    """Print the notes table, or nothing at all when there is nothing to say."""
    if not rows:
        return
    output.print_md("### Window To Curtain Wall - {} note(s)".format(len(rows)))
    output.print_table(
        table_data=rows,
        columns=["Window Id", "Link", "Type Mark", "Note"])


def feet_text(value):
    """Format a length in feet as feet and inches."""
    try:
        total_in = value * 12.0
        sign = "-" if total_in < 0 else ""
        total_in = abs(total_in)
        ft = int(total_in // 12)
        inches = total_in - ft * 12
        return "{}{}' {:.2f}\"".format(sign, ft, inches)
    except Exception:
        return "?"


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
    """Reshape *wall* to match its source, recording any note."""
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
        failure = apply_arch_profile(wall, moved)
        if failure:
            plan.notes.append(failure)
        return

    curves = None
    reason = None
    try:
        curve = wall.Location.Curve
        if isinstance(curve, Line):
            curves, reason = build_arch_profile(
                plan.top_profile, curve.GetEndPoint(0), plan.wall_dir,
                plan.width, plan.height, plan.sill)
        elif plan.top_profile:
            t_top  = max(x[1] for x in plan.top_profile)
            t_side = min(x[1] for x in plan.top_profile)
            if (t_top - t_side) * plan.height >= FLAT_TOP_TOL:
                reason = "shaped head on a curved wall; left rectangular"
    except Exception as ex:
        reason = "arch check failed ({})".format(ex)

    if curves:
        failure = apply_arch_profile(wall, curves)
        if failure:
            plan.notes.append(failure)
    elif reason:
        plan.notes.append(reason)


def main():
    picks = pick_pairs()
    if not picks:
        return          # nothing picked is a cancellation; stay silent

    rows = []

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
        plans.append((plan, host_wall))

    if not plans:
        report(rows)
        return

    types = curtain_wall_types()
    if not types:
        report(rows + [[p.window_id, p.link_name, p.mark or "-",
                        "no curtain wall types in the host model"]
                       for p, _w in plans])
        return

    # ---- Resolve the curtain wall type once per Type Mark prefix.
    chosen = {}
    ready  = []
    for plan, host_wall in plans:
        key = plan.prefix or "<none>"
        if key not in chosen:
            wall_type = match_curtain_type(plan, types)
            if wall_type is None:
                wall_type = prompt_curtain_type(types, plan.mark, plan.prefix)
                if wall_type is not None:
                    plan.notes.append("type picked by hand")
            chosen[key] = wall_type

        wall_type = chosen[key]
        if wall_type is None:
            rows.append([plan.window_id, plan.link_name, plan.mark or "-",
                         "no curtain wall type for prefix '{}'; skipped"
                         .format(plan.prefix or "?")])
            continue
        ready.append((plan, host_wall, wall_type))

    if not ready:
        report(rows)
        return

    # ---- Create every wall in one transaction.  Arched heads are re-sketched
    # ---- afterwards: SketchEditScope cannot run inside a transaction.
    arch_queue = []

    t = Transaction(doc, "Create curtain walls from linked windows")
    t.Start()
    try:
        # Clearing the grid raises the same mullion errors the profile edit
        # does, so this transaction answers them the same way.
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(SketchFailureSwallower())
        opts.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(opts)
    except Exception as ex:
        logger.debug("Could not set failure handling: {}".format(ex))

    try:
        for plan, host_wall, wall_type in ready:
            try:
                wall, reason = create_curtain_wall(plan, host_wall, wall_type)
            except Exception as ex:
                wall, reason = None, "wall creation failed: {}".format(ex)

            if wall is None:
                rows.append([plan.window_id, plan.link_name,
                             plan.mark or "-", reason])
                continue
            if reason:
                plan.notes.append(reason)
            plan.new_wall_id = eid_value(wall.Id)
            arch_queue.append((plan, wall))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    for plan, wall in arch_queue:
        resolve_profile(plan, wall)

    if arch_queue:
        # Revit rebuilds the grid from the type's layout when a wall is
        # reshaped, so the panels have to be cleared again afterwards.
        cleanup = Transaction(doc, "Remove curtain grid")
        cleanup.Start()
        try:
            opts = cleanup.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(SketchFailureSwallower())
            cleanup.SetFailureHandlingOptions(opts)
        except Exception as ex:
            logger.debug("Could not set failure handling: {}".format(ex))
        try:
            for plan, wall in arch_queue:
                plan.grid_removed.append(strip_curtain_grid(wall))
            cleanup.Commit()
        except Exception:
            if cleanup.HasStarted() and not cleanup.HasEnded():
                cleanup.RollBack()
            raise

    for plan, wall in arch_queue:
        if plan.notes:
            rows.append([plan.window_id, plan.link_name, plan.mark or "-",
                         "; ".join(plan.notes)])

    # Silence on a clean run: only notes are worth opening the output for.
    report_measurements([p for p, _w in arch_queue])
    report(rows)


main()
