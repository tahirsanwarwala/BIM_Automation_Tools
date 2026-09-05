# -*- coding: utf-8 -*-
"""Building a curtain wall from a window picked in a linked model.

Extracted from WindowToCurtainWall so Multi Wall Creation V2 can turn a
window in a linked wall into a curtain wall without carrying a second
copy of this path.  Behaviour is unchanged from that script: the only
differences are that *doc* is now passed in rather than read off a
module global, and measure_window takes an optional *direction* so a
caller that already knows which way the wall runs - because the wall it
would measure against does not exist yet - can skip wall_axis entirely.

WindowToCurtainWall's OTHER source path - a curtain wall picked in the
linked model - deliberately stays in that pushbutton.  It serves a
different source kind that V2 does not use, and moving it here would mix
two independent measuring strategies into one module for no reason.
"""

import re

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    Arc,
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    GeometryInstance,
    Level,
    Line,
    Options,
    Solid,
    StorageType,
    ViewDetailLevel,
    Wall,
    WallKind,
    WallType,
    XYZ,
)
from pyrevit import forms, script

logger = script.get_logger()

MIN_EXTENT      = 0.02    # feet, below this a measured width/height is junk
LEVEL_TOL       = 1e-4    # feet, when matching a level under the sill
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


def find_level_below(doc, elevation):
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


def curtain_wall_types(doc):
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


def copy_plan(plan):
    """A shallow copy of a WindowPlan, so one source can become several.

    A window or a curtain wall crossing a level becomes one curtain wall
    per storey, and each storey needs its own sill and height while
    everything else stays shared.  WindowPlan uses __slots__ and has no
    copy of its own.
    """
    other = WindowPlan()
    for name in WindowPlan.__slots__:
        try:
            setattr(other, name, getattr(plan, name))
        except AttributeError:
            continue
    other.notes        = list(plan.notes)
    other.grid_removed = []
    other.new_wall_id  = None
    return other


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


def measure_window(link_inst, window, host_wall, direction=None):
    """Return (WindowPlan, skip_reason).  On failure the plan is None."""
    link_doc  = link_inst.GetLinkDocument()
    transform = link_inst.GetTotalTransform()

    if direction is None:
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


def strip_curtain_grid(doc, wall):
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


def create_curtain_wall(doc, plan, host_wall, wall_type):
    """Create the curtain wall for *plan*.  Returns (wall, reason)."""
    curve, reason = segment_on_wall(host_wall, plan.centre, plan.width)
    if curve is None:
        return None, reason

    level, level_elev = find_level_below(doc, plan.sill)
    if level is None:
        return None, "no levels in the host model"

    base_off = plan.sill - level_elev
    wall = Wall.Create(doc, curve, wall_type.Id, level.Id,
                       plan.height, base_off, False, False)
    doc.Regenerate()
    plan.grid_removed.append(strip_curtain_grid(doc, wall))
    apply_bg_parameters(plan, wall, host_wall)

    plan.level_name = get_element_name(level)
    plan.base_offset = base_off
    return wall, reason
