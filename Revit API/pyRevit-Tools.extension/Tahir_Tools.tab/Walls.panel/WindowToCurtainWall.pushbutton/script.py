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
    "A window gives its width, height and sill from its own parameters "
    "and always comes out rectangular, arched ones included; a linked "
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
    ElementId,
    FamilyInstance,
    FilteredElementCollector,
    GeometryInstance,
    Level,
    Line,
    Options,
    Sketch,
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

from Tahir import wall_sketch

doc    = revit.doc
uidoc  = revit.uidoc
logger = script.get_logger()
output = script.get_output()

LEVEL_TOL       = 1e-4    # feet, when matching a level under the sill
MIN_EXTENT      = 0.02    # feet, below this a measured width/height is junk
SILL_TRIM_MAX   = 2.0     # feet; further than this below the opening and a
                          # Sill Height reading is wrong, not just trimmed
CENTRE_TOL_FRACTION = 0.25  # how far off centre an insertion point may sit,
                            # as a fraction of the window's width
CURTAIN_SUFFIX  = "_Window"

# Where a window's sill height can be written.  Built-in parameters are
# named rather than referenced so one missing from this Revit version is
# skipped instead of raising; the plain names catch family parameters.
SILL_INSTANCE_KEYS = ["INSTANCE_SILL_HEIGHT_PARAM", "Sill Height"]
SILL_TYPE_KEYS     = ["FAMILY_SILL_HEIGHT_PARAM", "WINDOW_SILL_HEIGHT",
                      "Sill Height", "Default Sill Height"]

# Shared parameters filled on every wall this tool makes.  BG_PROFILE is
# deliberately left alone.
BG_NUMBER_NAME  = "BG_WINDOW NUMBER"
BG_COPIED_NAMES = ["BG_BUILDING ID", "BG_ELEVATION", "BG_LEVEL"]

# Print the measurements table every run.  Off by default: a run that
# worked has nothing to say, and printing is what opens the output
# window, so a clean run now shows nothing at all.  Turn it on while
# dialling the numbers in on a troublesome window.
VERBOSE         = False


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

    A plan built from a linked curtain wall carries *profile_curves* -
    that wall's own sketched profile, already in host coordinates -
    together with *src_origin* and *src_dir*, the frame those curves are
    measured in, so the profile can be moved onto whichever wall is
    picked.  A plan built from a window carries none of that: it always
    becomes a plain rectangle.
    """

    __slots__ = ("window_id", "link_name", "mark", "prefix",
                 "centre", "width", "height", "sill",
                 "profile_curves", "src_origin", "src_dir",
                 "wall_dir", "notes", "source_kind", "level_name",
                 "base_offset", "new_wall_id", "grid_removed",
                 "sill_param", "geom_bottom")

    def __init__(self):
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


def sill_height_candidates(window, link_doc):
    """Every Sill Height reading a window offers, instance and type.

    Both are collected rather than the first one found: a family can
    carry a sill height on the instance and another on the type, and
    which of the two is the real one varies by family.
    """
    win_type = None
    try:
        win_type = link_doc.GetElement(window.GetTypeId())
    except Exception:
        pass

    found = []
    for elem, keys in ((window, SILL_INSTANCE_KEYS),
                       (win_type, SILL_TYPE_KEYS)):
        if elem is None:
            continue
        for key in keys:
            p = None
            bip = getattr(BuiltInParameter, key, None)
            try:
                p = elem.get_Parameter(bip) if bip is not None \
                    else elem.LookupParameter(key)
            except Exception:
                p = None
            if p is None or not p.HasValue:
                continue
            try:
                found.append(p.AsDouble())
            except Exception:
                continue
    return found


def sill_from_parameters(window, link_doc, transform):
    """Return the window's sill elevation in host coordinates, or None.

    Read as Sill Height above the window's own level rather than measured
    off the solids: sill trims, cast stone and aprons routinely hang below
    the sill, and measuring would start the curtain wall at the bottom of
    those instead of at the opening.

    The instance and type readings are both taken and the HIGHEST wins.
    A type default of zero left behind on a family whose instance carries
    the real height would otherwise drop the wall to the floor.
    """
    candidates = sill_height_candidates(window, link_doc)
    if not candidates:
        return None
    sill = max(candidates)

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
        logger.debug("No Sill Height parameter; measured the sill from geometry")
    elif abs(sill - z_min) > SILL_TRIM_MAX:
        logger.debug(
            "Sill Height puts the base at {} but the geometry starts at {}; "
            "used the geometry".format(feet_text(sill), feet_text(z_min)))
        sill = z_min
    plan.sill = sill

    if width is None:
        width = geo_width
        logger.debug("No width parameter; measured the width from geometry")
    if height is None:
        # Measure up from the real sill, not from the bottom of whatever
        # trim hangs below it, so the head still lands in the right place.
        height = z_max - sill
        logger.debug("No height parameter; measured the height from geometry")
        if height < MIN_EXTENT:
            return None, "window head sits at or below its sill height"

    plan.width  = width
    plan.height = height

    # Centre the wall on the middle of the solids, not on the family's
    # insertion point.  A stock window is inserted at the centre of its
    # opening, but a Generic Model standing in for one can be inserted at
    # an edge or a corner, which throws the wall sideways by half a window
    # - and drags the head trace off the geometry with it.  The insertion
    # point is more precise when it is there to be had, so it wins while
    # it agrees with the solids.
    geom_u = (u_min + u_max) / 2.0
    u_centre = geom_u

    located = window_centre(window, transform)
    if located is not None:
        located_u = (located - origin).DotProduct(direction)
        if abs(located_u - geom_u) <= width * CENTRE_TOL_FRACTION:
            u_centre = located_u
        else:
            logger.debug(
                "Insertion point sits {} off the middle of the geometry; "
                "centred on the geometry"
                .format(feet_text(located_u - geom_u)))

    plan.centre = XYZ(origin.X + direction.X * u_centre,
                      origin.Y + direction.Y * u_centre,
                      sill)
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
                    logger.debug("Type picked by hand for prefix {}"
                                 .format(plan.prefix))
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
                plan.grid_removed.append(strip_curtain_grid(wall))
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
